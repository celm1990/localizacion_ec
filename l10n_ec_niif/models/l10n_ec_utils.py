import base64
import logging

import pytz

from odoo import _, api, models, tools
from odoo.exceptions import UserError

_logger = logging.getLogger(__name__)


class L10necUtils(models.AbstractModel):
    _name = "l10n_ec.utils"
    _description = "Utilities miscellaneous"

    @api.model
    def indent(self, elem, level=0):
        i = "\n" + level * "  "
        if len(elem):
            if not elem.text or not elem.text.strip():
                elem.text = i + "  "
            if not elem.tail or not elem.tail.strip():
                elem.tail = i
            for elem in elem:
                self.indent(elem, level + 1)
            if not elem.tail or not elem.tail.strip():
                elem.tail = i
        else:
            if level and (not elem.tail or not elem.tail.strip()):
                elem.tail = i

    @api.model
    def formato_numero(self, valor, decimales=2):
        if isinstance(valor, (int, float)):
            str_format = "{:." + str(decimales) + "f}"
            return str_format.format(valor)
        else:
            return "0.00"

    @api.model
    def split_document_number(self, document_number, raise_error=False):
        """
        Separa un numero de la forma 001-001-000000001 en cada parte correspondiente a la agencia, punto de emision, secuencial
        @param document_number: str con el numero,
                si el numero no tiene el formato correcto se lanzara una excepcion si asi se pasa en el parametro raise_error
                caso contrario se pasara los valores por defecto 001-001-000000999
        @param raise_error: Opcional, si es True y el numero no tiene el formato adecuado, se lanzara una excepcion
                Si es False, no se lanza excepcion y se devuelven los valores por defecto
        @return: tuple(agencia, punto_emision, secuencial)
        """
        agency, printer_point, sequence_number = "", "", ""
        try:
            number_parts = document_number.split("-")
        except Exception as ex:
            _logger.error(tools.ustr(ex))
            number_parts = []
        if not number_parts or len(number_parts) != 3:
            if raise_error:
                raise UserError(
                    _("The document number is incorrect, must be as 001-00X-000XXXXXX, where X is a number")
                )
            else:
                agency, printer_point, sequence_number = "001", "001", "000000999"
        else:
            agency, printer_point, sequence_number = number_parts
        return agency.rjust(3, "0"), printer_point.rjust(3, "0"), sequence_number

    @api.model
    def get_obligado_contabilidad(self, fiscal_position=None):
        res = "SI"
        if fiscal_position and fiscal_position.l10n_ec_no_account:
            res = "NO"
        return res

    def get_formato_date(self):
        return "%d/%m/%Y"

    def ensure_id(self, recordset):
        # Devolver el ID del registro, hay problemas en los onchange, que no se pasa el id
        # sino un NewID, pero el id de BD se guarda en la variable _origin.id
        # sin embargo en algunos casos la variable _origin no se pasa
        # asi que tratar de tomar el id correctamente
        record_id = recordset.id
        if hasattr(recordset, "_origin") and recordset._origin.id:
            record_id = recordset._origin.id
        if isinstance(record_id, models.NewId):
            record_id = False
        return record_id

    @api.model
    def _clean_str(self, string_to_reeplace, list_characters=None, separator="", skip_character=None):
        """
        Reemplaza caracteres por otros caracteres especificados en la lista
        @param string_to_reeplace:  string a la cual reemplazar caracteres
        @param list_characters:  Lista de tuplas con dos elementos(elemento uno el caracter a reemplazar, elemento dos caracter que reemplazara al elemento uno)
        @return: string con los caracteres reemplazados
        """
        if not skip_character:
            skip_character = []
        if not string_to_reeplace:
            return string_to_reeplace
        else:
            string_to_reeplace = string_to_reeplace.lstrip()
        caracters = [".", ",", "-", "\a", "\b", "\f", "\n", "\r", "\t", "\v"]
        for c in caracters:
            if c not in skip_character:
                string_to_reeplace = string_to_reeplace.replace(c, separator)
        if not list_characters:
            list_characters = [
                ("á", "a"),
                ("à", "a"),
                ("ä", "a"),
                ("â", "a"),
                ("Á", "A"),
                ("À", "A"),
                ("Ä", "A"),
                ("Â", "A"),
                ("é", "e"),
                ("è", "e"),
                ("ë", "e"),
                ("ê", "e"),
                ("É", "E"),
                ("È", "E"),
                ("Ë", "E"),
                ("Ê", "E"),
                ("í", "i"),
                ("ì", "i"),
                ("ï", "i"),
                ("î", "i"),
                ("Í", "I"),
                ("Ì", "I"),
                ("Ï", "I"),
                ("Î", "I"),
                ("ó", "o"),
                ("ò", "o"),
                ("ö", "o"),
                ("ô", "o"),
                ("Ó", "O"),
                ("Ò", "O"),
                ("Ö", "O"),
                ("Ô", "O"),
                ("ú", "u"),
                ("ù", "u"),
                ("ü", "u"),
                ("û", "u"),
                ("Ú", "U"),
                ("Ù", "U"),
                ("Ü", "U"),
                ("Û", "U"),
                ("ñ", "n"),
                ("Ñ", "N"),
                ("/", "-"),
                ("&", "Y"),
                ("º", ""),
                ("´", ""),
            ]
        for character in list_characters:
            string_to_reeplace = string_to_reeplace.replace(character[0], character[1])
        SPACE = " "
        codigo_ascii = False
        # en range el ultimo numero no es inclusivo asi que agregarle uno mas
        # espacio en blanco
        range_ascii = [32]
        range_ascii += [ord(character) for character in skip_character]
        # numeros
        range_ascii += list(range(48, 57 + 1))
        # letras mayusculas
        range_ascii += list(range(65, 90 + 1))
        # letras minusculas
        range_ascii += list(range(97, 122 + 1))
        for c in string_to_reeplace:
            codigo_ascii = False
            try:
                codigo_ascii = ord(c)
            except TypeError:
                codigo_ascii = False
            if codigo_ascii:
                # si no esta dentro del rang ascii reemplazar por un espacio
                if codigo_ascii not in range_ascii:
                    string_to_reeplace = string_to_reeplace.replace(c, SPACE)
            # si no tengo codigo ascii, posiblemente dio error en la conversion
            else:
                string_to_reeplace = string_to_reeplace.replace(c, SPACE)
        return "".join(string_to_reeplace.lstrip().splitlines())

    @api.model
    def read_file(self, file, options=None):
        """
        read file from base64
        :options: data for read file, keys(encoding,separator_line,separator_field)
        :returns: [[str,str,...], [str,str,...],....]
        """
        if options is None:
            options = {}
        lines_read = []
        errors = []
        separator_line = str(options.get("separator_line", "\n"))
        separator_field = str(options.get("field_delimiter", ","))
        encoding = str(options.get("encoding", "utf-8"))
        try:
            lines_file = base64.decodebytes(file).decode(encoding).split(separator_line)
            for row in lines_file:
                line = row.split(separator_field)
                lines_read.append(line)
        except UnicodeDecodeError as er:
            raise UserError(
                _(
                    "Error to read file, please choose encoding, Field delimiter and text delimiter right. \n More info %s"
                    % (tools.ustr(er))
                )
            )
        except Exception as e:
            raise UserError(_("Error to read file. \nMore info %s" % (tools.ustr(e))))
        return lines_read, errors

    @api.model
    def _change_time_zone(self, date, from_zone=None, to_zone=None):
        """
        Cambiar la informacion de zona horaria a la fecha
        En caso de no pasar la zona horaria origen(from_zone), tomar la zona horaria del usuario
        En caso de no pasar la zona horaria destino(to_zone), tomar UTC
        @param date: Object datetime to convert according timezone in format '%Y-%m-%d %H:%M:%S'
        @return: datetime according timezone
        """
        fields_model = self.env["ir.fields.converter"]
        if not from_zone:
            # get timezone from user
            from_zone = fields_model._input_tz()
        # get UTC per Default
        if not to_zone:
            to_zone = pytz.UTC
        # si no hay informacion de zona horaria, establecer la zona horaria
        if not date.tzinfo:
            date = from_zone.localize(date)
        date = date.astimezone(to_zone)
        return date

    @api.model
    def get_selection_item(self, model, field, value=None):
        """
        Obtener el valor de un campo selection
        @param model: str, nombre del modelo
        @param field: str, nombre del campo selection
        @param value: str, optional, valor del campo selection del cual obtener el string
        @return: str, la representacion del campo selection que se muestra al usuario
        """
        try:
            field_val = value
            if field_val:
                return dict(self.env[model].fields_get(allfields=[field])[field]["selection"])[field_val]
            return ""
        except Exception:
            return ""
