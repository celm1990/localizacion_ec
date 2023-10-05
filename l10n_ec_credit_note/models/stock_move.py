from odoo import models


class StockMove(models.Model):
    _inherit = "stock.move"

    def _can_link_move_with_invoice_line(self, invoice_line):
        # No asociar picking con NC por descuento
        # puede darse el caso que primero crean una NC por descuento y luego una NC por devolucion
        # el picking se asociaria a la NC por descuento y no a la NC por devolucion
        if invoice_line.move_id.type == "out_refund" and invoice_line.move_id.l10n_ec_type_credit_note == "discount":
            return False
        return super()._can_link_move_with_invoice_line(invoice_line)
