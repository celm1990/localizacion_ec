from odoo.exceptions import UserError, ValidationError
from odoo.tests import tagged

from odoo.tests.common import SavepointCase


@tagged("post_install", "-at_install")
class EcuadorianNiifTest(SavepointCase):
    @classmethod
    def setUpClass(cls, chart_template_ref="l10n_ec_niif.ec_chart_template"):
        super().setUpClass(chart_template_ref=chart_template_ref)
        ec_chart_template = cls.env.ref("l10n_ec_niif.ec_chart_template")
        cls.env.company.write({"chart_template_id": ec_chart_template.id})
        cls.company_data = cls.setup_company_data(
            "company_EC_data", ec_chart_template, country_id=cls.env.ref("base.ec").id
        )
        cls.company = cls.company_data["company"]
        cls.env.user.write(
            {
                "company_id": cls.company.id,
            }
        )

    def setUp(self):
        super(EcuadorianNiifTest, self).setUp()
        self.test_obj1 = self.env["l10n_ec.agency"]
        self.test_agency1 = self.test_obj1.create(
            {
                "name": "Agency001",
                "number": 999,
                "active": True,
            }
        )
        self.test_agency2 = self.test_obj1.create(
            {
                "name": "Agency002",
                "number": 998,
                "active": False,
            }
        )

        self.test_obj2 = self.env["l10n_ec.point.of.emission"]
        self.test_pofe1 = self.test_obj2.create(
            {
                "name": "PofE001",
                "number": "001",
                "agency_id": self.test_agency1.id,
                "type_emission": "pre_printed",
            }
        )

        self.test_pofe2 = self.test_obj2.create(
            {
                "name": "PofE002",
                "number": "001",
                "agency_id": self.test_agency2.id,
                "type_emission": "pre_printed",
            }
        )

        self.test_obj3 = self.env["l10n_ec.sri.authorization"]
        self.test_auth1 = self.test_obj3.create(
            {
                "number": "AUTH001",
                "start_date": "2020-8-1",
                "expiration_date": "2020-8-20",
                "active": True,
            }
        )

        self.test_auth2 = self.test_obj3.create(
            {
                "number": "AUTH002",
                "start_date": "2020-9-1",
                "expiration_date": "2020-9-20",
                "active": True,
            }
        )

        self.test_obj4 = self.env["l10n_ec.sri.authorization.line"]
        self.test_doc1 = self.test_obj4.create(
            {
                "document_type": "invoice",
                "authorization_id": self.test_auth1.id,
                "first_sequence": "1",
                "last_sequence": "100",
                "point_of_emission_id": self.test_pofe1.id,
            }
        )
        self.test_doc2 = self.test_obj4.create(
            {
                "document_type": "invoice",
                "authorization_id": self.test_auth2.id,
                "first_sequence": "101",
                "last_sequence": "200",
                "point_of_emission_id": self.test_pofe2.id,
            }
        )

        self.test_obj5 = self.env["account.move"].with_context(
            internal_type="invoice",
            default_type="out_invoice",
        )
        self.test_invoice1 = self.test_obj5.create(
            {
                "move_type": "out_invoice",
                "l10n_ec_point_of_emission_id": self.test_pofe1.id,
                "l10n_ec_authorization_line_id": self.test_doc1.id,
            }
        )

    def test_creation_data(self):
        self.assertEqual(
            self.test_invoice1.l10n_ec_point_of_emission_id.id,
            self.test_pofe1.id,
            "The PofE/Invoice relationship is incorrect",
        )
        self.assertEqual(
            self.test_invoice1.l10n_ec_authorization_id.id,
            self.test_auth1.id,
            "The Authorization/Invoice relationship is incorrect",
        )

    def test_relationship_active_fiel_agency_pofe(self):
        self.assertIs(
            self.test_pofe2.active,
            self.test_agency2.active,
            "The relationship of the active field of the Agency / PofE is incorrect",
        )

    def test_delete_agency_with_invoice(self):
        """User should never be able to delete a agency with invoice"""
        with self.assertRaises(UserError):
            self.test_agency1.unlink()

    def test_delete_authorization_with_invoice(self):
        """User should never be able to delete a authorization with invoice"""
        with self.assertRaises(UserError):
            self.test_auth1.unlink()

    def test_delete_authorization_with_invoice_see_error(self):
        """User should never be able to delete a authorization with invoice"""
        with self.assertRaises(UserError):
            self.env["l10n_ec.sri.authorization"].search([("id", "=", self.test_auth1.id)]).unlink()

    def test_duplicate_or_cross_date_ranges(self):
        with self.assertRaises(UserError):
            self.test_auth2.write(
                {
                    "start_date": "2020-08-01",
                    "expiration_date": "2020-08-20",
                }
            )

    def test_invoice_date_range_outside(self):
        with self.assertRaises(UserError):
            self.test_invoice1.write(
                {
                    "invoice_date": "2020-09-01",
                }
            )

    def test_check_duplicate_sequence(self):
        with self.assertRaises(ValidationError):
            self.test_doc2.write(
                {
                    "first_sequence": "1",
                    "last_sequence": "100",
                    "point_of_emission_id": self.test_pofe1.id,
                }
            )
