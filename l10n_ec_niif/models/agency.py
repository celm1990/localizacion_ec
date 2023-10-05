import logging

from odoo import api, fields, models
from odoo.exceptions import UserError, ValidationError
from odoo.tools.translate import _

from ..models import modules_mapping

_logger = logging.getLogger(__name__)


class L10nEcAgency(models.Model):

    _name = "l10n_ec.agency"
    _description = "Agencia"

    name = fields.Char("Agency Name", required=True, readonly=False, index=True)
    count_invoice = fields.Integer(string="Count Invoice", compute="_compute_count_invoice")
    number = fields.Char(string="S.R.I. Number", size=3, required=True, readonly=False, index=True)
    printer_point_ids = fields.One2many(
        "l10n_ec.point.of.emission",
        "agency_id",
        "Points of Emission",
        context={"active_test": False},
    )
    user_ids = fields.Many2many("res.users", string="Allowed Users", help="", domain=[("share", "=", False)])
    address_id = fields.Many2one(
        "res.partner",
        "Address",
        required=False,
        help="",
    )
    company_id = fields.Many2one(
        "res.company",
        "Company",
        required=False,
        help="",
        default=lambda self: self.env.company,
    )
    partner_id = fields.Many2one("res.partner", string="Company's Partner", related="company_id.partner_id")
    active = fields.Boolean(string="Active?", default=True)

    def _compute_count_invoice(self):
        count = self.env["account.move"]
        search = count.search_count([("l10n_ec_agency_id", "in", [a.id for a in self])])
        self.count_invoice = search

    def unlink(self):
        # Check agency is empty
        for agency in self.with_context(active_test=False):
            if agency.count_invoice > 0:
                raise UserError(
                    _("You cannot delete an agency that contains an invoice. You can only archive the agency.")
                )
        # Delete the empty agency
        result = super(L10nEcAgency, self).unlink()
        return result

    @api.constrains("number")
    def _check_number(self):
        for agency in self:
            if agency.number:
                try:
                    number_int = int(agency.number)
                    if number_int < 1 or number_int > 999:
                        raise ValidationError(_("Number of agency must be between 1 and 999"))
                except ValueError as e:
                    _logger.debug("Error parsing agency number %s" % str(e))
                    raise ValidationError(_("Number of agency must be only numbers"))

    def write(self, values):
        if "active" in values:
            # Debo desactivar todos los puntos de misión o activales cuando se activa a desactiva la agencia
            self.mapped("printer_point_ids").write({"active": values.get("active")})
        return super(L10nEcAgency, self).write(values)

    _sql_constraints = [
        (
            "number_uniq",
            "unique (number, company_id)",
            _("Number of Agency must be unique by company!"),
        ),
    ]


L10nEcAgency()


class L10EcPointOfEmission(models.Model):

    _name = "l10n_ec.point.of.emission"
    _rec_name = "complete_name"

    name = fields.Char("Point of emission's name", required=True, readonly=False, index=True)
    complete_name = fields.Char(string="Complete Name", compute="_compute_complete_name", store=True)
    agency_id = fields.Many2one("l10n_ec.agency", "Agency", required=False, index=True, auto_join=True)
    company_id = fields.Many2one(comodel_name="res.company", string="Company", related="agency_id.company_id")
    number = fields.Char("S.R.I. Number", size=3, required=True, readonly=False, index=True)
    active = fields.Boolean(string="Active?", default=True)
    count_invoice = fields.Integer(string="Count Invoice", related="agency_id.count_invoice")
    type_emission = fields.Selection(
        string="Type Emission",
        selection=[
            ("electronic", "Electronic"),
            ("pre_printed", "Pre Printed"),
            ("auto_printer", "Auto Printer"),
        ],
        required=True,
        default="electronic",
    )
    sequence_ids = fields.One2many(
        comodel_name="l10n_ec.point.of.emission.document.sequence",
        inverse_name="printer_id",
        string="Initial Sequences",
        required=False,
    )

    @api.depends("name", "number", "agency_id", "agency_id.number")
    def _compute_complete_name(self):
        for printer_point in self:
            complete_name = (
                f"{printer_point.agency_id.number or ''}-{printer_point.number or ''} {printer_point.name or ''}"
            )
            printer_point.complete_name = complete_name

    @api.model
    def default_get(self, fields):
        values = super(L10EcPointOfEmission, self).default_get(fields)
        values["sequence_ids"] = [
            (0, 0, {"document_type": "out_invoice", "initial_sequence": 1}),
            (0, 0, {"document_type": "withhold_purchase", "initial_sequence": 1}),
            (0, 0, {"document_type": "liquidation", "initial_sequence": 1}),
            (0, 0, {"document_type": "out_refund", "initial_sequence": 1}),
            (0, 0, {"document_type": "debit_note_out", "initial_sequence": 1}),
            (0, 0, {"document_type": "delivery_note", "initial_sequence": 1}),
        ]
        return values

    @api.model
    def _l10n_ec_get_extra_domain_user(self):
        domain = []
        if (
            not self.env.is_admin()
            and self.env.company.country_id.code == "EC"
            and self.env.context.get("filter_point_emission")
        ):
            user_data = self.env.user.get_default_point_of_emission()
            domain.append(
                (
                    "id",
                    "in",
                    user_data["all_printer_ids"].ids,
                )
            )
        return domain

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
        args.extend(self._l10n_ec_get_extra_domain_user())
        res = super(L10EcPointOfEmission, self)._search(args, offset, limit, order, count, access_rights_uid)
        return res

    _sql_constraints = [
        (
            "number_uniq",
            "unique (number, agency_id)",
            _("The number of point of emission must be unique by Agency!"),
        ),
    ]

    @api.model
    def fill_padding(self, number, padding):
        return str(number).rjust(padding, "0")

    def create_number(self, number):
        self.ensure_one()
        return f"{self.agency_id.number}-{self.number}-{self.fill_padding(number, 9)}"

    def complete_number(self, number):
        self.ensure_one()
        document_format = number
        if number:
            aux = number.split("-")
            seq = ""
            try:
                if len(aux) == 3:
                    seq = int(aux[2])
                elif len(aux) == 1:
                    seq = int(number)
                document_format = self.create_number(seq)
            except Exception as e:
                _logger.debug("Error function complete_number %s" % str(e))
        return document_format

    def _get_first_number_electronic(self, invoice_type):
        self.ensure_one()
        first_number_electronic = False
        for doc in self.sequence_ids:
            if doc.document_type == invoice_type:
                first_number_electronic = doc.initial_sequence or False
                break
        return first_number_electronic

    def get_authorization_for_number(self, invoice_type, document_number, emission_date=None, company=None):
        """
        Search a authorization for document type and document_number requested
        :param invoice_type: Options available are:
                out_invoice, in_invoice, out_refund, in_refund, debit_note_in, debit_note_out
                liquidation, invoice_reembolso, withhold_sale, withhold_purchase, delivery_note
        :param document_number: Number to find authorization
        :param emission_date, Optional: Date emission of document
        :param company, Optional: Company for current document
        :return: browse_record(l10n_ec.sri.authorization.line)
        """
        self.ensure_one()
        auth_line_model = self.env["l10n_ec.sri.authorization.line"]
        xml_model = self.env["sri.xml.data"]
        if company is None:
            company = self.env.company
        if not emission_date:
            emission_date = fields.Date.context_today(self)
        document_type = modules_mapping.get_document_type(invoice_type)
        model_description = modules_mapping.get_document_name(document_type)
        doc_find = auth_line_model.browse()
        number = False
        is_number_valid = True
        try:
            number_shop, number_printer, number = document_number.split("-")
            number = int(number)
            if self.agency_id.number != number_shop:
                is_number_valid = False
            if self.number != number_printer:
                is_number_valid = False
        except Exception as e:
            _logger.debug("Error parsing number of document: %s" % str(e))
            is_number_valid = False
        if is_number_valid and number:
            doc_find = auth_line_model.search(
                [
                    ("document_type", "=", document_type),
                    ("point_of_emission_id", "=", self.id),
                    ("first_sequence", "<=", number),
                    ("last_sequence", ">=", number),
                    ("authorization_id.company_id", "=", company.id),
                    ("authorization_id.start_date", "<=", emission_date),
                    ("authorization_id.expiration_date", ">=", emission_date),
                ],
                order="first_sequence",
                limit=1,
            )
        # mostrar excepcion si el punto de emision es electronico
        # pero para el tipo de documento no se esta en produccion aun(ambiente pruebas)
        force_preprint = False
        if self.type_emission == "electronic" and not xml_model.l10n_ec_is_environment_production(invoice_type, self):
            force_preprint = True
        if self.type_emission in ("pre_printed", "auto_printer") or force_preprint:
            if not doc_find:
                raise UserError(
                    _(
                        "It is not possible to find authorization for the document type %s "
                        "at the point of emission %s for the agency %s with date %s on company: %s"
                    )
                    % (
                        model_description,
                        self.number,
                        self.agency_id.number,
                        emission_date,
                        company.name,
                    )
                )
        return doc_find

    def get_next_value_sequence(self, invoice_type, date, raise_exception=False):
        """
        Search and return next number available for document type requested
        :param invoice_type: Options available are:
                out_invoice, in_invoice, out_refund, in_refund, debit_note_in, debit_note_out
                liquidation, invoice_reembolso, withhold_sale, withhold_purchase, delivery_note
        :param date: Date emission of document
        :param raise_exception: If True, and not documents are find raise exception
        :return: tuple(str, browse_record(l10n_ec.sri.authorization.line))
        """
        self.ensure_one()
        auth_line_model = self.env["l10n_ec.sri.authorization.line"]
        xml_model = self.env["sri.xml.data"]
        if not date:
            date = fields.Date.context_today(self)
        document_type = modules_mapping.get_document_type(invoice_type)
        model_name = modules_mapping.get_model_name(document_type)
        field_name = modules_mapping.get_field_name(document_type)
        model_description = modules_mapping.get_document_name(document_type)
        res_model = self.env[model_name]
        doc_recs = auth_line_model.search(
            [
                ("document_type", "=", document_type),
                ("point_of_emission_id", "=", self.id),
                ("authorization_id.start_date", "<=", date),
                ("authorization_id.expiration_date", ">=", date),
            ],
            order="first_sequence",
        )
        start_doc_number = "{}-{}-{}".format(self.agency_id.number, self.number, "%")
        domain = modules_mapping.get_domain(invoice_type, include_state=False) + [
            (field_name, "like", start_doc_number)
        ]
        if self.env.context.get("doc_ids", []):
            domain += [("id", "not in", self.env.context.get("doc_ids", []))]
        recs_finded = res_model.search(domain, order=field_name + " DESC", limit=1)
        doc_finded = auth_line_model.browse()
        next_seq = False
        seq = False
        if recs_finded:
            next_seq = recs_finded[0][field_name]
        try:
            if next_seq:
                seq = int(next_seq.split("-")[2])
            if self.env.context.get("numbers_skip", []):
                seq = int(sorted(self.env.context.get("numbers_skip", []))[-1].split("-")[2])
        except Exception as e:
            _logger.debug("Error parsing number: %s" % str(e))
            seq = False
        if doc_recs:
            for doc in doc_recs:
                if date >= doc.authorization_id.start_date:
                    if seq and doc.first_sequence <= seq < doc.last_sequence:
                        next_seq = doc.point_of_emission_id.create_number(seq + 1)
                        doc_finded = doc
                        break
                    elif seq and seq == doc.last_sequence:
                        next_seq = "{}-{}-".format(self.agency_id.number, self.number)
                        doc_finded = doc
                        break
                    elif not seq:
                        next_seq = doc.point_of_emission_id.create_number(doc.first_sequence)
                        doc_finded = doc
                        break
            if not doc_finded and recs_finded:
                try:
                    seq = int(next_seq.split("-")[2])
                except Exception as e:
                    _logger.debug("Error parsing number: %s" % str(e))
                    seq = False
                if seq:
                    for doc in doc_recs:
                        if doc.first_sequence > seq and date >= doc.authorization_id.start_date:
                            next_seq = doc.point_of_emission_id.create_number(doc.first_sequence)
                            doc_finded = doc
                            break
                    if not doc_finded:
                        next_seq = ""
                else:
                    next_seq = ""
        else:
            next_seq = ""
        # mostrar excepcion si el punto de emision es electronico
        # pero para el tipo de documento no se esta en produccion aun(ambiente pruebas)
        force_preprint = False
        if self.type_emission == "electronic" and not xml_model.l10n_ec_is_environment_production(invoice_type, self):
            force_preprint = True
            raise_exception = True
        if self.type_emission in ("pre_printed", "auto_printer") or force_preprint:
            if not doc_finded and raise_exception:
                raise UserError(
                    _(
                        "It is not possible to find authorization for the document type %s "
                        "at the point of issue %s for the agency %s with date %s"
                    )
                    % (model_description, self.number, self.agency_id.number, date)
                )
            return next_seq, doc_finded
        elif self.type_emission == "electronic":
            xml_model = self.env["sri.xml.data"]
            first_number_electronic = self.env.context.get("first_number_electronic", "")
            # tomar el primer numero para facturacion electronica si esta en produccion
            if not first_number_electronic and self and xml_model.l10n_ec_is_environment_production(invoice_type, self):
                first_number_electronic = self._get_first_number_electronic(invoice_type)
            # si tengo un secuencial y es menor al configurado como el inicio de facturacion electronica
            # devolver el numero configurado
            # cuando el secuencial obtenido sea mayor, devolver ese secuencial
            if next_seq and first_number_electronic:
                if "-" in next_seq:
                    # obtener el secuencial solamente
                    if len(next_seq.split("-")[-1]) == 0:
                        next_seq = "{}-{}".format(next_seq, first_number_electronic)
                    next_seq_temp = next_seq.split("-")[-1]
                    # validar que sean numeros
                    try:
                        next_seq_temp = int(next_seq_temp)
                        first_number_electronic = int(first_number_electronic)
                    except Exception:
                        next_seq_temp = False
                        first_number_electronic = False
                    # si es menor al configurado, devolver el primer secuencial
                    # y hacer como que no se encontro secuencial, para que se empiece a generar a partir del secuencial configurado
                    if next_seq_temp and first_number_electronic:
                        if next_seq_temp <= first_number_electronic:
                            next_seq = False
            # si no encontro documento, y estoy en produccion
            # tomar el ultimo numero generado y sumarle 1
            if not next_seq and first_number_electronic and self:
                try:
                    first_number_electronic = int(first_number_electronic)
                except Exception:
                    return False, False
                next_seq = self.create_number(first_number_electronic)
                # todos los documentos de account.move se guardan en la misma tabla y con el mismo nombre de campo
                # obtener el domain segun el tipo de documento
                domain = modules_mapping.get_domain(invoice_type, include_state=False)
                if self.env.context.get("doc_ids", []):
                    domain += [("id", "not in", self.env.context.get("doc_ids", []))]
                start_doc_number = "{}-{}-{}".format(self.agency_id.number, self.number, "%")
                domain.append((field_name, "ilike", start_doc_number))
                domain.append(("company_id", "=", self.company_id.id))
                recs = res_model.with_context(skip_picking_type_filter=True).search(
                    domain, order=field_name + " DESC", limit=1
                )
                if recs:
                    try:
                        last_number = int(recs[0][field_name].split("-")[2])
                    except Exception:
                        last_number = 0
                    if last_number >= first_number_electronic:
                        next_seq = self.create_number(last_number + 1)
            return next_seq, doc_finded


class L10EcPointOfEmissionDocumentSequence(models.Model):

    _name = "l10n_ec.point.of.emission.document.sequence"

    printer_id = fields.Many2one(
        comodel_name="l10n_ec.point.of.emission",
        string="Printer",
        required=True,
    )
    initial_sequence = fields.Integer(string="Initial Sequence", required=True, default=1)
    document_type = fields.Selection(
        string="Document Type",
        selection=[
            ("out_invoice", _("Invoice")),
            ("withhold_purchase", _("Withhold")),
            ("liquidation", _("Liquidation of Purchases")),
            ("out_refund", _("Credit Note")),
            ("debit_note_out", _("Debit Note")),
            ("delivery_note", _("Delivery Note")),
        ],
        required=True,
    )
