from django.test import TestCase

from parking_permits.forms import PdfExportForm


class PdfExportFormTestCase(TestCase):
    def test_form_is_valid_when_valid_data_provided(self):
        data = {
            "data_type": "permit",
            "object_id": 1,
        }
        form = PdfExportForm(data)
        self.assertTrue(form.is_valid())

    def test_form_not_valid_when_data_type_not_provided(self):
        data = {
            "object_id": 1,
        }
        form = PdfExportForm(data)
        self.assertFalse(form.is_valid())

    def test_form_not_valid_when_object_id_not_provided(self):
        data = {
            "data_type": "permit",
        }
        form = PdfExportForm(data)
        self.assertFalse(form.is_valid())
