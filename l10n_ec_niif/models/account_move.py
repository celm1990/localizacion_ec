import json
import logging
import re
from xml.etree.ElementTree import SubElement

from lxml import etree

from odoo import _, api, fields, models, tools
from odoo.exceptions import UserError, ValidationError
from odoo.tools import float_compare, float_is_zero
from odoo.tools.misc import formatLang
from odoo.tools.safe_eval import safe_eval

from ..models import modules_mapping

_logger = logging.getLogger(__name__)


class L10nECIdentificationType(models.Model):
    _name = "l10n_ec.identification.type"

    code = fields.Char(string="Code", required=True)
    name = fields.Char(string="Name", required=True)
    document_type_ids = fields.Many2many("l10n_latam.document.type", string="Tipos de Transacciones Asociadas")
    sale_invoice_document_type_id = fields.Many2one(
        comodel_name="l10n_latam.document.type",
        string="Default Sales Document Type for Invoices",
        required=False,
    )
    sale_credit_note_document_type_id = fields.Many2one(
        comodel_name="l10n_latam.document.type",
        string="Default Sales Document Type for Credit Notes",
        required=False,
    )
    sale_debit_note_document_type_id = fields.Many2one(
        comodel_name="l10n_latam.document.type",
        string="Default Sales Document Type for Debit Notes",
        required=False,
    )
    purchase_invoice_document_type_id = fields.Many2one(
        comodel_name="l10n_latam.document.type",
        string="Default Purchases Document Type for Invoices",
        required=False,
    )
    purchase_credit_note_document_type_id = fields.Many2one(
        comodel_name="l10n_latam.document.type",
        string="Default Purchases Document Type for Credit Notes",
        required=False,
    )
    purchase_debit_note_document_type_id = fields.Many2one(
        comodel_name="l10n_latam.document.type",
        string="Default Purchases Document Type for Debit Notes",
        required=False,
    )
    purchase_liquidation_document_type_id = fields.Many2one(
        comodel_name="l10n_latam.document.type",
        string="Default Document Type for Purchase's Liquidation",
        required=False,
    )

    def _name_search(self, name, args=None, operator="ilike", limit=100, name_get_uid=None):
        args = args or []
        recs = self.browse()
        res = super(L10nECIdentificationType, self)._name_search(name, args, operator, limit, name_get_uid)
        if not res and name:
            recs = self.search([("name", operator, name)] + args, limit=limit)
            if not recs:
                recs = self.search([("code", operator, name)] + args, limit=limit)
            if recs:
                res = models.lazy_name_get(self.browse(recs.ids).with_user(name_get_uid)) or []
        return res

    def name_get(self):
        res = []
        for r in self:
            name = "{} - {}".format(r.code, r.name)
            res.append((r.id, name))
        return res


class AccountMove(models.Model):
    _inherit = [
        "account.move",
        "l10n_ec.common.document",
        "l10n_ec.common.document.electronic",
    ]
    _name = "account.move"

    @api.model
    def _get_default_journal(self):
        journal_model = self.env["account.journal"]
        domain = []
        company_id = self._context.get("default_company_id") or self.env.company.id
        if self.env["res.company"].browse(company_id).country_id.code != "EC":
            return super(AccountMove, self)._get_default_journal()
        internal_type = self._context.get("internal_type", "")
        move_type = self._context.get("default_type", "entry")
        journal_type = "general"
        if move_type in self.get_sale_types(include_receipts=True):
            journal_type = "sale"
        elif move_type in self.get_purchase_types(include_receipts=True):
            journal_type = "purchase"
        if self.env.context.get("default_type", "") in ("out_receipt", "in_receipt"):
            domain = [
                ("company_id", "=", company_id),
                (
                    "type",
                    "=",
                    "sale" if self.env.context.get("default_type") == "out_receipt" else "purchase",
                ),
                ("l10n_latam_use_documents", "=", False),
            ]
        elif internal_type in (
            "invoice",
            "debit_note",
            "credit_note",
            "liquidation",
        ):
            domain = [
                ("company_id", "=", company_id),
                ("type", "=", journal_type),
            ]
            if internal_type == "credit_note":
                domain.append(("l10n_latam_internal_type", "in", ("invoice", internal_type)))
            else:
                domain.append(("l10n_latam_internal_type", "=", internal_type))
        if domain:
            journal = journal_model.search(domain, limit=1)
            if journal:
                self = self.with_context(default_journal_id=journal.id)
        return super(AccountMove, self)._get_default_journal()

    # replace field for change default
    journal_id = fields.Many2one(default=_get_default_journal)
    # replace field from Abstract class for change attributes(readonly and states)
    l10n_ec_point_of_emission_id = fields.Many2one(
        comodel_name="l10n_ec.point.of.emission",
        readonly=True,
        states={"draft": [("readonly", False)]},
    )
    # TODO: ideal que este campo estuviera en el modulo l10n_latam_invoice_document
    # proponerlo en rama master de ser posible
    l10n_latam_internal_type = fields.Selection(
        [
            ("invoice", "Invoices"),
            ("debit_note", "Debit Notes"),
            ("credit_note", "Credit Notes"),
            ("liquidation", "Liquidation"),
        ],
        string="Latam internal type",
        compute="_compute_l10n_latam_document_type",
        store=True,
    )
    # Facturacion electronica
    l10n_ec_is_environment_production = fields.Boolean(
        "Es Ambiente de Produccion?",
        compute="_compute_l10n_ec_is_environment_production",
        store=True,
        index=True,
    )
    l10n_ec_electronic_authorization = fields.Char(readonly=False)
    l10n_ec_original_invoice_id = fields.Many2one(comodel_name="account.move", string="Original Invoice")
    l10n_ec_credit_note_ids = fields.One2many(
        comodel_name="account.move",
        inverse_name="l10n_ec_original_invoice_id",
        string="Credit Notes",
        required=False,
    )
    l10n_ec_refund_ids = fields.One2many(
        comodel_name="l10n_ec.account.invoice.refund",
        inverse_name="invoice_id",
        string="Refunds",
        required=False,
    )
    # campos relacionados al SRI
    l10n_ec_authorization_line_id = fields.Many2one(
        comodel_name="l10n_ec.sri.authorization.line",
        copy=False,
        string="Own Ecuadorian Authorization Line",
    )
    l10n_ec_authorization_id = fields.Many2one(
        comodel_name="l10n_ec.sri.authorization",
        string="Own Ecuadorian Authorization",
        related="l10n_ec_authorization_line_id.authorization_id",
        store=True,
    )
    l10n_ec_type_emission = fields.Selection(
        string="Type Emission",
        selection=[
            ("electronic", "Electronic"),
            ("pre_printed", "Pre Printed"),
            ("auto_printer", "Auto Printer"),
        ],
        required=False,
        default=False,
        readonly=True,
        states={"draft": [("readonly", False)]},
    )
    l10n_ec_sri_authorization_state = fields.Selection(
        string="Authorization state on SRI",
        selection=[
            ("to_check", "To Check"),
            ("valid", "Valid"),
            ("invalid", "Invalid"),
        ],
        readonly=True,
        copy=False,
        default="to_check",
    )
    l10n_ec_document_number = fields.Char(
        string="Ecuadorian Document Number",
        readonly=True,
        compute="_compute_l10n_ec_document_number",
        store=True,
    )
    l10n_ec_invoice_type = fields.Char(
        string="EC Invoice Type",
        compute="_compute_ecuadorian_invoice_type",
        store=True,
    )
    l10n_ec_supplier_authorization_id = fields.Many2one(
        comodel_name="l10n_ec.sri.authorization.supplier",
        string="Supplier Authorization",
        required=False,
    )
    l10n_ec_supplier_authorization_number = fields.Char(string="Supplier Authorization", required=False, size=10)
    l10n_ec_type_supplier_authorization = fields.Selection(related="company_id.l10n_ec_type_supplier_authorization")
    l10n_ec_consumidor_final = fields.Boolean(string="Consumidor Final", compute="_compute_l10n_ec_consumidor_final")
    l10n_ec_start_date = fields.Date("Start Date", related="l10n_ec_authorization_id.start_date")
    l10n_ec_expiration_date = fields.Date("Expiration Date", related="l10n_ec_authorization_id.expiration_date")
    l10n_ec_tax_support_id = fields.Many2one(
        comodel_name="l10n_ec.tax.support",
        string="Tax Support",
        required=False,
    )
    l10n_ec_identification_type_id = fields.Many2one(
        "l10n_ec.identification.type",
        string="Ecuadorian Identification Type",
        store=True,
        compute="_compute_l10n_ec_identification_type",
        compute_sudo=True,
    )
    l10n_ec_tax_support_domain_ids = fields.Many2many(
        comodel_name="l10n_ec.tax.support",
        string="Tax Support Domain",
        compute="_compute_l10n_ec_tax_support_domain",
        compute_sudo=True,
    )
    l10n_ec_is_exportation = fields.Boolean(string="Is Exportation?")
    l10n_ec_tipo_regimen_pago_exterior = fields.Selection(
        [
            ("01", "Régimen general"),
            ("02", "Paraíso fiscal"),
            ("03", "Régimen fiscal preferente o jurisdicción de menor imposición"),
        ],
        string="Tipo de regimen fiscal del exterior",
        states={},
        help="",
    )
    l10n_ec_aplica_convenio_doble_tributacion = fields.Selection(
        [
            ("si", "SI"),
            ("no", "NO"),
        ],
        string="Aplica convenio doble tributación",
        states={},
        help="",
    )
    l10n_ec_pago_exterior_sujeto_retencion = fields.Selection(
        [
            ("si", "SI"),
            ("no", "NO"),
        ],
        string="Pago sujeto a retención",
        states={},
        help="",
    )
    l10n_ec_sri_payment_id = fields.Many2one(
        "l10n_ec.sri.payment.method",
        "SRI Payment Method",
        default=lambda self: self.env.company.l10n_ec_sri_payment_id,
    )
    l10n_ec_foreign = fields.Boolean("Foreign?", related="partner_id.l10n_ec_foreign", store=True)
    l10n_ec_rise = fields.Char("R.I.S.E", copy=False)
    # campos para documentos externos
    l10n_ec_legacy_document = fields.Boolean(
        string="Is External Doc. Modified?",
        help="With this option activated, the system will not require an invoice to issue the Debut or Credit Note",
    )
    l10n_ec_legacy_document_date = fields.Date(string="External Document Date")
    l10n_ec_legacy_document_number = fields.Char(string="External Document Number")
    l10n_ec_legacy_document_authorization = fields.Char(string="External Authorization Number", size=49)
    l10n_ec_credit_days = fields.Integer(string="Días Crédito", compute="_compute_l10n_ec_credit_days", store=True)
    # RETENCIONES
    l10n_ec_point_of_emission_withhold_id = fields.Many2one(
        comodel_name="l10n_ec.point.of.emission",
        string="Point of emission",
        readonly=True,
        copy=False,
        states={"draft": [("readonly", False)]},
    )
    l10n_ec_type_emission_withhold = fields.Selection(
        string="Type emission withhold",
        selection=[
            ("electronic", "Electronic"),
            ("pre_printed", "Pre Printed"),
            ("auto_printer", "Auto Printer"),
        ],
        required=False,
    )
    l10n_ec_authorization_line_withhold_id = fields.Many2one(
        comodel_name="l10n_ec.sri.authorization.line",
        copy=False,
        string="Own Ecuadorian Authorization Line(Withhold)",
    )
    l10n_ec_authorization_withhold_id = fields.Many2one(
        comodel_name="l10n_ec.sri.authorization",
        string="Own Ecuadorian Authorization(Withhold)",
        related="l10n_ec_authorization_line_withhold_id.authorization_id",
        store=True,
    )
    l10n_ec_withhold_number = fields.Char(
        string="Withhold Number",
        required=False,
        readonly=True,
        copy=False,
        size=17,
        states={"draft": [("readonly", False)]},
    )
    l10n_ec_withhold_required = fields.Boolean(
        string="Withhold Required",
        compute="_compute_l10n_ec_withhold_required",
        store=True,
    )
    l10n_ec_withhold_date = fields.Date(
        string="Withhold Date",
        readonly=True,
        states={"draft": [("readonly", False)]},
    )
    l10n_ec_withhold_id = fields.Many2one(comodel_name="l10n_ec.withhold", string="Withhold", required=False)

    l10n_ec_withhold_line_ids = fields.One2many(
        comodel_name="l10n_ec.withhold.line",
        inverse_name="invoice_id",
        string="Withhold Lines",
        required=False,
    )
    l10n_ec_withhold_ids = fields.Many2many(
        comodel_name="l10n_ec.withhold",
        string="Withhold",
        compute="_compute_l10n_ec_withhold_ids",
    )
    l10n_ec_withhold_count = fields.Integer(
        string="Withhold Count", compute="_compute_l10n_ec_withhold_ids", store=False
    )
    l10n_ec_info_aditional_ids = fields.One2many(
        "sri.xml.info.aditional",
        "move_id",
        "Additional Info(RIDE)",
        readonly=True,
        copy=False,
        states={"draft": [("readonly", False)]},
    )

    l10n_ec_delivery_note_numbers = fields.Char(
        string="Delivery Note Numbers", compute="_compute_l10n_ec_delivery_note_numbers"
    )

    def _compute_l10n_ec_delivery_note_numbers(self):
        for rec in self:
            rec.l10n_ec_delivery_note_numbers = ""

    @api.depends(
        "invoice_line_ids.price_unit",
        "invoice_line_ids.product_id",
        "invoice_line_ids.quantity",
        "invoice_line_ids.discount",
        "invoice_line_ids.tax_ids",
        "partner_id",
        "currency_id",
        "company_id",
        "invoice_date",
    )
    def _compute_l10n_ec_amounts(self):
        for move in self:
            move_date = move.invoice_date or fields.Date.context_today(move)
            l10n_ec_base_iva_0 = sum(line.l10n_ec_base_iva_0 for line in move.invoice_line_ids)
            l10n_ec_base_iva = sum(line.l10n_ec_base_iva for line in move.invoice_line_ids)
            l10n_ec_iva = sum(line.l10n_ec_iva for line in move.invoice_line_ids)
            l10n_ec_discount_total = 0.0
            for line in move.invoice_line_ids:
                l10n_ec_discount_total += line._l10n_ec_get_discount_total()
            move.l10n_ec_base_iva_0 = l10n_ec_base_iva_0
            move.l10n_ec_base_iva = l10n_ec_base_iva
            move.l10n_ec_iva = l10n_ec_iva
            move.l10n_ec_discount_total = l10n_ec_discount_total
            move.l10n_ec_base_iva_0_currency = move.currency_id._convert(
                l10n_ec_base_iva_0, move.company_currency_id, move.company_id, move_date
            )
            move.l10n_ec_base_iva_currency = move.currency_id._convert(
                l10n_ec_base_iva, move.company_currency_id, move.company_id, move_date
            )
            move.l10n_ec_iva_currency = move.currency_id._convert(
                l10n_ec_iva, move.company_currency_id, move.company_id, move_date
            )
            move.l10n_ec_discount_total_currency = move.currency_id._convert(
                l10n_ec_discount_total,
                move.company_currency_id,
                move.company_id,
                move_date,
            )

    @api.depends(
        "type",
        "l10n_ec_point_of_emission_id",
        "l10n_latam_document_type_id",
    )
    def _compute_l10n_ec_is_environment_production(self):
        xml_model = self.env["sri.xml.data"]
        for invoice in self:
            if invoice.is_invoice():
                invoice_type = invoice.l10n_ec_get_invoice_type()
                invoice.l10n_ec_is_environment_production = xml_model.l10n_ec_is_environment_production(
                    invoice_type, invoice.l10n_ec_point_of_emission_id
                )
            else:
                invoice.l10n_ec_is_environment_production = False

    @api.depends(
        "l10n_latam_available_document_type_ids", "journal_id", "partner_id.commercial_partner_id.l10n_ec_type_sri"
    )
    @api.depends_context("internal_type")
    def _compute_l10n_latam_document_type(self):
        super(AccountMove, self)._compute_l10n_latam_document_type()
        for move in self.filtered(lambda x: x.state == "draft" and x.company_id.country_id.code == "EC"):
            if move.l10n_ec_identification_type_id:
                if move.type == "in_invoice":
                    if move.journal_id.l10n_latam_internal_type == "liquidation":
                        move.l10n_latam_document_type_id = (
                            move.l10n_ec_identification_type_id.purchase_liquidation_document_type_id.id
                        )
                    elif move.journal_id.l10n_latam_internal_type == "debit_note":
                        move.l10n_latam_document_type_id = (
                            move.l10n_ec_identification_type_id.purchase_debit_note_document_type_id.id
                        )
                    else:
                        move.l10n_latam_document_type_id = (
                            move.l10n_ec_identification_type_id.purchase_invoice_document_type_id.id
                        )
                elif move.type == "in_refund":
                    move.l10n_latam_document_type_id = (
                        move.l10n_ec_identification_type_id.purchase_credit_note_document_type_id.id
                    )
                elif move.type == "out_invoice":
                    if move.l10n_latam_internal_type == "invoice":
                        move.l10n_latam_document_type_id = (
                            move.l10n_ec_identification_type_id.sale_invoice_document_type_id.id
                        )
                    if move.l10n_latam_internal_type == "debit_note":
                        move.l10n_latam_document_type_id = (
                            move.l10n_ec_identification_type_id.sale_debit_note_document_type_id.id
                        )
                elif move.type == "out_refund":
                    move.l10n_latam_document_type_id = (
                        move.l10n_ec_identification_type_id.sale_credit_note_document_type_id.id
                    )
            move.l10n_latam_internal_type = move.l10n_latam_document_type_id.internal_type

    @api.depends(
        "name",
        "l10n_latam_document_type_id",
    )
    def _compute_l10n_ec_document_number(self):
        recs_with_name = self.filtered(lambda x: x.name != "/" and x.company_id.country_id.code == "EC")
        for rec in recs_with_name:
            name = rec.name
            doc_code_prefix = rec.l10n_latam_document_type_id.doc_code_prefix
            if doc_code_prefix and name:
                name = name.split(" ", 1)[-1]
            rec.l10n_ec_document_number = name
        remaining = self - recs_with_name
        remaining.l10n_ec_document_number = False

    @api.depends(
        "type",
        "partner_id",
        "l10n_latam_document_type_id",
        "l10n_ec_type_emission",
        "company_id.country_id",
    )
    def _compute_ecuadorian_invoice_type(self):
        for rec in self:
            l10n_ec_invoice_type = ""
            if rec.company_id.country_id.code == "EC":
                l10n_ec_invoice_type = rec.l10n_ec_get_invoice_type()
            rec.l10n_ec_invoice_type = l10n_ec_invoice_type
            rec.l10n_latam_internal_type = rec.l10n_latam_document_type_id.internal_type

    @api.depends(
        "partner_id.commercial_partner_id.l10n_ec_type_sri",
        "l10n_ec_is_exportation",
        "type",
        "company_id",
    )
    def _compute_l10n_ec_identification_type(self):
        identification_model = self.env["l10n_ec.identification.type"]
        for move in self:
            move.l10n_ec_identification_type_id = False
            if move.company_id.country_id.code != "EC" or not move.partner_id.commercial_partner_id.l10n_ec_type_sri:
                continue
            identification_code = False
            if move.type in ("in_invoice", "in_refund"):
                if move.partner_id.commercial_partner_id.l10n_ec_type_sri == "Ruc":
                    identification_code = "01"
                elif move.partner_id.commercial_partner_id.l10n_ec_type_sri == "Cedula":
                    identification_code = "02"
                elif move.partner_id.commercial_partner_id.l10n_ec_type_sri == "Pasaporte":
                    identification_code = "03"
            elif move.type in ("out_invoice", "out_refund"):
                if not move.l10n_ec_is_exportation:
                    if move.partner_id.commercial_partner_id.l10n_ec_type_sri == "Ruc":
                        identification_code = "04"
                    elif move.partner_id.commercial_partner_id.l10n_ec_type_sri == "Cedula":
                        identification_code = "05"
                    elif move.partner_id.commercial_partner_id.l10n_ec_type_sri == "Pasaporte":
                        identification_code = "06"
                    elif move.partner_id.commercial_partner_id.l10n_ec_type_sri == "Consumidor":
                        identification_code = "07"
                else:
                    if move.partner_id.commercial_partner_id.l10n_ec_type_sri == "Ruc":
                        identification_code = "20"
                    elif move.partner_id.commercial_partner_id.l10n_ec_type_sri == "Pasaporte":
                        identification_code = "21"
            if identification_code:
                move.l10n_ec_identification_type_id = identification_model.search(
                    [("code", "=", identification_code)], limit=1
                )

    @api.depends(
        "l10n_latam_document_type_id",
    )
    def _compute_l10n_ec_tax_support_domain(self):
        tax_support_model = self.env["l10n_ec.tax.support"]
        for move in self:
            move.l10n_ec_tax_support_domain_ids = []
            if move.company_id.country_id.code != "EC":
                continue
            supports = tax_support_model.browse()
            if move.l10n_latam_document_type_id:
                supports = tax_support_model.search(
                    [
                        (
                            "document_type_ids",
                            "in",
                            move.l10n_latam_document_type_id.ids,
                        )
                    ]
                )
            move.l10n_ec_tax_support_domain_ids = supports.ids

    @api.depends("invoice_date", "invoice_date_due")
    def _compute_l10n_ec_credit_days(self):
        now = fields.Date.context_today(self)
        for invoice in self:
            date_invoice = invoice.invoice_date or now
            date_due = invoice.invoice_date_due or date_invoice
            invoice.l10n_ec_credit_days = (date_due - date_invoice).days

    @api.depends(
        "l10n_ec_withhold_line_ids.withhold_id",
    )
    def _compute_l10n_ec_withhold_ids(self):
        for rec in self:
            l10n_ec_withhold_ids = rec.l10n_ec_withhold_line_ids.mapped("withhold_id").ids
            if not l10n_ec_withhold_ids:
                l10n_ec_withhold_ids = rec.l10n_ec_withhold_ids.search([("invoice_id", "=", rec.id)]).ids
            rec.l10n_ec_withhold_ids = l10n_ec_withhold_ids
            rec.l10n_ec_withhold_count = len(l10n_ec_withhold_ids)

    @api.depends("type", "line_ids.tax_ids")
    def _compute_l10n_ec_withhold_required(self):
        group_iva_withhold = self.env.ref("l10n_ec_niif.tax_group_iva_withhold", False)
        group_rent_withhold = self.env.ref("l10n_ec_niif.tax_group_renta_withhold", False)
        for rec in self:
            withhold_required = False
            if rec.type == "in_invoice" and group_iva_withhold and group_rent_withhold:
                withhold_required = any(
                    t.tax_group_id.id in (group_iva_withhold.id, group_rent_withhold.id)
                    for t in rec.line_ids.mapped("tax_ids")
                )
            rec.l10n_ec_withhold_required = withhold_required

    @api.depends("commercial_partner_id")
    def _compute_l10n_ec_consumidor_final(self):
        consumidor_final = self.env.ref("l10n_ec_niif.consumidor_final", False)
        for move in self:
            if consumidor_final and move.commercial_partner_id.id == consumidor_final.id:
                move.l10n_ec_consumidor_final = True
            else:
                move.l10n_ec_consumidor_final = False

    @api.constrains(
        "l10n_ec_supplier_authorization_number",
    )
    def _check_l10n_ec_supplier_authorization_number(self):
        cadena = r"(\d{10})"
        for move in self:
            if move.l10n_ec_supplier_authorization_number and not re.match(
                cadena, move.l10n_ec_supplier_authorization_number
            ):
                raise ValidationError(_("Invalid supplier authorization number, this must be like 0123456789"))

    @api.constrains("l10n_ec_legacy_document_number", "l10n_latam_document_type_id")
    @api.onchange("l10n_ec_legacy_document_number", "l10n_latam_document_type_id")
    def _check_l10n_ec_legacy_document_number(self):
        for invoice in self:
            if invoice.l10n_ec_legacy_document_number and invoice.l10n_latam_document_type_id:
                invoice.l10n_latam_document_type_id._format_document_number(invoice.l10n_ec_legacy_document_number)

    @api.constrains("l10n_ec_withhold_number")
    @api.onchange("l10n_ec_withhold_number")
    def _check_l10n_ec_withhold_number(self):
        for invoice in self:
            if (
                invoice.company_id.country_id.code == "EC"
                and invoice.l10n_ec_withhold_number
                and invoice.l10n_ec_withhold_required
            ):
                if not re.match(r"\d{3}-\d{3}-\d{9}$", invoice.l10n_ec_withhold_number):
                    raise UserError(
                        _("Ecuadorian Document for Withhold %s must be like 001-001-123456789")
                        % (invoice.l10n_ec_withhold_number)
                    )

    @api.constrains(
        "name",
        "l10n_ec_document_number",
        "company_id",
        "type",
        "l10n_latam_document_type_id",
    )
    def _check_l10n_ec_document_number_duplicity(self):
        auth_line_model = self.env["l10n_ec.sri.authorization.line"]
        for move in self.filtered(
            lambda x: x.company_id.country_id.code == "EC"
            and x.l10n_ec_get_invoice_type() in ("out_invoice", "out_refund", "debit_note_out", "liquidation")
            and x.l10n_ec_document_number
        ):
            auth_line_model.with_context(from_constrain=True).validate_unique_value_document(
                move.l10n_ec_get_invoice_type(),
                move.l10n_ec_document_number,
                move.company_id.id,
                move.id,
            )

    @api.constrains("l10n_ec_electronic_authorization", "l10n_ec_type_emission")
    def _check_electronic_authorization_supplier(self):
        string_electronic_authorization = r"(\d{37}$)|(\d{49}$)"
        for rec in self.filtered(lambda x: x.company_id.country_id.code == "EC"):
            if rec.l10n_ec_electronic_authorization and rec.l10n_ec_type_emission == "electronic":
                if len(rec.l10n_ec_electronic_authorization) not in (37, 49):
                    raise ValidationError(
                        _(
                            "The electronic authorization number is incorrect, "
                            "this must be 37 or 49 digits. Check the invoice %s of supplier %s"
                        )
                        % (rec.l10n_latam_document_number, rec.partner_id.display_name)
                    )
                if not re.match(string_electronic_authorization, rec.l10n_ec_electronic_authorization):
                    raise ValidationError(
                        _(
                            "The electronic authorization must have only numbers, "
                            "please check the invoice %s of supplier %s!"
                        )
                        % (rec.l10n_latam_document_number, rec.partner_id.display_name)
                    )

    @api.constrains("l10n_ec_start_date", "l10n_ec_expiration_date", "invoice_date")
    def _check_outside(self):
        if any(
            outside_start
            for outside_start in self
            if outside_start.invoice_date
            and outside_start.l10n_ec_start_date
            and outside_start.invoice_date < outside_start.l10n_ec_start_date
        ):
            raise UserError(_("Invoice date outside defined date range"))
        if any(
            outside_expiration
            for outside_expiration in self
            if outside_expiration.invoice_date
            and outside_expiration.l10n_ec_expiration_date
            and outside_expiration.invoice_date > outside_expiration.l10n_ec_expiration_date
        ):
            raise UserError(_("Invoice date outside defined date range2"))

    def _get_l10n_latam_documents_domain(self):
        if self.company_id.country_id.code != "EC":
            return super(AccountMove, self)._get_l10n_latam_documents_domain()
        if self.env.context.get("internal_type", "") == "liquidation":
            internal_types = ["liquidation"]
            domain = [
                ("internal_type", "in", internal_types),
                ("country_id", "=", self.company_id.country_id.id),
            ]
        else:
            domain = super(AccountMove, self)._get_l10n_latam_documents_domain()
        latam_type = self.l10n_latam_internal_type or self.env.context.get("internal_type") or "invoice"
        if self.type in ("out_refund", "in_refund"):
            latam_type = "credit_note"
        if latam_type and self.l10n_ec_identification_type_id.document_type_ids:
            domain.append(
                (
                    "id",
                    "in",
                    self.l10n_ec_identification_type_id.document_type_ids.filtered(
                        lambda x: x.internal_type == latam_type
                    ).ids,
                )
            )
        return domain

    @api.onchange("partner_id")
    def _onchange_partner_id(self):
        res = super(AccountMove, self)._onchange_partner_id()
        if self.partner_id:
            it_cedula = self.env.ref("l10n_ec_niif.it_cedula", False)
            it_ruc = self.env.ref("l10n_ec_niif.it_ruc", False)
            if self.partner_id.l10n_ec_sri_payment_id:
                self.l10n_ec_sri_payment_id = self.partner_id.l10n_ec_sri_payment_id.id
            if (
                self.l10n_ec_supplier_authorization_id
                and self.l10n_ec_supplier_authorization_id.partner_id != self.partner_id
            ):
                self.l10n_ec_supplier_authorization_id = False
            if self.partner_id.l10n_ec_foreign and self.type in ["in_invoice", "in_refund"]:
                self.l10n_ec_type_emission = False
            if (
                self.is_purchase_document()
                and self.l10n_latam_internal_type != "liquidation"
                and self.partner_id.l10n_latam_identification_type_id
                and self.partner_id.l10n_latam_identification_type_id == it_cedula
                and self.partner_id.country_id == self.env.ref("base.ec")
            ):
                raise UserError(
                    _("The provider {} must not be an identification of type Cedula.".format(self.partner_id.name))
                )
            if (
                self.is_purchase_document()
                and self.l10n_latam_internal_type == "liquidation"
                and self.partner_id.l10n_latam_identification_type_id
                and self.partner_id.l10n_latam_identification_type_id == it_ruc
                and self.partner_id.country_id == self.env.ref("base.ec")
            ):
                raise UserError(
                    _("The provider {} must not be an identification of type RUC.".format(self.partner_id.name))
                )
        return res

    @api.onchange("invoice_date")
    def _onchange_invoice_date(self):
        res = super(AccountMove, self)._onchange_invoice_date()
        if self.invoice_date:
            self.l10n_ec_withhold_date = self.invoice_date
        return res

    def _onchange_l10n_ec_document_number_in(self):
        domain = {}
        warning = {}
        auth_supplier_model = self.env["l10n_ec.sri.authorization.supplier"]
        UtilModel = self.env["l10n_ec.utils"]
        auth_ids = False
        l10n_latam_document_number = self.l10n_latam_document_number
        invoice_date = self.invoice_date or fields.Date.context_today(self)
        if self.partner_id.l10n_ec_foreign:
            return
        if not self.l10n_latam_document_number and not self.l10n_ec_type_emission:
            return
        if self.l10n_latam_document_number and not self.partner_id:
            self.l10n_latam_document_number = False
            warning = {
                "title": _("Information for user"),
                "message": _("Please select partner first"),
            }
            return {"domain": domain, "warning": warning}
        padding = self.l10n_ec_supplier_authorization_id.padding or 9
        if self.l10n_ec_type_emission == "electronic":
            self.l10n_ec_supplier_authorization_id = False
            # si es electronico y ya tengo agencia y punto de impresion, completar el numero
            if l10n_latam_document_number:
                try:
                    (
                        agency,
                        printer_point,
                        sequence_number,
                    ) = UtilModel.split_document_number(l10n_latam_document_number, True)
                    sequence_number = int(sequence_number)
                    sequence_number = auth_supplier_model.fill_padding(sequence_number, padding)
                    l10n_latam_document_number = f"{agency}-{printer_point}-{sequence_number}"
                    # no provocar el inverse nuevamente si el valor del campo es el mismo
                    if self.l10n_latam_document_number != l10n_latam_document_number:
                        self.l10n_latam_document_number = l10n_latam_document_number
                except Exception as ex:
                    _logger.error(tools.ustr(ex))
                    warning = {
                        "title": _("Information for User"),
                        "message": _(
                            "The document number is not valid, must be as 00X-00X-000XXXXXX, Where X is a number"
                        ),
                    }
                    return {"domain": domain, "warning": warning}
                # validar la duplicidad de documentos electronicos
                auth_supplier_model.validate_unique_document_partner(
                    self.l10n_ec_invoice_type,
                    self.l10n_latam_document_number,
                    self.partner_id.id,
                    UtilModel.ensure_id(self),
                )
            return {"domain": domain, "warning": warning}
        if self.company_id.l10n_ec_type_supplier_authorization == "simple":
            return
        auth_data = auth_supplier_model.get_supplier_authorizations(
            self.l10n_ec_invoice_type,
            self.partner_id.id,
            l10n_latam_document_number,
            invoice_date,
        )
        # si hay multiples autorizaciones, pero una de ellas es la que el usuario ha seleccionado, tomar esa autorizacion
        # xq sino, nunca se podra seleccionar una autorizacion
        if auth_data.get("multi_auth", False):
            if (
                self.l10n_ec_supplier_authorization_id
                and self.l10n_ec_supplier_authorization_id.id in auth_data.get("auth_ids", [])
                and l10n_latam_document_number
            ):
                auth_use = self.l10n_ec_supplier_authorization_id
                number_data = l10n_latam_document_number.split("-")
                number_to_check = ""
                if len(number_data) == 3:
                    number_to_check = number_data[2]
                elif len(number_data) == 1:
                    try:
                        number_to_check = str(int(number_data[0]))
                    except Exception as ex:
                        _logger.error(tools.ustr(ex))
                if (
                    number_to_check
                    and int(number_to_check) >= auth_use.first_sequence
                    and int(number_to_check) <= auth_use.last_sequence
                ):
                    l10n_latam_document_number = auth_supplier_model.fill_padding(number_to_check, auth_use.padding)
                    l10n_latam_document_number = (
                        f"{auth_use.agency}-{auth_use.printer_point}-{l10n_latam_document_number}"
                    )
                    # no provocar el inverse nuevamente si el valor del campo es el mismo
                    if self.l10n_latam_document_number != l10n_latam_document_number:
                        self.l10n_latam_document_number = l10n_latam_document_number
                    # si hay ids pasar el id para validar sin considerar el documento actual
                    auth_supplier_model.check_number_document(
                        self.l10n_ec_invoice_type,
                        l10n_latam_document_number,
                        auth_use,
                        invoice_date,
                        UtilModel.ensure_id(self),
                        self.l10n_ec_foreign,
                    )
                    # Si ya escogio una autorizacion, ya deberia dejar de mostrar el mensaje
                    if auth_data.get("message"):
                        auth_data.update({"message": ""})
                else:
                    self.l10n_latam_document_number = ""
                    self.l10n_ec_supplier_authorization_id = False
            else:
                self.l10n_latam_document_number = ""
            if auth_data.get("message", ""):
                warning = {
                    "title": _("Information for User"),
                    "message": auth_data.get("message", ""),
                }
            return {"domain": domain, "warning": warning}
        if not auth_data.get("auth_ids", []) and self.partner_id and l10n_latam_document_number:
            self.l10n_ec_supplier_authorization_id = False
            if auth_data.get("message", ""):
                warning = {
                    "title": _("Information for User"),
                    "message": auth_data.get("message", ""),
                }
            return {"domain": domain, "warning": warning}
        else:
            auth_ids = auth_data.get("auth_ids", [])
            if auth_ids:
                l10n_latam_document_number = auth_data.get("res_number", "")
                # no provocar el inverse nuevamente si el valor del campo es el mismo
                if self.l10n_latam_document_number != l10n_latam_document_number:
                    self.l10n_latam_document_number = l10n_latam_document_number
                self.l10n_ec_supplier_authorization_id = auth_ids[0]
            else:
                self.l10n_ec_supplier_authorization_id = False
        # si el numero esta ingresado, validar duplicidad
        l10n_latam_document_number = auth_data.get("res_number", "")
        if len(l10n_latam_document_number.split("-")) == 3 and auth_ids:
            auth = auth_supplier_model.browse(auth_ids[0])
            # si hay ids pasar el id para validar sin considerar el documento actual
            auth_supplier_model.check_number_document(
                self.l10n_ec_invoice_type,
                l10n_latam_document_number,
                auth,
                invoice_date,
                UtilModel.ensure_id(self),
                self.l10n_ec_foreign,
            )
        return {"domain": domain, "warning": warning}

    def _onchange_l10n_ec_document_number_out(self):
        UtilModel = self.env["l10n_ec.utils"]
        auth_line_model = self.env["l10n_ec.sri.authorization.line"]
        domain = {}
        warning = {}
        prefijo = ""
        if not self.l10n_ec_point_of_emission_id:
            return {"domain": domain, "warning": warning}
        prefijo = f"{self.l10n_ec_point_of_emission_id.agency_id.number}-{self.l10n_ec_point_of_emission_id.number}-"
        if not self.l10n_latam_document_number or self.l10n_latam_document_number == prefijo:
            return {"domain": domain, "warning": warning}
        if self.l10n_ec_point_of_emission_id:
            l10n_latam_document_number = self.l10n_ec_point_of_emission_id.complete_number(
                self.l10n_latam_document_number
            )
            # no provocar el inverse nuevamente si el valor del campo es el mismo
            if self.l10n_latam_document_number != l10n_latam_document_number:
                self.l10n_latam_document_number = l10n_latam_document_number
        doc_find = self.l10n_ec_point_of_emission_id.get_authorization_for_number(
            self.l10n_ec_invoice_type,
            self.l10n_latam_document_number,
            self.invoice_date,
            self.company_id,
        )
        if doc_find:
            self.l10n_ec_authorization_line_id = doc_find
        if len(self.l10n_latam_document_number.split("-")) == 3:
            auth_line_model.validate_unique_value_document(
                self.l10n_ec_invoice_type,
                self.l10n_latam_document_number,
                self.company_id.id,
                UtilModel.ensure_id(self),
            )
        return {"domain": domain, "warning": warning}

    @api.onchange(
        "l10n_ec_type_emission",
    )
    def onchange_l10n_ec_type_emission(self):
        if self.l10n_ec_type_emission == "electronic":
            self.l10n_ec_supplier_authorization_id = False
            self.l10n_ec_supplier_authorization_number = False

    @api.onchange(
        "l10n_ec_supplier_authorization_id",
    )
    def onchange_l10n_ec_supplier_authorization_id(self):
        auth_supplier_model = self.env["l10n_ec.sri.authorization.supplier"]
        UtilModel = self.env["l10n_ec.utils"]
        # al cambiar la autorizacion, si la agencia y punto de impresion
        # no coinciden con el de la autorizacion, pasar esos datos y borrar el numero  actual
        if self.l10n_ec_supplier_authorization_id:
            # si el numero esta completo, verificar si la autorizacion seleccionada es valida para el numero ingresado
            # si es valida no cambiar el numero,
            # pero si no es valida, cambiar el numero para que el usuario ingrese el numero correcto para la autorizacion seleccionada
            is_valid = True
            try:
                agency, printer_point, sequence = self.l10n_latam_document_number.split("-")
                sequence = int(sequence)
                auth_supplier_model.check_number_document(
                    self.l10n_ec_invoice_type,
                    self.l10n_latam_document_number,
                    self.l10n_ec_supplier_authorization_id,
                    self.invoice_date,
                    UtilModel.ensure_id(self),
                    self.l10n_ec_foreign,
                )
            except Exception as ex:
                _logger.error(tools.ustr(ex))
                is_valid = False
            if not is_valid:
                self.l10n_latam_document_number = "{}-{}-".format(
                    self.l10n_ec_supplier_authorization_id.agency,
                    self.l10n_ec_supplier_authorization_id.printer_point,
                )

    @api.onchange("l10n_latam_document_type_id", "l10n_latam_document_number")
    def _inverse_l10n_latam_document_number(self):
        # sobreescribir funcion para validar y dar formato al numero de documento
        # es una funcion inverse de un campo compute, pero tiene decorador onchange asi que reutilizarla
        # no se hace en otro onchange ya que por prioridades primero se ejecutaria esta funcion y luego nuestro nuevo onchange
        # y esta funcion llama al metodo _format_document_number el cual lanza excepcion cuando el numero de documento no tiene formato correcto
        # lo que impediria darle formato antes de validarlo
        if self.l10n_ec_invoice_type in ("in_invoice", "in_refund", "debit_note_in"):
            res = self._onchange_l10n_ec_document_number_in()
        else:
            res = self._onchange_l10n_ec_document_number_out()
        # cuando hay mensajes desde el onchange, devolver esos mensajes antes de llamada super
        # ya que en la llamada super se podria lanzar excepcion y los mensajes nunca se mostrarian al usuario
        if res and res.get("warning", {}).get("message"):
            return res
        super(
            AccountMove, self.with_context(l10n_ec_foreign=len(self) == 1 and self.l10n_ec_foreign or False)
        )._inverse_l10n_latam_document_number()
        return res

    @api.onchange(
        "type",
        "l10n_latam_document_type_id",
        "l10n_ec_point_of_emission_id",
        "invoice_date",
    )
    def _onchange_point_of_emission(self):
        for move in self.filtered(
            lambda x: x.company_id.country_id.code == "EC" and x.type in ("out_invoice", "out_refund", "in_invoice")
        ):
            if move.l10n_ec_point_of_emission_id:
                invoice_type = move.l10n_ec_get_invoice_type()
                if invoice_type in (
                    "out_invoice",
                    "out_refund",
                    "debit_note_out",
                    "liquidation",
                    "in_invoice",
                ):
                    if invoice_type not in ["in_invoice"]:
                        # CHECK ME: Si la factura ya esta guardada esta función dará siempre
                        # el siguiente número, sin importar
                        # lo que se cambie lo que hace saltos de secuencia
                        (next_number, auth_line,) = move.l10n_ec_point_of_emission_id.with_context(
                            doc_ids=self.ids
                        ).get_next_value_sequence(invoice_type, move.invoice_date, False)
                        move.l10n_ec_type_emission = move.l10n_ec_point_of_emission_id.type_emission
                        if next_number:
                            try:
                                current_agency, current_printer_point, _n = (
                                    move.l10n_latam_document_number
                                    and move.l10n_latam_document_number.split("-")
                                    or (False, False, False)
                                )
                                new_agency, new_printer_point, _n = next_number.split("-") or (False, False, False)
                                if current_agency != new_agency or current_printer_point != new_printer_point:
                                    move.l10n_latam_document_number = next_number
                            except Exception as e:
                                _logger.debug("Error parsing document numbers: %s", e)
                        move.l10n_ec_authorization_line_id = auth_line.id

    @api.onchange(
        "l10n_ec_point_of_emission_withhold_id",
        "l10n_ec_withhold_date",
    )
    def _onchange_point_of_emission_withhold(self):
        warning = {}
        for move in self.filtered(lambda x: x.company_id.country_id.code == "EC" and x.type == "in_invoice"):
            if move.l10n_ec_withhold_date and move.invoice_date and move.l10n_ec_withhold_required:
                if move.l10n_ec_withhold_date < move.invoice_date:
                    move.l10n_ec_withhold_date = move.invoice_date
                    warning = {
                        "title": _("Information for User"),
                        "message": _("Withhold date can not be less to Invoice Date"),
                    }
            if move.l10n_ec_point_of_emission_withhold_id and move.l10n_ec_withhold_required:
                move.l10n_ec_type_emission_withhold = move.l10n_ec_point_of_emission_withhold_id.type_emission
                (next_number, auth_line,) = move.l10n_ec_point_of_emission_withhold_id.get_next_value_sequence(
                    "withhold_purchase", move.l10n_ec_withhold_date, True
                )
                if next_number:
                    move.l10n_ec_withhold_number = next_number
                if auth_line:
                    move.l10n_ec_authorization_line_withhold_id = auth_line.id
            else:
                move.l10n_ec_type_emission_withhold = False
                move.l10n_ec_withhold_number = False
                move.l10n_ec_authorization_line_withhold_id = False
        return {"warning": warning}

    @api.onchange(
        "l10n_ec_original_invoice_id",
        "invoice_date",
    )
    def onchange_l10n_ec_original_invoice(self):
        line_model = self.env["account.move.line"].with_context(check_move_validity=False)
        if self.l10n_ec_original_invoice_id:
            lines = line_model.browse()
            default_move = {
                "ref": _("Reversal"),
                "date": self.invoice_date or fields.Date.context_today(self),
                "invoice_date": self.invoice_date or fields.Date.context_today(self),
                "journal_id": self.journal_id and self.journal_id.id,
                "invoice_payment_term_id": None,
            }
            move_vals = self.l10n_ec_original_invoice_id._reverse_move_vals(default_move)
            for _a, _b, line_data in move_vals.get("line_ids"):
                if line_data.get("exclude_from_invoice_tab", False):
                    continue
                if "move_id" in line_data:
                    line_data.pop("move_id")
                if "date" not in line_data:
                    line_data.update(
                        {
                            "date": self.invoice_date or fields.Date.context_today(self),
                        }
                    )
                new_line = line_model.new(line_data)
                if new_line.currency_id:
                    new_line._onchange_currency()
                lines += new_line
            self.line_ids = lines
            self._recompute_dynamic_lines(recompute_all_taxes=True)

    @api.model
    def default_get(self, fields):
        values = super(AccountMove, self).default_get(fields)
        inv_type = values.get("type", self.type)
        internal_type = values.get("internal_type") or self.env.context.get("internal_type") or "invoice"
        fields_ec_to_fill = {
            "l10n_ec_point_of_emission_id",
            "l10n_latam_document_number",
            "l10n_ec_authorization_line_id",
        }
        default_printer = self.env["l10n_ec.point.of.emission"].browse()
        if self.env.context.get("l10n_ec_point_of_emission_id"):
            default_printer = self.env["l10n_ec.point.of.emission"].browse(
                self.env.context.get("l10n_ec_point_of_emission_id")
            )
        if (
            inv_type
            in (
                "out_invoice",
                "out_refund",
                "in_invoice",
            )
            and fields_ec_to_fill.intersection(set(fields))
            and self.env.company.country_id.code == "EC"
        ):
            invoice_type = modules_mapping.l10n_ec_get_invoice_type(
                inv_type,
                internal_type,
            )
            if invoice_type in (
                "out_invoice",
                "out_refund",
                "debit_note_out",
                "liquidation",
                "in_invoice",
            ):
                if not default_printer:
                    default_printer = (
                        self.env["res.users"]
                        .get_default_point_of_emission(self.env.user.id, raise_exception=True)
                        .get("default_printer_default_id")
                    )
                values["l10n_ec_point_of_emission_id"] = default_printer.id
                if default_printer:
                    values["l10n_ec_type_emission"] = default_printer.type_emission
                    if invoice_type != "in_invoice":
                        (
                            next_number,
                            auth_line,
                        ) = default_printer.get_next_value_sequence(invoice_type, False, False)
                        if next_number:
                            values["l10n_latam_document_number"] = next_number
                        if auth_line:
                            values["l10n_ec_authorization_line_id"] = auth_line.id
        return values

    @api.model
    def fields_view_get(self, view_id=None, view_type=False, toolbar=False, submenu=False):
        res = super(AccountMove, self).fields_view_get(
            view_id=view_id, view_type=view_type, toolbar=toolbar, submenu=submenu
        )
        inv_type = self.env.context.get("type", "out_invoice")
        if view_type == "form" and inv_type == "out_invoice" and "invoice_line_ids" in res["fields"]:
            doc = etree.XML(res["fields"]["invoice_line_ids"]["views"]["tree"]["arch"])
            company = self.env.company
            for ind in [1, 2, 3]:
                field_name = "l10n_ec_xml_additional_info%s" % (ind)
                field_string = company["l10n_ec_string_ride_detail%s" % ind] or "Informacion Adicional %s" % (ind)
                modifiers = {
                    "invisible": not company["l10n_ec_print_ride_detail%s" % ind],
                }
                nodes = doc.xpath(f"//field[@name='{field_name}']")
                for node in nodes:
                    node.set("modifiers", json.dumps(modifiers))
                    node.set("string", field_string)
            res["fields"]["invoice_line_ids"]["views"]["tree"]["arch"] = etree.tostring(doc)
        return res

    def copy_data(self, default=None):
        if not default:
            default = {}
        if self.filtered(lambda x: x.company_id.country_id.code == "EC") and not default.get(
            "l10n_latam_document_number"
        ):
            inv_type = default.get("type") or self.type
            internal_type = (
                default.get("l10n_latam_internal_type")
                or self.env.context.get("internal_type")
                or self.l10n_latam_internal_type
            )
            invoice_type = modules_mapping.l10n_ec_get_invoice_type(inv_type, internal_type, False)
            if self.l10n_ec_point_of_emission_id and invoice_type in (
                "out_invoice",
                "out_refund",
                "liquidation",
                "debit_note_out",
            ):
                (
                    next_number,
                    auth_line,
                ) = self.l10n_ec_point_of_emission_id.get_next_value_sequence(invoice_type, False, False)
                default["l10n_latam_document_number"] = next_number
                default["l10n_ec_authorization_line_id"] = auth_line.id
        return super(AccountMove, self).copy_data(default)

    def unlink(self):
        ecuadorian_moves = self.filtered(lambda x: x.company_id.country_id.code == "EC")
        for move in ecuadorian_moves:
            if move.l10n_ec_xml_data_id and move.l10n_ec_xml_data_id.xml_authorization:
                raise UserError(_("You cannot delete a document that is authorized"))
            if move.is_invoice() and move.state != "draft":
                raise UserError(_("You only delete invoices in draft state"))
        super(AccountMove, ecuadorian_moves.with_context(force_delete=True)).unlink()
        return super(AccountMove, self - ecuadorian_moves).unlink()

    def action_cancel_invoice_sent_email(self):
        MailComposeMessage = self.env["mail.compose.message"]
        self.ensure_one()
        template = self.env.ref("l10n_ec_niif.email_template_cancel_invoice", False)
        ctx = {
            "default_model": self._name,
            "default_res_id": self.id,
            "default_use_template": bool(template),
            "default_template_id": template.id,
            "default_composition_mode": "comment",
            "custom_layout": "mail.mail_notification_light",
            "force_email": True,
            "model_description": self.l10n_ec_get_document_string(),
        }
        msj = MailComposeMessage.with_context(ctx).create({})
        try:
            msj.onchange_template_id_wrapper()
            msj.send_mail()
        except Exception:
            pass
        return

    @api.model
    def _l10n_ec_is_document_authorized_in_sri(self, client_ws, l10n_ec_xml_key):
        # La función retorna True en el caso que el estado del xml este autorizado, esto por que el sri  cuando un Doc
        # esta en estado cancelado no retorna un estado como tal por eso pregunta si el estado es Autorizado se devuelve un True
        # caso contrario se devuelve False para seguir la validación
        response = client_ws.service.autorizacionComprobante(claveAccesoComprobante=l10n_ec_xml_key)
        autorizacion_list = []
        if hasattr(response, "autorizaciones") and response.autorizaciones is not None:
            if not isinstance(response.autorizaciones.autorizacion, list):
                autorizacion_list = [response.autorizaciones.autorizacion]
            else:
                autorizacion_list = response.autorizaciones.autorizacion
        for doc in autorizacion_list:
            if doc.estado == "AUTORIZADO":
                return True
        return False

    @api.model
    def _l10n_ec_get_extra_domain_move(self):
        domain = []
        if self.env.context.get("filter_original_invoice_type") and self.env.context.get("original_invoice_type"):
            invoice_type = (
                "out_invoice" if self.env.context.get("original_invoice_type") == "out_refund" else "in_invoice"
            )
            domain.append(("type", "=", invoice_type))
        return domain

    @api.model
    def _search(
        self,
        args,
        offset=0,
        limit=None,
        order=None,
        count=False,
        access_rights_uid=None,
    ):
        args.extend(self._l10n_ec_get_extra_domain_move())
        res = super(AccountMove, self)._search(args, offset, limit, order, count, access_rights_uid)
        return res

    @api.model
    def _read_group_raw(self, domain, fields, groupby, offset=0, limit=None, orderby=False, lazy=True):
        domain.extend(self._l10n_ec_get_extra_domain_move())
        res = super(AccountMove, self)._read_group_raw(domain, fields, groupby, offset, limit, orderby, lazy)
        return res

    def _get_name_invoice_report(self, report_xml_id):
        self.ensure_one()
        if self.l10n_latam_use_documents and self.company_id.country_id.code == "EC":
            custom_report = {
                "account.report_invoice_document_with_payments": "l10n_ec_niif.report_invoice_document_with_payments_extension",
                "account.report_invoice_document": "l10n_ec_niif.report_invoice_document_extension",
            }
            return custom_report.get(report_xml_id) or report_xml_id
        return super()._get_name_invoice_report(report_xml_id)

    def _reverse_move_vals(self, default_values, cancel=True):
        # pasar la referencia al campo que se usa en localizacion ecuatoriana
        # TODO: revisar si realmente es necesario agregar un nuevo campo o se podria usar el de Odoo base
        default_values["l10n_ec_original_invoice_id"] = self.id
        return super(AccountMove, self)._reverse_move_vals(default_values, cancel=cancel)

    def button_draft(self):
        xml_data = self.env["sri.xml.data"]
        for move in self:
            # si esta en modo produccion, mostrar asistente para que ingrese autorizacion para cancelar
            # esta autorizacion se debe pedir al SRI(tramite manual)
            withhold_electronic = move.l10n_ec_withhold_ids.filtered(
                lambda x: x.l10n_ec_xml_data_id and x.l10n_ec_xml_data_id.state not in ["draft", "signed", "cancel"]
            )
            if (
                move.is_purchase_document()
                and withhold_electronic
                and not self.env.context.get("cancel_electronic_document", False)
            ):
                wizard = self.env["wizard.cancel.electronic.documents"].create(
                    {"withholding_id": withhold_electronic.id}
                )
                action = self.env.ref("l10n_ec_niif.action_wizard_cancel_electronic_documents_form_view").read()[0]
                action["context"] = {
                    "active_model": self._name,
                    "active_id": move.id,
                    "active_ids": self.ids,
                }
                action["res_id"] = wizard.id
                return action
            if (
                move.l10n_ec_is_environment_production
                and move.l10n_ec_xml_data_id
                and move.l10n_ec_xml_data_id.state not in ["draft", "signed", "cancel", "returned"]
                and not self.env.context.get("cancel_electronic_document", False)
            ):
                if move.company_id.l10n_ec_request_sri_validation_cancel_doc:
                    client_ws = xml_data.get_current_wsClient("2", "authorization")
                    if move._l10n_ec_is_document_authorized_in_sri(client_ws, move.l10n_ec_xml_data_id.l10n_ec_xml_key):
                        raise UserError(
                            _(
                                "You must first cancel the document: %s in the SRI portal and then cancel it in the system"
                            )
                            % (move.l10n_ec_get_document_number())
                        )
                wizard = self.env["wizard.cancel.electronic.documents"].create({"move_id": move.id})
                action = self.env.ref("l10n_ec_niif.action_wizard_cancel_electronic_documents_form_view").read()[0]
                action["context"] = {
                    "active_model": self._name,
                    "active_id": move.id,
                    "active_ids": self.ids,
                }
                action["res_id"] = wizard.id
                return action
            if move.is_purchase_document() and move.l10n_ec_withhold_ids:
                move.l10n_ec_withhold_ids.action_cancel()
                move.l10n_ec_withhold_ids.with_context(cancel_from_invoice=True).unlink()
        self.mapped("l10n_ec_xml_data_id").action_cancel()
        self.write({"l10n_ec_sri_authorization_state": "to_check"})
        res = super(AccountMove, self).button_draft()
        # solo notificar por correo documentos que estaban autorizados
        for move in self.filtered(lambda x: x.l10n_ec_xml_data_id and x.l10n_ec_xml_data_id.xml_authorization):
            move.action_cancel_invoice_sent_email()
        return res

    def post(self):
        withhold_model = self.env["l10n_ec.withhold"]
        withhold_line_model = self.env["l10n_ec.withhold.line"]
        for move in self:
            if move.company_id.country_id.code == "EC":
                move._check_document_values_for_ecuador()
                move._l10n_ec_action_validate_authorization_sri()
                move.validate_quantity_move_line()
                # proceso de retenciones en compra
                if move.type == "in_invoice":
                    if move.l10n_ec_withhold_required:
                        current_withhold = withhold_model.create(move._prepare_withhold_values())
                        tax_data = move._prepare_withhold_lines_values(current_withhold)
                        withhold_line_model.create(tax_data)

                        current_withhold.action_done()
                # proceso de facturacion electronica
                if move.is_invoice():
                    move.l10n_ec_action_create_xml_data()
                if (
                    move.l10n_latam_internal_type != "liquidation"
                    and move.l10n_latam_document_type_id
                    and move.l10n_latam_document_type_id.code != "41"
                    and move.l10n_ec_refund_ids
                ):
                    raise UserError(
                        _(
                            "The document %s has the code %s in the document type, but a "
                            "refund has been included, so it must be code 41."
                        )
                        % (move.l10n_latam_document_number, move.l10n_latam_document_type_id.code)
                    )
                if move.type == "out_invoice":
                    taxes = move.invoice_line_ids.mapped("tax_ids").filtered(
                        lambda x: x.tax_group_id.l10n_ec_xml_fe_code == "2"
                    )
                    if not taxes:
                        raise UserError(_("You must add at least one VAT tax on the invoice {}".format(move.name)))
        res = super(AccountMove, self).post()
        self.l10n_ec_asign_discount_to_lines()
        return res

    def action_invoice_sent(self):
        self.ensure_one()
        res = super(AccountMove, self).action_invoice_sent()
        # si es electronico, cambiar la plantilla de correo a usar
        if self.l10n_ec_xml_data_id:
            template = self.env.ref("l10n_ec_niif.email_template_e_invoice", False)
            if template:
                res["context"]["default_template_id"] = template.id
        return res

    def action_show_l10n_ec_withholds(self):
        self.ensure_one()
        action = self.env.ref("l10n_ec_niif.l10n_ec_withhold_purchase_act_window").read()[0]

        withholds = self.mapped("l10n_ec_withhold_ids")
        if len(withholds) > 1:
            action["domain"] = [("id", "in", withholds.ids)]
        elif withholds:
            form_view = [(self.env.ref("l10n_ec_niif.l10n_ec_withhold_form_view").id, "form")]
            if "views" in action:
                action["views"] = form_view + [(state, view) for state, view in action["views"] if view != "form"]
            else:
                action["views"] = form_view
            action["res_id"] = withholds.id
        action["context"] = dict(
            self._context,
            default_partner_id=self.partner_id.id,
            default_invoice_id=self.id,
        )
        # no mostrar botones de crear/editar en retenciones de compra
        if self.type == "in_invoice":
            action["context"].update({"create": False, "edit": False})
        return action

    def create_withhold_customer(self):
        self.ensure_one()
        action = self.env.ref("l10n_ec_niif.l10n_ec_withhold_sales_act_window").read()[0]
        action["views"] = [(self.env.ref("l10n_ec_niif.l10n_ec_withhold_form_view").id, "form")]
        ctx = safe_eval(action["context"])
        ctx.pop("default_type", False)
        ctx.update(
            {
                "default_partner_id": self.partner_id.id,
                "default_invoice_id": self.id,
                "withhold_type": "sale",
                "default_issue_date": self.invoice_date,
                "default_document_type": self.l10n_ec_type_emission,
                "default_l10n_ec_is_create_from_invoice": True,
            }
        )
        action["context"] = ctx
        return action

    def _check_amount_total_nc_invoice_move(self):
        currency = self.currency_id
        # La nota de crédito no puede ser superior al total de la factura
        if (float_compare(self.amount_total, self.l10n_ec_original_invoice_id.amount_total, precision_digits=2)) == 1:
            raise UserError(
                _(
                    "The total amount: {} of the credit note: {}, "
                    "cannot be greater than the total amount: {} of the invoice {}"
                ).format(
                    formatLang(self.env, currency.round(self.amount_total), currency_obj=currency),
                    self.l10n_ec_get_document_number(),
                    formatLang(
                        self.env,
                        currency.round(self.l10n_ec_original_invoice_id.amount_total),
                        currency_obj=currency,
                    ),
                    self.l10n_ec_original_invoice_id.l10n_ec_get_document_number(),
                )
            )
        # Si ya se encuentra parcialmente conciliada y es mayor al residual debe lanzar un error
        if self.l10n_ec_original_invoice_id.invoice_payment_state != "paid":
            if (
                float_compare(self.amount_total, self.l10n_ec_original_invoice_id.amount_residual, precision_digits=2)
                == 1
            ):
                raise UserError(
                    _(
                        "The total amount: {} of the credit note: {}, "
                        "cannot be greater than the amount residual: {} of the invoice {}."
                    ).format(
                        formatLang(self.env, currency.round(self.amount_total), currency_obj=currency),
                        self.l10n_ec_get_document_number(),
                        formatLang(
                            self.env,
                            currency.round(self.l10n_ec_original_invoice_id.amount_residual),
                            currency_obj=currency,
                        ),
                        self.l10n_ec_original_invoice_id.l10n_ec_get_document_number(),
                    )
                )
        else:
            credit_notes_recs = self.search(
                [
                    ("l10n_ec_original_invoice_id", "=", self.l10n_ec_original_invoice_id.id),
                    ("id", "!=", self.id),
                    ("state", "=", "posted"),
                ]
            )
            if credit_notes_recs:
                total = 0
                for cn in credit_notes_recs:
                    total += cn.amount_total
                total += self.amount_total
                if float_compare(total, self.l10n_ec_original_invoice_id.amount_total, precision_digits=2) == 1:
                    raise UserError(
                        _(
                            "The total amount of all credit notes: {}, "
                            "cannot be greater than the total amount: {} of the invoice {}"
                        ).format(
                            formatLang(self.env, currency.round(total), currency_obj=currency),
                            formatLang(
                                self.env,
                                currency.round(self.l10n_ec_original_invoice_id.amount_total),
                                currency_obj=currency,
                            ),
                            self.l10n_ec_original_invoice_id.l10n_ec_get_document_number(),
                        )
                    )

    def _check_document_values_for_ecuador(self):
        # TODO: se deberia agregar un campo en el grupo de impuesto para diferenciarlos(l10n_ec_type_ec)
        supplier_authorization_model = self.env["l10n_ec.sri.authorization.supplier"]
        withhold_iva_group = self.env.ref("l10n_ec_niif.tax_group_iva_withhold")
        withhold_rent_group = self.env.ref("l10n_ec_niif.tax_group_renta_withhold")
        iva_group = self.env.ref("l10n_ec_niif.tax_group_iva")
        iva_no_apply_group = self.env.ref("l10n_ec_niif.tax_group_iva_no_apply")
        iva_exempt_group = self.env.ref("l10n_ec_niif.tax_group_iva_exempt")
        iva_group_0 = self.env.ref("l10n_ec_niif.tax_group_iva_0")
        error_list = []
        # validar que la empresa tenga ruc y tipo de documento
        if self.is_invoice() and self.commercial_partner_id:
            self.commercial_partner_id._check_l10n_ec_values()
        # validaciones para consumidor final
        # * no permitir factura de ventas mayor a un monto configurado(200 USD por defecto)
        # * no permitir emitir Nota de credito ni factura de proveedor
        if self.l10n_ec_consumidor_final:
            if (
                self.type == "out_invoice"
                and float_compare(
                    self.amount_total,
                    self.company_id.l10n_ec_consumidor_final_limit,
                    precision_digits=2,
                )
                == 1
            ):
                raise UserError(
                    _("You can't make invoice where amount total %s " "is bigger than %s for final customer")
                    % (
                        self.amount_total,
                        self.company_id.l10n_ec_consumidor_final_limit,
                    )
                )
            if self.type in ("in_invoice", "in_refund", "out_refund"):
                raise UserError(_("You can't make bill or refund to final customer on ecuadorian company"))
        if self.l10n_ec_invoice_type in ("in_invoice", "in_refund", "debit_note_in"):
            if not self.commercial_partner_id.vat:
                raise UserError(_("Must be configure RUC to Partner: %s.") % (self.commercial_partner_id.name))
            supplier_authorization_model.validate_unique_document_partner(
                self.l10n_ec_invoice_type,
                self.l10n_latam_document_number,
                self.partner_id.id,
                self.id,
            )
            if self.l10n_ec_type_emission in ("pre_printed", "auto_printer"):
                if self.l10n_ec_supplier_authorization_id:
                    supplier_authorization_model.check_number_document(
                        self.l10n_ec_invoice_type,
                        self.l10n_latam_document_number,
                        self.l10n_ec_supplier_authorization_id,
                        self.invoice_date,
                        self.id,
                        self.commercial_partner_id.l10n_ec_foreign,
                    )
                elif not self.l10n_ec_supplier_authorization_number and not self.l10n_ec_foreign:
                    raise UserError(_("You must enter the authorization of the third party to continue"))
        # notas de credito validar monto no sea mayor al de factura
        if (
            self.type in ["in_refund", "out_refund"]
            and self.l10n_ec_original_invoice_id
            and self.company_id.l10n_ec_cn_reconcile_policy == "restrict"
        ):
            # La nota de credito no puede ser superior al total de la factura
            self._check_amount_total_nc_invoice_move()
        # validaciones en facturas de proveedor para emitir retenciones
        # * tener 1 impuesto de retencion IVA y 1 impuesto de retencion RENTA
        # * no permitir retener IVA si no hay impuesto de IVA(evitar IVA 0)
        if self.type == "in_invoice" and not self.env.context.get("skip_sri_validations_in_invoice"):
            if (
                self.partner_id.country_id.code == "EC"
                and not self.l10n_ec_tax_support_id
                and self.l10n_ec_invoice_type in ["in_invoice", "liquidation"]
            ):
                error_list.append(
                    _("You must select the fiscal support to validate invoices %s of supplier %s.")
                    % (self.l10n_latam_document_number, self.partner_id.display_name)
                )
            for line in self.invoice_line_ids:
                iva_taxes = line.tax_ids.filtered(lambda x: x.tax_group_id.id == iva_group.id and x.amount > 0)
                iva_0_taxes = line.tax_ids.filtered(
                    lambda x: x.tax_group_id.id in (iva_group_0.id, iva_no_apply_group.id, iva_exempt_group.id)
                    and x.amount == 0
                )
                withhold_iva_taxes = line.tax_ids.filtered(
                    lambda x: x.tax_group_id.id == withhold_iva_group.id and x.amount > 0
                )
                rent_withhold_taxes = line.tax_ids.filtered(lambda x: x.tax_group_id.id == withhold_rent_group.id)
                if self.partner_id.country_id.code == "EC":
                    if self.l10n_latam_document_type_id.code == "41":
                        if rent_withhold_taxes or withhold_iva_taxes:
                            error_list.append(
                                _("You cant not apply withholding for document types: %s")
                                % self.l10n_latam_document_type_id.name
                            )
                    else:
                        require_withhold = (
                            self.company_id.partner_id.property_account_position_id.l10n_ec_check_withhold
                            if self.company_id.partner_id.property_account_position_id
                            else True
                        )
                        if require_withhold and (
                            self.fiscal_position_id and not self.fiscal_position_id.l10n_ec_check_withhold
                        ):
                            require_withhold = False
                        if len(rent_withhold_taxes) == 0 and require_withhold:
                            error_list.append(_("You must apply at least one income withholding tax"))
                        if len(iva_taxes) == 0 and len(iva_0_taxes) == 0:
                            error_list.append(_("You must apply at least one VAT tax"))
                if len(withhold_iva_taxes) > 1:
                    error_list.append(
                        _("You cannot have more than one VAT Withholding tax %s")
                        % (" / ".join(t.description or t.name for t in withhold_iva_taxes))
                    )
                if len(rent_withhold_taxes) > 1:
                    error_list.append(
                        _("You cannot have more than one Rent Withholding tax %s")
                        % (" / ".join(t.description or t.name for t in rent_withhold_taxes))
                    )
                if len(iva_taxes) == 0 and len(withhold_iva_taxes) > 0:
                    error_list.append(
                        _("You cannot apply VAT withholding without an assigned VAT tax %s")
                        % (" / ".join(t.description or t.name for t in withhold_iva_taxes))
                    )
        for line in self.invoice_line_ids:
            iva_taxes = line.tax_ids.filtered(lambda x: x.tax_group_id.id == iva_group.id and x.amount > 0)
            iva_0_taxes = line.tax_ids.filtered(
                lambda x: x.tax_group_id.id in (iva_group_0.id, iva_no_apply_group.id, iva_exempt_group.id)
                and x.amount == 0
            )
            if len(iva_taxes) >= 1 and len(iva_0_taxes) >= 1:
                error_list.append(_("Cannot apply VAT zero rate with another VAT rate"))
            if len(iva_taxes) > 1:
                error_list.append(
                    _("You cannot have more than one VAT tax %s")
                    % (" / ".join(t.description or t.name for t in iva_taxes))
                )
            if len(iva_0_taxes) > 1:
                error_list.append(
                    _("You cannot have more than one VAT 0 tax %s")
                    % (" / ".join(t.description or t.name for t in iva_0_taxes))
                )
        # al validar un documento, si tiene xml autorizado
        # o una autorizacion de cancelacion, no permitir validar nuevamente,
        # ya que el SRI rechazara por secuencial registrado

        current_xml_recs = self.filtered(
            lambda x: x.l10n_ec_xml_data_id
            and (x.l10n_ec_xml_data_id.state == "cancel" and x.l10n_ec_xml_data_id.authorization_to_cancel)
        ).mapped("l10n_ec_xml_data_id")
        if current_xml_recs:
            error_list.append(_("You cannot validate this record, already is cancelled on the SRI"))
        if error_list:
            raise UserError("\n".join(error_list))
        return True

    @api.model
    def l10n_ec_validate_supplier_documents_sri(self):
        invoices = self.search(
            [
                (
                    "l10n_ec_invoice_type",
                    "in",
                    (
                        "in_invoice",
                        "in_refund",
                        "debit_note_in",
                    ),
                ),
                ("l10n_ec_sri_authorization_state", "=", "to_check"),
                ("state", "=", "posted"),
                ("company_id.country_id.code", "=", "EC"),
            ]
        )
        for invoice in invoices:
            try:
                with self.env.cr.savepoint():
                    invoice._l10n_ec_action_validate_authorization_sri()
            except Exception as ex:
                _logger.error(tools.ustr(ex))
        withholding = self.env["l10n_ec.withhold"].search(
            [
                ("type", "=", "sale"),
                ("l10n_ec_sri_authorization_state", "=", "to_check"),
                ("state", "=", "done"),
            ]
        )
        for withhold in withholding:
            try:
                with self.env.cr.savepoint():
                    withhold._l10n_ec_action_validate_authorization_sri()
            except Exception as ex:
                _logger.error(tools.ustr(ex))
        return True

    def _l10n_ec_action_validate_authorization_sri(self):
        # intentar validar el documento en linea con el SRI
        if self.l10n_ec_invoice_type in ("in_invoice", "in_refund", "debit_note_in"):
            if not tools.config.get("validate_authorization_sri", True):
                self.write({"l10n_ec_sri_authorization_state": "valid"})
                return True
            if self.l10n_ec_type_emission == "auto_printer":
                self.write({"l10n_ec_sri_authorization_state": "valid"})
                return True
            elif self.l10n_ec_type_emission == "pre_printed":
                # para in_invoice solo validar si es factura(01), Notas de venta u otro documento no validar
                if self.l10n_ec_invoice_type == "in_invoice" and self.l10n_latam_document_type_id.code != "01":
                    self.write({"l10n_ec_sri_authorization_state": "valid"})
                    return True
                if self.l10n_ec_supplier_authorization_id:
                    authorization_number = self.l10n_ec_supplier_authorization_id.number
                else:
                    authorization_number = self.l10n_ec_supplier_authorization_number
                response_sri = {}
                try:
                    response_sri = self.env["l10n_ec.sri.authorization.supplier"].validate_authorization_into_sri(
                        authorization_number,
                        self.commercial_partner_id.vat,
                        self.l10n_ec_invoice_type,
                        self.l10n_ec_get_document_number(),
                        self.l10n_ec_get_document_date(),
                    )
                except Exception as ex:
                    _logger.error(tools.ustr(ex))
                if "estado" in response_sri:
                    # el estado es un texto que no serviria para comparacion, puede cambiar en cualquier momento
                    # usar los datos del contribuyente en su lugar
                    if not response_sri.get("contribuyente"):
                        raise UserError(
                            _("Document was reviewed online with SRI and Authorization is invalid. %s")
                            % response_sri.get("estado")
                        )
                    else:
                        self.write({"l10n_ec_sri_authorization_state": "valid"})
            elif self.l10n_ec_type_emission == "electronic" and self.l10n_ec_electronic_authorization:
                xml_data = self.env["sri.xml.data"]
                try:
                    limit_days = int(
                        self.env["ir.config_parameter"].sudo().get_param("sri.days.to_validate_documents", 5)
                    )
                except Exception as ex:
                    limit_days = 5
                    _logger.error(
                        "Error get parameter sri.days.to_validate_documents %s",
                        tools.ustr(ex),
                    )
                is_authorized = False
                try:
                    client_ws = xml_data.get_current_wsClient("2", "authorization")
                    response = client_ws.service.autorizacionComprobante(
                        claveAccesoComprobante=self.l10n_ec_electronic_authorization
                    )
                    autorizacion_list = []
                    if hasattr(response, "autorizaciones") and response.autorizaciones is not None:
                        if not isinstance(response.autorizaciones.autorizacion, list):
                            autorizacion_list = [response.autorizaciones.autorizacion]
                        else:
                            autorizacion_list = response.autorizaciones.autorizacion
                    for doc in autorizacion_list:
                        if doc.estado == "AUTORIZADO" and doc.comprobante:
                            is_authorized = True
                            break
                except Exception as ex:
                    _logger.error(tools.ustr(ex))
                # en documentos electronicos no lanzar excepcion, puede ser emitido offline
                if is_authorized:
                    self.write({"l10n_ec_sri_authorization_state": "valid"})
                else:
                    # si ya pasaron N dias y aun no ha sido autorizado, marcarlo como documento invalido
                    date_delta = fields.Date.context_today(self) - self.invoice_date
                    if date_delta.days > limit_days:
                        self.write({"l10n_ec_sri_authorization_state": "invalid"})
        return True

    def validate_quantity_move_line(self):
        error_list, product_not_quantity = [], []
        for move in self:
            if move.l10n_ec_invoice_type in ("in_invoice", "out_invoice", "in_refund", "out_refund"):
                for line in move.invoice_line_ids.filtered(lambda x: not x.display_type):
                    if float_compare(line.quantity, 0.0, precision_digits=2) <= 0:
                        product_not_quantity.append("  - %s" % line.product_id.display_name)
                if product_not_quantity:
                    error_list.append(
                        _(
                            "You cannot validate an invoice with zero quantity. "
                            "Please review the following items:\n%s"
                        )
                        % "\n".join(product_not_quantity)
                    )
                if float_compare(move.amount_total, 0.0, precision_digits=2) <= 0:
                    error_list.append(_("You cannot validate an invoice with zero value."))
                if error_list:
                    raise UserError("\n".join(error_list))

    def _prepare_withhold_values(self):
        """
        :return: dict with values for create a new withhold
        """
        vals_to_write = {}
        # cuando no tengo numero de retencion, obtener el siguiente
        if (
            not self.l10n_ec_withhold_number
            and self.l10n_ec_point_of_emission_withhold_id
            and self.l10n_ec_type_emission_withhold == "electronic"
        ):
            (next_number, auth_line,) = self.l10n_ec_point_of_emission_withhold_id.get_next_value_sequence(
                "withhold_purchase", self.l10n_ec_withhold_date, True
            )
            if next_number:
                vals_to_write["l10n_ec_withhold_number"] = next_number
            if auth_line:
                vals_to_write["l10n_ec_authorization_line_withhold_id"] = auth_line.id
        if vals_to_write:
            self.write(vals_to_write)
        withhold_values = {
            "company_id": self.company_id.id,
            "number": self.l10n_ec_withhold_number,
            "issue_date": self.l10n_ec_withhold_date,
            "partner_id": self.partner_id.id,
            "invoice_id": self.id,
            "type": "purchase",
            "point_of_emission_id": self.l10n_ec_point_of_emission_withhold_id.id,
            "authorization_line_id": self.l10n_ec_authorization_line_withhold_id.id,
            "document_type": self.l10n_ec_type_emission_withhold,
            "state": "draft",
        }
        return withhold_values

    def _prepare_withhold_lines_values(self, withhold):
        """
        Compute withhold lines based on taxes groups for withhold IVA and RENTA
        :param withhold: recordset(l10n_ec.withhold) to create lines
        :return: list(dict) with values for create withhold lines
        """
        percent_model = self.env["l10n_ec.withhold.line.percent"]
        withhold_iva_group = self.env.ref("l10n_ec_niif.tax_group_iva_withhold")
        withhold_rent_group = self.env.ref("l10n_ec_niif.tax_group_renta_withhold")
        tax_data = {}
        for line in self.invoice_line_ids:
            for tax in line.tax_ids:
                if tax.tax_group_id.id in (
                    withhold_iva_group.id,
                    withhold_rent_group.id,
                ):
                    base_tag_id = tax.invoice_repartition_line_ids.filtered(
                        lambda x: x.repartition_type == "base"
                    ).mapped("tag_ids")
                    tax_tag_id = tax.invoice_repartition_line_ids.filtered(
                        lambda x: x.repartition_type == "tax"
                    ).mapped("tag_ids")
                    tax_type = "rent"
                    percent = abs(tax.amount)
                    if tax.tax_group_id.id == withhold_iva_group.id:
                        tax_type = "iva"
                        percent = abs(
                            tax.invoice_repartition_line_ids.filtered(
                                lambda x: x.repartition_type == "tax"
                            ).factor_percent
                        )
                    tax_data.setdefault(
                        tax,
                        {
                            "withhold_id": withhold.id,
                            "invoice_id": self.id,
                            "tax_id": tax.id,
                            "base_tag_id": base_tag_id and base_tag_id.ids[0] or False,
                            "tax_tag_id": tax_tag_id and tax_tag_id.ids[0] or False,
                            "type": tax_type,
                            "base_amount": 0.0,
                            "tax_amount": 0.0,
                            "base_amount_currency": 0.0,
                            "tax_amount_currency": 0.0,
                            "percent_id": percent_model._get_percent(percent, tax_type).id,
                        },
                    )
        for tax in tax_data.keys():
            base_amount = 0
            tax_amount = 0
            base_tag_id = tax_data[tax].get("base_tag_id")
            tax_tag_id = tax_data[tax].get("tax_tag_id")
            line_with_taxes = self.line_ids.filtered(
                lambda l: base_tag_id in l.tag_ids.ids or tax_tag_id in l.tag_ids.ids
            )
            for line in line_with_taxes:
                for tag in line.tag_ids.filtered(lambda x: x.id in (base_tag_id, tax_tag_id)):
                    tag_amount = line.balance
                    if tag.id == base_tag_id and tax in line.tax_ids:
                        base_amount = abs(tag_amount)
                        tax_data[tax]["base_amount"] += base_amount
                        tax_data[tax]["base_amount_currency"] += self.currency_id.compute(
                            base_amount, self.company_id.currency_id
                        )
                    if tag.id == tax_tag_id and tax == line.tax_line_id:
                        tax_amount = abs(tag_amount)
                        tax_data[tax]["tax_amount"] += tax_amount
                        tax_data[tax]["tax_amount_currency"] += self.currency_id.compute(
                            tax_amount, self.company_id.currency_id
                        )
            # cuando no hay lineas de impuesto por lo general sera en impuestos que el valor da 0
            # odoo no crea un apunte contable por esa linea, pero si debemos calcular la base de ese impuesto
            # para ello se tomaran todas las lineas que tengan el impuesto y desde ahi enviar a calcular la base
            if not line_with_taxes:
                lines_with_tax = self.invoice_line_ids.filtered(lambda l: tax in l.tax_ids)
                tax_values = tax.compute_all(sum(lines_with_tax.mapped("price_subtotal")))
                for tax_vals in tax_values.get("taxes", []):
                    if tax_vals["id"] != tax.id:
                        continue
                    base_amount = abs(tax_vals["base"])
                    tax_amount = abs(tax_vals["amount"])
                    if tax_vals.get("tax_repartition_line_id"):
                        tax_repartition_lines = self.env["account.tax.repartition.line"].browse(
                            tax_vals.get("tax_repartition_line_id")
                        )
                        factor = tax_repartition_lines.factor
                        # cuando es impuesto de retencion iva 0, a la base multiplicarla por el % de impuesto
                        # para obtener la base correcta
                        if not factor and tax.tax_group_id == withhold_iva_group:
                            factor = tax.amount
                        base_amount *= factor * 0.01
                    tax_data[tax]["base_amount"] += base_amount
                    tax_data[tax]["base_amount_currency"] += self.currency_id.compute(
                        base_amount, self.company_id.currency_id
                    )
                    tax_data[tax]["tax_amount"] += tax_amount
                    tax_data[tax]["tax_amount_currency"] += self.currency_id.compute(
                        tax_amount, self.company_id.currency_id
                    )
        for tax, tax_vals in tax_data.items():
            if tax.tax_group_id.id == withhold_iva_group.id:
                invoice_lines = self.invoice_line_ids.filtered(lambda x: tax in x.tax_ids)
                tax_vals["base_amount"] = sum(invoice_lines.mapped("l10n_ec_iva"))
                tax_vals["base_amount_currency"] = self.currency_id.compute(
                    tax_vals["base_amount"], self.company_id.currency_id
                )
        return tax_data.values()

    def l10n_ec_get_invoice_type(self):
        self.ensure_one()
        internal_type = (
            self.env.context.get("internal_type") or self.l10n_latam_document_type_id.internal_type or "invoice"
        )
        return modules_mapping.l10n_ec_get_invoice_type(self.type, internal_type, False)

    def l10n_ec_validate_fields_required_fe(self):
        message_list = []
        if not self.company_id.partner_id.vat:
            message_list.append(_("Must be configure RUC to Company: %s.") % (self.company_id.partner_id.name))
        if not self.company_id.partner_id.street:
            message_list.append(_("Must be configure Street to Company: %s.") % (self.company_id.partner_id.name))
        if not self.commercial_partner_id.vat:
            message_list.append(_("Must be configure RUC to Partner: %s.") % (self.commercial_partner_id.name))
        if not self.commercial_partner_id.country_id:
            message_list.append(_("Must be configure Country to Partner: %s.") % (self.commercial_partner_id.name))
        if not self.commercial_partner_id.street:
            message_list.append(_("Must be configure Street to Partner: %s.") % (self.commercial_partner_id.name))
        if self.l10n_ec_invoice_type != "in_invoice" and not self.l10n_ec_sri_payment_id:
            message_list.append(_("Must be configure Payment Method SRI on document: %s.") % (self.display_name))
        # validaciones para reembolso en liquidacion de compras
        if self.l10n_latam_internal_type == "liquidation" and self.l10n_ec_refund_ids:
            for refund in self.l10n_ec_refund_ids:
                if not refund.partner_id.commercial_partner_id.vat:
                    message_list.append(
                        _("On refunds must be configure RUC for partner: %s.")
                        % (refund.partner_id.commercial_partner_id.name)
                    )
                if refund.currency_id.is_zero(refund.total_invoice):
                    message_list.append(_("Amount total for refunds must be greater than zero."))
        if self.type == "out_refund":
            if not self.l10n_ec_original_invoice_id and not self.l10n_ec_legacy_document_number:
                message_list.append(
                    _("Credit Note: %s has not document to modified, please review.") % (self.display_name)
                )
            # validar que la factura este autorizada electronicamente(o en proceso de envio)
            if self.l10n_ec_original_invoice_id and not self.l10n_ec_original_invoice_id.l10n_ec_xml_data_id:
                message_list.append(
                    _(
                        "You cannot create Credit Note electronic if original document : %s has not electronic authorization"
                    )
                    % (self.l10n_ec_original_invoice_id.display_name)
                )
        return message_list

    def l10n_ec_action_create_xml_data(self):
        xml_model = self.env["sri.xml.data"]
        xml_recs = self.env["sri.xml.data"].browse()
        # si por context me pasan que no cree la parte electronica
        if self.env.context.get("no_create_electronic", False):
            return True
        # Si ya se encuentra autorizado, no hacer nuevamente el proceso de generacion del xml
        # pero si no esta autorizado, volver a reactivarlo
        current_xml_recs = self.filtered(
            lambda x: x.l10n_ec_xml_data_id and x.l10n_ec_xml_data_id.state not in ("draft", "authorized")
        ).mapped("l10n_ec_xml_data_id")
        if current_xml_recs:
            current_xml_recs.write({"state": "draft"})
            xml_recs |= current_xml_recs
        # proceso de retenciones, hacerlo indistinto si la factura o liquidacion de compra tiene xml
        for invoice in self:
            if invoice.type == "in_invoice":
                for retention in invoice.l10n_ec_withhold_ids:
                    if retention.point_of_emission_id.type_emission != "electronic":
                        continue
                    if not retention.no_number:
                        # si el documento esta habilitado, hacer el proceso electronico
                        if xml_model._is_document_authorized("withhold_purchase"):
                            message_list = invoice.l10n_ec_validate_fields_required_fe()
                            if message_list:
                                raise UserError("\n".join(message_list))
                            company = retention.company_id or self.env.company
                            sri_xml_vals = retention._prepare_l10n_ec_sri_xml_values(company)
                            sri_xml_vals["withhold_id"] = retention.id
                            new_xml_rec = xml_model.create(sri_xml_vals)
                            xml_recs += new_xml_rec
                            retention._l10n_ec_add_followers_to_electronic_documents()
        for invoice in self.filtered(lambda x: not x.l10n_ec_xml_data_id):
            invoice_type = invoice.l10n_ec_get_invoice_type()
            # si el documento esta habilitado, hacer el proceso electronico
            if (
                invoice.l10n_ec_point_of_emission_id.type_emission == "electronic"
                and xml_model._is_document_authorized(invoice_type)
            ):
                message_list = invoice.l10n_ec_validate_fields_required_fe()
                if message_list:
                    raise UserError("\n".join(message_list))
                # asegurarse que el documento tenga fecha
                # recien en la llamada super se haria esa asignacion
                # pero necesitamos la fecha para crear el xml
                # (codigo copiado del metodo post)
                # *********************************************************************************************
                if not invoice.invoice_date and invoice.is_invoice(include_receipts=True):
                    invoice.invoice_date = fields.Date.context_today(invoice)
                    invoice.with_context(check_move_validity=False)._onchange_invoice_date()
                # *********************************************************************************************
                company = invoice.company_id or self.env.company
                sri_xml_vals = invoice._prepare_l10n_ec_sri_xml_values(company)
                # factura
                if invoice_type == "out_invoice":
                    sri_xml_vals["invoice_out_id"] = invoice.id
                # nota de debito
                elif invoice_type == "debit_note_out":
                    sri_xml_vals["debit_note_out_id"] = invoice.id
                # nota de credito
                elif invoice_type == "out_refund":
                    sri_xml_vals["credit_note_out_id"] = invoice.id
                # liquidacion de compas
                elif invoice_type == "liquidation":
                    sri_xml_vals["liquidation_id"] = invoice.id
                new_xml_rec = xml_model.create(sri_xml_vals)
                xml_recs += new_xml_rec
                invoice._l10n_ec_add_followers_to_electronic_documents()
        if xml_recs:
            xml_recs.process_document_electronic()
        return True

    def _l10n_ec_add_followers_to_electronic_documents(self):
        partners = self.env["res.partner"].browse()
        invoice_type = self.l10n_ec_get_invoice_type()
        boolean_field_name = ""
        if invoice_type == "out_invoice":
            boolean_field_name = "l10n_ec_email_out_invoice"
        if invoice_type == "out_refund":
            boolean_field_name = "l10n_ec_email_out_refund"
        if invoice_type == "debit_note_out":
            boolean_field_name = "l10n_ec_email_debit_note_out"
        if invoice_type == "liquidation":
            boolean_field_name = "l10n_ec_email_liquidation"
        if boolean_field_name:
            if (
                self.commercial_partner_id[boolean_field_name]
                and self.commercial_partner_id not in self.message_partner_ids
            ):
                partners |= self.commercial_partner_id
            for contact in self.commercial_partner_id.child_ids:
                if contact[boolean_field_name] and contact not in self.message_partner_ids:
                    partners |= contact
        if partners:
            self.message_subscribe(partners.ids)
        return True

    @api.model
    def l10n_ec_get_total_impuestos(
        self,
        parent_node,
        codigo,
        codigo_porcentaje,
        base,
        valor,
        tag_name="totalImpuesto",
        tarifa=-1,
        refund=False,
        liquidation=False,
        decimales=2,
    ):
        util_model = self.env["l10n_ec.utils"]
        tag = SubElement(parent_node, tag_name)
        SubElement(tag, "codigo").text = codigo
        SubElement(tag, "codigoPorcentaje").text = codigo_porcentaje
        if liquidation:
            if refund:
                if tarifa != -1:
                    SubElement(tag, "tarifa").text = util_model.formato_numero(tarifa, 0)
                SubElement(tag, "baseImponibleReembolso").text = util_model.formato_numero(base, decimales)
                SubElement(tag, "impuestoReembolso").text = util_model.formato_numero(valor, decimales)
            else:
                SubElement(tag, "baseImponible").text = util_model.formato_numero(base, decimales)
                if tarifa != -1:
                    SubElement(tag, "tarifa").text = util_model.formato_numero(tarifa, 0)
                SubElement(tag, "valor").text = util_model.formato_numero(valor, decimales)
        else:
            if tarifa != -1:
                SubElement(tag, "tarifa").text = util_model.formato_numero(tarifa, 0)
            if refund:
                SubElement(tag, "baseImponibleReembolso").text = util_model.formato_numero(base, decimales)
                SubElement(tag, "impuestoReembolso").text = util_model.formato_numero(valor, decimales)
            else:
                SubElement(tag, "baseImponible").text = util_model.formato_numero(base, decimales)
                SubElement(tag, "valor").text = util_model.formato_numero(valor, decimales)
        return tag

    @api.model
    def l10n_ec_get_motives(self, parent_node, razon="", valor=0, tag_name="motivo"):
        util_model = self.env["l10n_ec.utils"]
        tag = SubElement(parent_node, tag_name)
        SubElement(tag, "razon").text = razon
        SubElement(tag, "valor").text = util_model.formato_numero(valor, 2)
        return tag

    def l10n_ec_get_payment_data(self):
        payment_data = []
        foreign_currency = self.currency_id if self.currency_id != self.company_id.currency_id else False
        pay_term_line_ids = self.line_ids.filtered(
            lambda line: line.account_id.user_type_id.type in ("receivable", "payable")
        )
        partials = pay_term_line_ids.mapped("matched_debit_ids") + pay_term_line_ids.mapped("matched_credit_ids")
        for partial in partials:
            counterpart_lines = partial.debit_move_id + partial.credit_move_id
            counterpart_line = counterpart_lines.filtered(lambda line: line not in self.line_ids)
            if not counterpart_line.payment_id.l10n_ec_sri_payment_id:
                continue
            if foreign_currency and partial.currency_id == foreign_currency:
                amount = partial.amount_currency
            else:
                amount = partial.company_currency_id._convert(
                    partial.amount, self.currency_id, self.company_id, self.date
                )
            if float_is_zero(amount, precision_rounding=self.currency_id.rounding):
                continue
            payment_vals = {
                "name": counterpart_line.payment_id.l10n_ec_sri_payment_id.name,
                "formaPago": counterpart_line.payment_id.l10n_ec_sri_payment_id.code,
                "total": amount,
            }
            if (
                self.invoice_payment_term_id
                and self.invoice_payment_term_id.l10n_ec_sri_type == "credito"
                and self.l10n_ec_credit_days > 0
            ):
                payment_vals.update(
                    {
                        "plazo": self.l10n_ec_credit_days,
                        "unidadTiempo": "dias",
                    }
                )
            payment_data.append(payment_vals)
        if not payment_data:
            l10n_ec_sri_payment = self.l10n_ec_sri_payment_id
            if not l10n_ec_sri_payment:
                l10n_ec_sri_payment = self.commercial_partner_id.l10n_ec_sri_payment_id
            if not l10n_ec_sri_payment:
                l10n_ec_sri_payment = self.company_id.l10n_ec_sri_payment_id
            if not l10n_ec_sri_payment:
                raise UserError(
                    _(
                        "Debe configurar la forma de pago por defecto esto lo encuentra en Contabilidad / SRI / Configuración"
                    )
                )
            payment_vals = {
                "name": l10n_ec_sri_payment.name,
                "formaPago": l10n_ec_sri_payment.code,
                "total": self.amount_total,
            }
            if (
                self.invoice_payment_term_id
                and self.invoice_payment_term_id.l10n_ec_sri_type == "credito"
                and self.l10n_ec_credit_days > 0
            ):
                payment_vals.update(
                    {
                        "plazo": self.l10n_ec_credit_days,
                        "unidadTiempo": "dias",
                    }
                )
            payment_data.append(payment_vals)
        return payment_data

    def l10n_ec_get_tarifa_iva(self):
        tarifa_iva = 0
        iva_group = self.env.ref("l10n_ec_niif.tax_group_iva")
        for line in self.line_ids:
            if line.tax_line_id.tax_group_id.id == iva_group.id and line.tax_line_id.amount > 0:
                tarifa_iva = line.tax_line_id.amount
        if not tarifa_iva:
            tarifa_iva = 12.0
        return tarifa_iva

    def l10n_ec_get_document_code_sri(self):
        invoice_type = self.l10n_ec_get_invoice_type()
        # factura de venta es codigo 18, pero aca debe pasarse codigo 01
        # los demas documentos tomar del tipo de documento(l10n_latam_document_type_id)
        if invoice_type == "out_invoice":
            document_code_sri = "01"
        else:
            document_code_sri = self.l10n_latam_document_type_id.code
        return document_code_sri

    def l10n_ec_get_document_number(self):
        # esta funcion debe devolver el numero de documento
        return self.l10n_latam_document_number

    def l10n_ec_get_document_date(self):
        # esta funcion debe devolver la fecha de emision del documento
        return self.invoice_date

    def l10n_ec_get_document_string(self):
        return self.l10n_latam_document_type_id.report_name

    def l10n_ec_get_document_version_xml(self):
        # esta funcion debe devolver la version del xml que se debe usar
        company = self.company_id or self.env.company
        invoice_type = self.l10n_ec_get_invoice_type()
        document_type = modules_mapping.get_document_type(invoice_type)
        return company[f"l10n_ec_{document_type}_version_xml_id"]

    def l10n_ec_get_document_filename_xml(self):
        # esta funcion debe devolver el nombre del archivo xml sin la extension
        # algo como: id, prefijo, secuencial
        return f"{self.id}_{self.l10n_latam_document_type_id.doc_code_prefix}_{self.l10n_ec_get_document_number()}"

    def l10n_ec_action_generate_xml_data(self, node_root, xml_version):
        invoice_type = self.l10n_ec_get_invoice_type()
        if invoice_type == "out_invoice":
            self.l10n_ec_get_info_factura(node_root, xml_version)
        # nota de credito
        elif invoice_type == "out_refund":
            self.l10n_ec_get_info_credit_note(node_root)
        # nota de debito
        elif invoice_type == "debit_note_out":
            self.l10n_ec_get_info_debit_note(node_root)
        # liquidacion de compras
        elif invoice_type == "liquidation":
            self.l10n_ec_get_info_liquidation(node_root)
        return True

    def _l10n_ec_get_invoice_lines_to_fe(self):
        """
        Repartir las lineas con total en negativo(descuentos) a las demas lineas segun los impuestos aplicados
        @return: diccionario con los datos calculados:
            invoice_lines: browse_record(account.move.line), lineas normales sobre los que se repartira el descuento
            lines_discount: browse_record(account.move.line) lineas de descuento con valores a repartir
            invoice_line_data: dict(line_id, dict), diccionario con los valores calculados por cada linea de factura
        """
        iva_group = self.env.ref("l10n_ec_niif.tax_group_iva")
        iva0_group = self.env.ref("l10n_ec_niif.tax_group_iva_0")
        invoice_lines = self.invoice_line_ids.filtered(lambda x: not x.display_type).sorted("price_subtotal")
        lines_discount = invoice_lines.filtered(lambda x: x.price_subtotal < 0)
        invoice_lines -= lines_discount
        invoice_line_data = {}
        discount_by_tax = {}
        invoice_lines_by_tax = {}
        for line in lines_discount:
            if line.tax_ids not in discount_by_tax:
                discount_by_tax[line.tax_ids] = self.env["account.move.line"]
            discount_by_tax[line.tax_ids] |= line
        for line in invoice_lines:
            if line.tax_ids not in invoice_lines_by_tax:
                invoice_lines_by_tax[line.tax_ids] = self.env["account.move.line"]
            invoice_lines_by_tax[line.tax_ids] |= line
        discount_applied_data = {}
        for line in invoice_lines:
            if line.tax_ids not in discount_applied_data:
                discount_applied_data[line.tax_ids] = {"lines": self.env["account.move.line"], "discount_applied": 0}
            discount_applied_data[line.tax_ids]["lines"] |= line
            discount_lines = discount_by_tax.get(line.tax_ids) or self.env["account.move.line"]
            total_discount_amount = abs(sum(discount_lines.mapped("price_subtotal")))
            ail_by_tax = invoice_lines_by_tax.get(line.tax_ids) or self.env["account.move.line"]
            ail_amount_total = abs(sum(ail_by_tax.mapped("price_subtotal")))
            discount_unit_additional = 0.0
            if ail_amount_total:
                discount_unit_additional = round((line.price_subtotal / ail_amount_total) * 100.0, 2)
            discount = round(((line.price_unit * line.quantity) * ((line.discount or 0.0) / 100)), 2)
            discount_additional = round((total_discount_amount * ((discount_unit_additional or 0.0) / 100)), 2)
            # en la ultima linea asignar la diferencia entre lo asignado y el total a asignar
            if len(discount_applied_data[line.tax_ids]["lines"]) == len(ail_by_tax):
                discount_additional = round(
                    total_discount_amount - discount_applied_data[line.tax_ids]["discount_applied"], 2
                )
            discount_applied_data[line.tax_ids]["discount_applied"] += round(discount_additional, 2)
            discount += discount_additional
            subtotal = round(((line.price_unit * line.quantity) - discount), 2)
            l10n_ec_base_iva_0 = line.l10n_ec_base_iva_0
            l10n_ec_base_iva = line.l10n_ec_base_iva
            if iva0_group in line.tax_ids.mapped("tax_group_id"):
                l10n_ec_base_iva_0 -= discount_additional
            if iva_group in line.tax_ids.mapped("tax_group_id"):
                l10n_ec_base_iva -= discount_additional
            l10n_ec_iva = line.l10n_ec_iva
            tarifa_iva = 12
            taxes_res = line.tax_ids._origin.compute_all(
                l10n_ec_base_iva,
                quantity=1,
                currency=self.currency_id,
                product=line.product_id,
                partner=self.partner_id,
                is_refund=self.type in ("out_refund", "in_refund"),
            )
            # impuestos de iva 0 no agregan reparticion de impuestos,
            # por ahora se consideran base_iva_0, verificar esto
            if taxes_res["taxes"]:
                for tax_data in taxes_res["taxes"]:
                    tax = self.env["account.tax"].browse(tax_data["id"])
                    if tax.tax_group_id.id == iva_group.id:
                        l10n_ec_iva = tax_data["amount"]
                    if tax.tax_group_id.id in [iva_group.id, iva0_group.id]:
                        tarifa_iva = tax.amount
            invoice_line_data[line.id] = {
                "discount": discount,
                "discount_additional": discount_additional,
                "subtotal": subtotal,
                "l10n_ec_base_iva_0": l10n_ec_base_iva_0,
                "l10n_ec_base_iva": l10n_ec_base_iva,
                "l10n_ec_iva": l10n_ec_iva,
                "tarifa_iva": tarifa_iva,
            }
        return {
            "invoice_lines": invoice_lines,
            "ordered_lines": self.env["account.move.line"].search(
                [("id", "in", self.invoice_line_ids.ids)], order="sequence"
            ),
            "lines_discount": lines_discount,
            "invoice_line_data": invoice_line_data,
        }

    def l10n_ec_asign_discount_to_lines(self):
        for invoice in self:
            invoice_lines_data = invoice._l10n_ec_get_invoice_lines_to_fe()
            invoice_lines = invoice_lines_data["invoice_lines"]
            invoice_line_data = invoice_lines_data["invoice_line_data"]
            for line in invoice_lines:
                line_data = invoice_line_data.get(line.id, {})
                line.write({"l10n_ec_discount_additional": line_data.get("discount_additional") or 0.0})
        return True

    def l10n_ec_get_info_factura(self, node, xml_version):
        util_model = self.env["l10n_ec.utils"]
        company = self.company_id or self.env.company
        currency = company.currency_id
        precision_get = self.env["decimal.precision"].precision_get
        digits_precision_product = precision_get("Product Price")
        digits_precision_qty = precision_get("Product Unit of Measure")
        digits_precision_discount = precision_get("Discount")
        infoFactura = SubElement(node, "infoFactura")
        fecha_factura = self.invoice_date.strftime(util_model.get_formato_date())
        SubElement(infoFactura, "fechaEmision").text = fecha_factura
        address = company.partner_id.street
        invoice_lines_data = self._l10n_ec_get_invoice_lines_to_fe()
        invoice_lines = invoice_lines_data["invoice_lines"]
        lines_discount = invoice_lines_data["lines_discount"]
        invoice_line_data = invoice_lines_data["invoice_line_data"]
        l10n_ec_discount_total = self.l10n_ec_discount_total
        l10n_ec_discount_total += abs(sum(lines_discount.mapped("price_subtotal")))
        SubElement(infoFactura, "dirEstablecimiento").text = util_model._clean_str(address)[:300]
        if self.l10n_ec_identification_type_id:
            tipoIdentificacionComprador = self.l10n_ec_identification_type_id.code
        elif self.commercial_partner_id:
            tipoIdentificacionComprador = self.commercial_partner_id.l10n_ec_get_sale_identification_partner()
        else:
            # si no tengo informacion paso por defecto consumiro final
            # pero debe tener como identificacion 13 digitos 99999999999999
            tipoIdentificacionComprador = "07"
        numero_contribuyente_especial = company.get_contribuyente_data(self.invoice_date)
        if numero_contribuyente_especial:
            SubElement(infoFactura, "contribuyenteEspecial").text = numero_contribuyente_especial
        SubElement(infoFactura, "obligadoContabilidad").text = util_model.get_obligado_contabilidad(
            company.partner_id.property_account_position_id
        )
        SubElement(infoFactura, "tipoIdentificacionComprador").text = tipoIdentificacionComprador
        # if self.remision_id:
        #     SubElement(infoFactura, "guiaRemision").text = self.remision_id.document_number
        SubElement(infoFactura, "razonSocialComprador").text = util_model._clean_str(
            self.commercial_partner_id.name[:300], skip_character=["-", "."]
        )
        vat = self.commercial_partner_id.vat
        if self.l10n_ec_identification_type_id.code == "06":
            vat = "9999999999"
        SubElement(infoFactura, "identificacionComprador").text = vat
        SubElement(infoFactura, "direccionComprador").text = util_model._clean_str(self.commercial_partner_id.street)[
            :300
        ]

        SubElement(infoFactura, "totalSinImpuestos").text = util_model.formato_numero(
            self.amount_untaxed, currency.decimal_places
        )
        SubElement(infoFactura, "totalDescuento").text = util_model.formato_numero(
            l10n_ec_discount_total, currency.decimal_places
        )
        # Comprobante de venta emitido por reembolso(codigo 41)
        if self.l10n_latam_document_type_id and self.l10n_latam_document_type_id.code == "41":
            self.l10n_ec_generate_info_reembolsos_head_xml(infoFactura)
        # Definicion de Impuestos
        totalConImpuestos = SubElement(infoFactura, "totalConImpuestos")
        if self.l10n_ec_base_iva_0 != 0:
            self.l10n_ec_get_total_impuestos(
                totalConImpuestos,
                "2",
                "0",
                self.l10n_ec_base_iva_0,
                0.0,
                decimales=currency.decimal_places,
            )
        if self.l10n_ec_base_iva != 0:
            self.l10n_ec_get_total_impuestos(
                totalConImpuestos,
                "2",
                "2",
                self.l10n_ec_base_iva,
                self.l10n_ec_iva,
                decimales=currency.decimal_places,
            )
        # if self.base_no_iva != 0:
        #     self.l10n_ec_get_total_impuestos(totalConImpuestos, '2', '6', self.base_no_iva, 0.0,
        #                              decimales=currency.decimal_places)
        # SubElement(infoFactura, "propina").text = util_model.formato_numero(self.propina or 0,
        #                                                                         currency.decimal_places)
        SubElement(infoFactura, "importeTotal").text = util_model.formato_numero(
            self.amount_total, currency.decimal_places
        )
        SubElement(infoFactura, "moneda").text = self.company_id.currency_id.name or "DOLAR"
        # Procesamiento de los pagos
        payments_data = self.l10n_ec_get_payment_data()
        pagos = SubElement(infoFactura, "pagos")
        for payment_data in payments_data:
            pago = SubElement(pagos, "pago")
            SubElement(pago, "formaPago").text = payment_data["formaPago"]
            SubElement(pago, "total").text = util_model.formato_numero(payment_data["total"])
            if payment_data.get("plazo"):
                SubElement(pago, "plazo").text = util_model.formato_numero(payment_data.get("plazo"), 0)
                SubElement(pago, "unidadTiempo").text = payment_data.get("unidadTiempo") or "dias"
        # Lineas de Factura
        detalles = SubElement(node, "detalles")
        for line in invoice_lines:
            line_data = invoice_line_data.get(line.id, {})
            discount = line_data["discount"]
            subtotal = line_data["subtotal"]
            l10n_ec_base_iva_0 = line_data["l10n_ec_base_iva_0"]
            l10n_ec_base_iva = line_data["l10n_ec_base_iva"]
            l10n_ec_iva = line_data["l10n_ec_iva"]
            tarifa_iva = line_data["tarifa_iva"]
            detalle = SubElement(detalles, "detalle")
            SubElement(detalle, "codigoPrincipal").text = util_model._clean_str(
                line.product_id and line.product_id.default_code and line.product_id.default_code[:25] or "N/A"
            )
            #             SubElement(detalle,"codigoAdicional").text = util_model._clean_str(line.product_id and line.product_id.default_code and line.product_id.default_code[:25] or 'N/A')
            SubElement(detalle, "descripcion").text = util_model._clean_str(
                line.product_id and line.product_id.name[:300] or line.name[:300]
            )
            # Debido a que los precios son en 2 decimales, es necesario hacer razonable el precio unitario
            SubElement(detalle, "cantidad").text = util_model.formato_numero(line.quantity, digits_precision_qty)
            SubElement(detalle, "precioUnitario").text = util_model.formato_numero(
                line.price_unit, digits_precision_product
            )
            SubElement(detalle, "descuento").text = util_model.formato_numero(
                discount or 0.0, digits_precision_discount
            )
            SubElement(detalle, "precioTotalSinImpuesto").text = util_model.formato_numero(
                subtotal, currency.decimal_places
            )
            if (
                line.l10n_ec_xml_additional_info1
                or line.l10n_ec_xml_additional_info2
                or line.l10n_ec_xml_additional_info3
            ):
                detallesAdicionales = SubElement(detalle, "detallesAdicionales")
                if line.l10n_ec_xml_additional_info1:
                    detAdicional = SubElement(detallesAdicionales, "detAdicional")
                    detAdicional.set("nombre", company.l10n_ec_string_ride_detail1 or "Detalle1")
                    detAdicional.set("valor", line.l10n_ec_xml_additional_info1)
                if line.l10n_ec_xml_additional_info2:
                    detAdicional = SubElement(detallesAdicionales, "detAdicional")
                    detAdicional.set("nombre", company.l10n_ec_string_ride_detail2 or "Detalle2")
                    detAdicional.set("valor", line.l10n_ec_xml_additional_info2)
                if line.l10n_ec_xml_additional_info3:
                    detAdicional = SubElement(detallesAdicionales, "detAdicional")
                    detAdicional.set("nombre", company.l10n_ec_string_ride_detail3 or "Detalle3")
                    detAdicional.set("valor", line.l10n_ec_xml_additional_info3)

            impuestos = SubElement(detalle, "impuestos")
            if tarifa_iva <= 0:
                self.l10n_ec_get_total_impuestos(
                    impuestos,
                    "2",
                    "0",
                    l10n_ec_base_iva_0,
                    0.0,
                    "impuesto",
                    0,
                    decimales=currency.decimal_places,
                )
            else:
                self.l10n_ec_get_total_impuestos(
                    impuestos,
                    "2",
                    "2",
                    l10n_ec_base_iva,
                    l10n_ec_iva,
                    "impuesto",
                    tarifa_iva,
                    decimales=currency.decimal_places,
                )
            # if line.base_no_iva != 0:
            #     self.l10n_ec_get_total_impuestos(impuestos, '2', '6', line.base_no_iva, 0.0, 'impuesto', 0,
            #                              decimales=currency.decimal_places)
        # Las retenciones solo aplican para el esquema de gasolineras
        # retenciones = SubElement(node,"retenciones")
        if xml_version.version_file in ("2.0.0", "2.1.0"):
            third_amounts_group = self.env.ref("l10n_ec_niif.tax_group_third_amounts")
            other_values = {}
            for group in self.amount_by_group:
                if group[6] == third_amounts_group.id:
                    other_values.setdefault(group[0], 0)
                    other_values[group[0]] += group[1]
            other_taxes = self.line_ids.mapped("tax_ids").filtered(
                lambda x: x.tax_group_id.id == third_amounts_group.id
            )
            if other_values and len(other_values.keys()) == 1 and len(other_taxes) == 1:
                otrosRubrosTerceros = SubElement(node, "otrosRubrosTerceros")
                for name in other_values.keys():
                    rubro = SubElement(otrosRubrosTerceros, "rubro")
                    SubElement(rubro, "concepto").text = other_taxes.name
                    SubElement(rubro, "total").text = util_model.formato_numero(other_values[name], 2)
        # informacion de reembolso solo se debe agregar si el tipo de documento es
        # Comprobante de venta emitido por reembolso(codigo 41)
        self.l10n_ec_generate_info_reembolsos_xml(node)
        self.l10n_ec_add_info_adicional(node)
        return node

    def l10n_ec_get_info_credit_note(self, node):
        util_model = self.env["l10n_ec.utils"]
        company = self.company_id or self.env.company
        currency = company.currency_id
        precision_get = self.env["decimal.precision"].precision_get
        digits_precision_product = precision_get("Product Price")
        digits_precision_qty = precision_get("Product Unit of Measure")
        digits_precision_discount = precision_get("Discount")
        infoNotaCredito = SubElement(node, "infoNotaCredito")
        fecha_factura = self.invoice_date.strftime(util_model.get_formato_date())
        SubElement(infoNotaCredito, "fechaEmision").text = fecha_factura
        address = company.partner_id.street
        invoice_lines_data = self._l10n_ec_get_invoice_lines_to_fe()
        invoice_lines = invoice_lines_data["invoice_lines"]
        invoice_line_data = invoice_lines_data["invoice_line_data"]
        SubElement(infoNotaCredito, "dirEstablecimiento").text = util_model._clean_str(address and address[:300] or "")
        if self.l10n_ec_identification_type_id:
            tipoIdentificacionComprador = self.l10n_ec_identification_type_id.code
        elif self.commercial_partner_id:
            tipoIdentificacionComprador = self.commercial_partner_id.l10n_ec_get_sale_identification_partner()
        else:
            # si no tengo informacion paso por defecto consumiro final
            # pero debe tener como identificacion 13 digitos 99999999999999
            tipoIdentificacionComprador = "07"
        SubElement(infoNotaCredito, "tipoIdentificacionComprador").text = tipoIdentificacionComprador
        SubElement(infoNotaCredito, "razonSocialComprador").text = util_model._clean_str(
            self.commercial_partner_id.name[:300], skip_character=["-", "."]
        )
        SubElement(infoNotaCredito, "identificacionComprador").text = self.commercial_partner_id.vat
        company = self.env.company
        numero_contribuyente_especial = company.get_contribuyente_data(self.invoice_date)
        if numero_contribuyente_especial:
            SubElement(infoNotaCredito, "contribuyenteEspecial").text = numero_contribuyente_especial
        SubElement(infoNotaCredito, "obligadoContabilidad").text = util_model.get_obligado_contabilidad(
            company.partner_id.property_account_position_id
        )
        if self.l10n_ec_rise:
            SubElement(infoNotaCredito, "rise").text = self.l10n_ec_rise
        # TODO: notas de credito solo se emitiran a facturas o a otros documentos???
        SubElement(infoNotaCredito, "codDocModificado").text = "01"
        SubElement(infoNotaCredito, "numDocModificado").text = (
            self.l10n_ec_legacy_document_number or self.l10n_ec_original_invoice_id.l10n_ec_get_document_number()
        )
        SubElement(infoNotaCredito, "fechaEmisionDocSustento").text = (
            self.l10n_ec_legacy_document_date or self.l10n_ec_original_invoice_id.l10n_ec_get_document_date()
        ).strftime(util_model.get_formato_date())
        SubElement(infoNotaCredito, "totalSinImpuestos").text = util_model.formato_numero(
            self.amount_untaxed, currency.decimal_places
        )
        SubElement(infoNotaCredito, "valorModificacion").text = util_model.formato_numero(
            self.amount_total, currency.decimal_places
        )
        SubElement(infoNotaCredito, "moneda").text = self.company_id.currency_id.name or "DOLAR"
        # Definicion de Impuestos
        totalConImpuestos = SubElement(infoNotaCredito, "totalConImpuestos")
        if self.l10n_ec_base_iva_0 != 0:
            self.l10n_ec_get_total_impuestos(
                totalConImpuestos,
                "2",
                "0",
                self.l10n_ec_base_iva_0,
                0.0,
                decimales=currency.decimal_places,
            )
        if self.l10n_ec_base_iva != 0:
            self.l10n_ec_get_total_impuestos(
                totalConImpuestos,
                "2",
                "2",
                self.l10n_ec_base_iva,
                self.l10n_ec_iva,
                decimales=currency.decimal_places,
            )
        # if self.base_no_iva != 0:
        #     self.l10n_ec_get_total_impuestos(totalConImpuestos, '2', '6', self.base_no_iva, 0.0,
        #                              decimales=currency.decimal_places)
        SubElement(infoNotaCredito, "motivo").text = util_model._clean_str(
            self.ref and self.ref[:300] or "NOTA DE CREDITO"
        )
        # Lineas de Factura
        detalles = SubElement(node, "detalles")
        for line in invoice_lines:
            line_data = invoice_line_data.get(line.id, {})
            discount = line_data["discount"]
            subtotal = line_data["subtotal"]
            l10n_ec_base_iva_0 = line_data["l10n_ec_base_iva_0"]
            l10n_ec_base_iva = line_data["l10n_ec_base_iva"]
            l10n_ec_iva = line_data["l10n_ec_iva"]
            tarifa_iva = line_data["tarifa_iva"]
            detalle = SubElement(detalles, "detalle")
            SubElement(detalle, "codigoInterno").text = util_model._clean_str(
                line.product_id and line.product_id.default_code and line.product_id.default_code[:25] or "N/A"
            )
            #             SubElement(detalle,"codigoAdicional").text = util_model._clean_str(line.product_id and line.product_id.default_code and line.product_id.default_code[:25] or 'N/A')
            SubElement(detalle, "descripcion").text = util_model._clean_str(
                line.product_id and line.product_id.name[:300] or line.name[:300]
            )
            # Debido a que los precios son en 2 decimales, es necesario hacer razonable el precio unitario
            SubElement(detalle, "cantidad").text = util_model.formato_numero(line.quantity, digits_precision_qty)
            SubElement(detalle, "precioUnitario").text = util_model.formato_numero(
                line.price_unit, digits_precision_product
            )
            SubElement(detalle, "descuento").text = util_model.formato_numero(
                discount or 0.0, digits_precision_discount
            )
            SubElement(detalle, "precioTotalSinImpuesto").text = util_model.formato_numero(
                subtotal, currency.decimal_places
            )
            impuestos = SubElement(detalle, "impuestos")
            if not currency.is_zero(l10n_ec_base_iva_0):
                self.l10n_ec_get_total_impuestos(
                    impuestos,
                    "2",
                    "0",
                    l10n_ec_base_iva_0,
                    0.0,
                    "impuesto",
                    0,
                    decimales=currency.decimal_places,
                )
            if not currency.is_zero(l10n_ec_base_iva):
                self.l10n_ec_get_total_impuestos(
                    impuestos,
                    "2",
                    "2",
                    l10n_ec_base_iva,
                    l10n_ec_iva,
                    "impuesto",
                    tarifa_iva,
                    decimales=currency.decimal_places,
                )
            # if line.base_no_iva != 0:
            #     self.l10n_ec_get_total_impuestos(impuestos, '2', '6', line.base_no_iva, 0.0, 'impuesto', 0,
            #                              decimales=currency.decimal_places)
        self.l10n_ec_add_info_adicional(node)
        return node

    def l10n_ec_get_info_debit_note(self, node):
        util_model = self.env["l10n_ec.utils"]
        company = self.company_id or self.env.company
        currency = company.currency_id
        infoNotaDebito = SubElement(node, "infoNotaDebito")
        fecha_emision = self.invoice_date.strftime(util_model.get_formato_date())
        SubElement(infoNotaDebito, "fechaEmision").text = fecha_emision
        address = company.partner_id.street
        SubElement(infoNotaDebito, "dirEstablecimiento").text = util_model._clean_str(address and address[:300] or "")
        if self.l10n_ec_identification_type_id:
            tipoIdentificacionComprador = self.l10n_ec_identification_type_id.code
        elif self.commercial_partner_id:
            tipoIdentificacionComprador = self.commercial_partner_id.l10n_ec_get_sale_identification_partner()
        else:
            # si no tengo informacion paso por defecto consumiro final
            # pero debe tener como identificacion 13 digitos 99999999999999
            tipoIdentificacionComprador = "07"
        SubElement(infoNotaDebito, "tipoIdentificacionComprador").text = tipoIdentificacionComprador
        SubElement(infoNotaDebito, "razonSocialComprador").text = util_model._clean_str(
            self.commercial_partner_id.name[:300], skip_character=["-", "."]
        )
        SubElement(infoNotaDebito, "identificacionComprador").text = self.commercial_partner_id.vat
        company = self.env.company
        numero_contribuyente_especial = company.get_contribuyente_data(self.invoice_date)
        if numero_contribuyente_especial:
            SubElement(infoNotaDebito, "contribuyenteEspecial").text = numero_contribuyente_especial
        SubElement(infoNotaDebito, "obligadoContabilidad").text = util_model.get_obligado_contabilidad(
            company.partner_id.property_account_position_id
        )
        if self.l10n_ec_rise:
            SubElement(infoNotaDebito, "rise").text = self.l10n_ec_rise
        # TODO: notas de debito solo se emitiran a facturas o a otros documentos???
        SubElement(infoNotaDebito, "codDocModificado").text = "01"
        SubElement(infoNotaDebito, "numDocModificado").text = (
            self.l10n_ec_legacy_document_number or self.debit_origin_id.l10n_ec_get_document_number()
        )
        SubElement(infoNotaDebito, "fechaEmisionDocSustento").text = (
            self.l10n_ec_legacy_document_date or self.debit_origin_id.l10n_ec_get_document_date()
        ).strftime(util_model.get_formato_date())
        SubElement(infoNotaDebito, "totalSinImpuestos").text = util_model.formato_numero(self.amount_untaxed)
        # Definicion de Impuestos
        # xq no itero sobre los impuestos???'
        impuestos = SubElement(infoNotaDebito, "impuestos")
        if self.l10n_ec_base_iva_0 != 0:
            self.l10n_ec_get_total_impuestos(
                impuestos,
                "2",
                "0",
                self.l10n_ec_base_iva_0,
                0.0,
                "impuesto",
                0,
                decimales=currency.decimal_places,
            )
        if self.l10n_ec_base_iva != 0:
            # TODO: no se debe asumir que el % del iva es 12, tomar del impuesto directamente
            self.l10n_ec_get_total_impuestos(
                impuestos,
                "2",
                "2",
                self.l10n_ec_base_iva,
                self.l10n_ec_iva,
                "impuesto",
                12,
                decimales=currency.decimal_places,
            )
        # if self.base_no_iva != 0:
        #     self.l10n_ec_get_total_impuestos(impuestos, '2', '6', self.base_no_iva, 0.0, 'impuesto', 0,
        #                              decimales=currency.decimal_places)
        SubElement(infoNotaDebito, "valorTotal").text = util_model.formato_numero(
            self.amount_total, currency.decimal_places
        )
        motivos = SubElement(node, "motivos")
        for line in self.invoice_line_ids.filtered(lambda x: not x.display_type):
            self.l10n_ec_get_motives(
                motivos,
                util_model._clean_str(line.product_id and line.product_id.name[:300] or line.name[:300]),
                line.price_subtotal,
            )
        self.l10n_ec_add_info_adicional(node)
        return node

    def l10n_ec_get_info_liquidation(self, node):
        util_model = self.env["l10n_ec.utils"]
        company = self.company_id or self.env.company
        currency = company.currency_id
        precision_get = self.env["decimal.precision"].precision_get
        digits_precision_product = precision_get("Product Price")
        digits_precision_qty = precision_get("Product Unit of Measure")
        digits_precision_discount = precision_get("Discount")
        infoLiquidacionCompra = SubElement(node, "infoLiquidacionCompra")
        fecha_emision = self.invoice_date.strftime(util_model.get_formato_date())
        SubElement(infoLiquidacionCompra, "fechaEmision").text = fecha_emision
        address = company.partner_id.street
        SubElement(infoLiquidacionCompra, "dirEstablecimiento").text = util_model._clean_str(
            address and address[:300] or ""
        )
        numero_contribuyente_especial = company.get_contribuyente_data(self.invoice_date)
        if numero_contribuyente_especial:
            SubElement(infoLiquidacionCompra, "contribuyenteEspecial").text = numero_contribuyente_especial
        SubElement(infoLiquidacionCompra, "obligadoContabilidad").text = util_model.get_obligado_contabilidad(
            company.partner_id.property_account_position_id
        )
        if self.commercial_partner_id:
            tipoIdentificacionComprador = self.commercial_partner_id.l10n_ec_get_sale_identification_partner()
        else:
            # si no tengo informacion paso por defecto consumiro final
            # pero debe tener como identificacion 13 digitos 99999999999999
            tipoIdentificacionComprador = "07"
        SubElement(infoLiquidacionCompra, "tipoIdentificacionProveedor").text = tipoIdentificacionComprador
        SubElement(infoLiquidacionCompra, "razonSocialProveedor").text = util_model._clean_str(
            self.commercial_partner_id.name[:300]
        )
        SubElement(infoLiquidacionCompra, "identificacionProveedor").text = self.commercial_partner_id.vat
        SubElement(infoLiquidacionCompra, "direccionProveedor").text = util_model._clean_str(
            self.commercial_partner_id.street[:300]
        )
        SubElement(infoLiquidacionCompra, "totalSinImpuestos").text = util_model.formato_numero(
            self.amount_untaxed, decimales=currency.decimal_places
        )
        SubElement(infoLiquidacionCompra, "totalDescuento").text = util_model.formato_numero(
            self.l10n_ec_discount_total, decimales=currency.decimal_places
        )
        if self.l10n_ec_refund_ids:
            self.l10n_ec_generate_info_reembolsos_head_xml(infoLiquidacionCompra)
        # Definicion de Impuestos
        # xq no itero sobre los impuestos???'
        impuestos = SubElement(infoLiquidacionCompra, "totalConImpuestos")
        if self.l10n_ec_base_iva_0 != 0:
            self.l10n_ec_get_total_impuestos(
                impuestos,
                "2",
                "0",
                self.l10n_ec_base_iva_0,
                0.0,
                "totalImpuesto",
                0,
                False,
                True,
                decimales=currency.decimal_places,
            )
        if self.l10n_ec_base_iva != 0:
            # TODO: no se debe asumir que el % del iva es 12, tomar del impuesto directamente
            self.l10n_ec_get_total_impuestos(
                impuestos,
                "2",
                "2",
                self.l10n_ec_base_iva,
                self.l10n_ec_iva,
                "totalImpuesto",
                12,
                False,
                True,
                decimales=currency.decimal_places,
            )
        # if self.base_no_iva != 0:
        #     self.l10n_ec_get_total_impuestos(impuestos, '2', '6', self.base_no_iva, 0.0, 'totalImpuesto', 0, False, True)
        SubElement(infoLiquidacionCompra, "importeTotal").text = util_model.formato_numero(
            self.amount_total + sum(self.l10n_ec_withhold_line_ids.mapped("tax_amount_currency")),
            decimales=currency.decimal_places,
        )
        SubElement(infoLiquidacionCompra, "moneda").text = self.company_id.currency_id.name
        payments_data = self.l10n_ec_get_payment_data()
        pagos = SubElement(infoLiquidacionCompra, "pagos")
        for payment_data in payments_data:
            pago = SubElement(pagos, "pago")
            SubElement(pago, "formaPago").text = payment_data["formaPago"]
            SubElement(pago, "total").text = util_model.formato_numero(payment_data["total"])
            if payment_data.get("plazo"):
                SubElement(pago, "plazo").text = util_model.formato_numero(payment_data.get("plazo"), 0)
                SubElement(pago, "unidadTiempo").text = payment_data.get("unidadTiempo") or "dias"
        detalles = SubElement(node, "detalles")
        for line in self.invoice_line_ids:
            detalle = SubElement(detalles, "detalle")
            SubElement(detalle, "codigoPrincipal").text = util_model._clean_str(
                line.product_id and line.product_id.default_code and line.product_id.default_code[:25] or "N/A"
            )
            SubElement(detalle, "descripcion").text = util_model._clean_str(
                line.product_id and line.product_id.name[:300] or line.name[:300]
            )
            SubElement(detalle, "unidadMedida").text = line.product_uom_id and line.product_uom_id.display_name or "N/A"
            # Debido a que los precios son en 2 decimales, es necesario hacer razonable el precio unitario
            SubElement(detalle, "cantidad").text = util_model.formato_numero(
                line.quantity, decimales=digits_precision_qty
            )
            SubElement(detalle, "precioUnitario").text = util_model.formato_numero(
                line.price_unit, decimales=digits_precision_product
            )
            discount = round(((line.price_unit * line.quantity) * ((line.discount or 0.0) / 100)), 2)
            # TODO: hacer un redondeo con las utilidades del sistema
            subtotal = round(((line.price_unit * line.quantity) - discount), 2)
            SubElement(detalle, "descuento").text = util_model.formato_numero(
                discount or 0.0, decimales=digits_precision_discount
            )
            SubElement(detalle, "precioTotalSinImpuesto").text = util_model.formato_numero(
                subtotal, decimales=currency.decimal_places
            )
            impuestos = SubElement(detalle, "impuestos")
            if line.l10n_ec_base_iva_0 != 0:
                self.l10n_ec_get_total_impuestos(
                    impuestos,
                    "2",
                    "0",
                    line.l10n_ec_base_iva_0,
                    0.0,
                    "impuesto",
                    0,
                    False,
                    decimales=currency.decimal_places,
                )
            if line.l10n_ec_base_iva != 0:
                self.l10n_ec_get_total_impuestos(
                    impuestos,
                    "2",
                    "2",
                    line.l10n_ec_base_iva,
                    line.l10n_ec_iva,
                    "impuesto",
                    12,
                    False,
                    decimales=currency.decimal_places,
                )
            # if line.base_no_iva != 0:
            #     self.l10n_ec_get_total_impuestos(impuestos, '2', '6', line.base_no_iva, 0.0, 'impuesto', 0,
            #     False, decimales=currency.decimal_places)
        # informacion de reembolso solo se debe agregar si el tipo de documento es
        # Comprobante de venta emitido por reembolso(codigo 41)
        self.l10n_ec_generate_info_reembolsos_xml(node)
        self.l10n_ec_add_info_adicional(node)
        return node

    def l10n_ec_action_sent_mail_electronic(self):
        # reemplazar funcion que es generica en modelo abstracto
        # esta funcion se llama desde el xml electronico para enviar mail al cliente
        MailComposeMessage = self.env["mail.compose.message"]
        self.ensure_one()
        res = self.action_invoice_sent()
        ctx = res["context"]
        msj = MailComposeMessage.with_context(ctx).create({})
        send_mail = True
        try:
            msj.onchange_template_id_wrapper()
            msj.send_mail()
        except Exception:
            send_mail = False
        return send_mail

    @api.constrains("invoice_date", "l10n_ec_withhold_date")
    def _check_invoice_date(self):
        for move in self:
            date_current = fields.Date.context_today(self)
            if (
                move.l10n_ec_type_emission == "electronic"
                and move.is_sale_document()
                and move.invoice_date
                and move.invoice_date > date_current
            ):
                raise UserError(_("You cannot create an electronic document with a date later than the current one"))
            if (
                move.l10n_ec_point_of_emission_withhold_id.type_emission == "electronic"
                and move.type == "in_invoice"
                and move.l10n_ec_withhold_date
                and move.l10n_ec_withhold_date > date_current
            ):
                raise UserError(
                    _("You cannot create the purchase withholding electronic %s with a date later than the current one")
                    % move.l10n_ec_withhold_number
                )
            if (
                move.l10n_ec_type_emission == "electronic"
                and move.type == "in_invoice"
                and move.l10n_latam_internal_type == "liquidation"
                and move.invoice_date
                and move.invoice_date > date_current
            ):
                raise UserError(
                    _("You cannot create the purchase liquidation electronic %s with a date later than the current one")
                    % move.l10n_latam_document_number
                )

    def l10n_ec_generate_info_reembolsos_head_xml(self, parent_node):
        util_model = self.env["l10n_ec.utils"]
        company = self.company_id or self.env.company
        currency = company.currency_id
        SubElement(parent_node, "codDocReembolso").text = "41"
        SubElement(parent_node, "totalComprobantesReembolso").text = util_model.formato_numero(
            sum([r.total_invoice for r in self.l10n_ec_refund_ids]),
            decimales=currency.decimal_places,
        )
        SubElement(parent_node, "totalBaseImponibleReembolso").text = util_model.formato_numero(
            sum([r.total_base_iva for r in self.l10n_ec_refund_ids])
            + sum([r.total_base_iva0 for r in self.l10n_ec_refund_ids]),
            decimales=currency.decimal_places,
        )
        SubElement(parent_node, "totalImpuestoReembolso").text = util_model.formato_numero(
            sum([r.total_iva for r in self.l10n_ec_refund_ids]) + sum([r.total_ice for r in self.l10n_ec_refund_ids]),
            decimales=currency.decimal_places,
        )

    def l10n_ec_generate_info_reembolsos_xml(self, node):
        util_model = self.env["l10n_ec.utils"]
        company = self.company_id or self.env.company
        currency = company.currency_id
        if self.l10n_ec_refund_ids:
            reembolsos = SubElement(node, "reembolsos")
            for refund in self.l10n_ec_refund_ids:
                reembolso_detail = SubElement(reembolsos, "reembolsoDetalle")
                tipoIdentificacionComprador = (
                    refund.partner_id.commercial_partner_id.l10n_ec_get_sale_identification_partner()
                )
                SubElement(reembolso_detail, "tipoIdentificacionProveedorReembolso").text = tipoIdentificacionComprador
                SubElement(
                    reembolso_detail, "identificacionProveedorReembolso"
                ).text = refund.partner_id.commercial_partner_id.vat
                country_code = refund.partner_id.commercial_partner_id.country_id.phone_code or "593"
                SubElement(reembolso_detail, "codPaisPagoProveedorReembolso").text = str(country_code)
                SubElement(reembolso_detail, "tipoProveedorReembolso").text = (
                    tipoIdentificacionComprador == "05" and "01" or "02"
                )
                SubElement(reembolso_detail, "codDocReembolso").text = "01"
                agency, printer, sequence = refund.document_number.split("-")
                SubElement(reembolso_detail, "estabDocReembolso").text = agency
                SubElement(reembolso_detail, "ptoEmiDocReembolso").text = printer
                SubElement(reembolso_detail, "secuencialDocReembolso").text = sequence
                fecha_emision = refund.date_invoice.strftime(util_model.get_formato_date())
                SubElement(reembolso_detail, "fechaEmisionDocReembolso").text = fecha_emision
                SubElement(reembolso_detail, "numeroautorizacionDocReemb").text = (
                    refund.l10n_ec_partner_authorization_id
                    and refund.l10n_ec_partner_authorization_id.number
                    or refund.electronic_authorization
                )
                detalleImpuestos = SubElement(reembolso_detail, "detalleImpuestos")
                tarifa_iva = refund.total_base_iva and round((refund.total_iva / refund.total_base_iva), 2) or 0.0
                tipo_iva = "2"
                if tarifa_iva == 0.14:
                    tipo_iva = "3"
                if refund.total_base_iva0 != 0:
                    self.l10n_ec_get_total_impuestos(
                        detalleImpuestos,
                        "2",
                        "0",
                        refund.total_base_iva0,
                        0.0,
                        "detalleImpuesto",
                        0,
                        liquidation=True,
                        refund=True,
                        decimales=currency.decimal_places,
                    )
                if refund.total_base_iva != 0:
                    self.l10n_ec_get_total_impuestos(
                        detalleImpuestos,
                        "2",
                        tipo_iva,
                        refund.total_base_iva,
                        refund.total_iva,
                        "detalleImpuesto",
                        int(tarifa_iva * 100),
                        liquidation=True,
                        refund=True,
                        decimales=currency.decimal_places,
                    )
                if refund.total_base_no_iva != 0:
                    self.l10n_ec_get_total_impuestos(
                        detalleImpuestos,
                        "2",
                        "6",
                        refund.total_base_no_iva,
                        0.0,
                        "detalleImpuesto",
                        0,
                        liquidation=True,
                        decimales=currency.decimal_places,
                    )

    def _l10n_ec_get_info_aditional(self):
        util_model = self.env["l10n_ec.utils"]
        info_data = super()._l10n_ec_get_info_aditional()
        narration = util_model._clean_str(self.narration or "")
        if narration:
            info_data.append(
                {
                    "name": "InformacionAdicional",
                    "description": narration,
                }
            )
        street = self.commercial_partner_id.street or (
            self.commercial_partner_id.child_ids and self.commercial_partner_id.child_ids[0].street
        )
        street = util_model._clean_str(street or "")
        if street:
            info_data.append(
                {
                    "name": "Direccion",
                    "description": street,
                }
            )
        phone = (
            self.commercial_partner_id.phone
            or self.commercial_partner_id.mobile
            or (
                self.commercial_partner_id.child_ids
                and (self.commercial_partner_id.child_ids[0].phone or self.commercial_partner_id.child_ids[0].mobile)
            )
        )
        phone = util_model._clean_str(phone or "")
        if phone:
            info_data.append(
                {
                    "name": "Telefono",
                    "description": phone,
                }
            )
        email = self.commercial_partner_id.email or (
            self.commercial_partner_id.child_ids and self.commercial_partner_id.child_ids[0].email
        )
        email = util_model._clean_str(email or "", skip_character=["@", ".", "-", "_"])
        if email:
            info_data.append(
                {
                    "name": "Email",
                    "description": email,
                }
            )
        if self.invoice_user_id:
            info_data.append(
                {
                    "name": "Vendedor",
                    "description": self.invoice_user_id.name,
                }
            )
        if self.invoice_payment_term_id:
            info_data.append(
                {
                    "name": "Forma Pago",
                    "description": self.invoice_payment_term_id.name,
                }
            )
        if self.invoice_date_due:
            info_data.append(
                {
                    "name": "F. Vencimiento",
                    "description": self.invoice_date_due.strftime("%Y-%m-%d"),
                }
            )
        return info_data


class AccountMoveLine(models.Model):
    _inherit = ["account.move.line", "l10n_ec.common.document.line"]
    _name = "account.move.line"

    l10n_ec_withhold_line_id = fields.Many2one(
        comodel_name="l10n_ec.withhold.line", string="Withhold Line", readonly=True
    )
    l10n_ec_original_invoice_line_id = fields.Many2one(
        "account.move.line", string="Origin invoice line", copy=False, index=True
    )
    l10n_ec_xml_additional_info1 = fields.Char(string="Additional Info")
    l10n_ec_xml_additional_info2 = fields.Char(string="Additional Info 2")
    l10n_ec_xml_additional_info3 = fields.Char(string="Additional Info 3")

    def _l10n_ec_get_discount_total(self):
        discount_total = self.price_unit * self.quantity * self.discount * 0.01
        return discount_total

    @api.depends(
        "price_unit",
        "product_id",
        "quantity",
        "discount",
        "tax_ids",
        "move_id.partner_id",
        "move_id.currency_id",
        "move_id.company_id",
        "move_id.invoice_date",
    )
    def _compute_l10n_ec_amounts(self):
        for move_line in self:
            move = move_line.move_id
            move_date = move.date or fields.Date.context_today(move)
            l10n_ec_base_iva_0 = 0.0
            l10n_ec_base_iva = 0.0
            l10n_ec_iva = 0.0
            price_unit_wo_discount = move_line.price_unit * (1 - (move_line.discount / 100.0))
            l10n_ec_discount_total = move_line._l10n_ec_get_discount_total()
            taxes_res = move_line.tax_ids._origin.compute_all(
                price_unit_wo_discount,
                quantity=move_line.quantity,
                currency=move.currency_id,
                product=move_line.product_id,
                partner=move.partner_id,
                is_refund=move.type in ("out_refund", "in_refund"),
            )
            # impuestos de iva 0 no agregan reparticion de impuestos,
            # por ahora se consideran base_iva_0, verificar esto
            if taxes_res["taxes"]:
                for tax_data in taxes_res["taxes"]:
                    tax = self.env["account.tax"].browse(tax_data["id"])
                    iva_group = self.env.ref("l10n_ec_niif.tax_group_iva")
                    iva_0_group = self.env.ref("l10n_ec_niif.tax_group_iva_0")
                    if tax.tax_group_id.id == iva_group.id:
                        l10n_ec_base_iva = tax_data["base"]
                        l10n_ec_iva = tax_data["amount"]
                    if tax.tax_group_id.id == iva_0_group.id:
                        l10n_ec_base_iva_0 = tax_data["base"]
            else:
                l10n_ec_base_iva_0 = taxes_res["total_excluded"]
            move_line.l10n_ec_base_iva_0 = l10n_ec_base_iva_0
            move_line.l10n_ec_base_iva = l10n_ec_base_iva
            move_line.l10n_ec_iva = l10n_ec_iva
            move_line.l10n_ec_discount_total = l10n_ec_discount_total
            # FIXME: cuando se crean lineas desde una NC, en el onchange de la factura a rectificar
            # no se tiene aun referencia a la moneda, asi que no hacer conversion de moneda
            if move.currency_id:
                move_line.l10n_ec_base_iva_0_currency = move.currency_id._convert(
                    l10n_ec_base_iva_0,
                    move.company_currency_id,
                    move.company_id,
                    move_date,
                )
                move_line.l10n_ec_base_iva_currency = move.currency_id._convert(
                    l10n_ec_base_iva,
                    move.company_currency_id,
                    move.company_id,
                    move_date,
                )
                move_line.l10n_ec_iva_currency = move.currency_id._convert(
                    l10n_ec_iva, move.company_currency_id, move.company_id, move_date
                )
                move_line.l10n_ec_discount_total_currency = move.currency_id._convert(
                    l10n_ec_discount_total,
                    move.company_currency_id,
                    move.company_id,
                    move_date,
                )
            else:
                move_line.l10n_ec_base_iva_0_currency = l10n_ec_base_iva_0
                move_line.l10n_ec_base_iva_currency = l10n_ec_base_iva
                move_line.l10n_ec_iva_currency = l10n_ec_iva
                move_line.l10n_ec_discount_total_currency = l10n_ec_discount_total

    def _copy_data_extend_business_fields(self, values):
        super(AccountMoveLine, self)._copy_data_extend_business_fields(values)
        values["l10n_ec_original_invoice_line_id"] = self.id

    def _get_third_amounts_line(self):
        self.ensure_one()
        res = {}
        other_tax = self.env.ref("l10n_ec_niif.tax_group_third_amounts")
        not_apply_iva = self.env.ref("l10n_ec_niif.1_tax_541_iva")
        if len(self.tax_ids.filtered(lambda x: x.tax_group_id.id == other_tax.id)) == 1:
            other_tax = self.tax_ids.filtered(lambda x: x.tax_group_id.id == other_tax.id)
            taxes = other_tax.compute_all(price_unit=self.price_subtotal, quantity=1.0)
            amount_tax = 0
            account_id = False
            for tax_data in taxes.get("taxes"):
                if tax_data.get("id", False) == other_tax.id:
                    amount_tax = tax_data.get("amount", 0)
                    account_id = tax_data.get("account_id", 0)
            res = {
                "line_id": self.id,
                "product_id": False,
                "process": True,
                "name": other_tax.name,
                "quantity": 1,
                "product_uom_id": False,
                "discount": 0,
                "price_unit": amount_tax,
                "price_total": amount_tax,
                "price_subtotal": amount_tax,
                "account_id": account_id,
                "analytic_account_id": self.analytic_account_id.id,
                "analytic_tag_ids": [(6, 0, self.analytic_tag_ids.ids)],
                "max_quantity": 1,
                "lot_id": False,
                "stock_move_line_id": False,
                "other_amounts": True,
                "tax_ids": [(6, 0, not_apply_iva.ids)],
            }
        return res
