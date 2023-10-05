from odoo import models


class StockPicking(models.Model):
    _inherit = "stock.picking"

    def _get_partner_to_invoice(self):
        self.ensure_one()
        if self.sale_id:
            return self.sale_id.partner_invoice_id.id
        return super()._get_partner_to_invoice()
