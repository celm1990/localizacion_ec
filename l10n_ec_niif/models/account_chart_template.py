from odoo import _, models


class AccountChartTemplate(models.Model):
    _inherit = "account.chart.template"

    def _load(self, sale_tax_rate, purchase_tax_rate, company):
        """Set tax calculation rounding method required in Ecuadorian localization"""
        res = super()._load(sale_tax_rate, purchase_tax_rate, company)
        if company.country_id.code == "EC":
            company.write({"tax_calculation_rounding_method": "round_globally"})
        return res

    def _prepare_all_journals(self, acc_template_ref, company, journals_dict=None):
        def _get_default_account(journal_vals, account_type="debit"):
            # Get the default accounts
            default_account = False
            if journal["type"] == "sale":
                default_account = acc_template_ref.get(self.property_account_income_categ_id.id)
            elif journal["type"] == "purchase":
                default_account = acc_template_ref.get(self.property_account_expense_categ_id.id)
            elif journal["type"] == "general" and journal["code"] == _("EXCH"):
                if account_type == "credit":
                    default_account = acc_template_ref.get(self.income_currency_exchange_account_id.id)
                else:
                    default_account = acc_template_ref.get(self.expense_currency_exchange_account_id.id)
            return default_account

        journal_data = super(AccountChartTemplate, self)._prepare_all_journals(acc_template_ref, company, journals_dict)
        if company._localization_use_documents():
            for vals_journal in journal_data:
                if vals_journal["type"] in ["sale", "purchase"]:
                    vals_journal["l10n_latam_internal_type"] = "invoice"
        if company.country_id.code == "EC":
            journals = [
                {
                    "name": _("Customer Debit Notes"),
                    "type": "sale",
                    "code": _("CDN"),
                    "favorite": True,
                    "color": 11,
                    "sequence": 12,
                    "l10n_latam_internal_type": "debit_note",
                },
                {
                    "name": _("Vendor Debit Notes"),
                    "type": "purchase",
                    "code": _("VDN"),
                    "favorite": True,
                    "color": 11,
                    "sequence": 13,
                    "l10n_latam_internal_type": "debit_note",
                },
                {
                    "name": _("Liquidation of Purchases"),
                    "type": "purchase",
                    "code": _("LDP"),
                    "favorite": True,
                    "color": 11,
                    "sequence": 14,
                    "l10n_latam_internal_type": "liquidation",
                },
                {
                    "name": _("Customer Voucher"),
                    "type": "sale",
                    "code": _("SV"),
                    "favorite": True,
                    "color": 12,
                    "sequence": 15,
                    "l10n_latam_use_documents": False,
                },
                {
                    "name": _("Vendor Voucher"),
                    "type": "purchase",
                    "code": _("VV"),
                    "favorite": True,
                    "color": 13,
                    "sequence": 16,
                    "l10n_latam_use_documents": False,
                },
            ]
            for journal in journals:
                vals = {
                    "type": journal["type"],
                    "name": journal["name"],
                    "code": journal["code"],
                    "company_id": company.id,
                    "default_credit_account_id": _get_default_account(journal, "credit"),
                    "default_debit_account_id": _get_default_account(journal, "debit"),
                    "show_on_dashboard": journal["favorite"],
                    "color": journal.get("color", False),
                    "sequence": journal["sequence"],
                    "l10n_latam_internal_type": journal.get("l10n_latam_internal_type"),
                    "l10n_latam_use_documents": journal.get("l10n_latam_use_documents", True),
                }
                journal_data.append(vals)
        return journal_data

    def generate_properties(self, acc_template_ref, company):
        res = super(AccountChartTemplate, self).generate_properties(acc_template_ref, company)
        account_model = self.env["account.account"]
        if company.country_id.code == "EC":
            tag_iva = self.env.ref("l10n_ec_niif.tag_f104_609")
            iva_account = account_model.search(
                [
                    ("code", "=", "101050107"),
                ],
                limit=1,
            )
            renta_account = account_model.search([("code", "=", "101050201")], limit=1)
            company.write(
                {
                    "l10n_ec_withhold_sale_iva_account_id": iva_account.id,
                    "l10n_ec_withhold_sale_rent_account_id": renta_account.id,
                    "l10n_ec_withhold_sale_iva_tag_id": tag_iva.id,
                }
            )
        return res
