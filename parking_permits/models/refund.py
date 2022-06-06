from django.contrib.gis.db import models
from django.utils.translation import gettext_lazy as _

from .mixins import TimestampedModelMixin, UserStampedModelMixin


class RefundStatus(models.TextChoices):
    OPEN = "OPEN", _("Open")
    REQUEST_FOR_APPROVAL = "REQUEST_FOR_APPROVAL", _("Request for approval")
    ACCEPTED = "ACCEPTED", _("Accepted")
    REJECTED = "REJECTED", _("Rejected")


class Refund(TimestampedModelMixin, UserStampedModelMixin):
    name = models.CharField(_("Name"), max_length=200, blank=True)
    order = models.OneToOneField(
        "Order",
        verbose_name=_("Permit"),
        on_delete=models.PROTECT,
        related_name="refund",
    )
    amount = models.DecimalField(
        _("Amount"), default=0.00, max_digits=6, decimal_places=2
    )
    iban = models.CharField(max_length=30, blank=True)
    status = models.CharField(
        _("Status"),
        max_length=32,
        choices=RefundStatus.choices,
        default=RefundStatus.OPEN,
    )
    description = models.TextField(_("Description"), blank=True)

    class Meta:
        verbose_name = _("Refund")
        verbose_name_plural = _("Refunds")

    def __str__(self):
        return f"{self.name} ({self.iban})"
