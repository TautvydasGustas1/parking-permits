import json

from django import forms
from django.contrib.postgres.forms import SimpleArrayField
from django.utils.translation import ugettext as _

from parking_permits.models.order import OrderPaymentType
from parking_permits.models.refund import RefundStatus
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


class RefundSearchForm(forms.Form):
    q = forms.CharField(required=False)
    status = forms.ChoiceField(
        choices=RefundStatus.choices + [("ALL", "All")], required=False
    )
    start_date = forms.DateField(required=False)
    end_date = forms.DateField(required=False)
    payment_types = SimpleArrayField(
        forms.ChoiceField(choices=OrderPaymentType.choices), required=False
    )
