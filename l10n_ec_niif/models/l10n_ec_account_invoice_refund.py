import re

from odoo import api, fields, models
from odoo.exceptions import ValidationError
from odoo.tools.translate import _


class AccountInvoiceRefund(models.Model):

    _name = "l10n_ec.account.invoice.refund"
    _description = "Invoice Refund"
    _rec_name = "document_number"

    @api.depends(
        "total_base_iva",
        "total_base_iva0",
        "total_base_no_iva",
        "total_iva",
        "total_ice",
    )
    def _compute_total_invoice(self):
        for refund in self:
            refund.total_invoice = (
                refund.total_base_iva
                + refund.total_base_iva0
                + refund.total_base_no_iva
                + refund.total_iva
                + refund.total_ice
            )

    invoice_id = fields.Many2one(
        "account.move",
        "Liquidación de Compras",
        ondelete="cascade",
        index=True,
        auto_join=True,
    )
    company_id = fields.Many2one(
        string="Company", store=True, readonly=True, related="invoice_id.company_id"
    )
    currency_id = fields.Many2one(
        string="Company Currency", readonly=True, related="company_id.currency_id"
    )
    document_number = fields.Char("Número de Factura", size=64, required=True)
    partner_id = fields.Many2one(
        "res.partner", "Proveedor", required=True, index=True, auto_join=True
    )
    l10n_ec_foreign = fields.Boolean(
        "Foreign?", readonly=True, related="partner_id.l10n_ec_foreign"
    )
    date_invoice = fields.Date(
        "Fecha de Emisión",
        required=True,
        default=lambda self: fields.Date.context_today(self),
    )
    document_type = fields.Selection(
        [("normal", "Normal"), ("electronic", "Electrónico"),],
        string="Tipo Documento",
        required=True,
        readonly=False,
        default="normal",
    )
    l10n_ec_partner_authorization_id = fields.Many2one(
        "l10n_ec.sri.authorization.supplier", "Autorización"
    )
    electronic_authorization = fields.Char("Autorización Electrónica", size=49)
    total_base_iva = fields.Monetary("Total Base IVA")
    total_base_iva0 = fields.Monetary("Total Base IVA 0")
    total_base_no_iva = fields.Monetary("Total Base no IVA")
    total_iva = fields.Monetary("Total IVA")
    total_ice = fields.Monetary("Total ICE")
    total_invoice = fields.Monetary(
        "Total Factura", compute="_compute_total_invoice", store=True
    )

    @api.constrains("document_number", "l10n_ec_partner_authorization_id")
    def _check_number_invoice(self):
        auth_s_model = self.env["l10n_ec.sri.authorization.supplier"]
        util_model = self.env["l10n_ec.utils"]
        padding_auth = "1,9"
        for refund in self:
            if (
                refund.l10n_ec_partner_authorization_id
                and refund.l10n_ec_partner_authorization_id.padding > 0
            ):
                padding_auth = refund.l10n_ec_partner_authorization_id.padding
            cadena = r"(\d{3})+\-(\d{3})+\-(\d{%s})" % (padding_auth)
            if (
                not refund.l10n_ec_foreign
                and refund.document_number
                and not re.match(cadena, refund.document_number)
            ):
                raise ValidationError(
                    _(
                        "The document number is not correct, it must be of the form 00X-00X-000XXXXXX, X is a number"
                    )
                )
            if refund.document_type == "normal":
                if not auth_s_model.check_number_document(
                    "invoice_reembolso",
                    refund.document_number,
                    refund.l10n_ec_partner_authorization_id,
                    refund.date_invoice,
                    refund.id,
                    refund.l10n_ec_foreign,
                ):
                    raise ValidationError(
                        _("Another document with the same number already exists")
                    )
            else:
                auth_s_model.validate_unique_document_partner(
                    "invoice_reembolso",
                    refund.document_number,
                    refund.partner_id.id,
                    util_model.ensure_id(refund),
                )

    @api.constrains("electronic_authorization", "document_type")
    def _check_electronic_authorization(self):
        cadena = r"(\d{37}$)|(\d{49}$)"
        for refund in self:
            if refund.document_type == "electronic" and refund.electronic_authorization:
                if len(refund.electronic_authorization) not in (37, 49):
                    raise ValidationError(
                        _(
                            "The electronic authorization number is incorrect, "
                            "This must be 37 or 49 digits. Check the refund"
                        )
                    )
                if not re.match(cadena, refund.electronic_authorization):
                    raise ValidationError(
                        _(
                            "The electronic authorization must have only numbers, "
                            "please check the refund!"
                        )
                    )

    @api.onchange(
        "document_number",
        "partner_id",
        "date_invoice",
        "document_type",
        "l10n_ec_partner_authorization_id",
    )
    def onchange_data_in(self):
        domain = {}
        warning = {}
        auth_supplier_model = self.env["l10n_ec.sri.authorization.supplier"]
        util_model = self.env["l10n_ec.utils"]
        auth_ids = False
        invoice_number = self.document_number
        date_invoice = self.date_invoice or fields.Date.context_today(self)
        if self.document_type == "electronic":
            self.l10n_ec_partner_authorization_id = False
            # si es electronico y ya tengo agencia y punto de impresion, completar el numero
            if invoice_number:
                number_data = invoice_number.split("-")
                if len(number_data) == 3:
                    try:
                        number_last = int(number_data[2])
                    except Exception:
                        warning = {
                            "title": _("Warning!!!"),
                            "message": _(
                                "The document number is not correct, it must be of the form 00X-00X-000XXXXXX, X is a number"
                            ),
                        }
                        number_last = False
                    if number_last:
                        # cuando deberia ser el padding(9 por defecto)
                        invoice_number = "{}-{}-{}".format(
                            number_data[0],
                            number_data[1],
                            auth_supplier_model.fill_padding(number_last, 9),
                        )
                        self.document_number = invoice_number
                else:
                    warning = {
                        "title": _("Warning!!!"),
                        "message": _(
                            "The document number is not correct, it must be of the form 00X-00X-000XXXXXX, X is a number"
                        ),
                    }
            return {"domain": domain, "warning": warning}
        if invoice_number and not self.partner_id:
            self.document_number = ""
            warning = {
                "title": _("Warning!!!"),
                "message": _(
                    "You must select company first to continue with this action"
                ),
            }
            return {"domain": domain, "warning": warning}
        if self.partner_id and self.partner_id.l10n_ec_foreign:
            return {"domain": domain, "warning": warning}
        auth_data = auth_supplier_model.get_supplier_authorizations(
            "invoice", self.partner_id.id, invoice_number, date_invoice
        )

        # si hay multiples autorizaciones, pero una de ellas es la que el usuario ha seleccionado, tomar esa autorizacion
        # xq sino, nunca se podra seleccionar una autorizacion
        if auth_data.get("multi_auth", False):
            if (
                self.l10n_ec_partner_authorization_id
                and self.l10n_ec_partner_authorization_id
                in auth_data.get("auth_ids", [])
            ):
                auth_use = self.l10n_ec_partner_authorization_id
                number_data = invoice_number.split("-")
                number_to_check = ""
                if len(number_data) == 3:
                    number_to_check = number_data[2]
                elif len(number_data) == 1:
                    try:
                        number_to_check = str(int(number_data[0]))
                    except Exception:
                        pass
                if (
                    number_to_check
                    and int(number_to_check) >= auth_use.first_sequence
                    and int(number_to_check) <= auth_use.last_sequence
                ):
                    invoice_number = (
                        auth_use.agency
                        + "-"
                        + auth_use.printer_point
                        + "-"
                        + auth_supplier_model.fill_padding(
                            invoice_number, auth_use.padding
                        )
                    )
                    self.document_number = invoice_number
                    # si hay ids pasar el id para validar sin considerar el documento actual
                    auth_supplier_model.check_number_document(
                        "invoice_reembolso",
                        invoice_number,
                        auth_use,
                        date_invoice,
                        util_model.ensure_id(self),
                    )
                else:
                    self.document_number = ""
            else:
                self.document_number = ""
            if auth_data.get("message", ""):
                warning = {
                    "title": _("Warning!!!"),
                    "message": auth_data.get("message", ""),
                }
            return {"domain": domain, "warning": warning}
        if not auth_data.get("auth_ids", []) and self.partner_id and invoice_number:
            if auth_data.get("message", ""):
                warning = {
                    "title": _("Warning!!!"),
                    "message": auth_data.get("message", ""),
                }
                return {"domain": domain, "warning": warning}
        else:
            auth_ids = auth_data.get("auth_ids", [])
            if auth_ids:
                self.document_number = auth_data.get("res_number", "")
                self.l10n_ec_partner_authorization_id = auth_ids[0]
            else:
                self.l10n_ec_partner_authorization_id = False
        # si el numero esta ingresado, validar duplicidad
        invoice_number = auth_data.get("res_number", "")
        if len(invoice_number.split("-")) == 3 and auth_ids:
            auth = auth_supplier_model.browse(auth_ids[0])
            # si hay ids pasar el id para validar sin considerar el documento actual
            auth_supplier_model.check_number_document(
                "invoice_reembolso",
                invoice_number,
                auth,
                date_invoice,
                util_model.ensure_id(self),
            )
        return {"domain": domain, "warning": warning}
