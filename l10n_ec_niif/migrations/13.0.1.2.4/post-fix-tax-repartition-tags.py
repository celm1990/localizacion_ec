from odoo import SUPERUSER_ID, api


def migrate(cr, version):
    env = api.Environment(cr, SUPERUSER_ID, {})
    AccountTax = env["account.tax"]
    tax_list = [
        ("tax_302", {"base": ["tag_f103_302"], "tax": ["tag_f103_352"]}),
    ]
    AccountTax._l10n_ec_action_update_tax_tags(tax_list)
