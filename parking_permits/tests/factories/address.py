import factory

from parking_permits.models import Address

from .zone import ParkingZoneFactory


class AddressFactory(factory.django.DjangoModelFactory):
    street_name = factory.Faker("street_name", locale="fi")
    street_number = factory.Faker("building_number")
    street_name_sv = factory.Faker("street_name", locale="sv")
    city = factory.Faker("city", locale="fi")
    city_sv = factory.Faker("city", locale="sv")
    postal_code = factory.Faker("postcode")
    _zone = factory.SubFactory(ParkingZoneFactory)
    location = factory.SelfAttribute("_zone.location.centroid")

    class Meta:
        model = Address
