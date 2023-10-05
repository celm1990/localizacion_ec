from odoo import api, models


class AccountDebitNote(models.TransientModel):
    _inherit = "account.debit.note"

    @api.model
    def default_get(self, fields):
        res = super(AccountDebitNote, self).default_get(fields)
        moves = (
            self.env["account.move"].browse(self.env.context["active_ids"])
            if self.env.context.get("active_model") == "account.move"
            else self.env["account.move"]
        )
        if "journal_id" in fields and "in_invoice" in moves.mapped("type"):
            journal = self.env["account.journal"].search(
                [
                    ("company_id", "=", self.env.company.id),
                    ("l10n_latam_internal_type", "=", "debit_note"),
                    ("type", "=", "purchase"),
                ]
            )
            if journal:
                res["journal_id"] = journal.id
        return res

    def create_debit(self):
        res = super(AccountDebitNote, self).create_debit()
        new_ctx = dict(self.env.context, internal_type="debit_note")
        res["context"] = new_ctx
        return res
