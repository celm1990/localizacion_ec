import re
from collections import OrderedDict

from odoo import _, api, fields, models
from odoo.exceptions import UserError, ValidationError


class AccountInvoiceRefund(models.TransientModel):
    _inherit = "account.move.reversal"

    partner_id = fields.Many2one("res.partner", "Partner")
    partner_shipping_id = fields.Many2one("res.partner", "Partner Shipping")
    l10n_ec_point_of_emission_id = fields.Many2one(comodel_name="l10n_ec.point.of.emission", string="Point Emission")
    l10n_latam_document_number = fields.Char("Number", size=17)
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
        selection=[("electronic", "Electronic"), ("pre_printed", "Pre Printed"), ("auto_printer", "Auto Printer")],
    )
    l10n_ec_supplier_authorization_id = fields.Many2one(
        comodel_name="l10n_ec.sri.authorization.supplier",
        string="Supplier Authorization",
        required=False,
    )
    l10n_ec_supplier_authorization_number = fields.Char(string="Supplier Authorization", required=False, size=10)
    company_id = fields.Many2one(comodel_name="res.company", string="Company", related="move_id.company_id")
    l10n_latam_country_code = fields.Char(string="Country Code", related="company_id.country_id.code")
    l10n_ec_type_supplier_authorization = fields.Selection(related="company_id.l10n_ec_type_supplier_authorization")
    l10n_ec_type_credit_note = fields.Selection(
        [("discount", "Discount"), ("return", "Return")], string="Credit Note type"
    )
    l10n_ec_picking_option = fields.Selection(
        [("create", "Create Devolution"), ("select", "Select Devolutions")],
        string="Devolution Option",
        default="select",
    )
    picking_ids = fields.Many2many(comodel_name="stock.picking", string="Devolutions")
    picking_type_id = fields.Many2one("stock.picking.type", "Operation Type")
    force_invoiced = fields.Boolean(
        string="Force invoiced",
        help="When you set this field, the sales order will be considered as "
        "fully invoiced, even when there may be ordered or delivered "
        "quantities pending to invoice.",
    )
    has_product_stockables = fields.Boolean(string="Has Product Stockable?", required=False)
    include_all_lines = fields.Boolean(string="Include All Services?")
    move_type = fields.Selection(
        [("out_invoice", "Customer Invoice"), ("in_invoice", "Supplier Invoice"), ("entry", "Entry")],
        string="Invoice Type",
    )
    line_ids = fields.One2many("account.move.reversal.line", "wizard_id", "Details")
    line_discount_ids = fields.One2many("account.move.reversal.discount", "wizard_id", "Discount Details")
    l10n_ec_electronic_authorization = fields.Char("Electronic authorization", size=49)
    account_id = fields.Many2one("account.account", "Account", required=False, save_readonly=True)

    @api.constrains("l10n_latam_document_number")
    def _check_number(self):
        cadena = r"(\d{3})+\-(\d{3})+\-(\d{9})"
        for wizard in self:
            if wizard.l10n_latam_document_number and not re.match(cadena, wizard.l10n_latam_document_number):
                raise ValidationError(
                    _("The number of Invoice is incorrect, it must be like 00X-00X-000XXXXXX, X is a number")
                )

    @api.onchange("l10n_ec_type_credit_note")
    def onchange_l10n_ec_type_credit_note(self):
        if self.l10n_ec_type_credit_note:
            # por defecto cuando sea NC por descuento marcar que no se marque la venta como a facturar
            self.force_invoiced = self.l10n_ec_type_credit_note == "discount"
            for line in self.line_ids.filtered(lambda x: not x.other_amounts):
                if not line.line_id:
                    continue
                line.account_id = self.get_account_line(line.line_id, self.l10n_ec_type_credit_note)

    @api.model
    def get_account_line(self, line, l10n_ec_type_credit_note):
        move_type = line.move_id and line.move_id.type or "out_invoice"
        account_id = line.account_id and line.account_id.id or None
        if line.product_id:
            if move_type == "out_invoice":
                if l10n_ec_type_credit_note == "return":
                    if line.product_id.property_stock_account_refund_id:
                        account_id = line.product_id.property_stock_account_refund_id.id
                    elif line.product_id.categ_id.property_stock_account_refund_id:
                        account_id = line.product_id.categ_id.property_stock_account_refund_id.id
                if l10n_ec_type_credit_note == "discount":
                    if line.product_id.property_stock_account_discount_id:
                        account_id = line.product_id.property_stock_account_discount_id.id
                    elif line.product_id.categ_id.property_stock_account_discount_id:
                        account_id = line.product_id.categ_id.property_stock_account_discount_id.id
            elif move_type == "in_invoice":
                if line.product_id.categ_id and line.product_id.categ_id.property_stock_account_output_categ_id:
                    account_id = line.product_id.categ_id.property_stock_account_output_categ_id.id
        return account_id

    @api.model
    def _prepare_values_from_invoice_line(self, line, l10n_ec_type_credit_note):
        vals_line = {
            "line_id": line.id,
            "process": True,
            "product_id": line.product_id.id,
            "product_uom_id": line.product_uom_id.id,
            "name": line.name,
            "quantity": line.quantity,
            "discount": line.discount,
            "price_unit": line.price_unit,
            "account_id": self.get_account_line(line, l10n_ec_type_credit_note),
            "analytic_account_id": line.analytic_account_id.id,
            "analytic_tag_ids": [(6, 0, line.analytic_tag_ids.ids)],
        }
        return vals_line

    @api.model
    def _get_data_from_invoice_line(self, invoice, picking_ids=None, force_type_credit_note=""):
        iva_group = self.env.ref("l10n_ec_niif.tax_group_iva")
        iva0_group = self.env.ref("l10n_ec_niif.tax_group_iva_0")
        lines = []
        has_product_stockables = False
        invoice_line_data = OrderedDict()
        if picking_ids is None:
            picking_ids = self.env["stock.picking"]
        for line in invoice.invoice_line_ids:
            other_values_line = line._get_third_amounts_line()
            if other_values_line:
                lines.append(other_values_line)
            stock_moves = self.env["stock.move"]
            if force_type_credit_note != "discount":
                # si tengo picking, tomar los movimientos de esos picking especificos
                if picking_ids:
                    stock_moves = self.env["stock.move"].search(
                        [
                            ("picking_id", "in", picking_ids.ids),
                            ("state", "=", "done"),
                            ("product_id", "=", line.product_id.id),
                        ]
                    )
                else:
                    stock_moves = line._l10n_ec_get_stock_move_from_invoice_line()
                if stock_moves or line.product_id.type == "product":
                    has_product_stockables = True
            l10n_ec_type_credit_note = stock_moves and "return" or "discount"
            # cuando no haya movimiento de stock, pero explicitamente el usuario selecciono NC por devolucion
            # forzar ese tipado para tomar la cuenta de devolucion y
            if not stock_moves and force_type_credit_note and force_type_credit_note == "return":
                l10n_ec_type_credit_note = "return"
            vals = self._prepare_values_from_invoice_line(line, l10n_ec_type_credit_note)
            if not stock_moves:
                # cuando tengo picking y es una NC parcial, no agregar las demas lineas de la factura(tipo servicio)
                # solo las lineas con productos en la devolucion
                # en devolucion completa si agregarlos
                if force_type_credit_note == "discount" or self.include_all_lines:
                    invoice_line_key = (line, self.env["stock.move.line"], self.env["stock.production.lot"])
                    invoice_line_data[invoice_line_key] = vals
            else:
                for move in stock_moves:
                    # encerar la cantidad de la linea de factura para tomar la cantidad de los movimientos
                    vals["quantity"] = 0
                    # cuando el usuario selecciona picking, asegurarse que la bodega sea de customer
                    if self.l10n_ec_picking_option == "select" and (
                        (invoice.is_purchase_document() and move.location_dest_id.usage != "supplier")
                        or (invoice.is_sale_document() and move.location_id.usage != "customer")
                    ):
                        continue
                    # cuando la factura tiene movimientos, asegurarse que el picking seleccionado tenga esos movimientos como devolucion
                    move_related = line._l10n_ec_get_stock_move_from_invoice_line()
                    if (
                        move_related
                        and move.origin_returned_move_id
                        and move.origin_returned_move_id not in move_related
                    ):
                        continue
                    for move_line in move.move_line_ids:
                        invoice_line_key = (line, move_line, move_line.lot_id)
                        invoice_line_data.setdefault(invoice_line_key, vals.copy())
                        invoice_line_data[invoice_line_key]["quantity"] += move_line.product_uom_id._compute_quantity(
                            move_line.qty_done, line.product_uom_id, rounding_method="HALF-UP"
                        )
        for (invoice_line, move_line, production_lot), vals in invoice_line_data.items():
            quantity_returned = 0.0
            all_move_lines_related = self.env["stock.move.line"]
            # restar las devoluciones previas
            # en caso de no haber movimientos de stock, restar de la informacion de devolucion por linea de NC
            for move in move_line.move_id.move_dest_ids:
                if move.state == "cancel":
                    continue
                # cuando el usuario selecciona picking de devolucion explicitamente
                # no restar la cantidad de los movimientos de destino
                # en almacenes que usan varios pasos, el picking de cliente siempre tendra movimiento de destino de los siguientes pasos
                if self.l10n_ec_picking_option == "select":
                    continue
                move_lines_related = move.move_line_ids.filtered(
                    lambda x: x.lot_id == production_lot and x not in all_move_lines_related
                )
                all_move_lines_related |= move_lines_related
                # descartar el movimiento original para no restarlo 2 veces en caso de devolucion previa
                all_move_lines_related |= move_line
                for line_related in move_lines_related:
                    move_line_qty = line_related.product_qty
                    if move.state == "done":
                        move_line_qty = line_related.qty_done
                    quantity_returned += line_related.product_uom_id._compute_quantity(
                        move_line_qty, invoice_line.product_uom_id, rounding_method="HALF-UP"
                    )
            devolution_domain = [
                ("invoice_line_id.l10n_ec_original_invoice_line_id", "=", invoice_line.id),
            ]
            if move_line:
                devolution_domain.append(("stock_move_line_id", "=", move_line.id))
            if production_lot:
                devolution_domain.append(("lot_id", "=", production_lot.id))
            if all_move_lines_related:
                devolution_domain.append(("stock_move_line_id", "not in", all_move_lines_related.ids))
            other_lines = self.env["account.move.line.devolution"].search(devolution_domain)
            # NOTE: no se agrega en el domain ('invoice_line_id.move_id.state', '!=', 'cancel')
            # por que se hacen  muchas subquery haciendo ineficiente la consulta y es mas rapido el filtered
            quantity_returned += sum(
                other_lines.filtered(lambda x: x.invoice_line_id.move_id.state != "cancel").mapped("product_qty")
            )
            if move_line:
                vals["stock_move_line_id"] = move_line.id
            if production_lot:
                vals["lot_id"] = production_lot.id
            if quantity_returned:
                vals["max_quantity"] = vals["quantity"] - quantity_returned
                vals["quantity"] = vals["max_quantity"]
            else:
                vals["max_quantity"] = vals["quantity"]
            if vals["quantity"] > 0:
                if vals["discount"] > 0:
                    vals["price_unit"] = vals["price_unit"] * (1 - (vals["discount"] or 0.0) / 100)
                    vals["discount"] = 0.0
                subtotal = vals["price_unit"] * vals["quantity"]
                taxes = invoice_line.tax_ids.filtered(lambda x: x.tax_group_id in [iva_group, iva0_group])
                vals["tax_ids"] = [(6, 0, taxes.ids)]
                amount_tax = 0
                taxes_res = taxes.compute_all(
                    subtotal,
                    currency=invoice_line.currency_id,
                    product=invoice_line.product_id,
                    partner=invoice_line.move_id.partner_id.commercial_partner_id,
                    is_refund=True,
                )
                for tax_data in taxes_res.get("taxes", []):
                    amount_tax = tax_data["amount"]
                total = subtotal + amount_tax
                vals["price_subtotal"] = subtotal
                vals["amount_tax"] = amount_tax
                vals["price_total"] = total
                lines.append(vals)
        return lines, has_product_stockables

    @api.onchange("picking_ids", "l10n_ec_type_credit_note", "l10n_ec_picking_option", "include_all_lines")
    def onchange_return_picking(self):
        line_model = self.env["account.move.reversal.line"]
        invoice = self.env["account.move"].browse(self.env.context.get("active_ids")[0])
        lines = line_model.browse()
        line_vals, _has_product_stockables = self._get_data_from_invoice_line(
            invoice, self.picking_ids, self.l10n_ec_type_credit_note
        )
        for line in line_vals:
            lines += line_model.new(line)
        self.line_ids = lines
        return {}

    @api.model
    def default_get(self, fields_list):
        invoice_model = self.env["account.move"]
        values = super(AccountInvoiceRefund, self).default_get(fields_list)
        # evitar error al hacer browse con account.move pero ID de otro modelo
        # este wizard se puede llamar desde otros modelos(account.payment por ejemplo con account_document_reversal instalado)
        if self.env.context.get("active_model") != invoice_model._name:
            return values
        invoice = invoice_model.browse(self.env.context.get("active_ids")[0])
        if not invoice.is_invoice():
            return values
        # por defecto se van a crear NC que anulen la factura(se concilie NC con factura)
        values["refund_method"] = "cancel"
        # cuando la factura ya esta pagada, pasar opcion que solo cree NC en borrador y no concilie con factura
        if invoice.invoice_payment_state == "paid":
            values["refund_method"] = "refund"
        values["include_all_lines"] = values["refund_method"] != "refund"
        if "line_ids" in fields_list:
            lines, has_product_stockables = self._get_data_from_invoice_line(
                invoice, force_type_credit_note=self.env.context.get("force_type_credit_note", "")
            )
            values["l10n_ec_type_credit_note"] = has_product_stockables and "return" or "discount"
            values["has_product_stockables"] = has_product_stockables
            values["line_ids"] = [(0, 0, line) for line in lines]
        values["date"] = fields.Date.context_today(self)
        values["partner_id"] = invoice.partner_id.id
        values["partner_shipping_id"] = invoice.partner_shipping_id.id or invoice.partner_id.id
        if invoice.type == "out_invoice" and "l10n_latam_document_number" in fields_list:
            values.update({"l10n_ec_point_of_emission_id": invoice.l10n_ec_point_of_emission_id.id})
        elif invoice.type == "in_invoice":
            values.update({"l10n_ec_type_emission": "pre_printed"})
        return values

    def get_invoice_vals(self, move_type):
        return {
            "l10n_latam_document_number": self.l10n_latam_document_number,
            "l10n_ec_point_of_emission_id": self.l10n_ec_point_of_emission_id.id,
            "l10n_ec_supplier_authorization_id": self.l10n_ec_supplier_authorization_id.id,
            "l10n_ec_authorization_id": self.l10n_ec_authorization_id.id,
            "l10n_ec_electronic_authorization": self.l10n_ec_electronic_authorization,
            "type": move_type,
            "l10n_ec_type_emission": self.l10n_ec_type_emission or "pre_printed",
            "partner_id": self.partner_id.commercial_partner_id.id,
            "invoice_date": self.date,
        }

    def get_invoice_for_onchange(self, move_type):
        invoice_model = self.env["account.move"]
        ctx = {
            "default_type": move_type,
            "type": move_type,
            "journal_type": "sale" if move_type == "out_refund" else "purchase",
        }
        invoice_aux = invoice_model.with_context(ctx).new(self.get_invoice_vals(move_type))
        return invoice_aux

    @api.onchange("l10n_ec_point_of_emission_id")
    def onchange_l10n_ec_point_of_emission_id(self):
        if self.l10n_ec_point_of_emission_id:
            invoice_aux = self.get_invoice_for_onchange("out_refund")
            invoice_aux._onchange_point_of_emission()
            new_values = invoice_aux._convert_to_write(invoice_aux._cache)
            wizard_values = {f: v for f, v in new_values.items() if f in self._fields}
            self.update(wizard_values)

    @api.onchange("l10n_ec_supplier_authorization_id")
    def onchange_l10n_ec_supplier_authorization_id(self):
        invoice_aux = self.get_invoice_for_onchange("in_refund")
        invoice_aux.onchange_l10n_ec_supplier_authorization_id()
        new_values = invoice_aux._convert_to_write(invoice_aux._cache)
        wizard_values = {f: v for f, v in new_values.items() if f in self._fields}
        self.update(wizard_values)

    def _onchange_number_in(self):
        invoice_aux = self.get_invoice_for_onchange("in_refund")
        onchange_res = invoice_aux._onchange_l10n_ec_document_number_in()
        if not onchange_res:
            onchange_res = {}
        domain = onchange_res.get("domain", {})
        warning = onchange_res.get("warning", {})
        new_values = invoice_aux._convert_to_write(invoice_aux._cache)
        wizard_values = {f: v for f, v in new_values.items() if f in self._fields}
        self.update(wizard_values)
        return {"domain": domain, "warning": warning}

    def _onchange_number_out(self):
        invoice_aux = self.get_invoice_for_onchange("out_refund")
        onchange_res = invoice_aux._onchange_l10n_ec_document_number_out()
        if not onchange_res:
            onchange_res = {}
        domain = onchange_res.get("domain", {})
        warning = onchange_res.get("warning", {})
        new_values = invoice_aux._convert_to_write(invoice_aux._cache)
        wizard_values = {f: v for f, v in new_values.items() if f in self._fields}
        self.update(wizard_values)
        return {"domain": domain, "warning": warning}

    @api.onchange("l10n_latam_document_number", "l10n_latam_document_type_id", "l10n_ec_type_emission", "date")
    def onchange_l10n_latam_document_number(self):
        res = {}
        if self.l10n_latam_document_number and self.move_type == "out_invoice":
            res = self._onchange_number_out()
        elif self.l10n_latam_document_number and self.move_type == "in_invoice":
            res = self._onchange_number_in()
        # cuando hay mensajes desde el onchange, devolver esos mensajes antes de llamada super
        # ya que en la llamada super se podria lanzar excepcion y los mensajes nunca se mostrarian al usuario
        if res and res.get("warning", {}).get("message"):
            return res
        return super(AccountInvoiceRefund, self)._onchange_l10n_latam_document_number()

    @api.model
    def _extract_data_from_line(self, line):
        """
        crear estructura para pasar datos a las lineas de facturas al crear la nota de credito
        ya que los datos pueden cambiar en el asistente
        """
        invoice_vals = {
            "name": line.name,
            "discount": line.discount,
            "price_unit": line.price_unit,
            "l10n_ec_scrap": line.l10n_ec_scrap,
            "product_id": line.product_id.id,
            "product_uom_id": line.product_uom_id.id,
            "l10n_ec_original_invoice_line_id": line.line_id.id,
            "account_id": line.account_id.id,
            "analytic_account_id": line.analytic_account_id.id,
            "analytic_tag_ids": [(6, 0, line.analytic_tag_ids.ids)],
            "tax_ids": [(6, 0, line.tax_ids.ids)],
        }
        # Se debe pasar el valor sin descuento cuando se pasa el valor desde la factura
        # Se corre el riesgo de que la NC no cuadre con la factura
        if line.discount > 0.0:
            invoice_vals["price_unit"] = line.price_unit - (line.price_unit * (1 - (line.discount / 100.0)))
            invoice_vals["discount"] = 0.0
        if line.line_id:
            invoice_vals = line.line_id.with_context(include_business_fields=True).copy_data(invoice_vals)[0]
            # borrar ciertos campos para forzar que se recalculen
            ACCOUNTING_FIELDS = ("move_id", "quantity", "debit", "credit", "amount_currency")
            for field_name in ACCOUNTING_FIELDS:
                invoice_vals.pop(field_name, False)
        return invoice_vals

    def _prepare_default_reversal(self, move):
        move_vals = super(AccountInvoiceRefund, self)._prepare_default_reversal(move)
        if not move.is_invoice():
            return move_vals
        move_vals.update(
            {
                "l10n_ec_type_credit_note": self.l10n_ec_type_credit_note,
                "l10n_ec_type_emission": self.l10n_ec_type_emission,
                "line_ids": [],
            }
        )
        if self.l10n_ec_type_credit_note == "return" and self.l10n_ec_picking_option == "create":
            move_vals.update(
                {
                    "picking_type_id": self.picking_type_id.id,
                    "create_picking": True,
                }
            )
        if self.move_type == "in_invoice":
            move_vals.update(
                {
                    "l10n_ec_supplier_authorization_id": self.l10n_ec_supplier_authorization_id.id,
                    "l10n_ec_supplier_authorization_number": self.l10n_ec_supplier_authorization_number,
                    "l10n_ec_electronic_authorization": self.l10n_ec_electronic_authorization,
                }
            )
        else:
            move_vals.update(
                {
                    "l10n_ec_point_of_emission_id": self.l10n_ec_point_of_emission_id.id,
                    "l10n_ec_authorization_line_id": self.l10n_ec_authorization_line_id.id,
                    "l10n_latam_document_number": self.l10n_latam_document_number,
                }
            )
        invoice_line_ids = []
        invoice_line_data = {}
        if self.move_type == "in_invoice" and self.l10n_ec_type_credit_note == "discount":
            if not self.line_discount_ids:
                raise UserError(_("You must specific almost one line with discount"))
            for line in self.line_discount_ids:
                invoice_line_ids.append(
                    (
                        0,
                        0,
                        {
                            "name": self.reason or _("Discount"),
                            "account_id": line.account_id.id,
                            "quantity": 1.0,
                            "price_unit": line.price_subtotal,
                            "tax_ids": [(6, 0, [line.tax_id.id])],
                        },
                    )
                )
        else:
            for line in self.line_ids.filtered("process"):
                invoice_line_vals = self._extract_data_from_line(line)
                current_line_id = line.line_id.id
                if line.other_amounts:
                    current_line_id = False
                invoice_line_data.setdefault(current_line_id, invoice_line_vals.copy())
                invoice_line_data[current_line_id].setdefault("move_line_ids", [])
                invoice_line_data[current_line_id].setdefault("quantity", 0)
                invoice_line_data[current_line_id]["quantity"] += line.quantity
                if (
                    self.l10n_ec_type_credit_note == "return"
                    and self.l10n_ec_picking_option == "select"
                    and self.picking_ids
                    and line.stock_move_line_id
                ):
                    invoice_line_data[current_line_id]["move_line_ids"].append(line.stock_move_line_id.move_id.id)
                if self.l10n_ec_type_credit_note != "discount":
                    devolution_vals = {
                        "stock_move_line_id": line.stock_move_line_id.id,
                        "product_qty": line.quantity,
                        "lot_id": line.lot_id.id,
                    }
                    invoice_line_data[current_line_id].setdefault("l10n_ec_line_devolution_ids", []).append(
                        (0, 0, devolution_vals)
                    )
            for line_vals in invoice_line_data.values():
                line_vals.update({"move_line_ids": [(6, 0, line_vals.get("move_line_ids", []))]})
                invoice_line_ids.append((0, 0, line_vals))
        if not invoice_line_ids:
            raise UserError(_("You must select almost one line"))
        move_vals["invoice_line_ids"] = invoice_line_ids
        if not move_vals.get("line_ids"):
            move_vals.pop("line_ids", None)
        if move.invoice_payments_widget != "false" and self.move_type == "out_invoice":
            move_vals.update(
                {
                    "l10n_ec_has_payments": True,
                }
            )
        return move_vals

    def reverse_moves(self):
        res = super(
            AccountInvoiceRefund, self.with_context(autocreate_picking_for_refund=True, is_credit_note=True)
        ).reverse_moves()
        moves = (
            self.env["account.move"].browse(self.env.context["active_ids"])
            if self.env.context.get("active_model") == "account.move"
            else self.move_id
        )
        if moves.is_sale_document():
            sales_order = moves.mapped("invoice_line_ids.sale_line_ids.order_id")
            if sales_order:
                sales_order.write({"force_invoiced": self.force_invoiced})
        if self.refund_method == "modify" and self.l10n_ec_type_credit_note == "discount":
            moves_to_redirect = self.env["account.move"].browse(res.get("res_id", False))
            if moves_to_redirect.is_invoice():
                moves_to_redirect.write(
                    {
                        "is_rebilling": True,
                        "invoice_user_id": moves.invoice_user_id,
                    }
                )
        return res

    @api.onchange("refund_method")
    def _onchange_type_credit_note_discount(self):
        for rec in self:
            if rec.refund_method == "modify":
                rec.l10n_ec_type_credit_note = "discount"


class AccountInvoiceRefundLine(models.TransientModel):
    _name = "account.move.reversal.line"
    _description = "Credit Note detail"

    wizard_id = fields.Many2one("account.move.reversal", "Wizard", ondelete="cascade")
    process = fields.Boolean("Process?")
    l10n_ec_scrap = fields.Boolean("Scrap?")
    line_id = fields.Many2one("account.move.line", "Invoice Line")
    product_id = fields.Many2one("product.product", "Product")
    lot_id = fields.Many2one("stock.production.lot", "Production Lot")
    stock_move_line_id = fields.Many2one(
        "stock.move.line",
        "Stock Move",
    )
    account_id = fields.Many2one("account.account", "Account")
    product_uom_id = fields.Many2one("uom.uom", "UoM")
    name = fields.Char("Description")
    quantity = fields.Float("Quantity", digits="Product Unit of Measure")
    max_quantity = fields.Float("Max Quantity", digits="Product Unit of Measure")
    discount = fields.Float("Discount(%)", digits="Discount")
    price_unit = fields.Float("Price Unit(on Fact)", digits="Product Price")
    tax_ids = fields.Many2many(comodel_name="account.tax", string="Taxes")
    analytic_account_id = fields.Many2one("account.analytic.account", string="Analytic Account")
    analytic_tag_ids = fields.Many2many("account.analytic.tag", string="Analytic Tags")
    currency_id = fields.Many2one(comodel_name="res.currency", string="Currency", related="line_id.company_currency_id")
    price_subtotal = fields.Monetary("Subtotal(on CN)", compute="_compute_amount", store=False)
    amount_tax = fields.Monetary("I.V.A.(on CN)", compute="_compute_amount", store=False)
    price_total = fields.Monetary("Total(on CN)", compute="_compute_amount", store=False)
    other_amounts = fields.Boolean(string="Other amounts?", required=False)

    @api.constrains("quantity", "max_quantity")
    @api.onchange("quantity", "max_quantity")
    def _check_quantities(self):
        # TODO: restringir solo en devoluciones o para todo?
        # por ahora se restringe cualquier tipo de NC
        for line in self:
            if line.max_quantity > 0 and line.quantity > line.max_quantity:
                raise ValidationError(
                    _("Quantity on line: %s cannot greater than max Available: %s") % (line.name, line.max_quantity)
                )

    @api.depends("quantity", "discount", "price_unit", "tax_ids", "line_id")
    def _compute_amount(self):
        for line in self:
            subtotal = line.price_unit * line.quantity
            if line.discount > 0:
                subtotal = (line.price_unit - (line.price_unit * (1 - (line.discount or 0.0) / 100))) * line.quantity
            amount_tax = 0
            taxes_res = line.tax_ids._origin.compute_all(
                subtotal,
                currency=line.currency_id,
                product=line.product_id,
                partner=line.wizard_id.partner_id.commercial_partner_id,
                is_refund=True,
            )
            for tax_data in taxes_res.get("taxes", []):
                amount_tax = tax_data["amount"]
            total = subtotal + amount_tax
            line.price_subtotal = subtotal
            line.amount_tax = amount_tax
            line.price_total = total


class AccountInvoiceRefundDiscount(models.TransientModel):
    _name = "account.move.reversal.discount"
    _description = "Credit Note detail(Discount)"

    wizard_id = fields.Many2one("account.move.reversal", "Wizard", ondelete="cascade")
    price_subtotal = fields.Float("Discount amount", digits="Account")
    account_id = fields.Many2one("account.account", "Account")
    tax_id = fields.Many2one("account.tax", "Tax")
