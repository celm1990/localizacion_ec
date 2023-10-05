import logging
import re

import requests
from stdnum.ec import ci, ruc

from odoo import SUPERUSER_ID, api, fields, models, tools
from odoo.exceptions import UserError
from odoo.tools.translate import _

_logger = logging.getLogger(__name__)


class ResPartner(models.Model):
    _inherit = "res.partner"

    l10n_is_bank = fields.Boolean(string="Is bank", required=False)

    @api.depends("country_id", "l10n_latam_identification_type_id")
    def _compute_l10n_ec_foreign(self):
        it_pasaporte = self.env.ref("l10n_ec_niif.it_pasaporte", False)
        for partner in self:
            l10n_ec_foreign = False
            if partner.country_id:
                if partner.country_id.code != "EC":
                    l10n_ec_foreign = True
                if (
                    it_pasaporte
                    and partner.country_id.code == "EC"
                    and partner.l10n_latam_identification_type_id.id == it_pasaporte.id
                ):
                    l10n_ec_foreign = True
                else:
                    partner.property_account_receivable_id = (
                        partner.env.company.partner_id.property_account_receivable_id.id
                    )
                    partner.property_account_payable_id = partner.env.company.partner_id.property_account_payable_id.id
            if l10n_ec_foreign:
                partner.set_accounting_account_foreign()
            partner.l10n_ec_foreign = l10n_ec_foreign

    def set_accounting_account_foreign(self):
        self.ensure_one()
        accounting_account_receivable_fireign_id = (
            self.env["ir.config_parameter"].sudo().get_param("l10n_ec_accounting_account_receivable_fireign_id")
        )
        accounting_account_payable_fireign_id = (
            self.env["ir.config_parameter"].sudo().get_param("l10n_ec_accounting_account_payable_fireign_id")
        )
        if accounting_account_receivable_fireign_id:
            self.property_account_receivable_id = int(accounting_account_receivable_fireign_id)
        if accounting_account_payable_fireign_id:
            self.property_account_payable_id = int(accounting_account_payable_fireign_id)

    l10n_ec_foreign = fields.Boolean(
        "Foreign?",
        readonly=True,
        store=True,
        compute="_compute_l10n_ec_foreign",
    )
    l10n_ec_foreign_type = fields.Selection(
        [
            ("01", "Persona Natural"),
            ("02", "Sociedad"),
        ],
        string="Foreign Type",
        readonly=False,
        help="",
    )
    l10n_ec_business_name = fields.Char(
        "Business Name",
        required=False,
        readonly=False,
        help="",
    )
    # Datos para el reporte dinardap
    l10n_ec_sex = fields.Selection(
        [
            ("M", "Masculino"),
            ("F", "Femenino"),
        ],
        string="Sex",
        readonly=False,
        help="",
        required=False,
    )
    l10n_ec_marital_status = fields.Selection(
        [
            ("S", "Soltero(a)"),
            ("C", "Casado(a)"),
            ("D", "Divorciado(a)"),
            ("", "Unión Libre"),
            ("V", "Viudo(o)"),
        ],
        string="Civil Status",
        readonly=False,
        help="",
        required=False,
    )
    l10n_ec_input_origins = fields.Selection(
        [
            ("B", "Empleado Público"),
            ("V", "Empleado Privado"),
            ("I", "Independiente"),
            ("A", "Ama de Casa o Estudiante"),
            ("R", "Rentista"),
            ("H", "Jubilado"),
            ("M", "Remesa del Exterior"),
        ],
        string="Input Origins",
        readonly=False,
        help="",
        required=False,
    )
    l10n_ec_related_part = fields.Boolean(
        "Related Part?",
        readonly=False,
        help="",
    )
    l10n_ec_is_ecuadorian_company = fields.Boolean(
        string="is Ecuadorian Company?", compute="_compute_ecuadorian_company"
    )
    l10n_ec_sri_payment_id = fields.Many2one("l10n_ec.sri.payment.method", "SRI Payment Method")
    vat = fields.Char(tracking=True)

    # campo tecnico para mostrar el campo l10n_ec_force_validate_nif
    # esto se usara solamente cuando el RUC no pase el modulo 11 y el SRI no responda
    # pero si el SRI responde, segun la respuesta se dara por valido o no el RUC, pero no se mostrara el campo l10n_ec_force_validate_nif
    l10n_ec_show_force_validate = fields.Boolean(string="Show force validate?", copy=False, default=False)
    # campo para permitir saltar la validacion de RUC solo bajo la condicion que no pase el modulo 11 y el SRI este caido
    l10n_ec_force_validate_nif = fields.Boolean(string="Force validate nif?", copy=False)

    @api.depends("company_id.country_id")
    def _compute_ecuadorian_company(self):
        for rec in self:
            l10n_ec_is_ecuadorian_company = False
            if rec.company_id and rec.company_id.country_id.code == "EC":
                l10n_ec_is_ecuadorian_company = True
            rec.l10n_ec_is_ecuadorian_company = l10n_ec_is_ecuadorian_company

    def copy_data(self, default=None):
        if not default:
            default = {}
        default.update(
            {
                "vat": False,
            }
        )
        return super(ResPartner, self).copy_data(default)

    # @api.constrains('vat')
    # def _check_duplicity(self):
    #     for rec in self:
    #         if rec.vat:
    #             other_partner = self.search([
    #                 ('vat', '=', rec.vat),
    #                 ('id', '!=', rec.id),
    #                                         ])
    #             if len(other_partner) >= 1:
    #                 raise UserError(_("The number %s must be unique as VAT") % rec.vat)

    def verify_final_consumer(self, vat):
        b = True
        c = 0
        try:
            for n in vat:
                if int(n) != 9:
                    b = False
                c += 1
            if c == 13:
                return b
        except Exception as e:
            _logger.debug("Error parsing final customer value %s" % str(e))
            return False

    def check_vat_ec(self, vat):
        consumidor_final = self.verify_final_consumer(vat)
        if consumidor_final:
            return consumidor_final, "Consumidor"
        elif len(vat) == 10:
            return ci.is_valid(vat), "Cedula"
        elif len(vat) == 13:
            valid = False
            type_doc = ""
            if vat[2] == "6":
                if ci.is_valid(vat[:10]):
                    valid = True
                    type_doc = "Ruc"
                elif ruc.is_valid(vat):
                    valid = True
                    type_doc = "Ruc"
            elif ruc.is_valid(vat):
                valid = True
                type_doc = "Ruc"
            if not valid:
                # cuando no pasa el algoritmo de modulo 11
                # intentar validarlo contra el SRI
                # si es un ruc valido, me devolvera la data del contribuyente
                # caso contrario me devolvera un mensaje
                # pero si no obtengo respuesta posiblemente este caido el SRI<data estara vacio>
                # NOTA: si el usuario activo l10n_ec_force_validate_nif se omitira la validacion
                data = self._get_partner_info_from_sri(vat)
                if data:
                    if data.get("razonSocial") or not data.get("mensaje"):
                        valid = True
                        type_doc = "Ruc"
            return valid, type_doc
        else:
            return False, False

    @api.model
    def _get_partner_info_from_sri(self, vat):
        """
        Consultar informacion del contribuyente segun el numero de RUC
        :return: dict con la data devuelta por el SRI
        """
        try:
            response = requests.get(f"https://srienlinea.sri.gob.ec/movil-servicios/api/v1.0/estadoTributario/{vat}")
            data = response.json()
        except Exception as e:
            data = {}
            _logger.error("Error retrieving data from sri: %s" % tools.ustr(e))
        return data

    @api.constrains("vat", "country_id", "l10n_latam_identification_type_id")
    def check_vat(self):
        it_ruc = self.env.ref("l10n_ec_niif.it_ruc", False)
        it_cedula = self.env.ref("l10n_ec_niif.it_cedula", False)
        if self.sudo().env.ref("base.module_base_vat").state == "installed":
            ecuadorian_partners = self.filtered(lambda partner: partner.country_id == self.env.ref("base.ec"))
            for partner in ecuadorian_partners:
                if partner.vat and it_ruc and it_cedula:
                    if partner.l10n_latam_identification_type_id and partner.l10n_latam_identification_type_id.id in (
                        it_ruc.id,
                        it_cedula.id,
                    ):
                        valid, vat_type = self.check_vat_ec(partner.vat)
                        if not valid and not partner.l10n_ec_force_validate_nif:
                            raise UserError(
                                _(
                                    "VAT %s is not valid for an Ecuadorian company, "
                                    "it must be like this form 17165373411001"
                                )
                                % (partner.vat)
                            )
            return super(ResPartner, self).check_vat()
        else:
            return True

    @api.onchange("vat", "country_id")
    def _onchange_vat(self):
        if self.country_id and self.vat and self.country_id.code == "EC":
            valid, vat_type = self.check_vat_ec(self.vat)
            # habilitar el mostrar check pasa saltar la validacion cuando el RUC no sea valido
            self.l10n_ec_show_force_validate = not valid
            self.l10n_ec_force_validate_nif = False
            if not valid:
                data = self._get_partner_info_from_sri(self.vat)
                # si el SRI me devuelve explicitamente que no es valido, no habilitar check NUNCA
                # cuando el SRI esta caido, data sera vacio y me habilitara el check para saltar la validacion temporalmente
                if data.get("razonSocial"):
                    self.l10n_ec_show_force_validate = False
                elif data.get("mensaje"):
                    self.l10n_ec_show_force_validate = False
                else:
                    self.l10n_ec_show_force_validate = True

    @api.depends("vat", "country_id", "l10n_latam_identification_type_id")
    def _compute_l10n_ec_type_sri(self):
        it_pasaporte = self.env.ref("l10n_ec_niif.it_pasaporte", False)
        for partner in self:
            vat_type = ""
            if partner.country_id:
                if partner.vat and partner.country_id.code == "EC":
                    try:
                        dni, vat_type = self.check_vat_ec(partner.vat)
                    except Exception as e:
                        _logger.debug(_("Error checking vat: %s error:%s") % (partner.vat, str(e)))
                if partner.country_id.code != "EC" or (
                    it_pasaporte
                    and partner.country_id.code == "EC"
                    and partner.l10n_latam_identification_type_id.id == it_pasaporte.id
                ):
                    vat_type = "Pasaporte"
            partner.l10n_ec_type_sri = vat_type

    l10n_ec_type_sri = fields.Char(
        "SRI Identification Type",
        store=True,
        readonly=True,
        compute="_compute_l10n_ec_type_sri",
    )

    @api.model_create_multi
    def create(self, vals):
        ecuador = self.env.ref("base.ec")
        it_ruc = self.env.ref("l10n_ec_niif.it_ruc", False)
        it_cedula = self.env.ref("l10n_ec_niif.it_cedula", False)
        it_pasaporte = self.env.ref("l10n_ec_niif.it_pasaporte", False)
        if (
            self.sudo().env.ref("base.module_base_vat").state == "installed"
            and self.env.company.partner_id.country_id.code == "EC"
        ):
            for val in vals:
                if not val.get("l10n_latam_identification_type_id", False) and val.get("vat"):
                    if val.get("country_id") == ecuador.id:
                        only_numbers = re.match(r"^([\s\d]+)$", val.get("vat"))
                        if only_numbers:
                            if len(val.get("vat")) == 10:
                                val.update(
                                    {
                                        "l10n_latam_identification_type_id": it_cedula.id,
                                    }
                                )
                            elif len(val.get("vat")) == 13:
                                val.update(
                                    {
                                        "l10n_latam_identification_type_id": it_ruc.id,
                                    }
                                )
                            else:
                                val.update(
                                    {
                                        "l10n_latam_identification_type_id": it_pasaporte.id,
                                    }
                                )
                        else:
                            val.update(
                                {
                                    "l10n_latam_identification_type_id": it_pasaporte.id,
                                }
                            )
        return super(ResPartner, self).create(vals)

    def write(self, values):
        for partner in self:
            if (
                partner.vat == "9999999999999"
                and self._uid != SUPERUSER_ID
                and ("name" in values or "vat" in values or "active" in values or "country_id" in values)
            ):
                raise UserError(_("You cannot modify record of final consumer"))
        return super(ResPartner, self).write(values)

    def unlink(self):
        for partner in self:
            if partner.vat == "9999999999999":
                raise UserError(_("You cannot unlink final consumer"))
        return super(ResPartner, self).unlink()

    def _name_search(self, name, args=None, operator="ilike", limit=100, name_get_uid=None):
        args = args or []
        recs = self.browse()
        res = super(ResPartner, self)._name_search(name, args, operator, limit, name_get_uid)
        if not res and name:
            recs = self.search([("vat", operator, name)] + args, limit=limit)
            if not recs:
                recs = self.search([("l10n_ec_business_name", operator, name)] + args, limit=limit)
            if recs:
                res = models.lazy_name_get(self.browse(recs.ids).with_user(name_get_uid)) or []
        return res

    l10n_ec_authorization_ids = fields.One2many(
        "l10n_ec.sri.authorization.supplier",
        "partner_id",
        string="Third Party Authorizations",
    )

    l10n_ec_email_out_invoice = fields.Boolean(
        "As Follower on Invoice",
        readonly=False,
        default=lambda self: not ("default_parent_id" in self.env.context),
    )
    l10n_ec_email_out_refund = fields.Boolean(
        "As Follower on Credit Note",
        readonly=False,
        default=lambda self: not ("default_parent_id" in self.env.context),
    )
    l10n_ec_email_debit_note_out = fields.Boolean(
        "As Follower on Debit Notes",
        readonly=False,
        default=lambda self: not ("default_parent_id" in self.env.context),
    )
    l10n_ec_email_liquidation = fields.Boolean(
        "As Follower on Liquidations",
        readonly=False,
        default=lambda self: not ("default_parent_id" in self.env.context),
    )
    l10n_ec_email_delivery_note = fields.Boolean(
        "As Follower Delivery Note",
        readonly=False,
        default=lambda self: not ("default_parent_id" in self.env.context),
    )
    l10n_ec_email_withhold_purchase = fields.Boolean(
        "As Follower on Withhold",
        readonly=False,
        default=lambda self: not ("default_parent_id" in self.env.context),
    )
    l10n_ec_require_email_electronic = fields.Boolean(
        string="Requerir Correo Electronico",
        store=False,
        compute="_compute_l10n_ec_require_email_electronic",
    )

    @api.depends(
        "l10n_ec_email_out_invoice",
        "l10n_ec_email_out_refund",
        "l10n_ec_email_debit_note_out",
        "l10n_ec_email_liquidation",
        "l10n_ec_email_delivery_note",
        "l10n_ec_email_withhold_purchase",
    )
    def _compute_l10n_ec_require_email_electronic(self):
        for partner in self:
            partner.l10n_ec_require_email_electronic = any(
                [
                    partner.l10n_ec_email_out_invoice,
                    partner.l10n_ec_email_out_refund,
                    partner.l10n_ec_email_debit_note_out,
                    partner.l10n_ec_email_liquidation,
                    partner.l10n_ec_email_delivery_note,
                    partner.l10n_ec_email_withhold_purchase,
                ]
            )

    def get_direccion_matriz(self, printer_point):
        return self.street or printer_point.agency_id.address_id.street or "NA"

    @api.depends(
        "country_id",
        "vat",
    )
    def _compute_sri_status(self):
        for rec in self:
            l10n_ec_sri_status = ""
            if rec.vat:
                data = self._get_partner_info_from_sri(rec.vat)
                if "razonSocial" in data:
                    l10n_ec_sri_status += "<p><strong>Razon Social: </strong><span>%s</span></p>" % data.get(
                        "razonSocial", ""
                    )
                if "descripcion" in data:
                    l10n_ec_sri_status += "<p><strong>Estado Tributario: </strong><span>%s</span></p>" % data.get(
                        "descripcion", ""
                    )
                if "plazoVigenciaDoc" in data:
                    l10n_ec_sri_status += "<p><strong>Plazo de Vigencia: </strong><span>%s</span></p>" % data.get(
                        "plazoVigenciaDoc", ""
                    )
                if "claseContribuyente" in data:
                    l10n_ec_sri_status += "<p><strong>Clase de Contribuyente: </strong><span>%s</span></p>" % data.get(
                        "claseContribuyente", ""
                    )
            rec.l10n_ec_sri_status = l10n_ec_sri_status

    l10n_ec_sri_status = fields.Html(string="SRI Status", readonly=True, compute="_compute_sri_status")

    def l10n_ec_get_sale_identification_partner(self):
        return self._l10n_ec_get_sale_identification_partner(self.l10n_ec_type_sri)

    def _check_l10n_ec_values(self):
        self.ensure_one()
        if not self.country_id or self.country_id.code != "EC":
            return True
        it_ruc = self.env.ref("l10n_ec_niif.it_ruc", False)
        it_cedula = self.env.ref("l10n_ec_niif.it_cedula", False)
        it_pasaporte = self.env.ref("l10n_ec_niif.it_pasaporte", False)
        # validar que la empresa tenga ruc y tipo de documento
        if not self.vat:
            raise UserError(_("Please enter Cedula/RUC to partner: %s") % (self.name,))
        if self.l10n_latam_identification_type_id.id not in (
            it_ruc.id,
            it_cedula.id,
            it_pasaporte.id,
        ):
            raise UserError(
                _("You must set Identification type as RUC, Cedula or Passport for ecuadorian company, on partner %s")
                % (self.name,)
            )

    @api.model
    def _l10n_ec_get_sale_identification_partner(self, l10n_ec_type_sri):
        # codigos son tomados de la ficha tecnica del SRI, tabla 7
        # pasar por defecto consumidor final
        tipoIdentificacion_sale = "07"
        if l10n_ec_type_sri == "Ruc":
            tipoIdentificacion_sale = "04"
        elif l10n_ec_type_sri == "Cedula":
            tipoIdentificacion_sale = "05"
        elif l10n_ec_type_sri == "Pasaporte":
            tipoIdentificacion_sale = "06"
        return tipoIdentificacion_sale

    def l10n_ec_get_purchase_identification_partner(self):
        # codigos son tomados de la ficha tecnica del SRI(para ATS), tabla 2
        if self.l10n_ec_type_sri == "Ruc":
            tipoIdentificacion_purchase = "01"
        elif self.l10n_ec_type_sri == "Cedula":
            tipoIdentificacion_purchase = "02"
        else:
            tipoIdentificacion_purchase = "03"
        return tipoIdentificacion_purchase
