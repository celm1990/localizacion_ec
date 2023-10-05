from odoo import fields, models


class ResCompany(models.Model):
    _inherit = "res.company"

    l10n_ec_sent_mail_credit_note_unreconcile_payment = fields.Boolean(string="Sent Mail new credit Note")
