import json
import logging

from odoo import _, api, fields, models
from odoo.exceptions import UserError

_logger = logging.getLogger(__name__)


class AccountMove(models.Model):
    _inherit = "account.move"

    l10n_ec_type_credit_note = fields.Selection(
        [("discount", "Discount"), ("return", "Return")],
        string="Credit note type",
        readonly=True,
        states={"draft": [("readonly", False)]},
        default="discount",
    )
    is_rebilling = fields.Boolean(string="Is rebilling?", required=False)
    l10n_ec_has_payments = fields.Boolean(string="Has payments?", required=False)

    @api.model
    def _move_autocomplete_invoice_lines_create(self, vals_list):
        rslt = super(AccountMove, self)._move_autocomplete_invoice_lines_create(vals_list)
        if self.env.context.get("is_credit_note") and rslt and vals_list:
            if rslt[0]["type"] != "entry" and "invoice_line_ids" in vals_list[0]:
                rslt[0]["invoice_line_ids"] = vals_list[0]["invoice_line_ids"]
                rslt[0]["line_ids"] = []
        return rslt

    @api.model_create_multi
    def create(self, vals_list):
        res = super(AccountMove, self.with_context(check_move_validity=False)).create(vals_list)
        if self.env.context.get("is_credit_note"):
            for move in res:
                move.invoice_line_ids._onchange_price_subtotal()
                move._recompute_dynamic_lines(recompute_all_taxes=True)
        return res

    def post(self):
        self._action_update_amount_cost()
        # codigo copiado de stock_account porque en reverso no crea asientos anglo
        # ver https://github.com/odoo/odoo/blob/13.0/addons/stock_account/models/account_move.py#L44-L46
        # en NC de devolucion es necesario crearlos
        if self._context.get("move_reverse_cancel"):
            for move in self:
                if move.type == "out_refund" and move.l10n_ec_type_credit_note == "return":
                    # Create additional COGS lines for customer invoices.
                    self.env["account.move.line"].create(move._stock_account_prepare_anglo_saxon_out_lines_vals())
        res = super(AccountMove, self).post()
        if self._context.get("move_reverse_cancel"):
            for move in self:
                if move.type == "out_refund" and move.l10n_ec_type_credit_note == "return":
                    # Reconcile COGS lines in case of anglo-saxon accounting with perpetual valuation.
                    move._stock_account_anglo_saxon_reconcile_valuation()
        return res

    def _action_update_amount_cost(self):
        """
        Tratar de obtener el costo de los movimientos de stock relacionados
        """
        for move in self.with_context(active_test=False):
            for line in move.invoice_line_ids:
                if not move.company_currency_id.is_zero(line.amount_cost):
                    continue
                # asociar el movimiento de devolucion en caso de no estar asociado
                if (
                    move.type == "out_refund"
                    and move.l10n_ec_type_credit_note == "return"
                    and not line.move_line_ids
                    and line.l10n_ec_original_invoice_line_id
                    and line.l10n_ec_original_invoice_line_id.move_line_ids
                ):
                    moves_devolution = line.l10n_ec_original_invoice_line_id.mapped(
                        "move_line_ids.move_dest_ids"
                    ).filtered(lambda x: not x.invoice_line_ids and x.location_id.usage == "customer")
                    if moves_devolution:
                        line.write({"move_line_ids": [(6, 0, moves_devolution.ids)]})
                if line.move_line_ids:
                    # tomar el costo del inventario, pero con signo cambiado(tal como en _action_propagate_valuation
                    # ventas el costo estara en negativo
                    # devoluciones costo estara en positivo
                    move_value = sum(line.move_line_ids.mapped("stock_valuation_layer_ids.value")) * -1
                    line.write({"amount_cost": move_value})
        return True

    def action_reverse(self):
        action = super(AccountMove, self).action_reverse()
        if self.type == "out_invoice":
            action["views"] = [(self.env.ref("l10n_ec_credit_note.view_account_invoice_refund_sale").id, "form")]
        elif self.type == "in_invoice":
            action["views"] = [(self.env.ref("l10n_ec_credit_note.view_account_invoice_refund_purchase").id, "form")]
        return action

    def _reverse_moves(self, default_values_list=None, cancel=False):
        before_invoice_payments_widget = self.invoice_payments_widget
        reverse_moves = super(AccountMove, self)._reverse_moves(default_values_list=default_values_list, cancel=cancel)
        if self.env.context.get("autocreate_picking_for_refund"):
            reverse_moves.filtered(lambda x: x.state == "posted").action_create_picking()
        if reverse_moves.is_invoice() and reverse_moves.l10n_ec_has_payments:
            msg = []
            for payment_widget in json.loads(before_invoice_payments_widget).get("content", False):
                if payment_widget.get("account_payment_id", False):
                    msg.append(
                        _("<li>Payments <a href=# data-oe-model=account.payment data-oe-id={}>{}</a></li>").format(
                            payment_widget["account_payment_id"],
                            self.env["account.payment"].browse(payment_widget["account_payment_id"]).display_name,
                        )
                    )
                else:
                    msg.append(
                        _("<li>Journal Entries <a href=# data-oe-model=account.move data-oe-id={}>{}</a></li>").format(
                            payment_widget["move_id"], self.browse(payment_widget["move_id"]).display_name
                        )
                    )
            # enviar correo solo cuando este habilitado en la company
            if reverse_moves.company_id.l10n_ec_sent_mail_credit_note_unreconcile_payment:
                template_id = self.env.ref("l10n_ec_credit_note.template_email_has_payments_credit_note")
                template_id.send_mail(reverse_moves.id, force_send=True)
            # postear mensaje en la factura original de los pagos que se desconciliaron
            self.message_post(
                body=_("When creating the credit note, the document has reconciled: <ul>%s</ul>") % "".join(msg)
            )
        return reverse_moves

    def _stock_account_prepare_anglo_saxon_out_lines_vals(self):
        discount_credit_notes = self.filtered(
            lambda x: (x.type in ["in_refund", "out_refund"] and x.l10n_ec_type_credit_note == "discount")
            or (x.type in ["out_invoice"] and x.is_rebilling)
        )
        return super(AccountMove, self - discount_credit_notes)._stock_account_prepare_anglo_saxon_out_lines_vals()

    def action_create_picking(self):
        credit_note_with_devolution = self.filtered(
            lambda x: x.type in ["in_refund", "out_refund"]
            and x.l10n_ec_type_credit_note == "return"
            and x.create_picking
            and not x.picking_ids
        )
        if credit_note_with_devolution:
            credit_note_with_devolution.l10n_ec_action_create_picking_devolution_cn()
        return super(AccountMove, self - credit_note_with_devolution).action_create_picking()

    @api.model
    def _l10n_ec_get_location_scrap(self, printer):
        location_model = self.env["stock.location"]
        # TODO: seria mejor que la bodega de desecho este configurada en algun lugar???
        # asi no se asume la primera bodega de desecho encontrada
        scrap_location_recs = location_model.search([("scrap_location", "=", True)], limit=1)
        if not scrap_location_recs:
            raise UserError(_("You must set up at least one l10n_ec_scrap location"))
        return scrap_location_recs

    @api.model
    def _l10n_ec_get_location_move(self, move):
        """
        Cuando son devoluciones, por lo general se invierten las bodegas
        @return: tuple(location_id, location_dest_id)
        """
        return move.location_dest_id, move.location_id

    def _l10n_ec_get_picking_to_create(self, printer_point, invoice_lines):
        # devolver la data de los picking a crear
        # se debe separar los picking por bodega
        # los de desecho en u picking y los de stock en otro picking
        # esto xq el picking no soporta movimientos de varias bodegas
        picking_data = {}
        scrap_location = self._l10n_ec_get_location_scrap(printer_point)
        picking_key = False
        picking_type = self._get_stock_picking_type()
        for invoice_line in invoice_lines:
            stock_moves = invoice_line._l10n_ec_get_stock_move_from_invoice_line()
            picking_type_specific = picking_type
            if not stock_moves and invoice_line.l10n_ec_original_invoice_line_id:
                stock_moves = invoice_line.l10n_ec_original_invoice_line_id._l10n_ec_get_stock_move_from_invoice_line()
            if not stock_moves:
                location, location_dest = self._get_locations_from_picking(picking_type_specific)
                if invoice_line.l10n_ec_scrap:
                    location_dest = scrap_location
                picking_key = (picking_type_specific, location, location_dest)
                picking_data.setdefault(picking_key, {}).setdefault(invoice_line, [])
                _logger.warning("la linea de factura %s, no tiene movimiento de stock", invoice_line.display_name)
                continue
            for stock_move in stock_moves:
                location, location_dest = self._l10n_ec_get_location_move(stock_move)
                if invoice_line.l10n_ec_scrap:
                    location_dest = scrap_location
                if stock_move.picking_type_id:
                    picking_type_specific = stock_move.picking_type_id
                elif stock_move.picking_id.picking_type_id:
                    picking_type_specific = stock_move.picking_id.picking_type_id
                # tomar el tipo de operacion de devolucion
                if picking_type_specific.return_picking_type_id:
                    picking_type_specific = picking_type_specific.return_picking_type_id
                picking_key = (picking_type_specific, location, location_dest)
                picking_data.setdefault(picking_key, {}).setdefault(invoice_line, []).append(stock_move)
        return picking_data

    def l10n_ec_action_create_picking_devolution_cn(self):
        picking_model = self.env["stock.picking"].with_context(create_lot_automatic=False)
        move_model = self.env["stock.move"].with_context(create_lot_automatic=False)
        move_line_model = self.env["stock.move.line"]
        picking_ids = []
        move_returned = move_model.browse()
        for invoice in self:
            if (
                invoice.type in ("out_refund", "in_refund")
                and invoice.l10n_ec_type_credit_note == "return"
                and not invoice.picking_ids
            ):
                invoice_lines_to_picking = invoice.invoice_line_ids.filtered(lambda x: x.product_id.type in ["product"])
                if not invoice_lines_to_picking:
                    raise UserError(
                        _(
                            "There are no Products stockables to process, "
                            "check if you need a credit note for discount instead"
                        )
                    )
                printer = invoice.l10n_ec_point_of_emission_id
                if not printer:
                    printer = self.env.user.get_default_point_of_emission()["default_printer_default_id"]
                picking_date = invoice._get_date_from_picking()
                origin = self.display_name
                picking_data = invoice._l10n_ec_get_picking_to_create(printer, invoice_lines_to_picking)
                for (picking_type, location, location_dest), invoice_line_data in picking_data.items():
                    move_returned = move_model.browse()
                    picking_vals = invoice._prepare_stock_picking(
                        picking_type, location.id, location_dest.id, origin, picking_date
                    )
                    picking_vals["l10n_ec_point_of_emission_id"] = printer.id
                    picking = picking_model.create(picking_vals)
                    picking_ids.append(picking.id)
                    for invoice_line, stock_moves in invoice_line_data.items():
                        move_lines_to_return = invoice_line.l10n_ec_line_devolution_ids.mapped("stock_move_line_id")
                        if stock_moves:
                            for stock_move in stock_moves:
                                # cuando no hay lineas de stock a devolver, no crear stock.move vacio
                                if move_lines_to_return and not (move_lines_to_return & stock_move.move_line_ids):
                                    continue
                                for vals in invoice_line._get_stock_moves_values(
                                    picking, location.id, location_dest.id, origin, picking_date
                                ):
                                    # +--------------------------------------------------------------------------------------------------------+
                                    # |       picking_pick     <--Move Orig--    picking_pack     --Move Dest-->   picking_ship
                                    # |              | returned_move_ids              ↑                                  | returned_move_ids
                                    # |              ↓                                | stock_move              ↓
                                    # |       return pick(Add as dest)          return toLink                    return ship(Add as orig)
                                    # +--------------------------------------------------------------------------------------------------------+
                                    move_orig_to_link = stock_move.move_dest_ids.mapped("returned_move_ids")
                                    # link to original move
                                    move_orig_to_link |= stock_move
                                    # link to siblings of original move, if any
                                    move_orig_to_link |= (
                                        stock_move.mapped("move_dest_ids")
                                        .filtered(lambda m: m.state not in ("cancel"))
                                        .mapped("move_orig_ids")
                                        .filtered(lambda m: m.state not in ("cancel"))
                                    )
                                    move_dest_to_link = stock_move.move_orig_ids.mapped("returned_move_ids")
                                    # link to children of originally returned moves, if any. Note that the use of
                                    # 'stock_move.move_orig_ids.returned_move_ids.move_orig_ids.move_dest_ids'
                                    # instead of 'stock_move.move_orig_ids.move_dest_ids' prevents linking a
                                    # return directly to the destination moves of its parents. However, the return of
                                    # the return will be linked to the destination moves.
                                    move_dest_to_link |= (
                                        stock_move.move_orig_ids.mapped("returned_move_ids")
                                        .mapped("move_orig_ids")
                                        .filtered(lambda m: m.state not in ("cancel"))
                                        .mapped("move_dest_ids")
                                        .filtered(lambda m: m.state not in ("cancel"))
                                    )
                                    vals["move_orig_ids"] = [(4, m.id) for m in move_orig_to_link]
                                    vals["move_dest_ids"] = [(4, m.id) for m in move_dest_to_link]
                                    # pasar el movimiento original para mantener trazabilidad
                                    vals["origin_returned_move_id"] = stock_move.id
                                    if stock_move.group_id:
                                        vals["group_id"] = stock_move.group_id.id
                                        vals["sale_line_id"] = stock_move.sale_line_id.id
                                        vals["to_refund"] = True
                                    # eliminar el campo quantity_done para que no se cree las lineas del movimiento
                                    vals.pop("quantity_done", 0)
                                    new_move = move_model.create(vals)
                                    move_returned |= new_move
                                    for move_line in stock_move.move_line_ids:
                                        # cuando el movimiento de stock tiene mas de 1 linea
                                        # y en el asistente de devolucion se escogio solo una de esas lineas
                                        # devolver esa linea especifica, pero las que no se devueven no hacer nada
                                        if move_lines_to_return and move_line not in move_lines_to_return:
                                            continue
                                        move_line_vals = new_move.with_context(
                                            specific_lot_id=move_line.lot_id.id
                                        )._prepare_move_line_vals()
                                        move_line_vals.update(
                                            {
                                                "lot_id": move_line.lot_id.id,
                                                "qty_done": move_line.qty_done,
                                            }
                                        )
                                        # si ese movimiento de stock esta en las lineas de devolucion
                                        # usar la cantidad a devolver(pasarla en la UdM por defecto)
                                        specific_devolution_line = invoice_line.l10n_ec_line_devolution_ids.filtered(
                                            lambda x: x.stock_move_line_id == move_line
                                        )
                                        if specific_devolution_line:
                                            move_line_vals["qty_done"] = specific_devolution_line.product_qty
                                            if invoice_line.product_uom_id.id != move_line.product_uom_id.id:
                                                move_line_vals.update(
                                                    {
                                                        "qty_done": invoice_line.product_uom_id._compute_quantity(
                                                            specific_devolution_line.product_qty,
                                                            move_line.product_uom_id,
                                                            rounding_method="HALF-UP",
                                                        ),
                                                        "product_uom_id": move_line.product_uom_id.id,
                                                    }
                                                )
                                        move_line_model.create(move_line_vals)
                        # cuando no hay movimientos de stock
                        # crear la devolucion en base a la cantidad de la linea de la NC
                        else:
                            for vals in invoice_line._get_stock_moves_values(
                                picking, location.id, location_dest.id, origin, picking_date
                            ):
                                new_move = move_model.create(vals)
                                move_returned |= new_move
                    if move_returned:
                        picking.action_confirm()
                        picking.action_assign()
                        # validar que haya stock disponible para hacer la devolucion
                        # pasar contexto para ello
                        picking.with_context(force_validation_stock=True).action_done()
                        picking.message_post_with_view(
                            "mail.message_origin_link",
                            values={"self": picking, "origin": invoice},
                            subtype_id=self.env.ref("mail.mt_note").id,
                        )
                        invoice_vals = {"picking_ids": [(4, picking.id)]}
                        # cuando no esta establecido el tipo de operacion
                        # escribirlo, ya que el campo es requerido a nivel de vistas
                        # y saldria error si no llenamos el campo
                        if not invoice.picking_type_id:
                            invoice_vals["picking_type_id"] = picking_type.id
                            # al ser devolucion, se toma el tipo de picking para devoluciones en caso de tener
                            if picking_type.return_picking_type_id:
                                invoice_vals["picking_type_id"] = picking_type.return_picking_type_id.id
                        invoice.write(invoice_vals)
        return picking_ids

    def button_cancel(self):
        res = super(AccountMove, self).button_cancel()
        ctx = self.env.context.copy()
        for rec in self:
            if ctx.get("cancel_electronic_document", False) and rec.l10n_ec_xml_data_id.xml_authorization:
                rec.invoice_line_ids.mapped("l10n_ec_line_devolution_ids").unlink()
                rec.invoice_line_ids.write({"move_line_ids": [(6, 0, [])]})
        return res


class AccountMoveLine(models.Model):
    _inherit = "account.move.line"

    l10n_ec_scrap = fields.Boolean("is Scrap?", readonly=False, copy=False)
    l10n_ec_line_devolution_ids = fields.One2many(
        "account.move.line.devolution", "invoice_line_id", "Devolution details", readonly=True, copy=False
    )

    def _can_update_amount_cost(self):
        if self.move_id.type in ["in_refund", "out_refund"] and self.move_id.l10n_ec_type_credit_note == "discount":
            return False
        return super(AccountMoveLine, self)._can_update_amount_cost()

    def reconcile(self, writeoff_acc_id=False, writeoff_journal_id=False):
        """
        No considerar lineas anglo al conciliar NC con facturas
        esto cuando se use mass_reconcile las cuentas de inventario se marcan como conciliables
        pero al intentar volver a conciliar se obtenia error que ya estaban conciliadas
        """
        lines_anglo = self.env["account.move.line"]
        if self.env.context.get("is_credit_note"):
            lines_anglo |= self.filtered(lambda x: x.is_anglo_saxon_line)
        res = super(AccountMoveLine, self - lines_anglo).reconcile(
            writeoff_acc_id=writeoff_acc_id, writeoff_journal_id=writeoff_journal_id
        )
        return res

    def remove_move_reconcile(self):
        """
        No considerar lineas anglo al romper conciliacion de NC
        esto cuando se use mass_reconcile las cuentas de inventario se marcan como conciliables
        pero al hacer NC no deberia romperse conciliacion
        """
        lines_anglo = self.env["account.move.line"]
        if self.env.context.get("is_credit_note"):
            lines_anglo |= self.filtered(lambda x: x.is_anglo_saxon_line)
        return super(AccountMoveLine, self - lines_anglo).remove_move_reconcile()

    def _l10n_ec_get_stock_move_from_invoice_line(self):
        self.ensure_one()
        stock_moves = self.env["stock.move"].browse()
        # para las NC tomar los movimientos de la estructura de devoluciones si existe
        if self.move_id.type in ["in_refund", "out_refund"]:
            stock_moves = self.l10n_ec_line_devolution_ids.mapped("stock_move_line_id").mapped("move_id")
        if not stock_moves:
            stock_moves = self.move_line_ids
        if not stock_moves:
            # no se agrega dependencia a modulo de sale_stock o purchase
            # asi que verificar si el campo existe
            if hasattr(self, "sale_line_ids"):
                if hasattr(self.sale_line_ids, "move_ids"):
                    stock_moves = self.sale_line_ids.mapped("move_ids").filtered(
                        lambda x: x.state == "done" and x.product_id.id == self.product_id.id
                    )
            if not stock_moves and hasattr(self, "purchase_line_id"):
                stock_moves = self.purchase_line_id.move_ids.filtered(
                    lambda x: x.state == "done" and x.product_id.id == self.product_id.id
                )
        return stock_moves


class AccountMoveLineDevolution(models.Model):
    _name = "account.move.line.devolution"
    _description = "Devolution detail for Credit note"

    invoice_line_id = fields.Many2one("account.move.line", "Invoice Line", ondelete="cascade")
    stock_move_line_id = fields.Many2one(
        "stock.move.line",
        "Stock move Line",
    )
    lot_id = fields.Many2one(
        "stock.production.lot",
        "Production Lot",
    )
    product_qty = fields.Float("Product qty", digits="Product Unit of Measure")
