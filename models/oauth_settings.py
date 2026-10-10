# -*- coding: utf-8 -*-
from odoo import models, fields, api, _
from odoo.exceptions import UserError


class GoogleSheetOAuthSettings(models.Model):
    """Singleton model for storing Google OAuth2 app credentials."""
    _name = 'google.sheet.oauth.settings'
    _description = 'Google OAuth2 Settings'

    name = fields.Char(default='Google OAuth Settings', readonly=True)
    client_id = fields.Char(
        string='OAuth Client ID',
        help='From Google Cloud Console → APIs & Services → Credentials → OAuth 2.0 Client ID'
    )
    client_secret = fields.Char(
        string='OAuth Client Secret',
        groups='base.group_system',
        help='OAuth Client Secret from Google Cloud Console'
    )
    base_url = fields.Char(
        string='Odoo Base URL',
        help='Your Odoo URL e.g. https://myodoo.com — used to build the redirect URI',
        default=lambda self: self.env['ir.config_parameter'].sudo().get_param('web.base.url', '')
    )

    @api.model
    def get_settings(self):
        settings = self.search([], limit=1)
        if not settings:
            settings = self.create({'name': 'Google OAuth Settings'})
        return settings

    def get_redirect_uri(self):
        self.ensure_one()
        base = (self.base_url or '').rstrip('/')
        return f"{base}/google_sheet_connector/oauth/callback"

    def action_open_settings(self):
        self.ensure_one()
        return {
            'type': 'ir.actions.act_window',
            'name': _('Google OAuth Settings'),
            'res_model': self._name,
            'res_id': self.id,
            'view_mode': 'form',
            'target': 'current',
        }
