from datetime import date

from django.test import TestCase

from parking_permits.utils import diff_months_ceil, diff_months_floor, find_next_date


class DiffMonthsFloorTestCase(TestCase):
    def test_diff_months_floor(self):
        self.assertEqual(diff_months_floor(date(2020, 10, 1), date(2021, 10, 1)), 12)
        self.assertEqual(diff_months_floor(date(2020, 10, 15), date(2021, 10, 1)), 11)
        self.assertEqual(diff_months_floor(date(2021, 9, 1), date(2021, 10, 1)), 1)
        self.assertEqual(diff_months_floor(date(2021, 9, 1), date(2021, 10, 15)), 1)
        self.assertEqual(diff_months_floor(date(2021, 10, 1), date(2021, 10, 15)), 0)
        self.assertEqual(diff_months_floor(date(2021, 10, 15), date(2021, 10, 1)), 0)
        self.assertEqual(diff_months_floor(date(2021, 12, 1), date(2021, 10, 1)), 0)


class DiffMonthsCeilTestCase(TestCase):
    def test_diff_months_ceil(self):
        self.assertEqual(diff_months_ceil(date(2020, 10, 1), date(2021, 10, 1)), 13)
        self.assertEqual(diff_months_ceil(date(2020, 10, 15), date(2021, 10, 1)), 12)
        self.assertEqual(diff_months_ceil(date(2021, 9, 1), date(2021, 10, 1)), 2)
        self.assertEqual(diff_months_ceil(date(2021, 9, 1), date(2021, 10, 15)), 2)
        self.assertEqual(diff_months_ceil(date(2021, 10, 1), date(2021, 10, 15)), 1)
        self.assertEqual(diff_months_ceil(date(2021, 10, 15), date(2021, 10, 1)), 0)
        self.assertEqual(diff_months_ceil(date(2021, 12, 1), date(2021, 10, 1)), 0)


class FindNextDateTestCase(TestCase):
    def test_find_next_date(self):
        self.assertEqual(find_next_date(date(2021, 1, 10), 5), date(2021, 2, 5))
        self.assertEqual(find_next_date(date(2021, 1, 10), 10), date(2021, 1, 10))
        self.assertEqual(find_next_date(date(2021, 1, 10), 20), date(2021, 1, 20))
        self.assertEqual(find_next_date(date(2021, 2, 10), 31), date(2021, 2, 28))
