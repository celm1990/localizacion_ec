import base64
from xml.etree.ElementTree import SubElement

from odoo import _, api, fields, models
from odoo.exceptions import UserError, ValidationError
from odoo.tools import DEFAULT_SERVER_DATETIME_FORMAT as DTF


class L10nEcCommonDocumentElectronic(models.AbstractModel):
    _name = "l10n_ec.common.document.electronic"
    _description = "Abstract Class for electronic documents"

    l10n_ec_electronic_authorization = fields.Char(
        "Autorizacion Electrónica", size=49, copy=False, index=True, readonly=True
    )
    l10n_ec_xml_data_id = fields.Many2one(
        "sri.xml.data",
        "XML electronico",
        copy=False,
        index=True,
        auto_join=True,
        readonly=True,
    )
    l10n_ec_xml_key = fields.Char("Clave de acceso", size=49, copy=False, index=True, readonly=True)
    l10n_ec_authorization_date = fields.Datetime("Fecha de Autorización", copy=False, index=True, readonly=True)

    @api.constrains("l10n_ec_electronic_authorization")
    def _check_duplicity_electronic_authorization(self):
        partner_company = self.env.company.partner_id
        for rec in self.filtered("l10n_ec_electronic_authorization"):
            other_docs = self.search(
                [
                    (
                        "l10n_ec_electronic_authorization",
                        "=",
                        rec.l10n_ec_electronic_authorization,
                    ),
                    ("commercial_partner_id", "!=", partner_company.id),
                ]
            )
            if len(other_docs) > 1:
                raise ValidationError(
                    _("There is already a document with electronic authorization %s please verify")
                    % (rec.l10n_ec_electronic_authorization)
                )

    def _prepare_l10n_ec_sri_xml_values(self, company):
        return {
            "company_id": company.id,
            "l10n_ec_type_conection_sri": company.l10n_ec_type_conection_sri,
        }

    def get_printed_report_name_l10n_ec(self):
        # funcion solo usada para ser llamada de manera externa
        # ya que no se puede llamar a la funcion declarada como privada
        return self._get_report_base_filename()

    def l10n_ec_get_attachments_electronic(self):
        """
        :return: An ir.attachment recordset
        """
        self.ensure_one()
        if not self.l10n_ec_xml_key:
            return []
        domain = [
            ("res_id", "=", self.id),
            ("res_model", "=", self._name),
            ("name", "=", "%s.xml" % self.get_printed_report_name_l10n_ec()),
            ("description", "=", self.l10n_ec_xml_key),
        ]
        return self.env["ir.attachment"].search(domain)

    def l10n_ec_action_create_attachments_electronic(self, file_data=None):
        """
        :return: An ir.attachment recordset
        """
        self.ensure_one()
        ctx = self.env.context.copy()
        # borrar el default_type de facturas
        ctx.pop("default_type", False)
        AttachmentModel = self.env["ir.attachment"].with_context(ctx)
        attachment = AttachmentModel.browse()
        if self.l10n_ec_xml_key and self.l10n_ec_xml_data_id:
            attachment = self.l10n_ec_get_attachments_electronic()
            if not attachment:
                if file_data is None:
                    file_data = self.l10n_ec_xml_data_id._action_create_file_authorized()
                file_name = self.get_printed_report_name_l10n_ec()
                if file_data:
                    attachment = AttachmentModel.create(
                        {
                            "name": "%s.xml" % file_name,
                            "res_id": self.id,
                            "res_model": self._name,
                            "datas": base64.encodebytes(file_data.encode()),
                            "store_fname": "%s.xml" % file_name,
                            "description": self.l10n_ec_xml_key,
                        }
                    )
        return attachment

    def l10n_ec_action_update_electronic_authorization(self, numeroAutorizacion, l10n_ec_authorization_date):
        self.write(
            {
                "l10n_ec_electronic_authorization": str(numeroAutorizacion),
                "l10n_ec_authorization_date": l10n_ec_authorization_date.strftime(DTF),
            }
        )

    def l10n_ec_action_sent_mail_electronic(self):
        # funcion debe ser reemplazada en cada clase heredada
        # es usada para envio del mail al cliente
        raise UserError(_("Debe reemplazar esta funcion l10n_ec_action_sent_mail_electronic en su clase heredada"))

    def l10n_ec_get_document_code_sri(self):
        # funcion debe ser reemplazada en cada clase heredada
        # esta funcion debe devolver el tipo de documento SRI que va en el xml electronico
        # 01 : Factura
        # 03 : Liquidacion de Compras
        # 04 : Nota de Credito
        # 05 : Nota de Debito
        # 06 : Guia de Remision
        # 07 : Comprobante de Retencion
        raise UserError(_("You must replace this function l10n_ec_get_document_code_sri in your inherited class"))

    def l10n_ec_get_document_number(self):
        # funcion debe ser reemplazada en cada clase heredada
        # esta funcion debe devolver el numero de documento
        raise UserError(_("You must replace this function l10n_ec_get_document_number in its inherited class"))

    def l10n_ec_get_document_date(self):
        # funcion debe ser reemplazada en cada clase heredada
        # esta funcion debe devolver la fecha de emision del documento
        raise UserError(_("You must replace this function l10n_ec_get_document_date in your inherited class"))

    def l10n_ec_get_document_string(self):
        # funcion debe ser reemplazada en cada clase heredada
        # esta funcion debe devolver el tipo de documento(Factura, Nota de Credito, etc)
        return ""

    def l10n_ec_get_document_version_xml(self):
        # funcion debe ser reemplazada en cada clase heredada
        # esta funcion debe devolver la version del xml que se debe usar
        raise UserError(_("You must replace this function l10n_ec_get_document_version_xml in your inherited class"))

    def l10n_ec_get_document_filename_xml(self):
        # funcion debe ser reemplazada en cada clase heredada
        # esta funcion debe devolver el nombre del archivo xml sin la extension
        # algo como: id, prefijo, secuencial
        raise UserError(_("You must replace this function l10n_ec_get_document_filename_xml in your inherited class"))

    def l10n_ec_action_generate_xml_data(self, node_root, xml_version):
        # funcion debe ser reemplazada en cada clase heredada
        # esta funcion debe crear la data del documento en el xml(node_root)
        raise UserError(_("You must replace this function l10n_ec_action_generate_xml_data in its inherited class"))

    def _l10n_ec_get_info_aditional(self):
        info_data = []
        if "l10n_ec_info_aditional_ids" in self._fields:
            for line in self.l10n_ec_info_aditional_ids:
                info_data.append(
                    {
                        "name": line.name,
                        "description": line.description,
                    }
                )
        if self.env.company.l10n_ec_rimpe_regime:
            info_data.append(
                {
                    "name": "Regimen",
                    "description": "CONTRIBUYENTE RÉGIMEN RIMPE",
                }
            )
        return info_data

    def l10n_ec_add_info_adicional(self, NodeRoot):
        infoAdicional = SubElement(NodeRoot, "infoAdicional")
        info_data = self._l10n_ec_get_info_aditional()
        if not info_data:
            info_data = [
                {
                    "name": "OtroCampo",
                    "description": "Otra Informacion",
                }
            ]
        for line in info_data:
            campoAdicional = SubElement(infoAdicional, "campoAdicional")
            campoAdicional.set("nombre", line.get("name", "OtroCampo"))
            campoAdicional.text = line.get("description", "Otra Informacion")
        return True
