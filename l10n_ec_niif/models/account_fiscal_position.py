from odoo import fields, models


class AccountFiscalPosition(models.Model):
    _inherit = "account.fiscal.position"

    l10n_ec_no_account = fields.Boolean("Not Required to Keep Accounting?")
    l10n_ec_check_withhold = fields.Boolean(
        string="Check Almost one Withhold Tax on Invoice Lines",
        default=True,
    )
