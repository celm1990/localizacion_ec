from odoo import api, models


class SaleOrderLine(models.Model):
    _inherit = "sale.order.line"

    @api.depends("invoice_lines.move_id.state", "invoice_lines.quantity")
    def _get_invoice_qty(self):
        # las NC por descuento no restar de la cantidad facturada
        # puedo facturar 10 unidades y dar un descuento a las 10 unidades de $1
        # pero eso no implica que tengo que volver a facturar las 10 unidades
        # solo en NC por devolucion deberia restarse
        # ********************************************************************
        # las facturas de refacturacion tampoco sumar la cantidad facturada
        # ********************************************************************
        # asi mismo puedo emitir una factura de 10U
        # y emitir una NC por refacturacion, y crear una nueva factura por las mismas 10U
        # como la NC era por descuento no se restaba la cantidad facturada, pero la nueva factura si se consideraba
        # y se duplicaba la cantidad facturada(de la factura original + la nueva factura por refacturacion)
        res = super()._get_invoice_qty()
        for line in self:
            for invoice_line in line.invoice_lines:
                if (
                    invoice_line.move_id.type == "out_refund"
                    and invoice_line.move_id.l10n_ec_type_credit_note == "discount"
                ):
                    # volver a sumar las cantidades
                    # xq en la llamada super se debieron restar
                    uom = invoice_line.product_uom_id
                    line.qty_invoiced += uom._compute_quantity(invoice_line.quantity, line.product_uom)
                elif invoice_line.move_id.is_rebilling:
                    # restar las cantidades
                    # xq en la llamada super se debieron sumar
                    uom = invoice_line.product_uom_id
                    line.qty_invoiced -= uom._compute_quantity(invoice_line.quantity, line.product_uom)
        return res
