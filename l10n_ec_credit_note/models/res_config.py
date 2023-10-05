from odoo import fields, models


class ResConfigSettings(models.TransientModel):
    _inherit = "res.config.settings"

    l10n_ec_sent_mail_credit_note_unreconcile_payment = fields.Boolean(
        related="company_id.l10n_ec_sent_mail_credit_note_unreconcile_payment",
        readonly=False,
    )
