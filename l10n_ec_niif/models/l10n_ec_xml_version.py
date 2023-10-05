from odoo import fields, models


class L10nEcXmlVersion(models.Model):
    _name = "l10n_ec.xml.version"
    _description = "Xml Version"

    name = fields.Char(string="Nombre", required=True)
    xml_header_name = fields.Char(string="Encabezado en XML", required=True)
    file_path = fields.Char(
        string="Ruta de archivo",
        required=True,
        help="La ruta del archivo xsd a usar, puede ser una ruta absoluta o relativa al modulo, "
        "pero debe incluir el nombre del archivo y la extension",
    )
    version_file = fields.Char(string="Version", required=True)
    document_type = fields.Selection(
        [
            ("invoice", "Facturas"),
            ("credit_note", "Notas de Credito"),
            ("debit_note", "Nota de Debito"),
            ("withholding", "Retenciones"),
            ("delivery_note", "Guias de Remision"),
            ("liquidation", "Liquidacion de compras"),
            ("ats", "ATS"),
        ],
        string="Aplicable en",
        required=True,
    )

    def name_get(self):
        res = []
        for element in self:
            name = "{} ({})".format(element.version_file, element.name)
            res.append((element.id, name))
        return res
