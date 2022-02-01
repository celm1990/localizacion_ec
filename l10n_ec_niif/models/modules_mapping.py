from odoo.exceptions import UserError
from odoo.tools.translate import _


def get_document_type(invoice_type):
    """
    Devolver el tipo de documento, el que se usa en los tipo de documento de las autorizaciones
    @param invoice_type: el tipo de factura(out_invoice. out_refund, in_invoice, in_refund, liquidation)
    @return: str, tipo de documento como lo espera los documentos de autorizaciones
    """
    document_type = ""
    # liquidacion de compras
    if invoice_type == "liquidation":
        document_type = "liquidation"
    # facturas
    elif invoice_type in ("out_invoice", "in_invoice"):
        document_type = "invoice"
    # notas de credito
    elif invoice_type in ("out_refund", "in_refund"):
        document_type = "credit_note"
    # Notas de debito
    elif invoice_type in ("debit_note_in", "debit_note_out"):
        document_type = "debit_note"
    elif invoice_type == "invoice_reembolso":
        document_type = "invoice_reembolso"
    elif invoice_type in ("withhold_sale", "withhold_purchase"):
        document_type = "withholding"
    elif invoice_type == "delivery_note":
        document_type = "delivery_note"
    else:
        raise UserError(_("Invoice / Document Type: %s is invalid, please check, get_document_type") % (invoice_type))
    return document_type


def l10n_ec_get_invoice_type(invoice_type, internal_type, raise_exception=True):
    """
    Devolver el tipo de factura
    con el concepto de notas de debito y liquidacion de compras,
    las facturas de clientes pueden ser notas de debito
    y las facturas de proveedor pueden ser liquidacion de compras
    @param invoice_type: para facturas, el tipo de factura(out_invoice. out_refund, in_invoice, in_refund)
    @param internal_type: tipo interno segun latam.document.type:
        * invoice
        * debit_note
        * credit_note
        * liquidation
    @return: str, tipo de factura considerando los dos tipos de documentos adicionales(ND y liquidacion de compras)
    """
    document_type = ""
    # Factura de Proveedor
    if invoice_type == "in_invoice" and internal_type == "invoice":
        document_type = "in_invoice"
    # Factura de Cliente
    elif invoice_type == "out_invoice" and internal_type == "invoice":
        document_type = "out_invoice"
    # NC de Cliente
    elif invoice_type == "out_refund":
        document_type = "out_refund"
    # NC de Proveedor
    elif invoice_type == "in_refund":
        document_type = "in_refund"
    # Liquidacion
    elif invoice_type == "in_invoice" and internal_type == "liquidation":
        document_type = "liquidation"
    # ND Proveedor
    elif invoice_type == "in_invoice" and internal_type == "debit_note":
        document_type = "debit_note_in"
    # ND Cliente
    elif invoice_type == "out_invoice" and internal_type == "debit_note":
        document_type = "debit_note_out"
    if not document_type and raise_exception:
        raise UserError(
            _("Invoice / Document Type: %s is invalid, please check, l10n_ec_get_invoice_type") % (invoice_type)
        )
    return document_type


def get_invoice_type_reverse(invoice_type):
    """
    Devolver el tipo de factura como esta en el campo que se guarda en la BD indicando si son ND o liquidacion
    con el concepto de notas de debito y liquidacion de compras,
    las facturas de clientes pueden ser notas de debito
    y las facturas de proveedor pueden ser liquidacion de compras
    @param invoice_type: para facturas, el tipo de factura(out_invoice. out_refund, in_invoice, in_refund, debit_note_in, debit_note_out, liquidacion)
    @return: tuple(invoice_type, internal_type)
        Tupla de 2 elementos:
            1) el tipo de factura tal como se guarda en la BD(campo type)
            2) el tipo interno(campo l10n_latam_internal_type)
    """
    invoice_type_reverse = ""
    l10n_latam_internal_type = ""
    # Liquidacion
    if invoice_type == "liquidation":
        invoice_type_reverse = "in_invoice"
        l10n_latam_internal_type = "liquidation"
    # ND Proveedor
    elif invoice_type == "debit_note_in":
        invoice_type_reverse = "in_invoice"
        l10n_latam_internal_type = "debit_note"
    # ND Cliente
    elif invoice_type == "debit_note_out":
        invoice_type_reverse = "out_invoice"
        l10n_latam_internal_type = "debit_note"
    # Factura de Proveedor
    elif invoice_type in ("in_invoice", "invoice_reembolso"):
        invoice_type_reverse = "in_invoice"
        l10n_latam_internal_type = "invoice"
    # Factura de Cliente
    elif invoice_type == "out_invoice":
        invoice_type_reverse = "out_invoice"
        l10n_latam_internal_type = "invoice"
    # NC de Cliente
    elif invoice_type == "out_refund":
        invoice_type_reverse = "out_refund"
        l10n_latam_internal_type = "credit_note"
    # NC de Proveedor
    elif invoice_type == "in_refund":
        invoice_type_reverse = "in_refund"
        l10n_latam_internal_type = "credit_note"
    elif invoice_type in ("withhold_sale", "withhold_purchase"):
        invoice_type_reverse = "withhold"
    elif invoice_type == "delivery_note":
        invoice_type_reverse = "delivery_note"
    else:
        raise UserError(
            _("Invoice / Document Type: %s is invalid, please check, get_invoice_type_reverse") % (invoice_type)
        )
    return invoice_type_reverse, l10n_latam_internal_type


def get_document_name(document_type):
    """
    Devolver la descripcion del modelo segun el tipo de documento(el que usa los documentos de autorizaciones)
    @param document_type: el tipo de documento(el que usa los documentos de autorizaciones)
    @return: str, la descripcion del tipo de documento, entendible por el usuario
    """
    document_names = {
        "invoice": _("Invoice"),
        "credit_note": _("Credit Note"),
        "debit_note": _("Debit Note"),
        "liquidation": _("Purchase liquidation"),
        "withholding": _("Withhold"),
        "delivery_note": _("Delivery Note"),
        "invoice_reembolso": _("Expense reimbursement"),
    }
    return document_names.get(document_type, "")


def get_model_name(document_type):
    """
    Devolver el nombre del modelo segun el tipo de documento(el que usa los documentos de autorizaciones)
    @param document_type: el tipo de documento(el que usa los documentos de autorizaciones)
    @return: str, el nombre tecnico del tipo de documento para usar ORM
    """
    model_name = {
        "invoice": "account.move",
        "credit_note": "account.move",
        "debit_note": "account.move",
        "liquidation": "account.move",
        "withholding": "l10n_ec.withhold",
        "delivery_note": "l10n_ec.delivery.note",
        "invoice_reembolso": "l10n_ec.account.invoice.refund",
    }
    return model_name.get(document_type, "")


def get_field_name(document_type):
    """
    Devolver el nombre del campo que tiene el numero del modelo segun el tipo de documento(el que usa los documentos de autorizaciones)
    @param document_type: el tipo de documento(el que usa los documentos de autorizaciones)
    @return: str, el nombre tecnico del campo que tiene el numero del modelo para usar ORM
    """
    field_name = {
        "invoice": "l10n_ec_document_number",
        "credit_note": "l10n_ec_document_number",
        "debit_note": "l10n_ec_document_number",
        "liquidation": "l10n_ec_document_number",
        "withholding": "number",
        "delivery_note": "document_number",
        "invoice_reembolso": "document_number",
    }
    return field_name.get(document_type, "")


def get_domain(invoice_type, include_state=True):
    """
    Devolver un domain para usarse en busquedas segun el tipo de documento(el que usa los documentos de autorizaciones de clientes)
    @param invoice_type: el tipo de documento(el que usa los documentos de autorizaciones de clientes)
    @return: lista de tuplas con domain valido para hacer busquedas con ORM
    """
    invoice_type_bd, l10n_latam_internal_type = get_invoice_type_reverse(invoice_type)
    domain_state_data = {
        "out_invoice": [("state", "=", "posted")],
        "out_refund": [("state", "=", "posted")],
        "in_refund": [("state", "=", "posted")],
        "debit_note_out": [("state", "=", "posted")],
        "debit_note_in": [("state", "=", "posted")],
        "liquidation": [("state", "=", "posted")],
        "in_invoice": [("state", "=", "posted")],
        "withhold_sale": [],
        "withhold_purchase": [],
    }
    common_domain = [
        ("move_type", "=", invoice_type_bd),
        ("l10n_latam_internal_type", "=", l10n_latam_internal_type),
    ]
    domain_state = []
    if include_state:
        domain_state = domain_state_data.get(invoice_type, [])
    domain_account_invoice = common_domain + domain_state
    domains = {
        "out_invoice": domain_account_invoice,
        "out_refund": domain_account_invoice,
        "in_refund": domain_account_invoice,
        "debit_note_out": domain_account_invoice,
        "debit_note_in": domain_account_invoice,
        "liquidation": domain_account_invoice,
        "in_invoice": domain_account_invoice,
        "withhold_sale": [("type", "=", "sale")],
        "withhold_purchase": [("type", "=", "purchase")],
        "delivery_note": [],
        "invoice_reembolso": [],
    }

    return domains.get(invoice_type, [])
