import logging

from odoo import SUPERUSER_ID, api

_logger = logging.getLogger(__name__)


def migrate(cr, version):
    env = api.Environment(cr, SUPERUSER_ID, {})
    all_companies = env["res.company"].search([])
    all_companies.write({"l10n_ec_consumidor_final_limit": 50.0})
