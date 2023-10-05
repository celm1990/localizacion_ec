from odoo import fields, models


class WizardChangeDateWithhold(models.TransientModel):

    _name = "wizard.change.date.withhold"

    l10n_ec_issue_date = fields.Date(string="Issue Date", required=False)

    def change_date_withhold(self):
        model_withhold = self.env["l10n_ec.withhold"]
        withhold_id = self.env.context.get("active_id")
        withhold = model_withhold.search([("id", "=", withhold_id)])
        if withhold.move_id:
            withhold.move_id.write(
                {
                    "date": self.l10n_ec_issue_date,
                }
            )
        withhold.write(
            {
                "issue_date": self.l10n_ec_issue_date,
            }
        )
        return {"type": "ir.actions.act_window_close"}
