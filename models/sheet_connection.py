# -*- coding: utf-8 -*-
import json
import logging
import re
import requests

from odoo import models, fields, api, _
from odoo.exceptions import UserError, ValidationError

_logger = logging.getLogger(__name__)


class GoogleSheetConnection(models.Model):
    _name = 'google.sheet.connection'
    _description = 'Google Sheet Connection'
    _inherit = ['mail.thread', 'mail.activity.mixin']
    _order = 'name'

    name = fields.Char(
        string='Connection Name',
        required=True,
        tracking=True,
        help='A descriptive name for this connection (e.g. "Lead Import - Marketing Sheet")'
    )
    active = fields.Boolean(default=True, tracking=True)
    state = fields.Selection([
        ('draft', 'Draft'),
        ('confirmed', 'Confirmed'),
        ('error', 'Error'),
    ], default='draft', string='Status', tracking=True)

    # ── Google Sheet Details ──────────────────────────────────────────────────
    sheet_url = fields.Char(
        string='Google Sheet URL',
        required=True,
        tracking=True,
        help='Full URL of the Google Sheet (must be publicly shared or use Service Account)'
    )
    sheet_id = fields.Char(
        string='Sheet ID',
        compute='_compute_sheet_id',
        store=True,
        help='Extracted automatically from the URL'
    )
    worksheet_name = fields.Char(
        string='Worksheet / Tab Name',
        required=True,
        default='Sheet1',
        tracking=True,
        help='Exact name of the tab/worksheet inside the spreadsheet'
    )
    header_row = fields.Integer(
        string='Header Row Number',
        default=1,
        help='Row number containing column headers (usually 1)'
    )
    data_start_row = fields.Integer(
        string='Data Start Row',
        default=2,
        help='Row number where actual data begins (usually 2)'
    )

    # ── Authentication ────────────────────────────────────────────────────────
    auth_method = fields.Selection([
        ('public', 'Public Sheet (No Auth / No API Key needed)'),
        ('oauth', 'Google OAuth2 (Login with Google)'),
        ('api_key', 'Google API Key'),
        ('service_account', 'Service Account (JSON)'),
    ], string='Authentication Method', default='public', required=True, tracking=True,
       help="Public: uses CSV export. OAuth: login with your Google account. API Key / Service Account: for advanced use.")

    google_api_key = fields.Char(
        string='Google API Key',
        groups='base.group_system',
        help='Google Cloud API Key with Sheets API enabled'
    )
    service_account_json = fields.Text(
        string='Service Account JSON',
        groups='base.group_system',
        help='Paste the full JSON content of your Google Service Account key file'
    )

    # ── OAuth2 Fields ─────────────────────────────────────────────────────────
    oauth_access_token = fields.Char(
        string='OAuth Access Token',
        groups='base.group_system',
        copy=False
    )
    oauth_refresh_token = fields.Char(
        string='OAuth Refresh Token',
        groups='base.group_system',
        copy=False
    )
    oauth_token_expiry = fields.Datetime(
        string='Token Expiry',
        readonly=True,
        copy=False
    )
    oauth_google_email = fields.Char(
        string='Connected Google Account',
        readonly=True,
        copy=False
    )
    oauth_authorize_url = fields.Char(
        string='Authorization URL',
        compute='_compute_oauth_authorize_url',
        help='Click to authorize with Google'
    )

    # ── Target Odoo Model ─────────────────────────────────────────────────────
    target_model_id = fields.Many2one(
        'ir.model',
        string='Target Odoo Model',
        tracking=True,
        ondelete='set null',
        domain=[('transient', '=', False)],
        help='The Odoo model where records will be created/updated'
    )
    target_model_name = fields.Char(
        related='target_model_id.model',
        string='Model Technical Name',
        store=True
    )
    duplicate_check_field_id = fields.Many2one(
        'ir.model.fields',
        string='Duplicate Check Field',
        ondelete='set null',
        domain="[('model_id', '=', target_model_id)]",
        help='Field used to detect duplicate records (e.g. email, phone). If found, record will be updated instead of created.'
    )
    on_duplicate = fields.Selection([
        ('skip', 'Skip (do not import)'),
        ('update', 'Update existing record'),
        ('create', 'Always create new'),
    ], string='On Duplicate', default='update')

    # ── Sync Settings ─────────────────────────────────────────────────────────
    auto_sync = fields.Boolean(
        string='Enable Scheduled Sync',
        default=False,
        help='If enabled, this sheet will sync automatically via cron job'
    )
    sync_interval_minutes = fields.Integer(
        string='Every (Minutes)',
        default=0,
        help='Sync every N minutes. Set to 0 to use hours instead. Example: 30 = every 30 minutes.'
    )
    sync_interval_hours = fields.Integer(
        string='Every (Hours)',
        default=1,
        help='Sync every N hours. Used when minutes is 0. Example: 2 = every 2 hours.'
    )
    last_sync_date = fields.Datetime(string='Last Sync', readonly=True)
    last_sync_row = fields.Integer(
        string='Last Synced Row',
        default=0,
        help='Last Google Sheet row processed; used for incremental sync'
    )

    # ── Field Mappings ────────────────────────────────────────────────────────
    field_mapping_ids = fields.One2many(
        'google.sheet.field.mapping',
        'connection_id',
        string='Field Mappings'
    )
    mapping_count = fields.Integer(
        string='Mappings',
        compute='_compute_mapping_count'
    )

    # ── Logs ──────────────────────────────────────────────────────────────────
    sync_log_ids = fields.One2many(
        'google.sheet.sync.log',
        'connection_id',
        string='Sync Logs'
    )
    log_count = fields.Integer(
        string='Logs',
        compute='_compute_log_count'
    )

    # ── Notes ─────────────────────────────────────────────────────────────────
    notes = fields.Text(string='Notes / Description')

    # ─────────────────────────────────────────────────────────────────────────
    # Constraints
    # ─────────────────────────────────────────────────────────────────────────

    @api.constrains('target_model_id')
    def _check_target_model(self):
        for rec in self:
            if not rec.target_model_id:
                raise ValidationError(_("Target Odoo Model is required."))

    # ─────────────────────────────────────────────────────────────────────────
    # Computed fields
    # ─────────────────────────────────────────────────────────────────────────

    @api.depends('sheet_url')
    def _compute_sheet_id(self):
        for rec in self:
            rec.sheet_id = self._extract_sheet_id(rec.sheet_url or '')

    @api.depends('field_mapping_ids')
    def _compute_mapping_count(self):
        for rec in self:
            rec.mapping_count = len(rec.field_mapping_ids)

    @api.depends('sync_log_ids')
    def _compute_log_count(self):
        for rec in self:
            rec.log_count = len(rec.sync_log_ids)

    # ─────────────────────────────────────────────────────────────────────────
    # Helpers
    # ─────────────────────────────────────────────────────────────────────────

    @staticmethod
    def _extract_sheet_id(url):
        """Extract the spreadsheet ID from a Google Sheets URL."""
        match = re.search(r'/spreadsheets/d/([a-zA-Z0-9_-]+)', url)
        return match.group(1) if match else ''

    @api.depends('auth_method')
    def _compute_oauth_authorize_url(self):
        import urllib.parse
        settings = self.env['google.sheet.oauth.settings'].get_settings()
        for rec in self:
            if rec.auth_method == 'oauth' and settings.client_id and rec._origin.id:
                redirect_uri = rec._get_oauth_redirect_uri()
                params = urllib.parse.urlencode({
                    'client_id': settings.client_id,
                    'redirect_uri': redirect_uri,
                    'response_type': 'code',
                    'scope': 'https://www.googleapis.com/auth/spreadsheets.readonly https://www.googleapis.com/auth/userinfo.email',
                    'access_type': 'offline',
                    'prompt': 'consent',
                    'state': str(rec._origin.id),
                })
                rec.oauth_authorize_url = f"https://accounts.google.com/o/oauth2/v2/auth?{params}"
            else:
                rec.oauth_authorize_url = ''

    def _get_oauth_redirect_uri(self):
        self.ensure_one()
        settings = self.env['google.sheet.oauth.settings'].sudo().get_settings()
        return settings.get_redirect_uri()

    def _get_valid_oauth_token(self):
        """Return a valid access token, refreshing if expired."""
        self.ensure_one()
        now = fields.Datetime.now()
        expiry = self.oauth_token_expiry

        if expiry and fields.Datetime.from_string(expiry) > now and self.oauth_access_token:
            return self.oauth_access_token

        if not self.oauth_refresh_token:
            raise UserError(_(
                "OAuth token expired and no refresh token available.\n"
                "Please re-authorize by clicking 'Login with Google'."
            ))

        settings = self.env['google.sheet.oauth.settings'].sudo().get_settings()
        try:
            resp = requests.post('https://oauth2.googleapis.com/token', data={
                'client_id': settings.client_id,
                'client_secret': settings.client_secret,
                'refresh_token': self.oauth_refresh_token,
                'grant_type': 'refresh_token',
            }, timeout=30)
            resp.raise_for_status()
            token_data = resp.json()
            from datetime import timedelta
            new_expiry = fields.Datetime.to_string(
                fields.Datetime.now() + timedelta(seconds=int(token_data.get('expires_in', 3600)) - 60)
            )
            self.sudo().write({
                'oauth_access_token': token_data['access_token'],
                'oauth_token_expiry': new_expiry,
            })
            return token_data['access_token']
        except Exception as e:
            raise UserError(_("Failed to refresh OAuth token: %s\nPlease re-authorize.") % str(e))

    def action_oauth_login(self):
        """Open Google OAuth authorization page."""
        self.ensure_one()
        if not self.oauth_authorize_url:
            settings = self.env['google.sheet.oauth.settings'].get_settings()
            if not settings.client_id or not settings.client_secret:
                raise UserError(_(
                    "Please configure OAuth Client ID and Secret first.\n"
                    "Go to: Google Sheet Connector → OAuth Settings"
                ))
            if not self.id:
                raise UserError(_("Please save the record first before authorizing."))
        return {
            'type': 'ir.actions.act_url',
            'url': self.oauth_authorize_url,
            'target': 'self',
        }

    def action_oauth_disconnect(self):
        """Clear OAuth tokens."""
        self.ensure_one()
        self.sudo().write({
            'oauth_access_token': False,
            'oauth_refresh_token': False,
            'oauth_token_expiry': False,
            'oauth_google_email': False,
            'state': 'draft',
        })

    def _get_headers(self):
        """Return HTTP headers for Google Sheets API calls."""
        self.ensure_one()
        headers = {}
        if self.auth_method == 'oauth':
            token = self._get_valid_oauth_token()
            headers['Authorization'] = f'Bearer {token}'
        elif self.auth_method == 'service_account':
            token = self._get_service_account_token()
            headers['Authorization'] = f'Bearer {token}'
        return headers

    def _get_service_account_token(self):
        """Exchange service account JSON for an access token."""
        try:
            import google.oauth2.service_account as sa
            import google.auth.transport.requests as tr
            info = json.loads(self.service_account_json)
            creds = sa.Credentials.from_service_account_info(
                info,
                scopes=['https://www.googleapis.com/auth/spreadsheets.readonly']
            )
            creds.refresh(tr.Request())
            return creds.token
        except Exception as e:
            raise UserError(_(
                "Service Account authentication failed.\n"
                "Make sure google-auth is installed:\n  pip install google-auth\n\nError: %s"
            ) % str(e))

    def _build_api_url(self, range_notation):
        """Build the Sheets API v4 URL for a given range."""
        self.ensure_one()
        base = 'https://sheets.googleapis.com/v4/spreadsheets'
        url = f"{base}/{self.sheet_id}/values/{range_notation}"
        if self.auth_method == 'api_key':
            url += f"?key={self.google_api_key}"
        return url

    def _fetch_sheet_data(self):
        """Fetch all rows from the configured worksheet."""
        self.ensure_one()
        if not self.sheet_id:
            raise UserError(_("Could not extract Sheet ID from the URL. Please check the URL."))

        if self.auth_method == 'public':
            return self._fetch_via_csv_export()
        else:
            return self._fetch_via_api()

    def _fetch_via_csv_export(self):
        """Use the public CSV export endpoint — no API key required."""
        import csv
        import urllib.parse

        base = 'https://docs.google.com/spreadsheets/d'
        gid = self._extract_gid_from_url(self.sheet_url or '')
        sheet_encoded = urllib.parse.quote(self.worksheet_name)
        urls_to_try = []

        if gid:
            urls_to_try.append(f"{base}/{self.sheet_id}/export?format=csv&gid={gid}")

        urls_to_try.append(
            f"{base}/{self.sheet_id}/gviz/tq?tqx=out:csv&sheet={sheet_encoded}"
        )
        urls_to_try.append(f"{base}/{self.sheet_id}/export?format=csv")

        last_error = None
        for url in urls_to_try:
            try:
                resp = requests.get(url, timeout=30, allow_redirects=True)
                resp.raise_for_status()
                content = resp.content.decode('utf-8-sig')
                reader = csv.reader(content.splitlines())
                rows = [row for row in reader if any(cell.strip() for cell in row)]
                if rows:
                    return rows
            except requests.exceptions.HTTPError as e:
                last_error = e
                continue
            except Exception as e:
                last_error = e
                continue

        raise UserError(_(
            "Could not fetch sheet data via CSV export.\n\n"
            "Make sure the sheet is shared as 'Anyone with the link can view'.\n\n"
            "Last error: %s"
        ) % str(last_error))

    @staticmethod
    def _extract_gid_from_url(url):
        """Extract gid (worksheet tab ID) from a Google Sheets URL if present."""
        match = re.search(r'[#&?]gid=(\d+)', url)
        return match.group(1) if match else None

    def _get_worksheet_gid(self):
        """Legacy method kept for compatibility."""
        return self._extract_gid_from_url(self.sheet_url or '')

    def _fetch_via_api(self):
        """Use Google Sheets API v4 with API key or service account."""
        range_notation = f"'{self.worksheet_name}'"
        url = self._build_api_url(range_notation)
        headers = self._get_headers()

        try:
            resp = requests.get(url, headers=headers, timeout=30)
            resp.raise_for_status()
            data = resp.json()
            return data.get('values', [])
        except requests.exceptions.HTTPError as e:
            raise UserError(_("HTTP Error fetching sheet data: %s\n\nMake sure the sheet is shared properly.") % str(e))
        except requests.exceptions.ConnectionError:
            raise UserError(_("Connection error. Please check your internet connection."))
        except Exception as e:
            raise UserError(_("Error fetching sheet data: %s") % str(e))

    # ─────────────────────────────────────────────────────────────────────────
    # Actions
    # ─────────────────────────────────────────────────────────────────────────

    def action_confirm(self):
        """Test connection and confirm."""
        self.ensure_one()
        try:
            rows = self._fetch_sheet_data()
            if rows:
                self.state = 'confirmed'
                return {
                    'type': 'ir.actions.client',
                    'tag': 'display_notification',
                    'params': {
                        'title': _('Connection Successful'),
                        'message': _('Sheet connected! Found %d rows (including header).') % len(rows),
                        'type': 'success',
                        'sticky': False,
                    }
                }
            else:
                self.state = 'error'
                raise UserError(_("Sheet is empty or could not be read. Check worksheet name and permissions."))
        except UserError:
            self.state = 'error'
            raise

    def action_reset_draft(self):
        self.state = 'draft'

    def action_sync_now(self):
        """Open sync wizard."""
        self.ensure_one()
        return {
            'type': 'ir.actions.act_window',
            'name': _('Sync Google Sheet'),
            'res_model': 'google.sheet.sync.wizard',
            'view_mode': 'form',
            'target': 'new',
            'context': {'default_connection_id': self.id},
        }

    def action_auto_load_headers(self):
        """Fetch header row from the sheet and suggest field mappings."""
        self.ensure_one()
        rows = self._fetch_sheet_data()
        if not rows:
            raise UserError(_("No data found in the sheet."))
        headers = rows[self.header_row - 1] if len(rows) >= self.header_row else []
        if not headers:
            raise UserError(_("Header row is empty."))

        self.field_mapping_ids.unlink()

        for idx, col_name in enumerate(headers):
            col_letter = self._col_index_to_letter(idx)
            self.env['google.sheet.field.mapping'].create({
                'connection_id': self.id,
                'sheet_column_header': col_name,
                'sheet_column_letter': col_letter,
                'sequence': idx + 1,
            })

        return {
            'type': 'ir.actions.client',
            'tag': 'display_notification',
            'params': {
                'title': _('Headers Loaded'),
                'message': _('%d columns loaded. Now map each column to an Odoo field.') % len(headers),
                'type': 'success',
                'sticky': False,
            }
        }

    @staticmethod
    def _col_index_to_letter(index):
        """Convert 0-based column index to spreadsheet letter (0→A, 25→Z, 26→AA)."""
        result = ''
        index += 1
        while index:
            index, rem = divmod(index - 1, 26)
            result = chr(65 + rem) + result
        return result

    def action_open_mappings(self):
        self.ensure_one()
        return {
            'type': 'ir.actions.act_window',
            'name': _('Field Mappings'),
            'res_model': 'google.sheet.field.mapping',
            'view_mode': 'list,form',
            'domain': [('connection_id', '=', self.id)],
            'context': {'default_connection_id': self.id},
        }

    def action_view_logs(self):
        self.ensure_one()
        return {
            'type': 'ir.actions.act_window',
            'name': _('Sync Logs'),
            'res_model': 'google.sheet.sync.log',
            'view_mode': 'list,form',
            'domain': [('connection_id', '=', self.id)],
            'context': {'default_connection_id': self.id},
        }

    # ─────────────────────────────────────────────────────────────────────────
    # Core import logic
    # ─────────────────────────────────────────────────────────────────────────

    def do_sync(self, incremental=False):
        """Main sync method. Called by wizard and cron."""
        self.ensure_one()
        if self.state != 'confirmed':
            raise UserError(_("Please confirm the connection before syncing."))
        if not self.field_mapping_ids:
            raise UserError(_("No field mappings configured. Please add at least one mapping."))

        rows = self._fetch_sheet_data()
        if not rows:
            return self._log_sync(0, 0, 0, 'success', 'Sheet is empty.')

        header_row_data = rows[self.header_row - 1] if len(rows) >= self.header_row else []
        data_rows = rows[self.data_start_row - 1:]

        if incremental and self.last_sync_row > 0:
            already_done = self.last_sync_row - self.data_start_row
            data_rows = data_rows[already_done:]

        TargetModel = self.env[self.target_model_name]
        active_mappings = self.field_mapping_ids.filtered(lambda m: m.odoo_field_id)

        # Build a set of field names that are mapped (so we know what the user configured)
        mapped_field_names = set(active_mappings.mapped('odoo_field_id.name'))

        # Detect required (NOT NULL, no default) fields on the target model that are NOT mapped.
        # We check ir.model.fields: required=True means the ORM enforces it; the DB column is also NOT NULL.
        required_unmapped = []
        for field_obj in self.env['ir.model.fields'].search([
            ('model_id', '=', self.target_model_id.id),
            ('required', '=', True),
            ('ttype', 'not in', ['one2many', 'many2many']),
        ]):
            if field_obj.name not in mapped_field_names:
                # Check if the ORM field has a default — if so, Odoo fills it automatically
                odoo_field = TargetModel._fields.get(field_obj.name)
                has_default = odoo_field and (odoo_field.default is not None)
                if not has_default:
                    required_unmapped.append(field_obj.field_description or field_obj.name)

        created = updated = skipped = 0
        errors = []

        if required_unmapped:
            errors.append(
                "⚠️ Required fields not mapped (will cause errors): "
                + ", ".join(required_unmapped)
                + ". Please add these fields to your Field Mappings and set a Default Value."
            )

        for row_index, row in enumerate(data_rows):
            row_label = f"Row {self.data_start_row + row_index}"
            try:
                with self.env.cr.savepoint():
                    vals = {}
                    row_errors = []
                    for mapping in active_mappings:
                        col_idx = self._letter_to_col_index(mapping.sheet_column_letter)
                        raw_value = row[col_idx] if col_idx < len(row) else ''
                        coerced = mapping._coerce_value(raw_value)
                        field_name = mapping.odoo_field_id.name
                        ftype = mapping.odoo_field_id.ttype
                        field_label = mapping.odoo_field_id.field_description or field_name

                        if coerced is not None and coerced is not False:
                            vals[field_name] = coerced
                        elif coerced is False and ftype == 'many2one':
                            # Many2one lookup failed. Try the mapping's default_value if set.
                            if mapping.default_value:
                                default_coerced = mapping._coerce_value(mapping.default_value)
                                if default_coerced:
                                    vals[field_name] = default_coerced
                                    continue
                            if raw_value:
                                row_errors.append(
                                    f"'{field_label}': value '{raw_value}' not found "
                                    f"(tip: enable 'Create if Not Found' or set a Default Value on the mapping)"
                                )
                            # coerced is False with empty raw_value = empty cell on a Many2one,
                            # fall through — ORM/DB default will apply (or raise if required)
                        # coerced is None = empty cell, omit from vals — ORM default applies

                    if row_errors:
                        errors.append(f"{row_label}: " + "; ".join(row_errors))

                    if not vals:
                        skipped += 1
                        continue

                    # ── Webinar Auto-Logic ────────────────────────────────────
                    # Mirrors the _onchange_webinar_attendance_percentage logic
                    # from custom_leads_19:
                    #   pct > 0  → webinar_attended = True
                    #   pct >= 90 → lead_quality = 'hot'
                    #   pct >= 50 → lead_quality = 'warm'
                    _webinar_pct = None
                    if 'webinar_attendance_percentage' in vals:
                        try:
                            _webinar_pct = float(vals['webinar_attendance_percentage'])
                        except (TypeError, ValueError):
                            _webinar_pct = 0.0
                    if _webinar_pct and _webinar_pct > 0:
                        vals['webinar_attended'] = True
                        if _webinar_pct >= 90:
                            vals['lead_quality'] = 'hot'
                        elif _webinar_pct >= 50:
                            vals['lead_quality'] = 'warm'
                        _logger.info(
                            "Google Sheet Connector: webinar_attendance_percentage=%.1f "
                            "-> webinar_attended=True, lead_quality=%r",
                            _webinar_pct, vals.get('lead_quality'),
                        )
                    # ─────────────────────────────────────────────────────────

                    # Duplicate detection
                    if self.duplicate_check_field_id and self.on_duplicate != 'create':
                        check_field = self.duplicate_check_field_id.name
                        check_val = vals.get(check_field)
                        if check_val:
                            existing = TargetModel.search([(check_field, '=', check_val)], limit=1)
                            if existing:
                                if self.on_duplicate == 'update':
                                    existing.write(vals)
                                    updated += 1
                                else:
                                    skipped += 1
                                continue

                    TargetModel.create(vals)
                    created += 1

            except Exception as e:
                err_msg = str(e)
                # Translate common DB errors into actionable messages
                if 'not-null constraint' in err_msg and 'column "' in err_msg:
                    import re as _re
                    col_match = _re.search(r'column "([^"]+)"', err_msg)
                    col_name = col_match.group(1) if col_match else '?'
                    errors.append(
                        f"{row_label}: Required field '{col_name}' is empty. "
                        f"Add a mapping for this field and set a Default Value, or ensure your sheet always provides a value."
                    )
                else:
                    errors.append(f"{row_label}: {err_msg}")
                skipped += 1

        total_rows = len(data_rows)
        status = 'error' if errors and created == 0 and updated == 0 else ('warning' if errors else 'success')
        message = f"Processed {total_rows} rows: {created} created, {updated} updated, {skipped} skipped."
        if errors:
            message += "\n\nErrors:\n" + "\n".join(errors[:20])

        self.last_sync_date = fields.Datetime.now()
        self.last_sync_row = self.data_start_row + len(data_rows)

        return self._log_sync(created, updated, skipped, status, message)

    def _log_sync(self, created, updated, skipped, status, message):
        log = self.env['google.sheet.sync.log'].create({
            'connection_id': self.id,
            'sync_date': fields.Datetime.now(),
            'records_created': created,
            'records_updated': updated,
            'records_skipped': skipped,
            'status': status,
            'message': message,
        })
        return log

    @staticmethod
    def _letter_to_col_index(letter):
        """Convert column letter(s) to 0-based index (A→0, B→1, AA→26)."""
        result = 0
        for char in letter.upper():
            result = result * 26 + (ord(char) - ord('A') + 1)
        return result - 1

    # ─────────────────────────────────────────────────────────────────────────
    # Scheduled action (cron)
    # ─────────────────────────────────────────────────────────────────────────

    @api.model
    def cron_sync_all(self):
        """Called by the scheduled action to sync all active auto-sync connections.
        Respects each connection's sync_interval_minutes / sync_interval_hours setting.
        """
        from datetime import timedelta
        now = fields.Datetime.now()
        connections = self.search([('active', '=', True), ('auto_sync', '=', True), ('state', '=', 'confirmed')])
        for conn in connections:
            try:
                # Determine interval in minutes
                if conn.sync_interval_minutes and conn.sync_interval_minutes > 0:
                    interval_mins = conn.sync_interval_minutes
                else:
                    interval_mins = max(conn.sync_interval_hours or 1, 1) * 60

                # Skip if not enough time has passed since last sync
                if conn.last_sync_date:
                    elapsed = (now - conn.last_sync_date).total_seconds() / 60
                    if elapsed < interval_mins:
                        _logger.debug(
                            "Google Sheet Connector: skipping '%s' — %.1f min elapsed, interval is %d min",
                            conn.name, elapsed, interval_mins,
                        )
                        continue

                conn.do_sync(incremental=True)
            except Exception as e:
                _logger.error("Google Sheet Connector cron error for '%s': %s", conn.name, str(e))
