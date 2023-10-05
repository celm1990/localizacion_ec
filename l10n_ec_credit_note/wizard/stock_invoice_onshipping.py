from odoo import models


class StockInvoiceOnshipping(models.TransientModel):
    _inherit = "stock.invoice.onshipping"

    def _build_invoice_values_from_pickings(self, pickings):
        """
        Build dict to create a new invoice from given pickings
        :param pickings: stock.picking recordset
        :return: dict
        """
        invoice, values = super(
            StockInvoiceOnshipping, self.with_context(internal_type=self.journal_id.l10n_latam_internal_type)
        )._build_invoice_values_from_pickings(pickings)
        if self.invoice_type in ("in_refund", "out_refund"):
            values["l10n_ec_type_credit_note"] = "return"
        # para el contexto ecuatoriano, pasar el punto de emision desde la venta
        if self.invoice_type in ("out_invoice", "out_refund"):
            sale_order = pickings.mapped("sale_id")
            point_of_emission = sale_order.mapped("l10n_ec_point_of_emission_id")
            invoice_payment_term = sale_order.mapped("payment_term_id")
            if point_of_emission:
                (
                    next_number,
                    auth_line,
                ) = point_of_emission.get_next_value_sequence(self.invoice_type, False, False)
                values.update(
                    {
                        "l10n_ec_point_of_emission_id": point_of_emission[0].id,
                        "l10n_latam_document_number": next_number,
                        "l10n_ec_authorization_line_id": auth_line.id,
                        "l10n_ec_type_emission": point_of_emission[0].type_emission,
                    }
                )
            if sale_order:
                values.update(
                    {
                        "narration": sale_order[0].note,
                        "user_id": sale_order[0].user_id.id,
                        "invoice_user_id": sale_order[0].user_id.id,
                    }
                )
            if invoice_payment_term:
                values.update(
                    {
                        "invoice_payment_term_id": invoice_payment_term[0].id,
                    }
                )
        return invoice, values

    def _create_invoice(self, invoice_values):
        """Overrite this metothod if you need to change any values of the
        invoice and the lines before the invoice creation
        :param invoice_values: dict with the invoice and its lines
        :return: invoice
        """
        return super(
            StockInvoiceOnshipping, self.with_context(internal_type=self.journal_id.l10n_latam_internal_type)
        )._create_invoice(invoice_values)

    def _get_invoice_line_values(self, moves, invoice_values, invoice):
        values = super()._get_invoice_line_values(moves, invoice_values, invoice)
        name = ", ".join(list(set(moves.mapped("name"))))
        values["name"] = name
        return values
