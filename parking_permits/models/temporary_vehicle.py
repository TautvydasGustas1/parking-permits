from django.contrib.gis.db import models
from django.utils import timezone as tz
from django.utils.translation import gettext_lazy as _

from .mixins import TimestampedModelMixin
from .vehicle import Vehicle


class TemporaryVehicle(TimestampedModelMixin):
    vehicle = models.ForeignKey(
        Vehicle,
        verbose_name=_("Vehicle"),
        on_delete=models.PROTECT,
    )
    start_time = models.DateTimeField(_("Start time"), default=tz.now)
    end_time = models.DateTimeField(_("End time"))
    is_active = models.BooleanField(default=True)

    def __str__(self):
        return str(self.vehicle)
