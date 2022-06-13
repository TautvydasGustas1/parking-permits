import calendar
import operator
from functools import reduce

from ariadne import convert_camel_case_to_snake
from dateutil.relativedelta import relativedelta
from django.db.models import Q
from django.utils import timezone
from pytz import utc


def apply_ordering(queryset, order_by):
    fields = order_by["order_fields"]
    direction = order_by["order_direction"]
    if direction == "DESC":
        fields = [f"-{field}" for field in fields]
    return queryset.order_by(*fields)


def apply_filtering(queryset, search_items):
    query = Q()
    connector_ops = {
        "or": operator.or_,
        "and": operator.and_,
    }
    for search_item in search_items:
        connector = search_item["connector"]
        fields = search_item["fields"]
        value = search_item["value"]
        connector_op = connector_ops[connector]
        field_queries = []
        for field in fields:
            field_query = Q(**{f'{field["field_name"]}__{field["match_type"]}': value})
            field_queries.append(field_query)
        search_item_query = reduce(connector_op, field_queries)
        query &= search_item_query
    return queryset.filter(query)


def diff_months_floor(start_date, end_date):
    if start_date > end_date:
        return 0
    diff = relativedelta(end_date, start_date)
    return diff.months + diff.years * 12


def diff_months_ceil(start_date, end_date):
    if start_date > end_date:
        return 0
    diff = relativedelta(end_date, start_date)
    diff_months = diff.months + diff.years * 12
    if diff.days >= 0:
        diff_months += 1
    return diff_months


def get_end_time(start_time, diff_months):
    end_time = start_time + relativedelta(months=diff_months, days=-1)
    return timezone.make_aware(
        end_time.replace(hour=23, minute=59, second=59, microsecond=999999, tzinfo=None)
    )


def find_next_date(dt, day):
    """
    Find the next date with specific day number after given date.
    If the day number of given date matches the day, the original
    date will be returned.

    Args:
        dt (datetime.date): the starting date to search for
        day (int): the day number of found date

    Returns:
        datetime.date: the found date
    """
    try:
        found = dt.replace(day=day)
    except ValueError:
        _, month_end = calendar.monthrange(dt.year, dt.month)
        found = dt.replace(day=month_end)
    if found < dt:
        found += relativedelta(months=1)
    return found


def date_time_to_utc(dt):
    return (
        dt.replace(microsecond=0).astimezone(utc).replace(tzinfo=None).isoformat() + "Z"
    )


def convert_to_snake_case(d):
    if isinstance(d, str):
        return convert_camel_case_to_snake(d)
    if isinstance(d, list):
        return [convert_to_snake_case(i) if isinstance(i, dict) else i for i in d]
    if isinstance(d, dict):
        converted = {}
        for k, v in d.items():
            if isinstance(v, (dict, list)):
                v = convert_to_snake_case(v)
            converted[convert_camel_case_to_snake(k)] = v
        return converted
    return d


def get_permit_prices(
    zone,
    is_low_emission,
    is_secondary,
    permit_start_date,
    permit_end_date,
):
    products = zone.products.for_resident().for_date_range(
        permit_start_date,
        permit_end_date,
    )
    permit_prices = []
    for product in products:
        start_date = max(product.start_date, permit_start_date)
        end_date = min(product.end_date, permit_end_date)
        quantity = diff_months_ceil(start_date, end_date)
        permit_prices.append(
            {
                "original_unit_price": product.unit_price,
                "unit_price": product.get_modified_unit_price(
                    is_low_emission, is_secondary
                ),
                "start_date": start_date,
                "end_date": end_date,
                "quantity": quantity,
            }
        )
    return permit_prices


def get_meta_value(meta_pair_list, meta_pair_key):
    return next(
        (
            meta_pair.get("value")
            for meta_pair in meta_pair_list
            if meta_pair.get("key") == meta_pair_key
        ),
        None,
    )


def snake_to_camel_dict(dictionary):
    res = dict()
    for key in dictionary.keys():
        if isinstance(dictionary[key], dict):
            res[camel_str(key)] = snake_to_camel_dict(dictionary[key])
        elif isinstance(dictionary[key], list):
            res[camel_str(key)] = [snake_to_camel_dict(val) for val in dictionary[key]]
        else:
            res[camel_str(key)] = dictionary[key]
    return res


def camel_str(snake_str):
    first, *others = snake_str.split("_")
    return "".join([first.lower(), *map(str.title, others)])
