# Part of Odoo. See LICENSE file for full copyright and licensing details.

from odoo import fields, models


class ResConfigSettings(models.TransientModel):

    _inherit = "res.config.settings"

    l10n_ec_consumidor_final_limit = fields.Float(
        string="Invoice Sales Limit Final Consumer",
        related="company_id.l10n_ec_consumidor_final_limit",
        readonly=False,
    )

    l10n_ec_withhold_sale_iva_account_id = fields.Many2one(
        comodel_name="account.account",
        string="Withhold Sales IVA Account",
        related="company_id.l10n_ec_withhold_sale_iva_account_id",
        readonly=False,
    )

    l10n_ec_request_sri_validation_cancel_doc = fields.Boolean(
        string="Request sri validation for cancel documents",
        related="company_id.l10n_ec_request_sri_validation_cancel_doc",
        readonly=False,
    )

    l10n_ec_withhold_sale_iva_tag_id = fields.Many2one(
        comodel_name="account.account.tag",
        string="Withhold Sales IVA Account Tag",
        related="company_id.l10n_ec_withhold_sale_iva_tag_id",
        readonly=False,
    )

    l10n_ec_withhold_sale_rent_account_id = fields.Many2one(
        comodel_name="account.account",
        string="Withhold Sales Rent Account",
        related="company_id.l10n_ec_withhold_sale_rent_account_id",
        readonly=False,
    )
    l10n_ec_withhold_iva_credit_card_account_id = fields.Many2one(
        related="company_id.l10n_ec_withhold_iva_credit_card_account_id",
        readonly=False,
    )

    l10n_ec_withhold_rent_credit_card_account_id = fields.Many2one(
        related="company_id.l10n_ec_withhold_rent_credit_card_account_id",
        readonly=False,
    )

    l10n_ec_withhold_journal_id = fields.Many2one(
        comodel_name="account.journal",
        string="Withhold Journal",
        related="company_id.l10n_ec_withhold_journal_id",
        readonly=False,
    )
    l10n_ec_type_supplier_authorization = fields.Selection(
        related="company_id.l10n_ec_type_supplier_authorization", readonly=False
    )
    l10n_ec_cn_reconcile_policy = fields.Selection(related="company_id.l10n_ec_cn_reconcile_policy", readonly=False)
    # configuracion para facturacion electronica
    l10n_ec_type_environment = fields.Selection(
        [
            ("test", "Test"),
            ("production", "Production"),
        ],
        string="Environment  type for electronic documents",
        related="company_id.l10n_ec_type_environment",
        readonly=False,
    )
    l10n_ec_type_conection_sri = fields.Selection(
        [
            ("online", "On-Line"),
            ("offline", "Off-Line"),
        ],
        string="Connection type with SRI",
        related="company_id.l10n_ec_type_conection_sri",
        readonly=False,
    )
    l10n_ec_key_type_id = fields.Many2one(
        "sri.key.type",
        "Certificate File",
        related="company_id.l10n_ec_key_type_id",
        readonly=False,
    )
    l10n_ec_ws_receipt_test = fields.Char(
        "URL WS for testing on SRI for documents reception",
        config_parameter="l10n_ec_ws_receipt_test",
    )
    l10n_ec_ws_auth_test = fields.Char(
        "URL WS for Testing environment on SRI for documents authorization",
        config_parameter="l10n_ec_ws_auth_test",
    )
    l10n_ec_ws_receipt_production = fields.Char(
        "URL WS for Production environment on SRI for documents reception",
        config_parameter="l10n_ec_ws_receipt_production",
    )
    l10n_ec_ws_auth_production = fields.Char(
        "URL WS for Production environment on SRI for documents authorization",
        config_parameter="l10n_ec_ws_auth_production",
    )
    l10n_ec_electronic_invoice = fields.Boolean(
        "Authorized for Invoice?",
        related="company_id.l10n_ec_electronic_invoice",
        readonly=False,
    )
    l10n_ec_electronic_withhold = fields.Boolean(
        "Authorized for Withholding?",
        related="company_id.l10n_ec_electronic_withhold",
        readonly=False,
    )
    l10n_ec_electronic_credit_note = fields.Boolean(
        "Authorized for Credit Note?",
        related="company_id.l10n_ec_electronic_credit_note",
        readonly=False,
    )
    l10n_ec_electronic_debit_note = fields.Boolean(
        "Authorized for Debit Note?",
        related="company_id.l10n_ec_electronic_debit_note",
        readonly=False,
    )
    l10n_ec_electronic_liquidation = fields.Boolean(
        "Authorized for Purchase Liquidation?",
        related="company_id.l10n_ec_electronic_liquidation",
        readonly=False,
    )
    # campo para la imagen que va en los documentos electronicos
    l10n_ec_electronic_logo = fields.Binary(
        "Logo for RIDE",
        related="company_id.l10n_ec_electronic_logo",
        readonly=False,
    )
    l10n_ec_max_intentos = fields.Integer(
        "Maximum attempts for authorization",
        related="company_id.l10n_ec_max_intentos",
        readonly=False,
    )
    l10n_ec_ws_timeout = fields.Integer("Timeout Web Service", related="company_id.l10n_ec_ws_timeout", readonly=False)
    l10n_ec_cron_process = fields.Integer(
        "Number Documents Process in Cron",
        related="company_id.l10n_ec_cron_process",
        readonly=False,
    )
    l10n_ec_send_mail_from = fields.Datetime(
        "Sent mail from", related="company_id.l10n_ec_send_mail_from", readonly=False
    )
    l10n_ec_send_mail_invoice = fields.Boolean(
        "Invoice?",
        related="company_id.l10n_ec_send_mail_invoice",
        readonly=False,
    )
    l10n_ec_send_mail_credit_note = fields.Boolean(
        "Credit Note?",
        related="company_id.l10n_ec_send_mail_credit_note",
        readonly=False,
    )
    l10n_ec_send_mail_debit_note = fields.Boolean(
        "Debit Note?",
        related="company_id.l10n_ec_send_mail_debit_note",
        readonly=False,
    )
    l10n_ec_send_mail_retention = fields.Boolean(
        "Withholding?", related="company_id.l10n_ec_send_mail_retention", readonly=False
    )
    l10n_ec_send_mail_liquidation = fields.Boolean(
        "Purchase liquidation?",
        related="company_id.l10n_ec_send_mail_liquidation",
        readonly=False,
    )
    l10n_ec_create_login_for_partners = fields.Boolean(
        "Create login for portal user?",
        related="company_id.l10n_ec_create_login_for_partners",
        readonly=False,
    )
    l10n_ec_invoice_version_xml_id = fields.Many2one(
        "l10n_ec.xml.version",
        string="XML Version for Invoice",
        domain=[("document_type", "=", "invoice")],
        related="company_id.l10n_ec_invoice_version_xml_id",
        readonly=False,
    )
    l10n_ec_withholding_version_xml_id = fields.Many2one(
        "l10n_ec.xml.version",
        string="XML Version for Withholding",
        domain=[("document_type", "=", "withholding")],
        related="company_id.l10n_ec_withholding_version_xml_id",
        readonly=False,
    )
    l10n_ec_credit_note_version_xml_id = fields.Many2one(
        "l10n_ec.xml.version",
        string="XML Version for Credit Note",
        domain=[("document_type", "=", "credit_note")],
        related="company_id.l10n_ec_credit_note_version_xml_id",
        readonly=False,
    )
    l10n_ec_debit_note_version_xml_id = fields.Many2one(
        "l10n_ec.xml.version",
        string="XML Version for Debit Note",
        domain=[("document_type", "=", "debit_note")],
        related="company_id.l10n_ec_debit_note_version_xml_id",
        readonly=False,
    )
    l10n_ec_liquidation_version_xml_id = fields.Many2one(
        "l10n_ec.xml.version",
        string="XML Version for Purchase Liquidation",
        domain=[("document_type", "=", "liquidation")],
        related="company_id.l10n_ec_liquidation_version_xml_id",
        readonly=False,
    )
    l10n_ec_print_ride_main_code = fields.Boolean(
        "Print main product code?",
        related="company_id.l10n_ec_print_ride_main_code",
        readonly=False,
    )
    l10n_ec_print_ride_aux_code = fields.Boolean(
        "Print secondary code?",
        related="company_id.l10n_ec_print_ride_aux_code",
        readonly=False,
    )
    l10n_ec_print_ride_detail1 = fields.Boolean(
        "Print detail additional 1?",
        related="company_id.l10n_ec_print_ride_detail1",
        readonly=False,
    )
    l10n_ec_print_ride_detail2 = fields.Boolean(
        "Print detail additional 2?",
        related="company_id.l10n_ec_print_ride_detail2",
        readonly=False,
    )
    l10n_ec_print_ride_detail3 = fields.Boolean(
        "Print detail additional 3?",
        related="company_id.l10n_ec_print_ride_detail3",
        readonly=False,
    )
    l10n_ec_string_ride_detail1 = fields.Char(
        related="company_id.l10n_ec_string_ride_detail1",
        readonly=False,
    )
    l10n_ec_string_ride_detail2 = fields.Char(
        related="company_id.l10n_ec_string_ride_detail2",
        readonly=False,
    )
    l10n_ec_string_ride_detail3 = fields.Char(
        related="company_id.l10n_ec_string_ride_detail3",
        readonly=False,
    )
    l10n_ec_sri_payment_id = fields.Many2one(
        "l10n_ec.sri.payment.method",
        string="S.R.I Payment Method",
        related="company_id.l10n_ec_sri_payment_id",
        readonly=False,
    )
    l10n_ec_sri_login_url = fields.Char(
        related="company_id.l10n_ec_sri_login_url",
        readonly=False,
    )
    l10n_ec_sri_password = fields.Char(
        related="company_id.l10n_ec_sri_password",
        readonly=False,
    )
    l10n_ec_accounting_account_receivable_fireign_id = fields.Many2one(
        string="Accounting Account Receivable",
        comodel_name="account.account",
        config_parameter="l10n_ec_accounting_account_receivable_fireign_id",
    )
    l10n_ec_accounting_account_payable_fireign_id = fields.Many2one(
        string="Accounting Account Payable",
        comodel_name="account.account",
        config_parameter="l10n_ec_accounting_account_payable_fireign_id",
    )
    l10n_ec_retention_resolution = fields.Char(
        string="Retention Resolution",
        related="company_id.l10n_ec_retention_resolution",
        readonly=False,
    )
    l10n_ec_retention_resolution_number = fields.Integer(
        string="Retention Resolution No.",
        related="company_id.l10n_ec_retention_resolution_number",
        readonly=False,
    )
    l10n_ec_microenterprise_regime_taxpayer = fields.Boolean(
        string="Microenterprise Regime Taxpayer",
        related="company_id.l10n_ec_microenterprise_regime_taxpayer",
        readonly=False,
    )
    l10n_ec_rimpe_regime = fields.Boolean(
        string="Régimen RIMPE",
        related="company_id.l10n_ec_rimpe_regime",
        readonly=False,
    )
    l10n_ec_authorization_expired_days = fields.Integer(
        string="Notificar expiración antes de (días)",
        related="company_id.l10n_ec_authorization_expired_days",
        readonly=False,
    )
