{
    "name": "Credit Notes extension for Ecuador",
    "version": "13.0.1.0.1",
    "category": "Localization",
    "author": "Spearhead",
    "website": "https://www.spearhead.global",
    "license": "LGPL-3",
    "depends": [
        "account",
        "l10n_ec_niif",
        "stock",
        "stock_picking_from_invoice",
        "stock_picking_invoicing",
        "stock_picking_invoice_link_base",
        "stock_picking_invoice_link_sale",
        "sale_force_invoiced",
    ],
    "data": [
        "data/email_template.xml",
        "security/ir.model.access.csv",
        "views/account_move_view.xml",
        "wizard/account_invoice_refund_view.xml",
        "views/product_category_view.xml",
        "views/product_template_view.xml",
        "views/res_config_view.xml",
    ],
    "demo": [],
    "installable": True,
    "auto_install": False,
}