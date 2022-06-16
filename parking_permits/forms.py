import json

from django import forms
from django.contrib.postgres.forms import SimpleArrayField
from django.db import models
from django.db.models import Q
from django.utils.translation import ugettext as _

from parking_permits.models import Address, Product
from parking_permits.models.order import Order, OrderPaymentType
from parking_permits.models.parking_permit import ParkingPermit, ParkingPermitStatus
from parking_permits.models.refund import Refund, RefundStatus
from parking_permits.paginator import QuerySetPaginator
from parking_permits.utils import convert_to_snake_case

EXPORT_DATA_TYPE_CHOICES = [
    ("permits", "Permits"),
    ("orders", "Orders"),
    ("refunds", "Refunds"),
    ("products", "Products"),
]

PDF_EXPORT_DATA_TYPE_CHOICES = [
    ("permit", "Permit"),
    ("order", "Order"),
    ("refund", "Refund"),
]


class DataExportForm(forms.Form):
    data_type = forms.ChoiceField(choices=EXPORT_DATA_TYPE_CHOICES)
    order_by = forms.CharField(required=False)
    search_items = forms.CharField(required=False)

    def _validate_order_by(self, order_by):
        return (
            isinstance(order_by, dict)
            and order_by.get("order_fields")
            and order_by.get("order_direction")
        )

    def clean_order_by(self):
        value = self.cleaned_data.get("order_by")
        if not value:
            return None
        try:
            order_by = json.loads(value)
            converted_order_by = convert_to_snake_case(order_by)
            if self._validate_order_by(converted_order_by):
                return converted_order_by
            else:
                raise forms.ValidationError(_("Invalid order by"), code="invalid_data")
        except json.JSONDecodeError:
            raise forms.ValidationError(_("Invalid order by"), code="decode_error")

    def _validate_search_item(self, search_item):
        return (
            isinstance(search_item, dict)
            and search_item.get("match_type")
            and search_item.get("fields")
            and search_item.get("value")
        )

    def clean_search_items(self):
        value = self.cleaned_data.get("search_items")
        if not value:
            return None
        try:
            search_items = json.loads(value)
            converted_search_items = convert_to_snake_case(search_items)
            if all(
                [
                    self._validate_search_item(search_item)
                    for search_item in converted_search_items
                ]
            ):
                return converted_search_items
            else:
                raise forms.ValidationError(
                    _("Invalid search items"), code="invalid_data"
                )
        except json.JSONDecodeError:
            raise forms.ValidationError(_("Invalid search items"), code="decode_error")


class PdfExportForm(forms.Form):
    data_type = forms.ChoiceField(choices=PDF_EXPORT_DATA_TYPE_CHOICES)
    object_id = forms.IntegerField()


class OrderDirection(models.TextChoices):
    DESC = "DESC"
    ASC = "ASC"


class SearchFormBase(forms.Form):
    page = forms.IntegerField(min_value=1, required=False)
    order_field = forms.CharField(required=False)
    order_direction = forms.ChoiceField(choices=OrderDirection.choices, required=False)

    def filter_queryset(self, qs):
        return qs

    def page_queryset(self, qs):
        paginator = QuerySetPaginator(qs, self.cleaned_data)
        return {
            "page_info": paginator.page_info,
            "objects": paginator.object_list,
        }

    def get_order_fields_mapping(self):
        return {}

    def get_model_class(self):
        raise NotImplementedError

    def order_queryset(self, qs):
        order_field = self.cleaned_data.get("order_field")
        order_fields_mapping = self.get_order_fields_mapping()
        model_fields = order_fields_mapping.get(order_field)
        if not model_fields:
            return qs.order_by("-id")
        order_direction = self.cleaned_data.get("order_direction")
        if order_direction and order_direction == OrderDirection.DESC:
            model_fields = [f"-{field}" for field in model_fields]
        return qs.order_by(*model_fields)

    def get_queryset(self):
        model_class = self.get_model_class()
        qs = self.filter_queryset(model_class.objects.all())
        return self.order_queryset(qs)

    def get_paged_queryset(self):
        return self.page_queryset(self.get_queryset())


class PermitSearchForm(SearchFormBase):
    q = forms.CharField(required=False)
    status = forms.ChoiceField(
        choices=ParkingPermitStatus.choices + [("ALL", "All")],
        required=False,
    )

    def get_model_class(self):
        return ParkingPermit

    def get_order_fields_mapping(self):
        return {
            "name": ["customer__first_name", "customer__last_name"],
            "nationalIdNumber": ["customer__national_id_number"],
            "registrationNumber": ["vehicle__registration_number"],
            "primaryAddress": [
                "customer__primary_address__street_name",
                "customer__primary_address__street_number",
            ],
            "otherAddress": [
                "customer__other_address__street_name",
                "customer__other_address__street_number",
            ],
            "parkingZone": ["parking_zone__name"],
            "startTime": ["start_time"],
            "endTime": ["end_time"],
            "status": ["status"],
        }

    def filter_queryset(self, qs):
        q = self.cleaned_data.get("q")
        status = self.cleaned_data.get("status")
        if status and status != "ALL":
            qs = qs.filter(status=status)
        if q:
            if q.isdigit():
                query = Q(id=int(q))
            else:
                query = (
                    Q(customer__first_name__icontains=q)
                    | Q(customer__last_name__icontains=q)
                    | Q(customer__national_id_number=q)
                    | Q(vehicle__registration_number=q)
                )
            qs = qs.filter(query)
        return qs


class RefundSearchForm(SearchFormBase):
    q = forms.CharField(required=False)
    status = forms.ChoiceField(
        choices=RefundStatus.choices + [("ALL", "All")], required=False
    )
    start_date = forms.DateField(required=False)
    end_date = forms.DateField(required=False)
    payment_types = SimpleArrayField(
        forms.ChoiceField(choices=OrderPaymentType.choices), required=False
    )

    def get_model_class(self):
        return Refund

    def get_order_fields_mapping(self):
        return {
            "id": ["id"],
            "name": ["name"],
            "orderId": ["order_id"],
            "registrationNumber": ["order__permits__vehicle__registration_number"],
            "accountNumber": ["iban"],
            "createdAt": ["created_at"],
            "acceptedAt": ["accepted_at"],
            "status": ["status"],
            "amount": ["amount"],
        }

    def filter_queryset(self, qs):
        q = self.cleaned_data.get("q")
        start_date = self.cleaned_data.get("start_date")
        end_date = self.cleaned_data.get("end_date")
        status = self.cleaned_data.get("status")
        payment_types = self.cleaned_data.get("payment_types")
        if q:
            text_filters = (
                Q(name__icontains=q)
                | Q(order__permits__vehicle__registration_number__icontains=q)
                | Q(iban__icontains=q)
            )
            qs = qs.filter(text_filters)
        if start_date:
            qs = qs.filter(created_at__gte=start_date)
        if end_date:
            qs = qs.filter(created_at__lte=end_date)
        if status and status != "ALL":
            qs = qs.filter(status=status)
        if payment_types:
            qs = qs.filter(order__payment_type__in=payment_types)
        return qs


class OrderSearchForm(SearchFormBase):
    def get_model_class(self):
        return Order

    def get_order_fields_mapping(self):
        return {
            "name": ["customer__first_name", "customer__last_name"],
            "permits": ["permits__id"],
            "parkingZone": ["permits__parking_zone__name"],
            "address": [
                "permits__address__street_name",
                "permits__address__street_number",
            ],
            "permitType": ["permits__type"],
            "id": ["id"],
            "paidTime": ["paid_time"],
        }


class ProductSearchForm(SearchFormBase):
    def get_model_class(self):
        return Product

    def get_order_fields_mapping(self):
        return {
            "productType": ["type"],
            "zone": ["zone__name"],
            "price": ["unit_price"],
            "vat": ["vat"],
            "validPeriod": ["start_date"],
            "modifiedAt": ["modified_at"],
            "modifiedBy": ["modified_by"],
        }


class AddressSearchForm(SearchFormBase):
    def get_model_class(self):
        return Address

    def get_order_fields_mapping(self):
        return {
            "streetName": ["street_name"],
            "streetNameSv": ["street_name_sv"],
            "streetNumber": ["street_number"],
            "postalCode": ["postal_code"],
            "city": ["city"],
            "citySv": ["city_sv"],
            "zone": ["_zone__name"],
        }
