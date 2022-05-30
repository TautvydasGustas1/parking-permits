import logging

from django.db import models, transaction
from django.utils import timezone
from django.utils.translation import gettext_lazy as _
from helsinki_gdpr.models import SerializableMixin

from parking_permits.mixins import TimestampedModelMixin

from ..exceptions import OrderCreationFailed
from ..utils import diff_months_ceil
from .customer import Customer
from .parking_permit import ContractType, ParkingPermit, ParkingPermitStatus
from .product import Product

logger = logging.getLogger("db")


class SubscriptionStatus(models.TextChoices):
    CONFIRMED = "CONFIRMED", _("Confirmed")
    CANCELLED = "CANCELLED", _("Cancelled")


class Subscription(SerializableMixin, TimestampedModelMixin):
    customer = models.ForeignKey(
        Customer, verbose_name=_("Customer"), on_delete=models.PROTECT
    )
    talpa_subscription_id = models.UUIDField(
        _("Talpa subscription id"), unique=True, editable=False, null=True, blank=True
    )
    status = models.CharField(
        _("Status"), max_length=20, choices=SubscriptionStatus.choices
    )
    start_date = models.DateField(_("Start date"))
    end_date = models.DateField(_("End date"))
    period_unit = models.CharField(_("Period unit"), max_length=20)
    period_frequency = models.IntegerField(_("Period frequency"))

    serialize_fields = (
        {"name": "customer"},
        {"name": "status"},
    )

    class Meta:
        verbose_name = _("Subscription")
        verbose_name_plural = _("Subscriptions")

    def __str__(self):
        return f"Subscription #{self.id} ({self.status})"


class OrderPaymentType(models.TextChoices):
    ONLINE_PAYMENT = "ONLINE_PAYMENT", _("Online payment")
    CASHIER_PAYMENT = "CASHIER_PAYMENT", _("Cashier payment")


class OrderStatus(models.TextChoices):
    DRAFT = "DRAFT", _("Draft")
    CONFIRMED = "CONFIRMED", _("Confirmed")
    CANCELLED = "CANCELLED", _("Cancelled")


class OrderManager(SerializableMixin.SerializableManager):
    def _validate_permits(self, permits):
        if len(permits) > 2:
            raise OrderCreationFailed("More than 2 draft permits found")
        if len(permits) == 2:
            if permits[0].contract_type != permits[1].contract_type:
                raise OrderCreationFailed("Permits contract types do not match")
            if permits[0].customer_id != permits[1].customer_id:
                raise OrderCreationFailed("Permits customer do not match")

    @transaction.atomic
    def create_for_permits(self, permits, status=OrderStatus.DRAFT):
        self._validate_permits(permits)

        paid_time = timezone.now() if status == OrderStatus.CONFIRMED else None
        order = Order.objects.create(
            customer=permits[0].customer,
            status=status,
            paid_time=paid_time,
        )

        for permit in permits:
            products_with_quantity = permit.get_products_with_quantities()
            for product, quantity, date_range in products_with_quantity:
                unit_price = product.get_modified_unit_price(
                    permit.vehicle.is_low_emission, permit.is_secondary_vehicle
                )
                start_date, end_date = date_range
                OrderItem.objects.create(
                    order=order,
                    product=product,
                    permit=permit,
                    unit_price=unit_price,
                    payment_unit_price=unit_price,
                    vat=product.vat,
                    quantity=quantity,
                    start_date=start_date,
                    end_date=end_date,
                )

        order.permits.add(*permits)
        return order

    def _validate_customer_permits(self, permits):
        date_ranges = []
        for permit in permits:
            if permit.status != ParkingPermitStatus.VALID:
                raise OrderCreationFailed(
                    "Cannot create renewal order for non-valid permits"
                )
            if permit.is_open_ended:
                raise OrderCreationFailed(
                    "Cannot create renewal order for open ended permits"
                )

            start_date = timezone.localdate(permit.next_period_start_time)
            end_date = timezone.localdate(permit.end_time)
            date_ranges.append([start_date, end_date])

        if all([start_date >= end_date for start_date, end_date in date_ranges]):
            raise OrderCreationFailed(
                "Cannot create renewal order. All permits are ending or ended already."
            )

    @transaction.atomic
    def create_renewal_order(self, customer, status=OrderStatus.DRAFT):
        """
        Create new order for updated permits information that affect
        permit prices, e.g. change address or change vehicle
        """
        customer_permits = ParkingPermit.objects.active().filter(
            contract_type=ContractType.FIXED_PERIOD, customer=customer
        )
        self._validate_customer_permits(customer_permits)

        new_order = Order.objects.create(
            customer=customer,
            status=status,
        )
        for permit in customer_permits:
            start_date = timezone.localdate(permit.next_period_start_time)
            end_date = timezone.localdate(permit.end_time)
            if start_date >= end_date:
                # permit already ended or will be ended after current month period
                continue

            order_item_detail_list = permit.get_unused_order_items()
            product_detail_list = permit.get_products_with_quantities()

            order_item_detail_iter = iter(order_item_detail_list)
            product_detail_iter = iter(product_detail_list)

            order_item_detail = next(order_item_detail_iter, None)
            product_detail = next(product_detail_iter, None)

            while order_item_detail and product_detail:
                product, product_quantity, product_date_range = product_detail
                product_start_date, product_end_date = product_date_range
                (
                    order_item,
                    order_item_quantity,
                    order_item_date_range,
                ) = order_item_detail
                order_item_start_date, order_item_end_date = order_item_date_range

                # find the period in which the months have the same payment price
                period_start_date = max(product_start_date, order_item_start_date)
                period_end_date = min(product_end_date, order_item_end_date)
                period_quantity = diff_months_ceil(period_start_date, period_end_date)

                if period_start_date >= period_end_date:
                    raise ValueError(
                        "Error on product date ranges or order item date ranges"
                    )

                unit_price = product.get_modified_unit_price(
                    permit.vehicle.is_low_emission, permit.is_secondary_vehicle
                )

                # the price the customer needs to pay after deducting the price
                # that the customer has already paid in previous order for this
                # order item
                payment_unit_price = unit_price - order_item.unit_price
                OrderItem.objects.create(
                    order=new_order,
                    product=product,
                    permit=permit,
                    unit_price=unit_price,
                    payment_unit_price=payment_unit_price,
                    vat=product.vat,
                    quantity=period_quantity,
                    start_date=period_start_date,
                    end_date=period_end_date,
                )

                if product_end_date < order_item_end_date:
                    # current product ended but order item is not
                    product_detail = next(product_detail_iter, None)
                elif product_end_date > order_item_end_date:
                    # current order item is ended but product is not
                    order_item_detail = next(order_item_detail_iter, None)
                else:
                    # when the end dates from product and order items are the same
                    product_detail = next(product_detail_iter, None)
                    order_item_detail = next(order_item_detail_iter, None)

        # permits should be added to new order after all
        # calculation and processing are done
        new_order.permits.add(*customer_permits)
        return new_order


class Order(SerializableMixin, TimestampedModelMixin):
    subscription = models.ForeignKey(
        Subscription,
        verbose_name=_("Subscription"),
        null=True,
        blank=True,
        on_delete=models.PROTECT,
    )
    talpa_order_id = models.UUIDField(
        _("Talpa order id"), unique=True, editable=False, null=True, blank=True
    )
    talpa_checkout_url = models.URLField(_("Talpa checkout url"), blank=True)
    talpa_receipt_url = models.URLField(_("Talpa receipt_url"), blank=True)
    payment_type = models.CharField(
        _("Payment type"),
        max_length=50,
        choices=OrderPaymentType.choices,
        default=OrderPaymentType.CASHIER_PAYMENT,
    )
    customer = models.ForeignKey(
        Customer,
        verbose_name=_("Customer"),
        related_name="orders",
        on_delete=models.PROTECT,
    )
    status = models.CharField(
        _("Order status"),
        max_length=50,
        choices=OrderStatus.choices,
        default=OrderStatus.DRAFT,
    )
    paid_time = models.DateTimeField(_("Paid time"), blank=True, null=True)
    permits = models.ManyToManyField(
        ParkingPermit, verbose_name=_("permits"), related_name="orders"
    )
    objects = OrderManager()

    serialize_fields = (
        {"name": "id"},
        {"name": "status"},
        {"name": "order_items"},
    )

    class Meta:
        verbose_name = _("Order")
        verbose_name_plural = _("Orders")

    def __str__(self):
        return f"Order #{self.id} ({self.status})"

    @property
    def is_confirmed(self):
        return self.status == OrderStatus.CONFIRMED

    @property
    def order_permits(self):
        return self.permits.all()

    @property
    def total_price(self):
        return sum([item.total_price for item in self.order_items.all()])

    @property
    def total_price_net(self):
        return sum([item.total_price_net for item in self.order_items.all()])

    @property
    def total_price_vat(self):
        return sum([item.total_price_vat for item in self.order_items.all()])

    @property
    def total_payment_price(self):
        return sum([item.total_payment_price for item in self.order_items.all()])

    @property
    def total_payment_price_net(self):
        return sum([item.total_payment_price_net for item in self.order_items.all()])

    @property
    def total_payment_price_vat(self):
        return sum([item.total_payment_price_vat for item in self.order_items.all()])


class OrderItem(SerializableMixin, TimestampedModelMixin):
    talpa_order_item_id = models.UUIDField(
        _("Talpa order item id"), unique=True, editable=False, null=True, blank=True
    )
    order = models.ForeignKey(
        Order,
        verbose_name=_("Order"),
        related_name="order_items",
        on_delete=models.PROTECT,
    )
    product = models.ForeignKey(
        Product, verbose_name=_("Product"), on_delete=models.PROTECT
    )
    permit = models.ForeignKey(
        ParkingPermit,
        verbose_name=_("Parking permit"),
        related_name="order_items",
        on_delete=models.PROTECT,
    )
    unit_price = models.DecimalField(_("Unit price"), max_digits=6, decimal_places=2)
    payment_unit_price = models.DecimalField(
        _("Payment unit price"), max_digits=6, decimal_places=2
    )
    vat = models.DecimalField(_("VAT"), max_digits=6, decimal_places=4)
    quantity = models.IntegerField(_("Quantity"))
    start_date = models.DateField(_("Start date"), null=True, blank=True)
    end_date = models.DateField(_("End date"), null=True, blank=True)

    serialize_fields = (
        {"name": "product", "accessor": lambda x: str(x)},
        {"name": "unit_price"},
        {"name": "vat_percentage"},
        {"name": "quantity"},
        {"name": "start_date"},
        {"name": "end_date"},
    )

    class Meta:
        verbose_name = _("Order item")
        verbose_name_plural = _("Order items")

    def __str__(self):
        return f"Order item: {self.id}"

    @property
    def vat_percentage(self):
        return self.vat * 100

    @property
    def unit_price_net(self):
        return self.unit_price * (1 - self.vat)

    @property
    def unit_price_vat(self):
        return self.unit_price * self.vat

    @property
    def total_price(self):
        return self.quantity * self.unit_price

    @property
    def total_price_net(self):
        return self.total_price * (1 - self.vat)

    @property
    def total_price_vat(self):
        return self.total_price * self.vat

    @property
    def payment_unit_price_net(self):
        return self.payment_unit_price * (1 - self.vat)

    @property
    def payment_unit_price_vat(self):
        return self.payment_unit_price * self.vat

    @property
    def total_payment_price(self):
        return self.quantity * self.payment_unit_price

    @property
    def total_payment_price_net(self):
        return self.total_payment_price * (1 - self.vat)

    @property
    def total_payment_price_vat(self):
        return self.total_payment_price * self.vat
