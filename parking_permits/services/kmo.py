import re

import requests
import xmltodict
from django.conf import settings
from django.contrib.gis.geos import GEOSGeometry
from rest_framework import status


def get_wfs_result(street_name="", street_number_token=""):
    street_number_first_part = re.search(r"^\d+", street_number_token)
    street_number = (
        int(street_number_first_part.group()) if street_number_first_part else 0
    )
    street_address = f"katunimi=''{street_name}'' AND osoitenumero=''{street_number}''"
    query_single_args = [
        "'avoindata:Helsinki_osoiteluettelo'",
        "'geom'",
        f"'{street_address}'",
    ]
    cql_filter = f"CONTAINS(geom,querySingle({','.join(query_single_args)}))"
    type_names = [
        "avoindata:Asukas_ja_yrityspysakointivyohykkeet_alue",
        "avoindata:Helsinki_osoiteluettelo",
    ]

    params = {
        "CQL_FILTER": cql_filter,
        "OUTPUTFORMAT": "json",
        "REQUEST": "GetFeature",
        "SERVICE": "WFS",
        "srsName": "EPSG:4326",
        "TYPENAME": ",".join(type_names),
        "VERSION": "2.0.0",
    }

    response = requests.get(settings.KMO_URL, params=params)

    if response.status_code != status.HTTP_200_OK:
        xml_response = xmltodict.parse(response.content)

        error_message = (
            xml_response.get("ows:ExceptionReport", dict())
            .get("ows:Exception", dict())
            .get("ows:ExceptionText", "Unknown Error")
        )
        raise Exception(error_message)

    result = response.json()

    result_features = [
        feature
        for feature in result.get("features")
        if not (
            feature.get("geometry").get("type") == "Point"
            and feature.get("properties").get("katunimi") != street_name
        )
    ]

    return {**result, "features": result_features}


def parse_street_name_and_number(street_address):
    tokens = street_address.split()

    street_name = tokens[0] if len(tokens) >= 1 else ""

    return dict(
        street_name=street_name,
        street_number=" ".join(tokens[1:]) if len(tokens) else "",
    )


def get_address_detail_from_kmo(street_name, street_number):
    results = get_wfs_result(street_name, street_number)
    address_feature = next(
        feature
        for feature in results.get("features")
        if feature.get("geometry").get("type") == "Point"
    )
    address_property = address_feature.get("properties")
    location = GEOSGeometry(str(address_feature.get("geometry")))
    return {
        "street_name_sv": address_property.get("gatan"),
        "city_sv": address_property.get("staden"),
        "location": location,
    }
