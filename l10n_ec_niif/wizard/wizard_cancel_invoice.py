import re

from odoo import api, fields, models
from odoo.exceptions import UserError, ValidationError
from odoo.tools.translate import _

from odoo.addons.l10n_ec_niif.models import modules_mapping


class WizardCancelInvoice(models.TransientModel):
    _name = "wizard.cancel.invoice"

    line_ids = fields.One2many("wizard.cancel.invoice.line", "wizard_id", "Document Cancel", required=True)
    date = fields.Date("Date cancel", required=True, default=lambda self: fields.Date.context_today(self))
    company_id = fields.Many2one("res.company", "Company", required=True, default=lambda self: self.env.company)
    account_line_id = fields.Many2one(comodel_name="account.account", string="Account line", required=True)

    type_document = fields.Selection(
        string="Type document",
        selection=[
            ("invoice", "Invoice"),
            ("credit_note", "Credit Note"),
            ("debit_note", "Debit Note"),
            ("liquidation", "Liquidation"),
        ],
        required=True,
    )

    def action_cancel_invoice(self):
        account_move_model = self.env["account.move"]
        shop_model = self.env["l10n_ec.agency"]
        printer_model = self.env["l10n_ec.point.of.emission"]
        obj_model = self.env["ir.model.data"]
        internal_type = ""
        type_move = ""
        invoice_cancel_ids = []
        msj = []
        account_id = self.account_line_id.id
        invoice_partner = self.env.ref("l10n_ec_niif.consumidor_final", False)

        if self.type_document == "invoice":
            type_move = internal_type = "out_invoice"
        elif self.type_document == "credit_note":
            type_move = internal_type = "out_refund"
        elif self.type_document == "debit_note":
            type_move = "out_invoice"
            internal_type = "debit_note_out"
        elif self.type_document == "liquidation":
            type_move = "in_invoice"
            internal_type = "liquidation"
        domain = modules_mapping.get_domain(internal_type, include_state=False)
        document_type = modules_mapping.get_document_type(internal_type)
        document_name = modules_mapping.get_document_name(document_type)
        ctx = self.env.context.copy()
        ctx["type"] = type_move
        for line in self.line_ids:
            partner = line.partner_id and line.partner_id or invoice_partner
            invoice_recs = account_move_model.search(domain + [("l10n_ec_document_number", "=", line.number)])
            number = line.number.split("-")
            company_id = self.company_id
            shop_recs = shop_model.search([("number", "=", number[0]), ("company_id", "=", company_id.id)], limit=1)
            if not shop_recs:
                raise UserError(_("No existe una agencia con el numero %s, por favor verifique") % (number[0]))
            printer_recs = printer_model.search([("number", "=", number[1]), ("agency_id", "=", shop_recs.id)], limit=1)
            if not printer_recs:
                raise UserError(
                    _("No existe un punto de emisión con el numero %s en la agencia %s, por favor verifique")
                    % (number[1], number[0])
                )
            if not invoice_recs:
                auth_line_id = printer_recs.get_authorization_for_number(
                    internal_type, line.number, emission_date=line.date or self.date, company=company_id
                )
                ctx = {
                    "allowed_company_ids": company_id.ids,
                    "default_type": type_move,
                    "internal_type": self.type_document,
                }
                vals_line = {
                    "name": "Cancelacion de {} {}".format(document_name, line.number),
                    "price_unit": 0.0,
                    "quantity": 1,
                    "tax_ids": [],
                    "account_id": account_id,
                }
                vals = {
                    "type": type_move,
                    "invoice_date": line.date or self.date,
                    "name": line.number,
                    "partner_id": partner.id,
                    "l10n_latam_internal_type": self.type_document,
                    "l10n_ec_invoice_type": internal_type,
                    "l10n_ec_point_of_emission_id": printer_recs.id,
                    "l10n_ec_type_emission": printer_recs.type_emission,
                    "l10n_ec_authorization_id": auth_line_id.authorization_id.id,
                    "l10n_ec_authorization_line_id": auth_line_id.id,
                    "l10n_ec_electronic_authorization": line.auth_number or "",
                    "state": "draft",
                    "invoice_line_ids": [(0, 0, vals_line)],
                }
                new_invoice = account_move_model.with_context(ctx).create(vals)
                new_invoice._onchange_partner_id()
                new_invoice.with_context(ctx)._compute_l10n_latam_document_type()
                new_invoice.write(
                    {
                        "l10n_ec_document_number": line.number,
                        "l10n_ec_electronic_authorization": line.auth_number or "",
                        "state": "cancel",
                    }
                )
                new_invoice.message_post(body=_("Document create as cancel from wizard"))
                invoice_cancel_ids.append(new_invoice.id)
            else:
                for invoice in invoice_recs:
                    msj.append(
                        "Existe una %s con el número %s de la empresa %s, debe cancelar primero dicho documento."
                        % (document_name, invoice.l10n_ec_document_number, invoice.partner_id.name_get()[0][1])
                    )
        if msj:
            raise UserError("\n".join(msj))
        model_data_recs = obj_model.search([("model", "=", "ir.ui.view"), ("name", "=", "view_invoice_tree")])
        if model_data_recs and invoice_cancel_ids:
            ctx = self.env.context.copy()
            ctx["active_model"] = account_move_model._name
            ctx["active_ids"] = invoice_cancel_ids
            ctx["active_id"] = invoice_cancel_ids[0]
            view_id = model_data_recs[0].res_id
            res = {
                "name": _("Documentos Anulados"),
                "view_type": "form",
                "view_mode": "tree",
                "res_model": account_move_model._name,
                "views": [(view_id, "tree")],
                "type": "ir.actions.act_window",
                "domain": [("id", "in", invoice_cancel_ids)],
                "context": ctx,
            }
        else:
            res = {"type": "ir.actions.act_window_close"}
        return res


class WizardCancelInvoiceLine(models.TransientModel):
    _name = "wizard.cancel.invoice.line"

    @api.constrains(
        "number",
    )
    def _check_number(self):
        cadena = r"(\d{3})+\-(\d{3})+\-(\d{9})"
        for rec in self:
            if not re.match(cadena, rec.number):
                raise ValidationError(
                    _("El número de factura es incorrecto, este debe tener la forma 001-00X-000XXXXXX, X es número")
                )

    wizard_id = fields.Many2one("wizard.cancel.invoice", "Wizard", ondelete="cascade")
    number = fields.Char(
        "Document number",
        size=17,
        required=True,
    )
    partner_id = fields.Many2one(
        "res.partner",
        "Partner",
    )
    name = fields.Char(
        "Description",
        size=256,
    )
    date = fields.Date("Date cancel")
    auth_number = fields.Char(string="Auth number")
