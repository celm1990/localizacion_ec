from odoo import fields, models


class L10nEcSriPaymentMethod(models.Model):

    _name = "l10n_ec.sri.payment.method"
    _description = "SRI Payment method"

    code = fields.Char(string="Code", required=True)
    name = fields.Char(string="Name", required=True)
    active = fields.Boolean("Active?", default=lambda *a: True)

    _sql_constraints = [
        (
            "code_uniq",
            "unique (code)",
            "Code of Payment Method must be unique, please review!",
        )
    ]

    def _name_search(self, name, args=None, operator="ilike", limit=100, name_get_uid=None):
        args = args or []
        res = super(L10nEcSriPaymentMethod, self)._name_search(name, args, operator, limit, name_get_uid)
        if not res and name:
            recs = self.search([("code", operator, name)] + args, limit=limit)
            if recs:
                res = models.lazy_name_get(self.browse(recs.ids).with_user(name_get_uid)) or []
        return res

    def name_get(self):
        res = []
        for r in self:
            name = "{}-{}".format(r.code, r.name)
            res.append((r.id, name))
        return res
