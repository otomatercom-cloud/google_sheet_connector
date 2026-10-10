# -*- coding: utf-8 -*-
import logging
from odoo import models, fields, api, _
from odoo.exceptions import UserError

_logger = logging.getLogger(__name__)


class GoogleSheetFieldMapping(models.Model):
    _name = 'google.sheet.field.mapping'
    _description = 'Google Sheet Field Mapping'
    _order = 'sequence, id'

    connection_id = fields.Many2one(
        'google.sheet.connection',
        string='Connection',
        required=True,
        ondelete='cascade'
    )
    sequence = fields.Integer(default=10)

    # ── Sheet Side ────────────────────────────────────────────────────────────
    sheet_column_header = fields.Char(
        string='Sheet Column Header',
        help='The column header as it appears in the Google Sheet (for reference)'
    )
    sheet_column_letter = fields.Char(
        string='Column Letter',
        required=True,
        help='Column letter in the spreadsheet (A, B, C, ... AA, AB, ...)',
        size=5
    )

    # ── Odoo Side ─────────────────────────────────────────────────────────────
    odoo_field_id = fields.Many2one(
        'ir.model.fields',
        string='Odoo Field',
        ondelete='set null',
        # Odoo 19: domain using 'parent.' is supported; ttype exclusion unchanged
        domain="[('model_id', '=', parent.target_model_id), ('ttype', 'not in', ['one2many', 'many2many'])]",
        help='The Odoo field this column maps to'
    )
    # Computed char to avoid type mismatch with ir.model.fields.ttype (Selection)
    odoo_field_type = fields.Char(
        string='Field Type',
        compute='_compute_odoo_field_type',
        store=True,
        readonly=True
    )

    # ── Transformation ────────────────────────────────────────────────────────
    default_value = fields.Char(
        string='Default Value',
        help='If the sheet cell is empty, use this default value'
    )
    value_transform = fields.Selection([
        ('none', 'No Transform'),
        ('upper', 'UPPERCASE'),
        ('lower', 'lowercase'),
        ('title', 'Title Case'),
        ('strip', 'Strip Whitespace'),
        ('bool_yes_no', 'Yes/No → True/False'),
    ], string='Transform', default='strip')

    # Many2one relation helper
    relation_search_field = fields.Char(
        string='Relation Search By',
        help='For Many2one fields: which field to search on the related model (e.g. "name", "email"). Defaults to "name".',
        default='name'
    )
    m2o_create_if_missing = fields.Boolean(
        string='Create if Not Found',
        default=False,
        help='For Many2one fields: if no matching record is found, automatically create one.\n'
             'Example: if lead source "Google Ads" does not exist, it will be created automatically.'
    )

    notes = fields.Char(string='Notes')

    # ─────────────────────────────────────────────────────────────────────────
    # Computed
    # ─────────────────────────────────────────────────────────────────────────

    @api.depends('odoo_field_id')
    def _compute_odoo_field_type(self):
        for rec in self:
            rec.odoo_field_type = rec.odoo_field_id.ttype or ''

    # ─────────────────────────────────────────────────────────────────────────
    # Value coercion
    # ─────────────────────────────────────────────────────────────────────────

    def _coerce_value(self, raw_value):
        """Convert a raw sheet string value to the correct Python type for the Odoo field."""
        self.ensure_one()

        value = str(raw_value).strip() if raw_value else ''

        if not value:
            value = self.default_value or ''
        if not value:
            return None

        # Apply transforms
        transform = self.value_transform or 'strip'
        if transform == 'upper':
            value = value.upper()
        elif transform == 'lower':
            value = value.lower()
        elif transform == 'title':
            value = value.title()
        elif transform == 'strip':
            value = value.strip()
        elif transform == 'bool_yes_no':
            return value.lower() in ('yes', 'true', '1', 'y')

        if not self.odoo_field_id:
            return value

        ftype = self.odoo_field_id.ttype

        if ftype in ('char', 'text', 'html'):
            return value

        elif ftype == 'integer':
            try:
                return int(float(value))
            except (ValueError, TypeError):
                return 0

        elif ftype == 'float':
            try:
                return float(value)
            except (ValueError, TypeError):
                return 0.0

        elif ftype == 'boolean':
            return value.lower() in ('true', '1', 'yes', 'y')

        elif ftype == 'date':
            from odoo.tools import DEFAULT_SERVER_DATE_FORMAT
            import dateutil.parser
            try:
                return dateutil.parser.parse(value).strftime(DEFAULT_SERVER_DATE_FORMAT)
            except Exception:
                return False

        elif ftype == 'datetime':
            from odoo.tools import DEFAULT_SERVER_DATETIME_FORMAT
            import dateutil.parser
            try:
                return dateutil.parser.parse(value).strftime(DEFAULT_SERVER_DATETIME_FORMAT)
            except Exception:
                return False

        elif ftype == 'many2one':
            related_model = self.odoo_field_id.relation
            search_field = self.relation_search_field or 'name'
            try:
                RelatedModel = self.env[related_model].sudo()
                record = RelatedModel.search(
                    [(search_field, '=ilike', value)], limit=1
                )
                if record:
                    return record.id
                if self.m2o_create_if_missing:
                    new_record = RelatedModel.create({search_field: value})
                    _logger.info(
                        "Google Sheet Connector: created new %s with %s=%r",
                        related_model, search_field, value
                    )
                    return new_record.id
                _logger.warning(
                    "Google Sheet Connector: no %s found where %s=%r — "
                    "field skipped. Enable 'Create if Not Found' or set a Default Value on the mapping.",
                    related_model, search_field, value
                )
                return False
            except Exception as e:
                _logger.error(
                    "Google Sheet Connector: error resolving many2one %s.%s=%r: %s",
                    related_model, search_field, value, str(e)
                )
                return False

        elif ftype == 'selection':
            return value

        return value
