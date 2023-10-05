# Part of Odoo. See LICENSE file for full copyright and licensing details.

from odoo import api, fields, models


class ResCompany(models.Model):
    _inherit = "res.company"

    @api.onchange("country_id")
    def onchange_country(self):
        """Ecuadorian companies use round_globally as tax_calculation_rounding_method"""
        for rec in self.filtered(lambda x: x.country_id == self.env.ref("base.ec")):
            rec.tax_calculation_rounding_method = "round_globally"

    def _localization_use_documents(self):
        """Ecuadorian localization use documents"""
        self.ensure_one()
        return True if self.country_id == self.env.ref("base.ec") else super()._localization_use_documents()

    l10n_ec_consumidor_final_limit = fields.Float(string="Invoice Sales Limit Final Consumer", default=50.0)

    l10n_ec_request_sri_validation_cancel_doc = fields.Boolean(
        string="Request sri validation for cancel documents", required=False
    )

    l10n_ec_withhold_sale_iva_account_id = fields.Many2one(
        comodel_name="account.account",
        string="Withhold Sales IVA Account",
        required=False,
    )

    l10n_ec_withhold_sale_iva_tag_id = fields.Many2one(
        comodel_name="account.account.tag",
        string="Withhold Sales IVA Account Tag",
        required=False,
    )

    l10n_ec_withhold_sale_rent_account_id = fields.Many2one(
        comodel_name="account.account",
        string="Withhold Sales Rent Account",
        required=False,
    )
    l10n_ec_withhold_iva_credit_card_account_id = fields.Many2one(
        comodel_name="account.account",
        string="Withhold IVA Account(Credit Card)",
        required=False,
    )

    l10n_ec_withhold_rent_credit_card_account_id = fields.Many2one(
        comodel_name="account.account",
        string="Withhold Rent Account(Credit Card)",
        required=False,
    )

    l10n_ec_withhold_journal_id = fields.Many2one(
        comodel_name="account.journal", string="Withhold Journal", required=False
    )
    l10n_ec_type_supplier_authorization = fields.Selection(
        [
            ("simple", "Simple"),
            ("complete", "Complete"),
        ],
        string="Type of Suppliers authorization",
        default="simple",
    )
    l10n_ec_cn_reconcile_policy = fields.Selection(
        [
            ("restrict", "Restrict greater than Invoice"),
            ("open", "Always Allow"),
        ],
        string="Conciliation Policy for Credit Note",
        default="restrict",
    )
    # campos para facturacion electronica
    l10n_ec_type_environment = fields.Selection(
        [
            ("test", "Test"),
            ("production", "Production"),
        ],
        string="Environment  type for electronic documents",
        default="test",
    )
    l10n_ec_type_conection_sri = fields.Selection(
        [
            ("online", "On-Line"),
            ("offline", "Off-Line"),
        ],
        string="Connection type with SRI",
        default="offline",
    )
    l10n_ec_key_type_id = fields.Many2one("sri.key.type", "Certificate File", ondelete="restrict")
    l10n_ec_electronic_invoice = fields.Boolean("Authorized for Invoice?")
    l10n_ec_electronic_withhold = fields.Boolean("Authorized for Withholding?")
    l10n_ec_electronic_credit_note = fields.Boolean("Authorized for Credit Note?")
    l10n_ec_electronic_debit_note = fields.Boolean("Authorized for Debit Note?")
    l10n_ec_electronic_liquidation = fields.Boolean("Authorized for Purchase Liquidation?")
    l10n_ec_invoice_version_xml_id = fields.Many2one(
        "l10n_ec.xml.version",
        string="XML Version for Invoice",
        domain=[("document_type", "=", "invoice")],
    )
    l10n_ec_withholding_version_xml_id = fields.Many2one(
        "l10n_ec.xml.version",
        string="XML Version for Withholding",
        domain=[("document_type", "=", "withholding")],
    )
    l10n_ec_credit_note_version_xml_id = fields.Many2one(
        "l10n_ec.xml.version",
        string="XML Version for Credit Note",
        domain=[("document_type", "=", "credit_note")],
    )
    l10n_ec_debit_note_version_xml_id = fields.Many2one(
        "l10n_ec.xml.version",
        string="XML Version for Debit Note",
        domain=[("document_type", "=", "debit_note")],
    )
    l10n_ec_liquidation_version_xml_id = fields.Many2one(
        "l10n_ec.xml.version",
        string="XML Version for Purchase Liquidation",
        domain=[("document_type", "=", "liquidation")],
    )
    # campo para la imagen que va en los documentos electronicos
    l10n_ec_electronic_logo = fields.Binary("Logo for RIDE")
    l10n_ec_max_intentos = fields.Integer("Maximum attempts for authorization")
    l10n_ec_ws_timeout = fields.Integer("Timeout Web Service", default=30)
    l10n_ec_cron_process = fields.Integer("Number Documents Process in Cron", default=100)
    l10n_ec_send_mail_from = fields.Datetime("Sent mail from", default=lambda self: fields.Datetime.now())
    l10n_ec_send_mail_invoice = fields.Boolean(
        "Invoice?",
        default=True,
    )
    l10n_ec_send_mail_credit_note = fields.Boolean("Credit Note?", default=True)
    l10n_ec_send_mail_debit_note = fields.Boolean("Debit Note?", default=True)
    l10n_ec_send_mail_retention = fields.Boolean("Withholding?", default=True)
    l10n_ec_send_mail_liquidation = fields.Boolean("Purchase liquidation?", default=True)
    l10n_ec_create_login_for_partners = fields.Boolean(
        "Create login for portal user?",
        default=False,
    )
    l10n_ec_print_ride_main_code = fields.Boolean("Print main product code?", default=True)
    l10n_ec_print_ride_aux_code = fields.Boolean("Print secondary code?", default=False)
    l10n_ec_print_ride_detail1 = fields.Boolean("Print detail additional 1?", default=True)
    l10n_ec_print_ride_detail2 = fields.Boolean("Print detail additional 2?", default=False)
    l10n_ec_print_ride_detail3 = fields.Boolean("Print detail additional 3?", default=False)
    l10n_ec_string_ride_detail1 = fields.Char("Nombre Detalle 1")
    l10n_ec_string_ride_detail2 = fields.Char("Nombre Detalle 2")
    l10n_ec_string_ride_detail3 = fields.Char("Nombre Detalle 3")

    l10n_ec_sri_payment_id = fields.Many2one("l10n_ec.sri.payment.method", string="S.R.I Payment Method")

    def get_contribuyente_data(self, date=None):
        sri_resolution_model = self.env["l10n_ec.sri.company.resolution"]
        if not date:
            date = fields.Date.context_today(self)
        sri_resolution_recs = sri_resolution_model.search([("date_from", "<=", date), ("company_id", "=", self.id)])
        sri_resolution_rec = sri_resolution_model.browse()
        for sri_resolution in sri_resolution_recs:
            if not sri_resolution.date_to or sri_resolution.date_to >= date:
                sri_resolution_rec = sri_resolution
        return sri_resolution_rec and sri_resolution_rec.resolution or ""

    def get_l10n_ec_documents_electronic_rejected(self):
        self.ensure_one()
        return (
            self.env["sri.xml.data"]
            .with_context(
                allowed_company_ids=self.ids,
                l10n_ec_xml_call_from_cron=True,
            )
            ._get_documents_rejected(self)
        )

    l10n_ec_sri_login_url = fields.Char(
        string="Sri Login URL",
        required=False,
        default="https://srienlinea.sri.gob.ec/movil-servicios/api/v2.0/secured",
    )

    l10n_ec_sri_password = fields.Char(string="Sri Portal Password", required=False)
    l10n_ec_retention_resolution = fields.Char(string="Retention Resolution")
    l10n_ec_retention_resolution_number = fields.Integer(string="Retention Resolution No.")
    l10n_ec_microenterprise_regime_taxpayer = fields.Boolean(string="Microenterprise Regime Taxpayer", required=False)
    l10n_ec_rimpe_regime = fields.Boolean(string="Régimen RIMPE", required=False)
    l10n_ec_authorization_expired_days = fields.Integer(
        string="Notificar expiración antes de (días)",
        default=lambda *a: 5,
        help="Cuando el número de días antes de expirar la autorización sea "
        "menor o igual al número configurado, se enviará la notificación correspondiente",
    )

    @api.model
    def date_expire_send_mail(self):
        keys_expired = self.env["sri.key.type"].search([])
        notification = []
        company = self.env.company
        authorization_days = company.l10n_ec_authorization_expired_days
        for key in keys_expired:
            expiration_date = key.expire_date
            total_date = expiration_date - fields.Date.context_today(self)
            days = round(total_date.days + (total_date.seconds / 86400.0), 0)
            if days <= authorization_days:
                notification.append("Nombre: " + key.name)
                notification.append("Fecha expiración: " + str(key.expire_date))
                notification.append("La llave expira en " + str(days) + " dias")
        return notification
