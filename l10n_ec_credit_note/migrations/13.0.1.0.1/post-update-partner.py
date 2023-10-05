def migrate(cr, version):
    cr.execute(
        """
        UPDATE account_move_line aml
        SET partner_id = am.partner_id
        FROM account_move am
        WHERE am.id = aml.move_id AND aml.partner_id IS NULL AND am.partner_id IS NOT NULL
            AND am.type = 'out_refund' AND am.l10n_ec_type_credit_note = 'discount';
    """
    )
