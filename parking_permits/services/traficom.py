import logging
import xml.etree.ElementTree as ET

import requests
from django.conf import settings
from django.utils import timezone as tz
from django.utils.translation import gettext as _

from parking_permits.exceptions import TraficomFetchVehicleError
from parking_permits.models.driving_class import DrivingClass
from parking_permits.models.vehicle import (
    EmissionType,
    Vehicle,
    VehicleClass,
    VehiclePowerType,
    VehicleUser,
)

logger = logging.getLogger("db")

CONSUMPTION_TYPE_NEDC = "4"
CONSUMPTION_TYPE_WLTP = "10"
VEHICLE_TYPE = 1
LIGHT_WEIGHT_VEHICLE_TYPE = 2
VEHICLE_SEARCH = 841
DRIVING_LICENSE_SEARCH = 890

POWER_TYPE_MAPPER = {
    "01": VehiclePowerType.BENSIN.value,
    "02": VehiclePowerType.DIESEL.value,
    "04": VehiclePowerType.ELECTRIC.value,
}

VEHICLE_SUB_CLASS_MAPPER = {
    "900": VehicleClass.L3eA1,
    "905": VehicleClass.L3eA2,
    "906": VehicleClass.L3eA3,
    "907": VehicleClass.L3eA1E,
    "908": VehicleClass.L3eA2E,
    "909": VehicleClass.L3eA3E,
    "910": VehicleClass.L3eA1T,
    "911": VehicleClass.L3eA2T,
    "912": VehicleClass.L3eA3T,
    "916": VehicleClass.L5eA,
    "917": VehicleClass.L5eB,
    "919": VehicleClass.L6eBP,
    "920": VehicleClass.L6eBU,
}


class Traficom:
    url = settings.TRAFICOM_ENDPOINT
    headers = {"Content-type": "application/xml"}

    def fetch_vehicle_details(self, registration_number):
        et = self._fetch_info(registration_number=registration_number)
        vehicle_detail = et.find(".//ajoneuvonTiedot")

        if not vehicle_detail:
            raise TraficomFetchVehicleError(
                _(
                    f"Could not find vehicle detail with given {registration_number} registration number"
                )
            )

        vehicle_class = vehicle_detail.find("ajoneuvoluokka").text
        vehicle_sub_class = vehicle_detail.findall("ajoneuvoryhmat/ajoneuvoryhma")
        if (
            vehicle_sub_class
            and VEHICLE_SUB_CLASS_MAPPER.get(vehicle_sub_class[-1].text, None)
            is not None
        ):
            vehicle_class = VEHICLE_SUB_CLASS_MAPPER.get(vehicle_sub_class[-1].text)

        if vehicle_class not in VehicleClass:
            raise TraficomFetchVehicleError(
                _(
                    f"Unsupported vehicle class {vehicle_class} for {registration_number}"
                )
            )

        vehicle_identity = et.find(".//tunnus")
        motor = et.find(".//moottori")
        owners_et = et.findall(".//omistajatHaltijat/omistajaHaltija")
        emissions = motor.findall("kayttovoimat/kayttovoima/kulutukset/kulutus")
        inspection_detail = et.find(".//ajoneuvonPerustiedot")
        last_inspection_date = inspection_detail.find("mkAjanLoppupvm")
        emission_type = EmissionType.NEDC
        co2emission = None
        for e in emissions:
            kulutuslaji = e.find("kulutuslaji").text
            if (
                kulutuslaji == CONSUMPTION_TYPE_NEDC
                or kulutuslaji == CONSUMPTION_TYPE_WLTP
            ):
                co2emission = e.find("maara").text
                if kulutuslaji == CONSUMPTION_TYPE_WLTP:
                    emission_type = EmissionType.WLTP

        mass = et.find(".//massa")
        module_weight = mass.find("modulinKokonaismassa")
        technical_weight = mass.find("teknSuurSallKokmassa")
        weight = module_weight if module_weight else technical_weight

        vehicle_power_type = motor.find("kayttovoima")
        vehicle_manufacturer = vehicle_detail.find("merkkiSelvakielinen")
        vehicle_model = vehicle_detail.find("mallimerkinta")
        vehicle_serial_number = vehicle_identity.find("valmistenumero")
        user_ssns = [
            owner_et.find("omistajanTunnus").text
            if owner_et.find("omistajanTunnus")
            else ""
            for owner_et in owners_et
        ]
        vehicle_details = {
            "updated_from_traficom_on": str(tz.now().date()),
            "power_type": POWER_TYPE_MAPPER.get(vehicle_power_type.text),
            "vehicle_class": vehicle_class,
            "manufacturer": vehicle_manufacturer.text,
            "model": vehicle_model.text if vehicle_model is not None else "",
            "weight": int(weight.text) if weight else 0,
            "registration_number": registration_number,
            "euro_class": 6,  # It will always be 6 class atm.
            "emission": float(co2emission) if co2emission else None,
            "emission_type": emission_type,
            "serial_number": vehicle_serial_number.text,
            "last_inspection_date": last_inspection_date.text
            if last_inspection_date is not None
            else None,
        }
        vehicle_users = []
        for user_nin in user_ssns:
            user = VehicleUser.objects.get_or_create(national_id_number=user_nin)
            vehicle_users.append(user[0])
        vehicle = Vehicle.objects.update_or_create(
            registration_number=registration_number, defaults=vehicle_details
        )
        vehicle[0].users.set(vehicle_users)
        return vehicle[0]

    def fetch_driving_licence_details(self, hetu):
        et = self._fetch_info(hetu=hetu)
        driving_licence_et = et.find(".//ajokorttiluokkatieto")
        if not driving_licence_et.find("ajooikeusluokat"):
            raise TraficomFetchVehicleError(
                _("Could not find any driving license information for given customer")
            )

        driving_licence_categories_et = driving_licence_et.findall(
            "viimeisinajooikeus/ajooikeusluokka"
        )
        categories = [
            category.find("ajooikeusluokka").text
            for category in driving_licence_categories_et
        ]

        driving_classes = []
        for category in categories:
            driving_class = DrivingClass.objects.get_or_create(identifier=category)
            driving_classes.append(driving_class[0])

        return {
            "driving_classes": driving_classes,
            "issue_date": driving_licence_et.find("ajokortinMyontamisPvm").text,
        }

    def _fetch_info(self, registration_number=None, hetu=None):
        is_l_type_vehicle = (
            len(registration_number) == 6 if registration_number else False
        )
        vehicle_payload = f"""
            <laji>{LIGHT_WEIGHT_VEHICLE_TYPE if is_l_type_vehicle else VEHICLE_TYPE}</laji>
            <rekisteritunnus>{registration_number}</rekisteritunnus>
        """
        hetu_payload = f"<hetu>{hetu}</hetu>"
        payload = f"""
        <kehys xsi:noNamespaceSchemaLocation="schema.xsd" xmlns:xsi="http://www.w3.org/2001/XMLSchema-instance">
           <yleinen>
              <sanomatyyppi>{settings.TRAFICOM_SANOMA_TYYPPI}</sanomatyyppi>
              <sovellus>{settings.TRAFICOM_SOVELLUS}</sovellus>
              <ymparisto>{settings.TRAFICOM_YMPARISTO}</ymparisto>
              <kayttooikeudet>
                 <tietojarjestelma>
                    <tunnus>{settings.TRAFICOM_USERNAME}</tunnus>
                    <salasana>{settings.TRAFICOM_PASSWORD}</salasana>
                 </tietojarjestelma>
                 <kayttaja />
              </kayttooikeudet>
           </yleinen>
           <sanoma>
              <ajoneuvonHakuehdot>
                 {vehicle_payload if registration_number else hetu_payload}
                 <kyselylaji>{VEHICLE_SEARCH if registration_number else DRIVING_LICENSE_SEARCH}</kyselylaji>
                 <kayttotarkoitus>4</kayttotarkoitus>
                 <asiakas>{settings.TRAFICOM_ASIAKAS}</asiakas>
                 <soku-tunnus>{settings.TRAFICOM_SOKU_TUNNUS}</soku-tunnus>
                 <palvelutunnus>{settings.TRAFICOM_PALVELU_TUNNUS}</palvelutunnus>
              </ajoneuvonHakuehdot>
           </sanoma>
        </kehys>
        """

        response = requests.post(
            self.url,
            data=payload,
            headers=self.headers,
            verify=settings.TRAFICOM_VERIFY_SSL,
        )
        if response.status_code >= 300:
            logger.error(f"Fetching data from traficom failed. Error: {response.text}")
            raise TraficomFetchVehicleError(_("Failed to fetch data from traficom"))

        return ET.fromstring(response.text)
