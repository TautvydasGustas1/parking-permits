import logging

from django.conf import settings
from django.contrib.gis.db import models
from django.utils.translation import gettext_lazy as _
from helsinki_gdpr.models import SerializableMixin

from .mixins import TimestampedModelMixin
from .parking_zone import ParkingZone
from ..exceptions import LocationDoesNotExist

logger = logging.getLogger("db")


class Address(SerializableMixin, TimestampedModelMixin):
    street_name = models.CharField(_("Street name"), max_length=128)
    street_name_sv = models.CharField(_("Street name sv"), max_length=128, blank=True)
    street_number = models.CharField(_("Street number"), max_length=128)
    city = models.CharField(_("City"), max_length=128)
    city_sv = models.CharField(_("City sv"), max_length=128, blank=True)
    postal_code = models.CharField(_("Postal code"), max_length=5, blank=True)
    location = models.PointField(
        _("Location (2D)"), srid=settings.SRID, blank=True, null=True
    )
    start_date = models.DateField(_("Start date"), blank=True, null=True)
    end_date = models.DateField(_("End date"), blank=True, null=True)
    _zone = models.ForeignKey(
        ParkingZone,
        verbose_name=_("Zone"),
        db_column="zone",
        null=True,
        blank=True,
        on_delete=models.SET_NULL,
    )

    serialize_fields = (
        {"name": "street_name"},
        {"name": "street_name_sv"},
        {"name": "street_number"},
        {"name": "city"},
        {"name": "city_sv"},
        {"name": "postal_code"},
    )

    class Meta:
        verbose_name = _("Address")
        verbose_name_plural = _("Addresses")

    def __str__(self):
        return f"{self.street_name} {self.street_number}, {self.city}"

    @property
    def zone(self):
        if not self.location:
            raise LocationDoesNotExist('Location is not set')
        try:
            self._zone = ParkingZone.objects.get_for_location(self.location)
            self.save()
            return self._zone
        except ParkingZone.DoesNotExist:
            logger.warning(f"Cannot find parking zone for the address {self}")
