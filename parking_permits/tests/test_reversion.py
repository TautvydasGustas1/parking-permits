import datetime

import reversion
from django.test import TestCase, override_settings

from parking_permits.models import ParkingPermit
from parking_permits.models.parking_permit import ParkingPermitStatus
from parking_permits.reversion import (
    EventType,
    FieldChangeResolver,
    get_obj_changelogs,
    get_reversion_comment,
)
from parking_permits.tests.factories.customer import CustomerFactory
from parking_permits.tests.factories.parking_permit import ParkingPermitFactory
from users.tests.factories.user import UserFactory


@override_settings(LANGUAGE_CODE="en")
class FieldChangeResolverTestCase(TestCase):
    def test_is_changed_return_true_for_time_diff_greater_than_1_millisecond(self):
        dt_1 = datetime.datetime(2021, 10, 1, 0, 0, 0, 0)
        dt_2 = datetime.datetime(2021, 10, 1, 0, 0, 0, 1001)
        field = ParkingPermit._meta.get_field("start_time")
        change_resolver = FieldChangeResolver(field, dt_1, dt_2)
        self.assertTrue(change_resolver.is_changed)

    def test_is_changed_return_false_for_time_diff_not_greater_than_1_millisecond(self):
        dt_1 = datetime.datetime(2021, 10, 1, 0, 0, 0, 0)
        dt_2 = datetime.datetime(2021, 10, 1, 0, 0, 0, 1000)
        field = ParkingPermit._meta.get_field("start_time")
        change_resolver = FieldChangeResolver(field, dt_1, dt_2)
        self.assertFalse(change_resolver.is_changed)

    def test_change_message(self):
        field = ParkingPermit._meta.get_field("status")
        change_resolver = FieldChangeResolver(
            field, ParkingPermitStatus.DRAFT, ParkingPermitStatus.VALID
        )
        self.assertEqual(change_resolver.change_message, "Status: DRAFT --> VALID")

    def test_change_message_return_format_time_for_datetime_field(self):
        dt_1 = datetime.datetime(2021, 10, 1, 9, 0, 0)
        dt_2 = datetime.datetime(2021, 11, 1, 8, 59, 59)
        field = ParkingPermit._meta.get_field("start_time")
        change_resolver = FieldChangeResolver(field, dt_1, dt_2)
        self.assertEqual(
            change_resolver.change_message,
            "Start time: 2021-10-01 09:00:00 --> 2021-11-01 08:59:59",
        )

    def test_change_message_return_string_repr_for_foreginkey_field(self):
        customer_1 = CustomerFactory()
        customer_2 = CustomerFactory()
        field = ParkingPermit._meta.get_field("customer_id")
        change_resolver = FieldChangeResolver(field, customer_1.id, customer_2.id)
        self.assertEqual(
            change_resolver.change_message, f"Customer: {customer_1} --> {customer_2}"
        )


class GetReversionCommentTestCase(TestCase):
    def test_get_created_reversion_comment(self):
        permit = ParkingPermitFactory()
        comment = get_reversion_comment(EventType.CREATED, permit)
        self.assertTrue(comment.startswith("CREATED"))

    @override_settings(LANGUAGE_CODE="en")
    def test_get_changed_reversion_comment(self):
        with reversion.create_revision():
            permit = ParkingPermitFactory(status=ParkingPermitStatus.DRAFT)
        with reversion.create_revision():
            permit.status = ParkingPermitStatus.VALID
            permit.save(update_fields=["status"])
            comment = get_reversion_comment(EventType.CHANGED, permit)
            self.assertEqual(comment, "CHANGED|Status: DRAFT --> VALID")


class GetObjChangeLogsTestCase(TestCase):
    def test_get_changelogs(self):
        user = UserFactory()
        with reversion.create_revision():
            permit = ParkingPermitFactory()
            reversion.set_user(user)
            comment = get_reversion_comment(EventType.CREATED, permit)
            reversion.set_comment(comment)
        with reversion.create_revision():
            permit.status = ParkingPermitStatus.VALID
            permit.save(update_fields=["status"])
            comment = get_reversion_comment(EventType.CHANGED, permit)
            reversion.set_comment(comment)

        changelogs = get_obj_changelogs(permit)
        self.assertEqual(len(changelogs), 2)
        # most recent changelog is in the beginning of th elist
        self.assertEqual(changelogs[0]["event"], EventType.CHANGED)
        self.assertEqual(changelogs[1]["event"], EventType.CREATED)
