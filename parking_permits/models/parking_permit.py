import json
import logging
from decimal import Decimal

import requests
import reversion
from dateutil.relativedelta import relativedelta
from django.conf import settings
from django.contrib.gis.db import models
from django.db.models import Q
from django.utils import timezone
from django.utils.translation import gettext_lazy as _
from helsinki_gdpr.models import SerializableMixin

from ..constants import ParkingPermitEndType
from ..exceptions import (
    InvalidContractType,
    ParkkihubiPermitError,
    PermitCanNotBeEnded,
    RefundError,
)
from ..utils import diff_months_ceil, get_end_time, get_permit_prices
from .mixins import TimestampedModelMixin
from .parking_zone import ParkingZone
from .vehicle import Vehicle

logger = logging.getLogger("db")


class ParkingPermitType(models.TextChoices):
    RESIDENT = "RESIDENT", _("Resident permit")
    COMPANY = "COMPANY", _("Company permit")


class ContractType(models.TextChoices):
    FIXED_PERIOD = "FIXED_PERIOD", _("Fixed period")
    OPEN_ENDED = "OPEN_ENDED", _("Open ended")


class ParkingPermitStartType(models.TextChoices):
    IMMEDIATELY = "IMMEDIATELY", _("Immediately")
    FROM = "FROM", _("From")


class ParkingPermitStatus(models.TextChoices):
    DRAFT = "DRAFT", _("Draft")
    ARRIVED = "ARRIVED", _("Arrived")
    PROCESSING = "PROCESSING", _("Processing")
    ACCEPTED = "ACCEPTED", _("Accepted")
    REJECTED = "REJECTED", _("Rejected")
    PAYMENT_IN_PROGRESS = "PAYMENT_IN_PROGRESS", _("Payment in progress")
    VALID = "VALID", _("Valid")
    CLOSED = "CLOSED", _("Closed")


class ParkingPermitQuerySet(models.QuerySet):
    def fixed_period(self):
        return self.filter(contract_type=ContractType.FIXED_PERIOD)

    def open_ended(self):
        return self.filter(contract_type=ContractType.OPEN_ENDED)

    def active(self):
        active_status = [
            ParkingPermitStatus.VALID,
            ParkingPermitStatus.PAYMENT_IN_PROGRESS,
        ]
        return self.filter(status__in=active_status)

    def active_after(self, time):
        return self.active().filter(Q(end_time__isnull=True) | Q(end_time__gt=time))


class ParkingPermitManager(SerializableMixin.SerializableManager):
    pass


@reversion.register()
class ParkingPermit(SerializableMixin, TimestampedModelMixin):
    customer = models.ForeignKey(
        "Customer",
        verbose_name=_("Customer"),
        on_delete=models.PROTECT,
        related_name="permits",
    )
    vehicle = models.ForeignKey(
        Vehicle,
        verbose_name=_("Vehicle"),
        on_delete=models.PROTECT,
    )
    parking_zone = models.ForeignKey(
        ParkingZone,
        verbose_name=_("Parking zone"),
        on_delete=models.PROTECT,
    )
    type = models.CharField(
        _("Type"),
        max_length=32,
        choices=ParkingPermitType.choices,
        default=ParkingPermitType.RESIDENT,
    )
    status = models.CharField(
        _("Status"),
        max_length=32,
        choices=ParkingPermitStatus.choices,
        default=ParkingPermitStatus.DRAFT,
    )
    start_time = models.DateTimeField(_("Start time"), default=timezone.now)
    end_time = models.DateTimeField(_("End time"), blank=True, null=True)
    primary_vehicle = models.BooleanField(default=True)
    vehicle_changed = models.BooleanField(default=False)
    synced_with_parkkihubi = models.BooleanField(default=False)
    vehicle_changed_date = models.DateField(
        _("Vehicle changed date"), null=True, blank=True
    )
    contract_type = models.CharField(
        _("Contract type"),
        max_length=16,
        choices=ContractType.choices,
        default=ContractType.OPEN_ENDED,
    )
    start_type = models.CharField(
        _("Start type"),
        max_length=16,
        choices=ParkingPermitStartType.choices,
        default=ParkingPermitStartType.IMMEDIATELY,
    )
    month_count = models.IntegerField(_("Month count"), default=1)
    description = models.TextField(_("Description"), blank=True)
    address = models.ForeignKey(
        "Address",
        verbose_name=_("Address"),
        on_delete=models.PROTECT,
        related_name="permits",
        null=True,
        blank=True,
    )

    serialize_fields = (
        {"name": "id"},
        {"name": "vehicle", "accessor": lambda v: str(v)},
        {"name": "status"},
        {"name": "contract_type"},
        {"name": "start_type"},
        {"name": "start_time"},
        {"name": "end_time"},
        {"name": "month_count"},
        {"name": "description"},
    )

    objects = ParkingPermitManager.from_queryset(ParkingPermitQuerySet)()

    class Meta:
        ordering = ["-id"]
        verbose_name = _("Parking permit")
        verbose_name_plural = _("Parking permits")

    def __str__(self):
        return str(self.id)

    @property
    def is_secondary_vehicle(self):
        return not self.primary_vehicle

    @property
    def consent_low_emission_accepted(self):
        return self.vehicle.consent_low_emission_accepted

    @property
    def latest_order(self):
        """Get latest order for the permit

        Multiple orders can be created for the same permit
        when, for example, the vehicle or the address of
        the permit is changed.
        """
        return self.orders.latest("id") if self.orders.exists() else []

    @property
    def talpa_order_id(self):
        if self.latest_order and self.latest_order.talpa_order_id:
            return self.latest_order.talpa_order_id
        return None

    @property
    def latest_order_items(self):
        """Get latest order items for the permit"""
        return self.order_items.filter(order=self.latest_order)

    @property
    def permit_prices(self):
        if self.is_fixed_period:
            end_time = self.end_time
        else:
            end_time = get_end_time(self.start_time, 1)
        return get_permit_prices(
            self.parking_zone,
            self.vehicle.is_low_emission,
            not self.primary_vehicle,
            self.start_time.date(),
            end_time.date(),
        )

    @property
    def is_valid(self):
        return self.status == ParkingPermitStatus.VALID

    @property
    def is_open_ended(self):
        return self.contract_type == ContractType.OPEN_ENDED

    @property
    def is_fixed_period(self):
        return self.contract_type == ContractType.FIXED_PERIOD

    @property
    def can_end_immediately(self):
        now = timezone.now()
        return self.is_valid and (self.end_time is None or now < self.end_time)

    @property
    def can_end_after_current_period(self):
        return self.is_valid and (
            self.end_time is None or self.current_period_end_time < self.end_time
        )

    @property
    def months_used(self):
        now = timezone.now()
        diff_months = diff_months_ceil(self.start_time, now)
        if self.is_fixed_period:
            return min(self.month_count, diff_months)
        return diff_months

    @property
    def months_left(self):
        if self.is_open_ended:
            return None
        return self.month_count - self.months_used

    @property
    def current_period_start_time(self):
        return self.start_time + relativedelta(months=self.months_used - 1)

    @property
    def current_period_end_time(self):
        return get_end_time(self.start_time, self.months_used)

    @property
    def next_period_start_time(self):
        return self.start_time + relativedelta(months=self.months_used)

    @property
    def can_be_refunded(self):
        return self.is_valid and self.is_fixed_period

    @property
    def total_refund_amount(self):
        return self.get_refund_amount_for_unused_items()

    @property
    def zone_changed(self):
        addresses = [self.customer.primary_address, self.customer.other_address]
        return not any(
            address and address.zone == self.parking_zone for address in addresses
        )

    def get_price_change_list(self, new_zone, is_low_emission):
        """Get a list of price changes if the permit is changed

        Only vehicle and zone change will affect the price

        Args:
            new_zone: new zone used in the permit
            is_low_emission: True if the new vehicle is a low emission one

        Returns:
            A list of price change information
        """
        # TODO: currently, company permit type is not available
        previous_products = self.parking_zone.products.for_resident()
        new_products = new_zone.products.for_resident()
        is_secondary = not self.primary_vehicle
        if self.is_open_ended:
            start_date = timezone.localdate(self.next_period_start_time)
            end_date = start_date + relativedelta(months=1, days=-1)
            previous_product = previous_products.get_for_date(start_date)
            previous_price = previous_product.get_modified_unit_price(
                self.vehicle.is_low_emission,
                is_secondary,
            )
            new_product = new_products.get_for_date(start_date)
            new_price = new_product.get_modified_unit_price(
                is_low_emission,
                is_secondary,
            )
            diff_price = new_price - previous_price
            price_change_vat = (diff_price * new_product.vat).quantize(
                Decimal("0.0001")
            )
            return [
                {
                    "product": new_product.name,
                    "previous_price": previous_price,
                    "new_price": new_price,
                    "price_change_vat": price_change_vat,
                    "price_change": diff_price,
                    "start_date": start_date,
                    "end_date": end_date,
                    "month_count": 1,
                }
            ]

        if self.is_fixed_period:
            # price change affected date range and products
            start_date = timezone.localdate(self.next_period_start_time)
            end_date = timezone.localdate(self.end_time)
            previous_product_iter = previous_products.for_date_range(
                start_date, end_date
            ).iterator()
            new_product_iter = new_products.for_date_range(
                start_date, end_date
            ).iterator()

            # calculate the price change list in the affected date range
            month_start_date = start_date
            previous_product = next(previous_product_iter, None)
            new_product = next(new_product_iter, None)
            price_change_list = []
            while month_start_date < end_date and previous_product and new_product:
                previous_price = previous_product.get_modified_unit_price(
                    self.vehicle.is_low_emission,
                    is_secondary,
                )
                new_price = new_product.get_modified_unit_price(
                    is_low_emission,
                    is_secondary,
                )
                diff_price = new_price - previous_price
                if (
                    len(price_change_list) > 0
                    and price_change_list[-1]["product"] == new_product.name
                    and price_change_list[-1]["price_change"] == diff_price
                ):
                    # if it's the same product and diff price is the same as
                    # previous one, combine the price change by increase the
                    # quantity by 1
                    price_change_list[-1]["month_count"] += 1
                else:
                    # if the product is different or diff price is different,
                    # create a new price change item
                    price_change_vat = (diff_price * new_product.vat).quantize(
                        Decimal("0.0001")
                    )
                    price_change_list.append(
                        {
                            "product": new_product.name,
                            "previous_price": previous_price,
                            "new_price": new_price,
                            "price_change_vat": price_change_vat,
                            "price_change": diff_price,
                            "start_date": month_start_date,
                            "month_count": 1,
                        }
                    )

                month_start_date += relativedelta(months=1)
                if month_start_date > previous_product.end_date:
                    previous_product = next(previous_product_iter, None)
                if month_start_date > new_product.end_date:
                    new_product = next(new_product_iter, None)

            # calculate the end date based on month count in
            # each price change item
            for price_change in price_change_list:
                price_change["end_date"] = price_change["start_date"] + relativedelta(
                    months=price_change["month_count"], days=-1
                )
            return price_change_list

    def end_permit(self, end_type):
        if end_type == ParkingPermitEndType.AFTER_CURRENT_PERIOD:
            end_time = self.current_period_end_time
        else:
            end_time = timezone.now()

        if (
            self.primary_vehicle
            and self.customer.permits.active_after(end_time)
            .exclude(id=self.id)
            .exists()
        ):
            raise PermitCanNotBeEnded(
                _(
                    "Cannot close primary vehicle permit if an active secondary vehicle permit exists"
                )
            )

        self.end_time = end_time
        if end_type == ParkingPermitEndType.IMMEDIATELY:
            self.status = ParkingPermitStatus.CLOSED
        self.save()

    def get_refund_amount_for_unused_items(self):
        if not self.can_be_refunded:
            raise RefundError("This permit cannot be refunded")

        unused_order_items = self.get_unused_order_items()
        total = Decimal(0)
        for order_item, quantity, date_range in unused_order_items:
            total += order_item.unit_price * quantity
        return total

    def get_unused_order_items(self):
        if self.is_open_ended:
            raise InvalidContractType(
                "Cannot get unused order items for open ended permit"
            )

        unused_start_date = timezone.localdate(self.next_period_start_time)
        order_items = self.latest_order_items.filter(
            end_date__gte=unused_start_date
        ).order_by("start_date")

        if len(order_items) == 0:
            return []

        # first order item is partially used, so should calculate
        # the remaining quantity and date range starting from
        # unused_start_date
        first_item = order_items[0]
        first_item_unused_quantity = diff_months_ceil(
            unused_start_date, first_item.end_date
        )
        first_item_with_quantity = [
            first_item,
            first_item_unused_quantity,
            (unused_start_date, first_item.end_date),
        ]

        return [
            first_item_with_quantity,
            *[
                [item, item.quantity, (item.start_date, item.end_date)]
                for item in order_items[1:]
            ],
        ]

    def get_products_with_quantities(self):
        """Return a list of product and quantities for the permit"""
        # TODO: currently, company permit type is not available
        qs = self.parking_zone.products.for_resident()

        if self.is_open_ended:
            permit_start_date = timezone.localdate(self.start_time)
            product = qs.get_for_date(permit_start_date)
            return [[product, 1, (permit_start_date, None)]]

        if self.is_fixed_period:
            permit_start_date = timezone.localdate(self.start_time)
            permit_end_date = timezone.localdate(self.end_time)
            return qs.get_products_with_quantities(permit_start_date, permit_end_date)

    def update_parkkihubi_permit(self):
        response = requests.patch(
            f"{settings.PARKKIHUBI_OPERATOR_ENDPOINT}{str(self.id)}/",
            data=json.dumps(self._get_parkkihubi_data()),
            headers=self._get_parkkihubi_headers(),
        )
        self.synced_with_parkkihubi = response.status_code == 200
        self.save()

        if response.status_code == 200:
            logger.info("Parkkihubi update permit")
        else:
            logger.error(
                "Failed to update permit to pakkihubi."
                f"Error: {response.status_code} {response.reason}. "
                f"Detail: {response.text}"
            )
            raise ParkkihubiPermitError(
                "Cannot update permit to Parkkihubi."
                f"Error: {response.status_code} {response.reason}."
            )

    def create_parkkihubi_permit(self):
        response = requests.post(
            settings.PARKKIHUBI_OPERATOR_ENDPOINT,
            data=json.dumps(self._get_parkkihubi_data()),
            headers=self._get_parkkihubi_headers(),
        )
        self.synced_with_parkkihubi = response.status_code == 201
        self.save()

        if response.status_code == 201:
            logger.info("Parkkihubi permit created")
        else:
            logger.error(
                "Failed to create permit to pakkihubi."
                f"Error: {response.status_code} {response.reason}. "
                f"Detail: {response.text}"
            )
            raise ParkkihubiPermitError(
                "Cannot create permit to Parkkihubi."
                f"Error: {response.status_code} {response.reason}."
            )

    def _get_parkkihubi_headers(self):
        return {
            "Authorization": f"ApiKey {settings.PARKKIHUBI_TOKEN}",
            "Content-Type": "application/json",
        }

    def _get_parkkihubi_data(self):
        start_time = str(self.start_time)
        end_time = (
            str(get_end_time(self.start_time, 30))
            if not self.end_time
            else str(self.end_time)
        )
        return {
            "series": settings.PARKKIHUBI_PERMIT_SERIES,
            "domain": settings.PARKKIHUBI_DOMAIN,
            "external_id": str(self.id),
            "properties": {"permit_type": self.type},
            "subjects": [
                {
                    "start_time": start_time,
                    "end_time": end_time,
                    "registration_number": self.vehicle.registration_number,
                }
            ],
            "areas": [
                {
                    "start_time": start_time,
                    "end_time": end_time,
                    "area": self.parking_zone.name,
                }
            ],
        }
