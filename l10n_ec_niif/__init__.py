from . import controllers
from . import models
from . import wizard

from odoo import api, SUPERUSER_ID

def update_payment_term_type(cr, registry):
    env = api.Environment(cr, SUPERUSER_ID, {})
    payment_term_inmediate = env.ref("account.account_payment_term_immediate", False)
    if payment_term_inmediate:
        payment_term_inmediate.write({"l10n_ec_sri_type": "contado"})
