import base64
import logging
import time
import traceback
import xml.etree.ElementTree as ET
from collections import OrderedDict
from datetime import datetime
from pprint import pformat
from random import randint
from xml.etree.ElementTree import Element, SubElement, tostring

import pytz
from lxml import etree
from zeep import Client
from zeep.transports import Transport

from odoo import _, api, fields, models, tools
from odoo.exceptions import UserError
from odoo.tools import DEFAULT_SERVER_DATETIME_FORMAT as DTF

_logger = logging.getLogger(__name__)


class SriXmlData(models.Model):
    _inherit = ["mail.thread", "mail.activity.mixin", "portal.mixin"]
    _name = "sri.xml.data"
    _description = "SRI XML Electronic"
    _rec_name = "number_document"

    fields_size = {
        "l10n_ec_xml_key": 49,
        "xml_authorization": 49,
    }

    @api.depends(
        "invoice_out_id",
        "credit_note_out_id",
        "debit_note_out_id",
        "withhold_id",
        "liquidation_id",
        "invoice_out_id.invoice_date",
        "credit_note_out_id.invoice_date",
        "debit_note_out_id.invoice_date",
        "liquidation_id.invoice_date",
        "withhold_id.issue_date",
    )
    def _compute_document_datas(self):
        for xml_data in self:
            number = "SN"
            date_emision_document = False
            point_emission = self.env["l10n_ec.point.of.emission"]
            if xml_data.invoice_out_id:
                number = "FV: %s" % xml_data.invoice_out_id.l10n_ec_get_document_number()
                date_emision_document = xml_data.invoice_out_id.l10n_ec_get_document_date()
                point_emission = xml_data.invoice_out_id.l10n_ec_point_of_emission_id
            elif xml_data.credit_note_out_id:
                number = "NCC: %s" % xml_data.credit_note_out_id.l10n_ec_get_document_number()
                date_emision_document = xml_data.credit_note_out_id.l10n_ec_get_document_date()
                point_emission = xml_data.credit_note_out_id.l10n_ec_point_of_emission_id
            elif xml_data.debit_note_out_id:
                number = "NDC: %s" % xml_data.debit_note_out_id.l10n_ec_get_document_number()
                date_emision_document = xml_data.debit_note_out_id.l10n_ec_get_document_date()
                point_emission = xml_data.debit_note_out_id.l10n_ec_point_of_emission_id
            elif xml_data.withhold_id:
                number = "RET: %s" % xml_data.withhold_id.l10n_ec_get_document_number()
                date_emision_document = xml_data.withhold_id.l10n_ec_get_document_date()
                point_emission = xml_data.withhold_id.point_of_emission_id
            elif xml_data.liquidation_id:
                number = "LIQ: %s" % xml_data.liquidation_id.l10n_ec_get_document_number()
                date_emision_document = xml_data.liquidation_id.l10n_ec_get_document_date()
                point_emission = xml_data.liquidation_id.l10n_ec_point_of_emission_id
            xml_data.number_document = number
            xml_data.date_emision_document = date_emision_document
            xml_data.l10n_ec_point_of_emission_id = point_emission

    number_document = fields.Char("Document Number", compute="_compute_document_datas", store=True, index=True)
    date_emision_document = fields.Date("Fecha de emision", compute="_compute_document_datas", store=True, index=True)
    l10n_ec_point_of_emission_id = fields.Many2one(
        "l10n_ec.point.of.emission",
        string="Punto de Emisión",
        compute="_compute_document_datas",
        store=True,
        index=True,
    )
    agency_id = fields.Many2one(
        "l10n_ec.agency",
        string="Agencia",
        related="l10n_ec_point_of_emission_id.agency_id",
        store=True,
    )
    xml_file = fields.Binary(readonly=False, copy=False)
    xml_filename = fields.Char(string="Nombre de archivo xml", readonly=False, copy=False)
    xml_file_version = fields.Char("Version XML")
    l10n_ec_xml_key = fields.Char("Clave de Acceso", size=49, readonly=True, index=True, tracking=True)
    xml_authorization = fields.Char("Autorización SRI", size=49, readonly=True, index=True)
    description = fields.Char("Description")
    invoice_out_id = fields.Many2one("account.move", "Factura", index=True, auto_join=True)
    credit_note_out_id = fields.Many2one("account.move", "Nota de Crédito", index=True, auto_join=True)
    debit_note_out_id = fields.Many2one("account.move", "Nota de Débito", index=True, auto_join=True)
    liquidation_id = fields.Many2one("account.move", "Liquidacion de compras", index=True, auto_join=True)
    withhold_id = fields.Many2one("l10n_ec.withhold", "Retención", index=True, auto_join=True)
    company_id = fields.Many2one("res.company", string="Compañía", default=lambda self: self.env.company)
    partner_id = fields.Many2one("res.partner", "Cliente", index=True, auto_join=True)
    create_uid = fields.Many2one("res.users", "Creado por", readonly=True)
    create_date = fields.Datetime("Fecha de Creación", readonly=True)
    signed_date = fields.Datetime("Fecha de Firma", readonly=True, index=True)
    send_date = fields.Datetime("Fecha de Envío", readonly=True)
    response_date = fields.Datetime("Fecha de Respuesta", readonly=True)
    l10n_ec_authorization_date = fields.Datetime("Fecha de Autorización", readonly=True, index=True)
    notification_active = fields.Boolean(
        string="Notificación de Documentos Electrónicos no Autorizados?",
        default=True,
        help="Esto permite activar o desactivar las notificaciones del presente documento",
    )
    l10n_ec_type_conection_sri = fields.Selection(
        [
            ("online", "On-Line"),
            ("offline", "Off-Line"),
        ],
        string="Tipo de conexion con SRI",
        default="offline",
    )
    state = fields.Selection(
        [
            ("draft", "Creado"),
            ("signed", "Firmado"),
            # Emitido x Contingencia, en espera de autorizacion
            ("waiting", "En Espera de Autorización"),
            ("authorized", "Autorizado"),
            ("returned", "Devuelta"),
            ("rejected", "No Autorizado"),
            ("cancel", "Cancelado"),
        ],
        string="Estado",
        index=True,
        readonly=True,
        default="draft",
        tracking=True,
    )
    l10n_ec_type_environment = fields.Selection(
        [
            ("test", "Pruebas"),
            ("production", "Producción"),
        ],
        string="Tipo de Ambiente",
        index=True,
        readonly=True,
    )
    last_error_id = fields.Many2one("sri.error.code", "Ultimo Mensaje de error", readonly=True, index=True)
    sri_message_ids = fields.One2many("sri.xml.data.message.line", "xml_id", "Mensajes Informativos", auto_join=True)
    try_ids = fields.One2many("sri.xml.data.send.try", "xml_id", "Send Logs", auto_join=True)
    # campo para enviar los mail a los clientes por lotes, u mejorar el proceso de autorizacion
    send_mail = fields.Boolean("Mail enviado?")
    # campo para el numero de autorizacion cuando se cancelan documentos electronicos
    authorization_to_cancel = fields.Char("Autorización para cancelar", size=64, readonly=True)
    cancel_date = fields.Datetime("Fecha de cancelación", readonly=True)
    cancel_user_id = fields.Many2one("res.users", "Usuario que canceló", readonly=True)

    _sql_constraints = [
        (
            "invoice_out_id_uniq",
            "unique (invoice_out_id, company_id)",
            "Ya existe una factura con el mismo numero!",
        ),
        (
            "credit_note_out_id_uniq",
            "unique (credit_note_out_id, company_id)",
            "Ya existe una Nota de credito con el mismo numero!",
        ),
        (
            "debit_note_out_id_uniq",
            "unique (debit_note_out_id, company_id)",
            "Ya existe una Nota de debito con el mismo numero!",
        ),
        (
            "liquidation_id_uniq",
            "unique (liquidation_id, company_id)",
            "Ya existe una Liquidacion de compras con el mismo numero!",
        ),
        (
            "withhold_id_uniq",
            "unique (withhold_id, company_id)",
            "Ya existe una Retencion con el mismo numero!",
        ),
    ]

    @api.model
    def get_current_wsClient(self, environment, url_type):
        """

        :param environment: tipo de ambiente, puede ser:
            1: Pruebas
            2: Produccion
        :param url_type: el tipo de url a solicitar, puede ser:
            reception: url para recepcion de documentos
            authorization: url para autorizacion de documentos
        :return:
        """
        # Debido a que el servidor me esta rechazando las conexiones contantemente, es necesario que se cree una sola instancia
        # Para conexion y asi evitar un reinicio constante de la comunicacion
        wsClient = None
        company = self.env.company
        ws_url = self._get_url_ws(environment, url_type)
        try:
            transport = Transport(timeout=company.l10n_ec_ws_timeout)
            wsClient = Client(ws_url, transport=transport)
        except Exception as e:
            _logger.warning(
                "Error in Connection with web services of SRI: %s. Error: %s",
                ws_url,
                tools.ustr(e),
            )
        return wsClient

    def get_current_document(self):
        self.ensure_one()
        document = self.invoice_out_id
        if not document and self.credit_note_out_id:
            document = self.credit_note_out_id
        if not document and self.debit_note_out_id:
            document = self.debit_note_out_id
        if not document and self.liquidation_id:
            document = self.liquidation_id
        if not document and self.withhold_id:
            document = self.withhold_id
        return document

    @api.model
    def get_sequence(self, number):
        res = None
        try:
            number_splited = number.split("-")
            res = int(number_splited[2])
        except Exception as e:
            _logger.debug("Error getting sequence: %s" % str(e))
            res = None
        return res

    @api.model
    def _get_environment(self):
        company = self.company_id or self.env.company
        # Si no esta configurado el campo, x defecto tomar pruebas
        res = "1"
        if company.l10n_ec_type_environment == "production":
            res = "2"
        return res

    @api.model
    def _is_document_authorized(self, invoice_type):
        company = self.company_id or self.env.company
        document_active = False
        if invoice_type == "out_invoice" and company.l10n_ec_electronic_invoice:
            document_active = True
        elif invoice_type == "out_refund" and company.l10n_ec_electronic_credit_note:
            document_active = True
        elif invoice_type == "debit_note_out" and company.l10n_ec_electronic_debit_note:
            document_active = True
        elif invoice_type == "withhold_purchase" and company.l10n_ec_electronic_withhold:
            document_active = True
        elif invoice_type == "liquidation" and company.l10n_ec_electronic_liquidation:
            document_active = True
        elif invoice_type == "lote_masivo" and company.electronic_batch:
            document_active = True
        return document_active

    @api.model
    def l10n_ec_is_environment_production(self, invoice_type, printer_emission):
        """
        Verifica si esta en ambiente de produccion y el tipo de documento esta habilitado para facturacion electronica
        @param invoice_type: Puede ser los tipos :
            out_invoice : Factura
            out_refund : Nota de Credito
            debit_note_out : Nota de Debito
            delivery_note : Guia de Remision
            withhold_purchase : Comprobante de Retencion
            lote_masivo : Lote Masivo
        @requires: bool True si el documento esta habilidado para facturacion electronica y en modo produccion
            False caso contrario
        """
        res = False
        if printer_emission.type_emission != "electronic":
            return False
        environment = self._get_environment()
        if environment == "2" and self._is_document_authorized(invoice_type):
            res = True
        return res

    @api.model
    def get_check_digit(self, key):
        """Devuelve el digito verificador por el metodo del modulo 11
        :param key: Llave a Verificar
        :rtype: clave para adjuntar al xml a ser firmado
        """
        mult = 1
        current_sum = 0
        # Paso 1, 2, 3
        for i in reversed(list(range(len(key)))):
            mult += 1
            if mult == 8:
                mult = 2
            current_sum += int(key[i]) * mult
        # Paso 4 y 5
        check_digit = 11 - (current_sum % 11)
        if check_digit == 11:
            check_digit = 0
        if check_digit == 10:
            check_digit = 1
        return check_digit

    @api.model
    def get_single_key(
        self,
        company,
        document_code_sri,
        environment,
        printer_point,
        sequence,
        date_document=None,
    ):
        """Devuelve la clave para archivo xml a enviar a firmar en comprobantes unicos
        :paran: company: browse_record(res.company)
        :param document_code_sri: Puede ser los siguientes tipos :
            01 : Factura
            04 : Nota de Credito
            05 : Nota de Debito
            06 : Guia de Remision
            07 : Comprobante de Retencion
        :param environment: Puede ser los siguientes ambientes :
            1 : Pruebas
            2 : Produccion
        :param printer_point: Punto de Emision del Documento, con esto se obtendra la serie del documento p.e. 001001
        :param sequence: El secuencial del Documento debe ser tipo numerico
        :rtype: clave para adjuntar al xml a ser firmado
        """
        if not date_document:
            date_document = fields.Date.context_today(self)
        emission = "1"  # emision normal, ya no se admite contingencia(2)
        now_date = date_document.strftime("%d%m%Y")
        serie = printer_point.agency_id.number + printer_point.number
        sequencial = str(sequence).rjust(9, "0")
        code_numeric = randint(1, 99999999)
        code_numeric = str(code_numeric).rjust(8, "0")
        prenumber = (
            now_date
            + document_code_sri
            + company.partner_id.vat
            + environment
            + serie
            + sequencial
            + code_numeric
            + emission
        )
        check_digit = "%s" % self.get_check_digit(prenumber)
        key_value = prenumber + check_digit
        return key_value

    def generate_info_tributaria(self, node, document, environment, company):
        """Asigna al nodo raiz la informacion tributaria que es comun en todos los documentos, asigna clave interna
        al documento para ser firmado posteriormente
        :param node: tipo Element
        :param environment: Puede ser los siguientes ambientes :
            1 : Pruebas
            2 : Produccion
        :param company: compania emisora
        :rtype: objeto root agregado con info tributaria

        """
        util_model = self.env["l10n_ec.utils"]
        document_code_sri = document.l10n_ec_get_document_code_sri()
        document_number = document.l10n_ec_get_document_number()
        date_document = document.l10n_ec_get_document_date()
        printer = self.l10n_ec_point_of_emission_id
        sequence = self.get_sequence(document_number)
        infoTributaria = SubElement(node, "infoTributaria")
        SubElement(infoTributaria, "ambiente").text = environment
        SubElement(infoTributaria, "tipoEmision").text = "1"  # emision normal
        razonSocial = "PRUEBAS SERVICIO DE RENTAS INTERNAS"
        nombreComercial = "PRUEBAS SERVICIO DE RENTAS INTERNAS"
        if environment == "2":
            razonSocial = util_model._clean_str(company.partner_id.name)
            nombreComercial = util_model._clean_str(company.partner_id.l10n_ec_business_name or razonSocial)
        SubElement(infoTributaria, "razonSocial").text = razonSocial
        SubElement(infoTributaria, "nombreComercial").text = nombreComercial
        SubElement(infoTributaria, "ruc").text = company.partner_id.vat
        clave_acceso = self.l10n_ec_xml_key
        if not clave_acceso:
            clave_acceso = self.get_single_key(
                company,
                document_code_sri,
                environment,
                printer,
                sequence,
                date_document,
            )
        SubElement(infoTributaria, "claveAcceso").text = clave_acceso
        SubElement(infoTributaria, "codDoc").text = document_code_sri
        SubElement(infoTributaria, "estab").text = printer.agency_id.number
        SubElement(infoTributaria, "ptoEmi").text = printer.number
        SubElement(infoTributaria, "secuencial").text = str(sequence).rjust(9, "0")
        # Debe ser la direccion matriz
        company_address = company.partner_id.get_direccion_matriz(printer)
        SubElement(infoTributaria, "dirMatriz").text = util_model._clean_str(company_address or "")
        if company.l10n_ec_microenterprise_regime_taxpayer:
            SubElement(infoTributaria, "regimenMicroempresas").text = "CONTRIBUYENTE RÉGIMEN MICROEMPRESAS"
        if company.l10n_ec_retention_resolution_number:
            SubElement(infoTributaria, "agenteRetencion").text = util_model._clean_str(
                str(company.l10n_ec_retention_resolution_number) or ""
            )
        if company.l10n_ec_rimpe_regime and False:
            SubElement(infoTributaria, "contribuyenteRimpe").text = "CONTRIBUYENTE RÉGIMEN RIMPE"
        return clave_acceso, node

    def check_xsd(self, xml_string, xsd_file_path):
        try:
            xsd_file = tools.file_open(xsd_file_path)
            xmlschema_doc = etree.parse(xsd_file)
            xmlschema = etree.XMLSchema(xmlschema_doc)
            xml_doc = etree.fromstring(xml_string)
            result = xmlschema.validate(xml_doc)
            if not result:
                xmlschema.assert_(xml_doc)
            return result
        except AssertionError as e:
            if self.env.context.get("l10n_ec_xml_call_from_cron") or tools.config.get("skip_xsd_check", False):
                _logger.error(
                    "Wrong Creation on XML File, faltan datos, verifique clave de acceso: %s, Detalle de error: %s",
                    self.l10n_ec_xml_key,
                    tools.ustr(e),
                )
            else:
                raise UserError(_("Wrong Creation on XML File, missing data : \n%s") % tools.ustr(e))
        return True

    def action_generate_xml_file(self, document):
        """Genera estructura xml del archivo a ser firmado
        :param document: documento a firmar
        :rtype: objeto root agregado con info tributaria
        """
        # Cuando se encuentre en un ambiente de pruebas el sistema se debera usar para la razon social
        # PRUEBAS SERVICIO DE RENTAS INTERNAS
        util_model = self.env["l10n_ec.utils"]
        company = self.company_id or self.env.company
        sign_now = self.env.context.get("sign_now", True)
        environment = self._get_environment()
        xml_version = document.l10n_ec_get_document_version_xml()
        partner_id = document.partner_id
        root = Element(
            xml_version.xml_header_name,
            id="comprobante",
            version=xml_version.version_file,
        )
        clave_acceso, root = self.generate_info_tributaria(root, document, environment, company)
        state = self.state
        l10n_ec_type_environment = ""
        if environment == "1":
            l10n_ec_type_environment = "test"
        elif environment == "2":
            l10n_ec_type_environment = "production"
        self.write(
            {
                "l10n_ec_type_environment": l10n_ec_type_environment,
                "state": state,
                "l10n_ec_xml_key": clave_acceso,
                "partner_id": partner_id and partner_id.id or False,
                "xml_file_version": xml_version.version_file,
            }
        )
        # escribir en los objetos relacionados, la clave de acceso y el xml_data para pasar la relacion
        document.write(
            {
                "l10n_ec_xml_key": clave_acceso,
                "l10n_ec_xml_data_id": self.id,
            }
        )
        # si estoy con un documento externo, y no debo hacer el proceso electronico en ese momento
        # no tomar la info de los documentos, la tarea cron debe encargarse de eso
        if sign_now:
            document.l10n_ec_action_generate_xml_data(root, xml_version)
        # Se identa con propositos de revision, no debe ser asi al enviar el documento
        util_model.indent(root)
        bytes_data = tostring(root, encoding="UTF-8")
        string_data = bytes_data.decode()
        self.check_xsd(string_data, xml_version.file_path)
        binary_data = base64.encodebytes(bytes_data)
        return string_data, binary_data

    def _create_messaje_response(self, messajes, authorized, raise_error):
        message_model = self.env["sri.xml.data.message.line"]
        error_model = self.env["sri.error.code"]
        last_error_rec = self.env["sri.error.code"].browse()
        last_error_id, raise_error = False, False
        vals_messages = {}
        method_messages = "create"
        messages_recs = message_model.browse()
        messages_error = []
        for message in messajes:
            method_messages = "create"
            messages_recs = message_model.browse()
            # si no fue autorizado, y es clave 70, escribir estado para que la tarea cron se encargue de autorizarlo
            # el identificador puede ser str o numerico
            if not authorized and message.get("identificador") and message.get("identificador") in ("70", 70):
                _logger.warning(
                    "Clave 70, en espera de autorizacion. %s %s",
                    message.get("mensaje", ""),
                    message.get("informacionAdicional", ""),
                )
                self.write({"state": "waiting"})
                raise_error = False
            error_recs = error_model.search([("code", "=", message.get("identificador"))])
            if error_recs:
                last_error_rec = error_recs[0]
            # el mensaje 60 no agregarlo, es informativo y no debe lanzar excepcion por ese error
            if message.get("identificador") and message.get("identificador") not in (
                "60",
                60,
            ):
                messages_error.append("{}. {}".format(message.get("mensaje"), message.get("informacionAdicional")))
            vals_messages = {
                "xml_id": self.id,
                "message_code_id": last_error_rec.id,
                "message_type": message.get("tipo"),
                "other_info": message.get("informacionAdicional"),
                "message": message.get("mensaje"),
            }
            for msj in self.sri_message_ids:
                # si ya existe un mensaje con el mismo codigo
                # y el texto es el mismo, modificar ese registro
                if msj.message_type in ("ERROR", "ERROR DE SERVIDOR") and last_error_rec:
                    last_error_id = last_error_rec.id
                if msj.message_code_id and last_error_rec:
                    if msj.message_code_id.id == last_error_rec.id and (
                        msj.message == message.get("mensaje") or msj.other_info == message.get("other_info")
                    ):
                        method_messages = "write"
                        messages_recs += msj
            if method_messages == "write" and messages_recs:
                messages_recs.write(vals_messages)
            elif method_messages == "create":
                message_model.create(vals_messages)
                if vals_messages.get("message_type", "") in ("ERROR", "ERROR DE SERVIDOR") and last_error_rec:
                    last_error_id = last_error_rec.id
        # una vez creado todos los mensajes, si hubo uno de error escribirlo como el ultimo error recibido
        if last_error_id:
            values = {"last_error_id": last_error_id}
            # si el ultimo codigo de error es codigo 43(Clave acceso registrada)
            # cambiar el estado a En espera de autorizacion, para que la tarea cron la procese posteriormente
            if self.state not in ("authorized", "cancel") and last_error_rec.code == "43":
                values["state"] = "waiting"
            self.write(values)
        return messages_error, raise_error

    def _send_xml_data_to_valid(self, client_ws, client_ws_auth):
        """
        Enviar a validar el comprobante con la clave de acceso
        :param client_ws: instancia del webservice para realizar el proceso
        """
        try_model = self.env["sri.xml.data.send.try"]
        self.write({"send_date": time.strftime(DTF)})
        response = False
        try:
            send = True
            # En caso de ya haber tratado de enviar anteriormente, no debe enviar 2 veces
            if len(self.try_ids) >= 1:
                # En caso de ya haber hecho un intento es necesario que se verifique directamente con la clave de acceso
                try_rec = try_model.create(
                    {
                        "xml_id": self.id,
                        "send_date": time.strftime(DTF),
                        "type_send": "check",
                    }
                )
                responseAuth = client_ws_auth.service.autorizacionComprobante(
                    claveAccesoComprobante=self.l10n_ec_xml_key
                )
                try_rec.write({"response_date": time.strftime(DTF)})
                ok, msgs = self._process_response_autorization(responseAuth)
                if ok:
                    response = {"estado": "RECIBIDA"}
                    # Si ya fue recibida y autorizada, no tengo que volver a enviarla
                    send = False
                elif msgs:
                    self._create_messaje_response(msgs, ok, False)
            if self.env.context.get("no_send") and self.try_ids:
                send = False
            if send:
                try_rec = try_model.create(
                    {
                        "xml_id": self.id,
                        "send_date": time.strftime(DTF),
                        "type_send": "send",
                    }
                )
                # el parametro xml del webservice espera recibir xs:base64Binary
                # con suds nosotros haciamos la conversion
                # pero con zeep la libreria se encarga de hacer la conversion
                # tenerlo presente cuando se use adjuntos en lugar del sistema de archivos
                response = client_ws.service.validarComprobante(xml=self.get_file().encode())
                try_model.write({"response_date": time.strftime(DTF)})
                _logger.info(
                    "Send file succesful, claveAcceso %s. %s",
                    self.l10n_ec_xml_key,
                    str(response.estado) if hasattr(response, "estado") else "SIN RESPUESTA",
                )
            self.write({"response_date": time.strftime(DTF)})
        except Exception as e:
            _logger.info(
                "can't validate document in %s, claveAcceso %s. ERROR: %s",
                str(client_ws),
                self.l10n_ec_xml_key,
                tools.ustr(e),
            )
            _logger.info(
                "can't validate document in %s, claveAcceso %s. TRACEBACK: %s",
                str(client_ws),
                self.l10n_ec_xml_key,
                tools.ustr(traceback.format_exc()),
            )
            self.write({"state": "waiting"})
            ok = False
            messajes = [
                {
                    "identificador": "50",
                    "informacionAdicional": "Cuando ocurre un error inesperado en el servidor.",
                    "mensaje": "Error Interno General del servidor",
                    "tipo": "ERROR DE SERVIDOR",
                }
            ]
            self._create_messaje_response(messajes, ok, False)
        return response

    def _process_response_check(self, response):
        """
        Procesa la respuesta del webservice
        si fue devuelta, devolver False los mensajes
        si fue recibida, devolver True y los mensajes
        """
        ok, error, previous_authorized = False, False, False
        msj_res = []
        if response and not isinstance(response, dict):
            if hasattr(response, "estado") and response.estado == "DEVUELTA":
                # si fue devuelta, intentar nuevamente, mientras no supere el numero maximo de intentos
                self.write({"state": "returned"})
                ok = False
            else:
                ok = True
            try:
                comprobantes = hasattr(response.comprobantes, "comprobante") and response.comprobantes.comprobante or []
                for comprobante in comprobantes:
                    for msj in comprobante.mensajes.mensaje:
                        msj_res.append(
                            {
                                "identificador": msj.identificador if hasattr(msj, "identificador") else "",
                                "informacionAdicional": msj.informacionAdicional
                                if hasattr(msj, "informacionAdicional")
                                else "",
                                "mensaje": msj.mensaje if hasattr(msj, "mensaje") else "",
                                "tipo": msj.tipo if hasattr(msj, "tipo") else "",
                            }
                        )
                        # si el mensaje es error, se debe mostrar el msj al usuario
                        if hasattr(msj, "tipo") and msj.tipo == "ERROR":
                            error = True
                            ok = False
            except Exception as e:
                _logger.info(
                    "can't validate document, claveAcceso %s. ERROR: %s",
                    self.l10n_ec_xml_key,
                    tools.ustr(e),
                )
                _logger.info(
                    "can't validate document, claveAcceso %s. TRACEBACK: %s",
                    self.l10n_ec_xml_key,
                    tools.ustr(traceback.format_exc()),
                )
                ok = False
        if response and isinstance(response, dict) and response.get("estado", False) == "RECIBIDA":
            ok = True
            previous_authorized = True
        return ok, msj_res, error, previous_authorized

    def _send_xml_data_to_autorice(self, client_ws):
        """
        Envia a autorizar el archivo
        :param client_ws: direccion del webservice para realizar el proceso
        """
        try:
            response = client_ws.service.autorizacionComprobante(claveAccesoComprobante=self.l10n_ec_xml_key)
        except Exception as e:
            response = False
            self.write({"state": "waiting"})
            _logger.warning("Error send xml to server %s. ERROR: %s", client_ws, tools.ustr(e))
            messajes = [
                {
                    "identificador": "50",
                    "informacionAdicional": "Cuando ocurre un error inesperado en el servidor.",
                    "mensaje": "Error Interno General del servidor",
                    "tipo": "ERROR DE SERVIDOR",
                }
            ]
            self._create_messaje_response(messajes, False, False)
        return response

    def _process_response_autorization(self, response):
        """
        Procesa la respuesta del webservice
        si fue devuelta, devolver False los mensajes
        si fue recibida, devolver True y los mensajes
        """
        vals = {}
        ok = False
        msj_res = []
        no_write = self.env.context.get("no_write", False)

        def dump(obj):
            data_srt = pformat(obj, indent=3, depth=5)
            _logger.warning("Data dump: %s", data_srt)

        if not response:
            # si no tengo respuesta, dejar el documento en espera de autorizacion, para que la tarea cron se encargue de procesarlo y no quede firmado el documento
            _logger.warning("Authorization response error, No response get. Documento en espera de autorizacion")
            self.write({"state": "waiting"})
            return ok, msj_res
        if isinstance(response, object) and not hasattr(response, "autorizaciones"):
            # si no tengo respuesta, dejar el documento en espera de autorizacion, para que la tarea cron se encargue de procesarlo y no quede firmado el documento
            _logger.warning(
                "Authorization response error, No Autorizacion in response. Documento en espera de autorizacion"
            )
            self.write({"state": "waiting"})
            return ok, msj_res
        # a veces el SRI devulve varias autorizaciones, unas como no autorizadas
        # pero otra si autorizada, si pasa eso, tomar la que fue autorizada
        # las demas ignorarlas
        autorizacion_list = []
        list_aux = []
        l10n_ec_authorization_date = False
        if hasattr(response, "autorizaciones") and response.autorizaciones is not None:
            if isinstance(response.autorizaciones, str):
                _logger.warning(
                    "Authorization data error, reponse message is not correct. %s",
                    str(response.autorizaciones),
                )
                dump(response)
                return ok, msj_res
            if not isinstance(response.autorizaciones.autorizacion, list):
                list_aux = [response.autorizaciones.autorizacion]
            else:
                list_aux = response.autorizaciones.autorizacion
        for doc in list_aux:
            estado = doc.estado
            if estado == "AUTORIZADO":
                autorizacion_list.append(doc)
                break
        # si ninguna fue autorizada, procesarlas todas, para que se creen los mensajes
        if not autorizacion_list:
            autorizacion_list = list_aux
        for doc in autorizacion_list:
            estado = doc.estado
            if estado == "AUTORIZADO" and not no_write:
                ok = True
                # TODO: escribir la autorizacion en el archivo xml o no???
                numeroAutorizacion = doc.numeroAutorizacion
                # tomar la fecha de autorizacion que envia el SRI
                l10n_ec_authorization_date = doc.fechaAutorizacion if hasattr(doc, "fechaAutorizacion") else False
                # si no es una fecha valida, tomar la fecha actual del sistema
                if not isinstance(l10n_ec_authorization_date, datetime):
                    l10n_ec_authorization_date = datetime.now()
                if l10n_ec_authorization_date.tzinfo:
                    l10n_ec_authorization_date = l10n_ec_authorization_date.astimezone(pytz.UTC)
                _logger.info(
                    "Authorization succesful, claveAcceso %s. Autohrization: %s. Fecha de autorizacion: %s",
                    self.l10n_ec_xml_key,
                    str(numeroAutorizacion),
                    l10n_ec_authorization_date,
                )
                vals["xml_authorization"] = str(numeroAutorizacion)
                vals["l10n_ec_authorization_date"] = l10n_ec_authorization_date.strftime(DTF)
                vals["state"] = "authorized"
                # escribir en los objetos relacionados, la autorizacion y fecha de autorizacion
                document = self.get_current_document()
                if document:
                    document.l10n_ec_action_update_electronic_authorization(
                        numeroAutorizacion, l10n_ec_authorization_date
                    )
            else:
                # si no fue autorizado, validar que no sea clave 70
                ok = False
                if not self.env.context.get("no_change_state", False):
                    vals["state"] = "rejected"
            if vals and not no_write:
                self.write(vals)
                # # si fue autorizado, enviar a crear el xml
                # if 'state' in vals and vals['state'] == 'authorized':
                #     self.action_create_file_authorized()
            try:
                # el webservice en mensajes a veces devuelve un texto vacio
                if doc.mensajes:
                    if isinstance(doc.mensajes.mensaje, list):
                        for msj in doc.mensajes.mensaje:
                            msj_res.append(
                                {
                                    "identificador": msj.identificador if hasattr(msj, "identificador") else "",
                                    "informacionAdicional": msj.informacionAdicional
                                    if hasattr(msj, "informacionAdicional")
                                    else "",
                                    "mensaje": msj.mensaje if hasattr(msj, "mensaje") else "",
                                    "tipo": msj.tipo if hasattr(msj, "tipo") else "",
                                }
                            )
                    else:
                        for msj in doc.mensajes:
                            msj_res.append(
                                {
                                    "identificador": msj.identificador if hasattr(msj, "identificador") else "",
                                    "informacionAdicional": msj.informacionAdicional
                                    if hasattr(msj, "informacionAdicional")
                                    else "",
                                    "mensaje": msj.mensaje if hasattr(msj, "mensaje") else "",
                                    "tipo": msj.tipo if hasattr(msj, "tipo") else "",
                                }
                            )
            except Exception as e:
                _logger.warning("Can't process messages %s. ERROR: %s", doc.mensajes, tools.ustr(e))
                _logger.debug(traceback.format_exc())
        return ok, msj_res

    def _action_create_file_authorized(self):
        xml_authorized = ""
        # el xml debe estar autorizado, tener fecha de autorizacion
        # si tengo xml firmado, a ese anexarle la autorizacion
        if self.state == "authorized" and self.xml_authorization and self.xml_file:
            tree = ET.fromstring(self.get_file())
            xml_authorized = self._create_file_authorized(
                tree,
                self.xml_authorization,
                fields.Datetime.context_timestamp(self, self.l10n_ec_authorization_date),
                self.l10n_ec_type_environment,
            )
        return xml_authorized

    @api.model
    def _create_file_authorized(self, tree, authorization_number, authorization_date, environment):
        root = Element("RespuestaAutorizacion")
        authorizacion_ele = SubElement(root, "estado")
        authorizacion_ele.text = "AUTORIZADO"
        # anexar la fecha y numero de autorizacion
        authorizacion_ele = SubElement(root, "numeroAutorizacion")
        authorizacion_ele.text = authorization_number
        authorizacion_ele = SubElement(root, "fechaAutorizacion")
        authorizacion_ele.text = authorization_date.strftime(DTF)
        authorizacion_ele = SubElement(root, "ambiente")
        authorizacion_ele.text = "PRODUCCION" if environment == "production" else "PRUEBAS"
        # agregar el resto del xml
        comprobante_node = SubElement(root, "comprobante")
        comprobante_node.text = tostring(tree).decode()
        xml_authorized = tostring(root).decode()
        return xml_authorized

    def action_create_file_authorized(self):
        for xml_data in self:
            xml_authorized = self._action_create_file_authorized()
            # crear el adjunto
            document = xml_data.get_current_document()
            document.l10n_ec_action_create_attachments_electronic(xml_authorized)
        return True

    @api.model
    def _get_url_ws(self, environment, url_type):
        """
        Retorna la url para pruebas o produccion segun el tipo de ambiente
        @:param environment: tipo de ambiente, puede ser:
            1: Pruebas
            2: Produccion
        @param url_type: el tipo de url a solicitar, puede ser:
            reception: url para recepcion de documentos
            authorization: url para autorizacion de documentos
        """
        ICPSudo = self.env["ir.config_parameter"].sudo()
        url_data = ""
        if environment == "1":
            if url_type == "reception":
                url_data = ICPSudo.get_param("l10n_ec_ws_receipt_test")
            elif url_type == "authorization":
                url_data = ICPSudo.get_param("l10n_ec_ws_auth_test")
        elif environment == "2":
            if url_type == "reception":
                url_data = ICPSudo.get_param("l10n_ec_ws_receipt_production")
            elif url_type == "authorization":
                url_data = ICPSudo.get_param("l10n_ec_ws_auth_production")
        return url_data

    def action_send_xml_to_check(self):
        l10n_ec_max_intentos = 1
        for xml_rec in self:
            environment = xml_rec._get_environment()
            xml_rec.with_context(no_send=True).send_xml_data_to_check(environment, l10n_ec_max_intentos)
        return True

    def send_xml_data_to_check(self, environment, l10n_ec_max_intentos=1):
        """Envia al web service indicado el xml a ser verificado
        :param environment: Puede ser los siguientes ambientes :
            1 : Pruebas
            2 : Produccion
        :rtype: code of message
        """

        def _check_intentos(context=None):
            if not context:
                context = {}
            # si supero el maximo de intentos liberar la clave actual y generar una en modo contingencia
            # una tarea cron debe encargarse de reenviar para autorizar
            if l10n_ec_max_intentos > company.l10n_ec_max_intentos:
                return False
            elif send_again:
                # si no supera el maximo de intentos, volve a intentar
                return self.send_xml_data_to_check(environment, l10n_ec_max_intentos=l10n_ec_max_intentos + 1)
            return True

        company = self.company_id or self.env.company
        send_again, authorized, raise_error = False, False, True
        messages_error, message_data = [], []
        # si esta esperando autorizacion, una tarea cron debe encargarse de eso
        if self.state == "waiting" and not self.env.context.get("no_send", False):
            return True
        try:
            if self.env["ir.module.module"].search([("name", "=", "l10n_ec_niif")]).demo:
                self.write(
                    {
                        "xml_authorization": self.l10n_ec_xml_key,
                        "l10n_ec_authorization_date": fields.Datetime.now(),
                        "state": "authorized",
                    }
                )
                return self.action_create_file_authorized()
            if not tools.config.get("send_sri_documents", False):
                _logger.warning("Envio de documentos electronicos desactivado, verifique su archivo de configuracion")
                return True
            receipt_client = self.get_current_wsClient(environment, "reception")
            auth_client = self.get_current_wsClient(environment, "authorization")
            response = self._send_xml_data_to_valid(receipt_client, auth_client)
            (
                res_ws_valid,
                msj,
                raise_error,
                previous_authorized,
            ) = self._process_response_check(response)
            message_data.extend(msj)
            # si no hay respuesta, el webservice no esta respondiendo, la tarea cron se debe encargar de este proceso
            if not res_ws_valid and not raise_error:
                send_again = True
            elif res_ws_valid and not previous_authorized:
                response_auth = self._send_xml_data_to_autorice(auth_client)
                # si el sri no me respondio o no es la respuesta que esperaba
                # verificar si quedo en procesamiento antes de volver a autorizar
                if not response_auth or isinstance(response_auth.autorizaciones, str):
                    response_check = self._send_xml_data_to_valid(receipt_client, auth_client)
                    (
                        res_ws_valid,
                        msj,
                        raise_error,
                        previous_authorized,
                    ) = self._process_response_check(response_check)
                    # si se intento una vez mas y no se pudo autorizar , dejar el documento en espera de autorizacion para que la tarea cron se encargue de eso
                    if not res_ws_valid and not previous_authorized:
                        self.write({"state": "waiting"})
                else:
                    authorized, msj = self._process_response_autorization(response_auth)
                    message_data.extend(msj)
            messages_error, raise_error = self._create_messaje_response(message_data, authorized, raise_error)
        except Exception as e:
            self.write({"state": "rejected"})
            # FIX: pasar a unicode para evitar problemas
            _logger.warning("Error send xml to server. ERROR: %s", tools.ustr(e))
            send_again = True
        if send_again:
            return _check_intentos(self.env.context)
        # si llamo de tarea cron, no mostrar excepcion para que se creen los mensajes
        if self.env.context.get("l10n_ec_xml_call_from_cron", False):
            raise_error = False
        # si estoy en produccion y tengo errores lanzar excepcion, en pruebas no lanzar excepcion
        if messages_error and raise_error and environment == "2":
            # TODO: en flujo de datos se mensiona que se debe mostrar los errores recibidos al autorizar
            # pero si lanzo excepcion se revierte toda la transaccion realizada, siempre sera asi
            # o encontrar manera de mostrar mensajes al usuario sin revertir transaccion(a manera informativa)
            messages_error.insert(0, "No se pudo autorizar, se detalla errores recibidos")
            raise UserError("\n".join(messages_error))
        return authorized

    def _get_messages_before_sent_sri(self, res_document):
        """
        Validar ciertos campos y devolver una lista de mensajes si no es cumple alguna validacion de datos
        """
        return []

    def action_create_xml_file(self):
        xml_to_notify = {}
        xml_to_sign = self.browse()
        for xml_rec in self:
            res_document = xml_rec.get_current_document()
            if not res_document:
                continue
            if self.env.context.get("l10n_ec_xml_call_from_cron", False):
                message_list = xml_rec._get_messages_before_sent_sri(res_document)
                if message_list:
                    xml_to_notify[xml_rec] = message_list
                    continue
            xml_to_sign |= xml_rec
            string_data, binary_data = xml_rec.action_generate_xml_file(res_document)
            xml_rec.write_file(string_data)
        return xml_to_sign, xml_to_notify

    def action_sing_xml_file(self):
        for xml_rec in self:
            company = xml_rec.company_id
            vals = {}
            try:
                if not company.l10n_ec_key_type_id:
                    raise UserError(
                        _(
                            "Es obligatorio seleccionar el tipo de llave o archivo de cifrado usa para la firma de los documentos electrónicos, verificar la configuración de la compañia"
                        )
                    )
                if xml_rec.xml_file:
                    xml_string_data = xml_rec.get_file()
                    xml_signed = company.l10n_ec_key_type_id.action_sign(xml_string_data)
                    if not xml_signed:
                        raise UserError(
                            _(
                                "No se pudo firmar el documento, "
                                "por favor verifique que la configuracion de firma electronica este correcta"
                            )
                        )
                    xml_rec.write_file(xml_signed)
                    vals = {
                        "signed_date": time.strftime(DTF),
                        "state": "signed",
                    }
                if vals:
                    xml_rec.write(vals)
            except Exception as ex:
                raise UserError(tools.ustr(ex))
        return True

    def action_send_xml_file(self):
        for xml_rec in self:
            environment = xml_rec._get_environment()
            xml_rec.send_xml_data_to_check(environment)
        return True

    # @api.model
    # def check_retention_asumida(self, document, invoice_type):
    #     if invoice_type in ('out_invoice', 'out_refund', 'debit_note_out'):
    #         if document.fiscal_position_id and document.fiscal_position_id.retencion_asumida:
    #             return True
    #     if document.partner_id and document.partner_id.property_account_position_id and document.partner_id.property_account_position_id.retencion_asumida:
    #         return True
    #     return False

    def _is_document_enabled_for_send_mail(self):
        company = self.company_id or self.env.company
        is_enabled = False
        if self.invoice_out_id and company.l10n_ec_send_mail_invoice:
            is_enabled = True
        elif self.credit_note_out_id and company.l10n_ec_send_mail_credit_note:
            is_enabled = True
        elif self.debit_note_out_id and company.l10n_ec_send_mail_debit_note:
            is_enabled = True
        elif self.liquidation_id and company.l10n_ec_send_mail_liquidation:
            is_enabled = True
        elif self.withhold_id and company.l10n_ec_send_mail_retention:
            is_enabled = True
        return is_enabled

    def _action_send_mail_partner(self):
        documents_sended = self.browse()
        counter = 1
        total = len(self)
        for xml_rec in self:
            _logger.info("Enviando mail documento electronico: %s/%s", counter, total)
            counter += 1
            document = xml_rec.get_current_document()
            # cuando hay xml que se elimino el documento principal, ignorarlos
            if not document:
                documents_sended |= xml_rec
                continue
            # retencion_asumida = self.check_retention_asumida(document, invoice_type)
            # if retencion_asumida:
            #     documents_sended |= xml_rec
            #     continue
            try:
                if document.l10n_ec_action_sent_mail_electronic():
                    documents_sended |= xml_rec
            except Exception as e:
                if self.env.context.get("l10n_ec_xml_call_from_cron", False):
                    _logger.warning("Error send mail to partner. ERROR: %s", tools.ustr(e))
                else:
                    raise
        return documents_sended

    def action_send_mail_partner(self):
        self.ensure_one()
        document = self.get_current_document()
        # al consumidor final no se debe enviar mail, pero marcarlo como enviado
        if self.partner_id and self.partner_id.l10n_ec_type_sri == "Consumidor":
            raise UserError(_("No esta permitido el envio de correos a consumidor final"))
        if not self._is_document_enabled_for_send_mail():
            raise UserError(
                _("No esta habilitado el envio de correos para los documentos tipo: %s, verifique su configuracion")
                % (document.get_document_string())
            )
        self._action_send_mail_partner()
        return True

    def process_document_electronic(self, force_send_now=False):
        """
        Funcion para procesar los documentos(crear xml, firmar, autorizar y enviar mail al cliente)
        """
        # si se hace el proceso electronico completamente
        if force_send_now:
            xml_process_offline = self.browse()
            xml_process_online = self
        else:
            xml_process_offline = self.filtered(lambda x: x.l10n_ec_type_conection_sri == "offline")
            xml_process_online = self - xml_process_offline
        # crear el xml, firmarlo y enviarlo al SRI
        if xml_process_online:
            xml_to_sign, xml_to_notify = self.action_create_xml_file()
            if xml_to_sign:
                xml_to_sign.action_sing_xml_file()
                xml_to_sign.filtered(lambda x: x.state == "signed").action_send_xml_file()
        # solo enviar a crear el xml con la clave de acceso,
        # una tarea cron se debe encargar de continuar con el proceso electronico
        if xml_process_offline:
            self.action_create_xml_file()
        return True

    @api.model
    def send_documents_offline(self):
        if not tools.config.get("send_sri_documents", False):
            _logger.warning("Envio de documentos electronicos desactivado, verifique su archivo de configuracion")
            return True
        all_companies = self.env["res.company"].search([])
        # pasar flag: l10n_ec_xml_call_from_cron para que los errores salgan x log y no por excepcion
        # pasar flag: no_change_state para que en caso de no autorizar, no me cambie estado del documento y seguir intentado
        for company in all_companies:
            self.with_context(
                allowed_company_ids=company.ids,
                l10n_ec_xml_call_from_cron=True,
                no_change_state=True,
            )._send_documents_offline()
        return True

    @api.model
    def _send_documents_offline(self):
        """
        Procesar los documentos emitidos en modo offline
        """
        company = self.env.company
        xml_recs = self.search(
            [("state", "=", "draft"), ("company_id", "=", company.id)],
            order="number_document",
            limit=company.l10n_ec_cron_process,
        )
        # si no hay documentos evitar establecer conexion con el SRI
        if not xml_recs:
            return True
        environment = self._get_environment()
        receipt_client = self.get_current_wsClient(environment, "reception")
        auth_client = self.get_current_wsClient(environment, "authorization")
        if receipt_client is None or auth_client is None:
            _logger.error("No se puede conectar con el SRI, por favor verifique su conexion o intente luego")
            return False
        counter = 1
        total = len(xml_recs)
        xml_to_notify_no_autorize = self.browse()
        xml_to_notify2 = OrderedDict()
        xml_to_notify = OrderedDict()
        for xml_data in xml_recs:
            _logger.info("Procesando documentos offline: %s de %s", counter, total)
            counter += 1
            document = xml_data.get_current_document()
            if not document:
                continue
            # enviar a crear el xml, si no devuelve nada es xq no paso la validacion y no debe firmarse
            xml_to_sign, xml_to_notify2 = xml_data.action_create_xml_file()
            if xml_to_notify2:
                xml_to_notify.update(xml_to_notify2)
            if not xml_to_sign:
                continue
            # enviar a firmar el xml
            xml_data.action_sing_xml_file()
            if xml_data.state != "signed":
                continue
            # enviar a autorizar el xml(si se autorizo, enviara el mail a los involucrados)
            response = xml_data._send_xml_data_to_valid(receipt_client, auth_client)
            (
                ok,
                messages,
                raise_error,
                previous_authorized,
            ) = xml_data._process_response_check(response)
            # si recibio la solicitud, enviar a autorizar
            if ok:
                response = xml_data._send_xml_data_to_autorice(auth_client)
                ok, messages = xml_data._process_response_autorization(response)
            xml_data._create_messaje_response(messages, ok, raise_error)
            # TODO: si no se puede autorizar, que se debe hacer??
            # por ahora, no hago nada para que la tarea siga intentando en una nueva llamada
            if not ok and messages:
                xml_to_notify_no_autorize |= xml_data
        return True

    @api.model
    def _get_documents_rejected(self, company):
        """
        Buscar los documentos rechazados y filtrar los que tengan documento asociado
        algunos xml electronicos se elimina el documento original y se quedan huerfanos
        """
        xml_recs = self.search(
            [
                ("state", "in", ("returned", "rejected")),
                ("company_id", "=", company.id),
                ("notification_active", "=", True),
            ],
            limit=company.l10n_ec_cron_process,
        )
        xml_recs = xml_recs.filtered(lambda x: x.get_current_document())
        return xml_recs

    @api.model
    def send_documents_rejected(self):
        """
        Enviar mail de documentos rechazados o devueltos
        """
        if not tools.config.get("send_sri_documents", False):
            _logger.warning("Envio de documentos electronicos desactivado, verifique su archivo de configuracion")
            return True
        all_companies = self.env["res.company"].search([])
        template_mail_docs_no_autorization = self.env.ref("l10n_ec_niif.mail_documents_electronic_rejected")
        for company in all_companies:
            xml_rejected = self.with_context(
                allowed_company_ids=company.ids,
                l10n_ec_xml_call_from_cron=True,
            )._get_documents_rejected(company)
            _logger.info(f"{len(xml_rejected)} Documentos electronicos rechazados a notificar")
            if xml_rejected:
                template_mail_docs_no_autorization.with_context(custom_layout="mail.mail_notification_light").send_mail(
                    company.id
                )
        return True

    @api.model
    def send_documents_waiting_autorization(self):
        if not tools.config.get("send_sri_documents", False):
            _logger.warning("Envio de documentos electronicos desactivado, verifique su archivo de configuracion")
            return True
        all_companies = self.env["res.company"].search([])
        # pasar flag: l10n_ec_xml_call_from_cron para que los errores salgan x log y no por excepcion
        # pasar flag: no_change_state para que en caso de no autorizar, no me cambie estado del documento y seguir intentado
        for company in all_companies:
            self.with_context(
                allowed_company_ids=company.ids,
                l10n_ec_xml_call_from_cron=True,
                no_change_state=True,
            )._send_documents_waiting_autorization()
        return True

    @api.model
    def _send_documents_waiting_autorization(self):
        """
        Procesar documentos que no fueron autorizados
        pero recibieron error 70(en espera de autorizacion)
        los cuales no debe volver a enviar a autorizar,
        solo esperar que sean confirmada su autorizacion
        """
        company = self.env.company
        xml_recs = self.search(
            [("state", "=", "waiting"), ("company_id", "=", company.id)],
            limit=company.l10n_ec_cron_process,
        )
        # en algunas ocaciones los documentos se envian a autorizar, pero se quedan como firmados
        # buscar los documentos firmados que se hayan enviado a autorizar para verificar si fueron autorizados o no
        xml_signed_recs = self.search(
            [("state", "in", ("signed", "rejected")), ("company_id", "=", company.id)],
            limit=company.l10n_ec_cron_process,
        )
        xml_send_to_autorice = False
        for xml_signed in xml_signed_recs:
            xml_send_to_autorice = False
            # si hay un intento de envio a autorizar, verificar si el registro fue autorizado
            if xml_signed.try_ids.filtered(lambda x: x.type_send == "send"):
                # cuando el estado sea rechazado(no autorizado) solo enviar a verificar si no hay mensajes informativos
                # caso contrario se ignorara y una tarea cron lo enviara por correo notificando el error devuelto por el SRI
                if xml_signed.state == "rejected":
                    if not xml_signed.message_ids:
                        xml_send_to_autorice = True
                else:
                    xml_send_to_autorice = True
            # agregarlo a la lista para verificar si fue autorizado
            if xml_send_to_autorice and xml_signed not in xml_recs:
                xml_recs += xml_signed
                continue
        if not xml_recs:
            return True
        environment = self._get_environment()
        receipt_client = self.get_current_wsClient(environment, "reception")
        auth_client = self.get_current_wsClient(environment, "authorization")
        if receipt_client is None or auth_client is None:
            _logger.error("No se puede conectar con el SRI, por favor verifique su conexion o intente luego")
            return False
        counter = 1
        total = len(xml_recs)
        xml_to_notify = self.browse()
        for xml_data in xml_recs:
            _logger.info(
                "Procesando documentos en espera de autorizacion: %s de %s",
                counter,
                total,
            )
            counter += 1
            document = xml_data.get_current_document()
            if not document:
                continue
            response = xml_data._send_xml_data_to_valid(receipt_client, auth_client)
            (
                ok,
                messages,
                raise_error,
                previous_authorized,
            ) = xml_data._process_response_check(response)
            # si recibio la solicitud, enviar a autorizar
            if ok:
                response = xml_data._send_xml_data_to_autorice(auth_client)
                ok, messages = xml_data._process_response_autorization(response)
            xml_data._create_messaje_response(messages, ok, raise_error)
            # TODO: si no se puede autorizar, que se debe hacer??
            # por ahora, no hago nada para que la tarea siga intentando en una nueva llamada
            if not ok and messages:
                xml_to_notify |= xml_data
        return True

    @api.model
    def _prepare_domain_for_send_mail(self, company, date_from):
        domain = [
            ("company_id", "=", company.id),
            ("state", "=", "authorized"),
            ("partner_id.l10n_ec_type_sri", "!=", "Consumidor"),
            ("send_mail", "=", False),
            ("l10n_ec_authorization_date", ">=", date_from),
        ]
        if not company.l10n_ec_send_mail_invoice:
            domain.append(("invoice_out_id", "=", False))
        if not company.l10n_ec_send_mail_credit_note:
            domain.append(("credit_note_out_id", "=", False))
        if not company.l10n_ec_send_mail_debit_note:
            domain.append(("debit_note_out_id", "=", False))
        if not company.l10n_ec_send_mail_liquidation:
            domain.append(("liquidation_id", "=", False))
        if not company.l10n_ec_send_mail_retention:
            domain.append(("withhold_id", "=", False))
        return domain

    @api.model
    def send_mail_to_partner(self):
        all_companies = self.env["res.company"].search([])
        # pasar flag: l10n_ec_xml_call_from_cron para que los errores salgan x log y no por excepcion
        for company in all_companies:
            self.with_context(
                allowed_company_ids=company.ids,
                l10n_ec_xml_call_from_cron=True,
            )._send_mail_to_partner()
        return True

    @api.model
    def _send_mail_to_partner(self):
        company = self.env.company
        if company.l10n_ec_type_environment != "production":
            _logger.info(
                "Envio de correos electronicos solo en ambiente de produccion, por favor verifique su configuracion"
            )
            return
        date_from = company.l10n_ec_send_mail_from
        if not date_from:
            date_from = fields.Datetime.now()
        domain = self._prepare_domain_for_send_mail(company, date_from)
        xml_to_send = self.search(domain, limit=company.l10n_ec_cron_process)
        if xml_to_send:
            documents_send = xml_to_send._action_send_mail_partner()
            if documents_send:
                documents_send.write({"send_mail": True})
                # enviar a crear usuario de los que aun no tienen
                documents_send.create_login_for_partner()
        return True

    def create_login_for_partner(self):
        portal_model = self.env["portal.wizard"]
        if not self.env.company.l10n_ec_create_login_for_partners:
            return False
        partners = self.mapped("partner_id").filtered(lambda x: not x.user_ids and x.l10n_ec_type_sri != "Consumidor")
        if partners:
            ctx = self.env.context.copy()
            ctx["active_model"] = "res.partner"
            ctx["active_ids"] = partners.ids
            ctx["active_id"] = partners[0].id
            user_changes = []
            for partner in partners.sudo():
                user_changes.append(
                    (
                        0,
                        0,
                        {
                            "partner_id": partner.id,
                            "email": partner.email,
                            "in_portal": True,
                        },
                    )
                )
            wizard = portal_model.with_context(ctx).create({"user_ids": user_changes})
            try:
                wizard.action_apply()
            except Exception as e:
                _logger.info(tools.ustr(e))
        return True

    def generate_file_name(self):
        """
        Genera el nombre del archivo
        @return: str, el nombre del archivo
        """
        # la estructura para el nombre seria asi
        # id del sri_xml_data
        # id del documento
        # prefijo de documento(fc->facturas, nc->Notas de credito, nd->Notas de debito, re->Retenciones, gr->Guias de remision)
        # numero del documento
        # extension xml
        # 123_456_fc_001-001-0123456789.xml
        if self.xml_filename:
            file_name = self.xml_filename
        else:
            document = self.get_current_document()
            file_name = f"{self.id}_{document.l10n_ec_get_document_filename_xml()}.xml"
        return file_name

    def get_file(self):
        """Permite obtener un archivo desde el sistema de archivo
        @return: El archivo xml en str
        """
        file_data = base64.decodebytes(self.xml_file).decode()
        return file_data

    def write_file(self, file_content):
        """Permite crear un archivo firmado o autorizado
        @param file_content: el contenido del archivo, en str
        @return: el nombre del archivo generado
        """
        # obtener el nombre del archivo
        file_name = self.generate_file_name()
        self.write(
            {
                "xml_file": base64.encodebytes(file_content.encode()),
                "xml_filename": file_name,
            }
        )
        return file_name

    def action_cancel(self):
        for xml_data in self:
            if xml_data.state == "authorized" and not xml_data.authorization_to_cancel:
                raise UserError(_("You can't cancel document: %s is authorized on SRI") % (xml_data.display_name,))
        self.write(
            {
                "cancel_date": time.strftime(DTF),
                "cancel_user_id": self.env.uid,
                "state": "cancel",
            }
        )
        return True

    def unlink(self):
        for xml_data in self:
            # si el documento no esta en borrador no permitir eliminar
            if xml_data.state != "draft":
                # si esta cancelado, pero no tengo numero de autorizacion para cancelar, permitir eliminar
                if xml_data.state == "cancel" and not xml_data.authorization_to_cancel:
                    continue
                raise UserError(_("No puede eliminar registros a menos que esten en estado borrador"))
        res = super(SriXmlData, self).unlink()
        return res

    @api.model
    def _search(
        self,
        args,
        offset=0,
        limit=None,
        order=None,
        count=False,
        access_rights_uid=None,
    ):
        new_domain = []
        for domain in args:
            if len(domain) == 3:
                # reemplazar ilike o like por el operador =
                # mejora el rendimiento en busquedas
                if (
                    domain[0] in self.fields_size
                    and len(domain[2]) == self.fields_size[domain[0]]
                    and domain[1] in ("like", "ilike")
                ):
                    new_domain.append((domain[0], "=", domain[2]))
                    continue
                else:
                    new_domain.append(domain)
            else:
                new_domain.append(domain)
        res = super(SriXmlData, self)._search(
            new_domain,
            offset=offset,
            limit=limit,
            order=order,
            count=count,
            access_rights_uid=access_rights_uid,
        )
        return res

    def get_l10n_ec_electronic_logo_image(self):
        self.ensure_one()
        if self.agency_id.l10n_ec_electronic_logo:
            return self.agency_id.l10n_ec_electronic_logo
        if self.company_id.l10n_ec_electronic_logo:
            return self.company_id.l10n_ec_electronic_logo
        if self.company_id.logo:
            return self.company_id.logo
        return False

    def action_desactive_notification_documents_no_autorization(self):
        return self.write(
            {
                "notification_active": False,
            }
        )

    def action_active_notification_documents_no_autorization(self):
        return self.write(
            {
                "notification_active": True,
            }
        )

    def get_mail_url(self):
        return self.get_current_document()._get_share_url(redirect=True)


class SriXmlDataMessageLine(models.Model):
    _name = "sri.xml.data.message.line"
    _description = "Mensajes S.R.I."
    _rec_name = "message"

    xml_id = fields.Many2one("sri.xml.data", "XML Data", index=True, auto_join=True, ondelete="cascade")
    message_code_id = fields.Many2one("sri.error.code", "Código de Mensaje", index=True, auto_join=True)
    message_type = fields.Char("Tipo", size=64)
    other_info = fields.Text(string="Información Adicional")
    message = fields.Text(string="Mensaje")
    create_date = fields.Datetime("Fecha de Creación", readonly=True)
    write_date = fields.Datetime("Ultima actualización", readonly=True)


class SriXmlDataSendTry(models.Model):
    _name = "sri.xml.data.send.try"
    _description = "Intentos de envio a SRI"

    xml_id = fields.Many2one("sri.xml.data", "XML Data", index=True, auto_join=True, ondelete="cascade")
    send_date = fields.Datetime("Send Date")
    response_date = fields.Datetime("Response Date")
    type_send = fields.Selection(
        [
            ("send", "Enviado a Autorizar"),
            ("check", "Verificar Clave de Acceso"),
        ],
        string="Tipo",
        index=True,
        readonly=True,
        default="send",
    )
