{
    "name": "Ecuador - Accounting IFRS",
    "version": "13.0.1.2.4",
    "category": "Localization",
    "author": "Spearhead",
    "website": "https://www.spearhead.global",
    "license": "LGPL-3",
    "depends": [
        "base",
        "account",
        "base_iban",
        "base_vat",
        "l10n_latam_base",
        "l10n_latam_invoice_document",
        "account_debit_note",
        "portal",
        "mail",
    ],
    "data": [
        "security/ir.model.access.csv",
        "security/security.xml",
        "data/parameters_data.xml",
        "data/l10n_latam.document.type.csv",
        "data/l10n_latam_identification_type_data.xml",
        "data/l10n_ec_identification_type_data.xml",
        "data/l10n_ec_sri_payment_method_data.xml",
        "data/partner_data.xml",
        "data/account_tag_data.xml",
        "data/l10n_ec_chart_data.xml",
        "data/account_group_template.xml",
        "data/account.account.template.csv",
        "data/tax_data.xml",
        "data/tax_support_data.xml",
        "data/l10n_ec_chart_post_data.xml",
        "data/bank_data.xml",
        "data/l10n_ec.xml.version.csv",
        "data/sri_error_code_data.xml",
        "data/paperformat.xml",
        "data/cron_jobs.xml",
        "data/fiscal_position_template.xml",
        "report/electronics_report_remplates.xml",
        "report/report_e_invoice.xml",
        "report/report_e_withhold.xml",
        "report/report_withholds_pre_printed.xml",
        "report/report_withholds_auto_printer.xml",
        "report/report_withholds.xml",
        "report/report_liquidation_preprinter_document.xml",
        "data/email_template.xml",
        "data/email_template_cancel_invoice.xml",
        "views/sri_menu.xml",
        "wizard/wizard_cancel_withhold.xml",
        "wizard/wizard_cancel_invoice.xml",
        "wizard/account_debit_note_view.xml",
        "wizard/wizard_cancel_electronic_documents_view.xml",
        "wizard/wizard_change_date_withhold_view.xml",
        "views/res_partner_view.xml",
        "views/tax_support_view.xml",
        "views/identification_type_view.xml",
        "views/account_tax_view.xml",
        "views/account_fiscal_position_view.xml",
        "views/account_payment_term_view.xml",
        "views/account_move_view.xml",
        "views/agency_view.xml",
        "views/authorization_view.xml",
        "views/authorization_supplier_view.xml",
        "views/res_users_view.xml",
        "views/l10n_latam_document_type_view.xml",
        "views/l10n_ec_sri_company_resolution_view.xml",
        "views/l10n_ec_sri_payment_method_view.xml",
        "views/account_journal_view.xml",
        "views/account_payment_view.xml",
        "views/withhold_view.xml",
        "views/sri_error_code_view.xml",
        "views/sri_key_type_view.xml",
        "views/xml_data_view.xml",
        "views/l10n_ec_portal_common_electronic_templates.xml",
        "views/l10n_ec_portal_withhold_templates.xml",
        "views/res_config_view.xml",
        "views/assets.xml",
    ],
    "demo": [
        "demo/agency_data.xml",
        "demo/partner_data.xml",
    ],
    "installable": True,
    "auto_install": False,
    "external_dependencies": {
        "python": ["stdnum", "xmlsig", "OpenSSL", "xades", "zeep"],
    },
    "post_init_hook": "update_payment_term_type",
}
