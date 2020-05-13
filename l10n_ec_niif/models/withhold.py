# -*- coding: utf-8 -*-
from odoo import fields, models, api, _

_STATES = {'draft': [('readonly', False)]}


class L10nEcWithhold(models.Model):

    _name = 'l10n_ec.withhold'
    _inherit = ['portal.mixin', 'mail.thread', 'mail.activity.mixin']
    _description = 'Ecuadorian Withhold'
    _rec_name = 'number'
    _mail_post_access = 'read'
    _order = 'issue_date DESC, number DESC'

    company_id = fields.Many2one(
        'res.company',
        'Company',
        required=True,
        ondelete="restrict",
        default=lambda self: self.env.user.company_id.id)
    currency_id = fields.Many2one(
        'res.currency',
        string='Currency',
        related="company_id.currency_id",
        store=True,)
    number = fields.Char(
        string='Number',
        required=True,
        readonly=True,
        states=_STATES)
    state = fields.Selection(
        string='State',
        selection=[
            ('draft', 'Draft'),
            ('done', 'Done'),
            ('cancelled', 'Cancelled'),
        ],
        required=True,
        readonly=True,
        default='draft')
    issue_date = fields.Date(
        string='Issue date',
        readonly=True,
        states=_STATES,
        required=True)
    partner_id = fields.Many2one(
        comodel_name='res.partner',
        string='Partner',
        readonly=True,
        ondelete="restrict",
        states=_STATES,
        required=True)
    commercial_partner_id = fields.Many2one(
        comodel_name='res.partner',
        string='Commercial partner',
        readonly=True,
        ondelete="restrict",
        related="partner_id.commercial_partner_id",
        store=True)
    invoice_id = fields.Many2one(
        comodel_name='account.move',
        string='Related Document',
        readonly=True,
        states=_STATES,
        required=False)
    partner_authorization_id = fields.Many2one(
        comodel_name='l10n_ec.sri.authorization.supplier',
        string='Partner authorization',
        readonly=True,
        states=_STATES,
        required=False)
    type = fields.Selection(
        string='Type',
        selection=[
            ('sale', 'On Sales'),
            ('purchase', 'On Purchases'),
            ('credit_card', 'On Credit Card Liquidation'),
        ],
        required=True, readonly=True, deafult=lambda self: self.env.context.get('withhold_type', 'sale'))
    document_type = fields.Selection(
        string='Document type',
        selection=[
            ('electronic', 'Electronic'),
            ('pre_printed', 'Pre Printed'),
            ('auto_printer', 'Auto Printer'),
        ],
        required=True,
        readonly=True,
        states=_STATES,
        default="electronic")
    electronic_authorization = fields.Char(
        string='Electronic authorization',
        size=49,
        readonly=True,
        states=_STATES,
        required=False)
    point_of_emission_id = fields.Many2one(
        comodel_name="l10n_ec.point.of.emission",
        string="Point of Emission",
        ondelete="restrict",
        readonly=True,
        states=_STATES)
    agency_id = fields.Many2one(
        comodel_name="l10n_ec.agency",
        string="Agency", related="point_of_emission_id.agency_id",
        ondelete="restrict",
        store=True,
        readonly=True)
    authorization_line_id = fields.Many2one(
        comodel_name="l10n_ec.sri.authorization.line",
        string="Own Ecuadorian Authorization Line",
        ondelete="restrict",
        readonly=True,
        states=_STATES,)
    concept = fields.Char(
        string='Concept',
        readonly=True,
        states=_STATES,
        required=False)
    note = fields.Char(
        string='Note', 
        required=False)
    move_id = fields.Many2one(
        comodel_name='account.move',
        string='Account Move',
        ondelete="restrict",
        readonly=True)
    line_ids = fields.One2many(
        comodel_name='l10n_ec.withhold.line',
        inverse_name='withhold_id',
        string='Lines',
        readonly=True,
        states=_STATES,
        required=True)

    @api.depends(
        'line_ids.type',
        'line_ids.tax_amount',
    )
    def _get_tax_amount(self):
        for rec in self:
            rec.tax_iva = sum(i.tax_amount_currency for i in rec.line_ids.filtered(lambda x: x.type == 'iva'))
            rec.tax_rent = sum(r.tax_amount_currency for r in rec.line_ids.filtered(lambda x: x.type == 'rent'))

    tax_iva = fields.Monetary(
        string='Withhold IVA',
        compute="_get_tax_amount",
        store=True,
        readonly=True)
    tax_rent = fields.Monetary(
        string='Withhold Rent',
        compute="_get_tax_amount",
        store=True,
        readonly=True)

    def action_done(self):
        self.write({
            'state': 'done',
        })


class L10nEcWithholdLinePercent(models.Model):

    _name = 'l10n_ec.withhold.line.percent'
    _order = 'percent ASC'

    name = fields.Char(
        string='Percent',
        required=False)
    type = fields.Selection(
        string='Type',
        selection=[
            ('iva', 'IVA'),
            ('rent', 'Rent'),
        ],
        required=False,)
    percent = fields.Float(
        string='Percent',
        required=False)

    def _get_percent(self, percent, type):
        rec = self.search([
            ('type', '=', type),
            ('percent', '=', percent),
        ])
        if not rec:
            rec = self.create({
                'name': str(percent),
                'type': type,
                'percent': percent,
            })
        return rec

    _sql_constraints = [
        (
            "type_percent_unique",
            "unique(type, percent)",
            "Percent Withhold must be unique by type",
        )
    ]


class AccountTax(models.Model):

    _inherit = 'account.tax'

    def create(self, vals):
        recs = super(AccountTax, self).create(vals)
        withhold_iva_group = self.env.ref('l10n_ec_niif.tax_group_iva_withhold')
        withhold_rent_group = self.env.ref('l10n_ec_niif.tax_group_renta_withhold')
        percent_model = self.env['l10n_ec.withhold.line.percent']
        for rec in recs:
            if rec.tax_group_id.id in (withhold_iva_group.id, withhold_rent_group.id):
                type = rec.tax_group_id.id == withhold_iva_group.id and 'iva' \
                       or rec.tax_group_id.id == withhold_rent_group.id and 'rent'
                percent = abs(rec.amount)
                if type == 'iva':
                    percent = abs(rec.invoice_repartition_line_ids.filtered(
                                            lambda x: x.repartition_type == 'tax').factor_percent)
                current_percent = percent_model.search([
                    ('type', '=', type),
                    ('percent', '=', percent)
                ])
                if not current_percent:
                    percent_model.create({
                        'name': str(percent),
                        'type': type,
                        'percent': percent,
                    })
        return recs


class L10nEcWithholdLine(models.Model):

    _name = 'l10n_ec.withhold.line'
    _description = 'Ecuadorian Withhold'

    withhold_id = fields.Many2one(
        comodel_name='l10n_ec.withhold',
        string='Withhold',
        required=True,
        ondelete="cascade",
        readonly=True,)
    company_id = fields.Many2one(
        comodel_name='res.company',
        string='Company',
        related="withhold_id.company_id",
        store=True
    )
    issue_date = fields.Date(
        string='Issue date',
        related="withhold_id.issue_date",
        store=True,
    )
    invoice_id = fields.Many2one(
        comodel_name='account.move',
        string='Related Document',
        required=False
    )
    tax_id = fields.Many2one(
        comodel_name='account.tax',
        string='Tax',
        required=False)
    base_tag_id = fields.Many2one(
        comodel_name='account.account.tag',
        string='Base Tax Tag',
        readonly=True)
    tax_tag_id = fields.Many2one(
        comodel_name='account.account.tag',
        string='Tax Tax Tag',
        readonly=True)
    type = fields.Selection(
        string='Type',
        selection=[('iva', 'IVA'),
                   ('rent', 'Rent'), ],
        required=False, )
    partner_currency_id = fields.Many2one(
        comodel_name='res.currency',
        string='Partner Currency',
        related="invoice_id.currency_id",
        store=True)
    base_amount = fields.Monetary(
        string='Base Amount Currency',
        currency_field="partner_currency_id",
        required=True)
    tax_amount = fields.Monetary(
        string='Withhold Amount Currency',
        currency_field="partner_currency_id",
        required=True)
    percent_id = fields.Many2one(
        comodel_name='l10n_ec.withhold.line.percent',
        string='Percent',
        required=False)
    percentage = fields.Float(
        string='Percent',
        related="percent_id.percent",
        store=True,)
    currency_id = fields.Many2one(
        'res.currency',
        string='Currency',
        related="withhold_id.currency_id",
        store=True,)
    base_amount_currency = fields.Monetary(
        string='Base Amount',
        required=True)
    tax_amount_currency = fields.Monetary(
        string='Withhold Amount',
        required=True)

    @api.onchange(
        'invoice_id',
        'type',
    )
    def _onchange_invoice(self):
        if self.invoice_id:
            base_amount = 0
            if self.type == 'iva':
                base_amount = self.invoice_id.l10n_ec_iva
            elif self.type == 'rent':
                base_amount = self.invoice_id.amount_untaxed
            self.update({
                'base_amount': base_amount
            })

    @api.onchange(
        'percent_id',
        'base_amount',
    )
    def _onchange_amount(self):
        if self.percent_id:
            self.base_amount_currency = self.partner_currency_id.compute(self.base_amount, self.currency_id)
            self.tax_amount = (self.percent_id.percent / 100.0) * self.base_amount
            self.tax_amount_currency = self.partner_currency_id.compute(self.tax_amount, self.currency_id)

