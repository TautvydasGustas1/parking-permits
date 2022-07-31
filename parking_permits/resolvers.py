import logging
from collections import Counter

from ariadne import (
    MutationType,
    QueryType,
    convert_kwargs_to_snake_case,
    load_schema_from_path,
    snake_case_fallback_resolvers,
)
from ariadne.contrib.federation import FederatedObjectType
from django.db import transaction
from django.utils.translation import ugettext

from project.settings import BASE_DIR

from .customer_permit import CustomerPermit
from .decorators import is_authenticated
from .exceptions import (
    AddressError,
    ObjectNotFound,
    ParkingZoneError,
    TraficomFetchVehicleError,
)
from .models import Address, Customer, Refund, Vehicle
from .models.order import Order, OrderStatus
from .models.parking_permit import ContractType, ParkingPermit, ParkingPermitStatus
from .services.hel_profile import HelsinkiProfile
from .services.kmo import get_address_detail_from_kmo
from .services.mail import (
    PermitEmailType,
    RefundEmailType,
    send_permit_email,
    send_refund_email,
)
from .services.traficom import Traficom
from .talpa.order import TalpaOrderManager

logger = logging.getLogger("db")

helsinki_profile_query = load_schema_from_path(
    BASE_DIR / "parking_permits" / "schema" / "helsinki_profile.graphql"
)

query = QueryType()
mutation = MutationType()
address_node = FederatedObjectType("AddressNode")
profile_node = FederatedObjectType("ProfileNode")

schema_bindables = [query, mutation, address_node, snake_case_fallback_resolvers]

ACTIVE_PERMIT_STATUSES = [
    ParkingPermitStatus.DRAFT,
    ParkingPermitStatus.VALID,
]


@query.field("getPermits")
@is_authenticated
@convert_kwargs_to_snake_case
def resolve_customer_permits(obj, info):
    request = info.context["request"]
    return CustomerPermit(request.user.customer.id).get()


def save_profile_address(address):
    street_name = address.get("street_name")
    street_number = address.get("street_number")
    address_detail = get_address_detail_from_kmo(street_name, street_number)
    address.update(address_detail)
    address_obj = Address.objects.update_or_create(
        street_name=street_name,
        street_number=street_number,
        city=address["city"],
        postal_code=address["postal_code"],
        defaults=address,
    )
    return address_obj[0]


@query.field("profile")
@is_authenticated
def resolve_user_profile(_, info, *args):
    request = info.context["request"]
    profile = HelsinkiProfile(request)
    customer = profile.get_customer()
    primary_address_data, other_address_data = profile.get_addresses()
    primary_address = save_profile_address(primary_address_data)
    other_address = save_profile_address(other_address_data)

    customer_obj, _ = Customer.objects.update_or_create(
        source_system=customer.get("source_system"),
        source_id=customer.get("source_id"),
        defaults={
            "user": request.user,
            **customer,
            **{"primary_address": primary_address, "other_address": other_address},
        },
    )
    customer_obj.fetch_driving_licence_detail()
    return customer_obj


@mutation.field("updateLanguage")
@is_authenticated
def resolve_update_language(_, info, lang):
    request = info.context["request"]
    customer = request.user.customer
    customer.language = lang
    customer.save()
    return customer


@address_node.field("primary")
def resolve_address_primary(address, info):
    address_node_path_key = info.path.prev.key
    if address_node_path_key == "otherAddress":
        return False
    return True


def validate_customer_address(customer, address_id):
    """Check if the given address a valid customer address

    Customers can only update the permits to their only addresses,
    i.e. either the primary address or the other address
    """
    addr_ids = [customer.primary_address_id, customer.other_address_id]
    allowed_addr_ids = [str(addr_id) for addr_id in addr_ids if addr_id is not None]
    if address_id not in allowed_addr_ids:
        logger.error("Not a valid customer address")
        raise AddressError(ugettext("Not a valid customer address"))

    try:
        return Address.objects.get(id=address_id)
    except Address.DoesNotExist:
        logger.error(f"updatePermitsAddress: address with id {address_id} not found")
        raise ObjectNotFound(ugettext("Address not found"))


@query.field("getUpdateAddressPriceChanges")
@is_authenticated
@convert_kwargs_to_snake_case
def resolve_get_update_address_price_changes(_, info, address_id):
    customer = info.context["request"].user.customer
    address = validate_customer_address(customer, address_id)
    new_zone = address.zone

    permits = ParkingPermit.objects.active().filter(customer=customer)
    if len(permits) == 0:
        logger.error(f"No active permits for the customer: {customer}")
        raise ObjectNotFound(ugettext("No active permits for the customer"))

    permit_price_changes = []
    for permit in permits:
        permit_price_changes.append(
            {
                "permit": permit,
                "price_changes": permit.get_price_change_list(
                    new_zone, permit.vehicle.is_low_emission
                ),
            }
        )
    return permit_price_changes


@mutation.field("deleteParkingPermit")
@is_authenticated
@convert_kwargs_to_snake_case
def resolve_delete_parking_permit(obj, info, permit_id):
    request = info.context["request"]
    return CustomerPermit(request.user.customer.id).delete(permit_id)


@mutation.field("createParkingPermit")
@is_authenticated
@convert_kwargs_to_snake_case
def resolve_create_parking_permit(obj, info, address_id, registration):
    request = info.context["request"]
    return CustomerPermit(request.user.customer.id).create(address_id, registration)


@mutation.field("updateParkingPermit")
@is_authenticated
@convert_kwargs_to_snake_case
def resolve_update_parking_permit(obj, info, input, permit_id=None):
    request = info.context["request"]
    return CustomerPermit(request.user.customer.id).update(input, permit_id)


@mutation.field("endParkingPermit")
@is_authenticated
@convert_kwargs_to_snake_case
def resolve_end_permit(_, info, permit_ids, end_type, iban=None):
    request = info.context["request"]
    return CustomerPermit(request.user.customer.id).end(permit_ids, end_type, iban)


@mutation.field("getVehicleInformation")
@is_authenticated
@convert_kwargs_to_snake_case
def resolve_get_vehicle_information(_, info, registration):
    request = info.context["request"]
    vehicle = Traficom().fetch_vehicle_details(registration_number=registration)
    customer = request.user.customer
    is_user_of_vehicle = customer.is_user_of_vehicle(vehicle)
    if not is_user_of_vehicle:
        raise TraficomFetchVehicleError(
            f"Customer is not an owner or holder of a vehicle {registration}"
        )

    has_valid_licence = customer.has_valid_driving_licence_for_vehicle(vehicle)
    if not has_valid_licence:
        raise TraficomFetchVehicleError(
            "Customer does not have a valid driving licence"
        )
    return vehicle


@mutation.field("updatePermitVehicle")
@is_authenticated
@convert_kwargs_to_snake_case
def resolve_update_permit_vehicle(_, info, permit_id, vehicle_id, iban=None):
    customer = info.context["request"].user.customer
    permit = ParkingPermit.objects.get(id=permit_id, customer=customer)
    new_vehicle = Vehicle.objects.get(id=vehicle_id)
    checkout_url = None

    if (
        permit.contract_type == ContractType.FIXED_PERIOD
        and permit.vehicle.is_low_emission != new_vehicle.is_low_emission
    ):
        price_change_list = permit.get_price_change_list(
            permit.parking_zone, new_vehicle.is_low_emission
        )
        permit_total_price_change = sum(
            [item["price_change"] for item in price_change_list]
        )
        permit.vehicle = new_vehicle
        permit.save()
        new_order = Order.objects.create_renewal_order(
            customer, status=OrderStatus.CONFIRMED
        )
        if permit_total_price_change < 0:
            refund = Refund.objects.create(
                name=str(customer),
                order=new_order,
                amount=-permit_total_price_change,
                iban=iban if iban else "",
                description=f"Refund for updating permits zone (customer switch vehicle to: {new_vehicle})",
            )
            logger.info(f"Refund for updating permits zone created: {refund}")
            send_refund_email(RefundEmailType.CREATED, customer)

        if permit_total_price_change > 0:
            checkout_url = TalpaOrderManager.send_to_talpa(new_order)
            permit.status = ParkingPermitStatus.PAYMENT_IN_PROGRESS
    else:
        permit.vehicle = new_vehicle

    permit.vehicle_changed = False
    permit.vehicle_changed_date = None
    permit.save()

    send_permit_email(PermitEmailType.UPDATED, permit)
    return {"checkout_url": checkout_url}


@mutation.field("createOrder")
@is_authenticated
def resolve_create_order(_, info):
    customer = info.context["request"].user.customer
    permits = ParkingPermit.objects.filter(
        customer=customer, status=ParkingPermitStatus.DRAFT
    )
    order = Order.objects.create_for_permits(permits)
    return {"checkout_url": TalpaOrderManager.send_to_talpa(order)}


@mutation.field("changeAddress")
@is_authenticated
@convert_kwargs_to_snake_case
@transaction.atomic
def resolve_change_address(_, info, address_id, iban=None):
    customer = info.context["request"].user.customer
    address = validate_customer_address(customer, address_id)
    new_zone = address.zone

    permits = ParkingPermit.objects.active().filter(customer=customer)
    if len(permits) == 0:
        logger.error(f"No active permits for the customer: {customer}")
        raise ObjectNotFound(ugettext("No active permits for the customer"))

    # check that active permits are all in the same zone
    permit_zone_ids = [permit.parking_zone_id for permit in permits]
    if len(set(permit_zone_ids)) > 1:
        logger.error(
            f"updatePermitsAddress: active permits have conflict parking zones. Customer: {customer}"
        )
        raise ParkingZoneError(ugettext("Conflict parking zones for active permits"))

    response = {"success": True}

    if permit_zone_ids[0] == new_zone.id:
        logger.info("No changes to the parking zone")
        return response

    fixed_period_permits = permits.fixed_period()
    if len(fixed_period_permits) > 0:
        # There can be two cases regarding customer's active permits:
        #
        # 1. A single permit or two permits are created at the same time.
        # In this case, there will be a single order for the permit[s],
        # and the total price changes for multiple permits are combined.
        # Only a single refund will be created if the price of the permits
        # goes down.
        #
        # 2. Two permits are created at different times.
        # In this case, permits will have different orders, and the total
        # price change need to be stored separately. We need to create
        # separate refunds also if the price of the permits goes down.
        #
        # The total_price_change_by_order Counter (with permit order as the key)
        # serves the purpose to combine the price change for multiple permits
        # if they belong to the same order and create separate entries otherwise.
        total_price_change_by_order = Counter()
        for permit in fixed_period_permits:
            price_change_list = permit.get_price_change_list(
                new_zone, permit.vehicle.is_low_emission
            )
            permit_total_price_change = sum(
                [item["price_change"] for item in price_change_list]
            )
            total_price_change_by_order.update(
                {permit.latest_order: permit_total_price_change}
            )

        # total price changes for customer's all valid permits
        customer_total_price_change = sum(total_price_change_by_order.values())
        if customer_total_price_change > 0:
            # if price of the permits goes higher, the customer needs to make
            # extra payments through Talpa before the orders can be set to confirmed
            new_order_status = OrderStatus.DRAFT
        else:
            new_order_status = OrderStatus.CONFIRMED

        # update permit to the new zone before creating
        # new order as the price is determined by the
        # new zone
        fixed_period_permits.update(parking_zone=new_zone)

        new_order = Order.objects.create_renewal_order(
            customer, status=new_order_status
        )
        for order, order_total_price_change in total_price_change_by_order.items():
            # create refund for each order
            if order_total_price_change < 0:
                refund = Refund.objects.create(
                    name=str(customer),
                    order=order,
                    amount=-order_total_price_change,
                    iban=iban if iban else "",
                    description=f"Refund for updating permits zone (customer switch address to: {address})",
                )
                logger.info(f"Refund for updating permits zone created: {refund}")
                send_refund_email(RefundEmailType.CREATED, customer)

        if customer_total_price_change > 0:
            # go through talpa checkout process if the price of
            # the permits goes up
            response["checkout_url"] = TalpaOrderManager.send_to_talpa(new_order)
            fixed_period_permits.update(status=ParkingPermitStatus.PAYMENT_IN_PROGRESS)

    # For open ended permits, it's enough to update the permit zone
    # as talpa will get the updated price based on new zone when
    # asking permit price for next month
    open_ended_permits = permits.open_ended()
    open_ended_permits.update(parking_zone=new_zone)

    for permit in permits:
        send_permit_email(PermitEmailType.UPDATED, permit)

    return response
