# -*- coding: utf-8 -*-
import logging
import requests

from odoo import http, _
from odoo.http import request

_logger = logging.getLogger(__name__)

GOOGLE_TOKEN_URL = 'https://oauth2.googleapis.com/token'
GOOGLE_USERINFO_URL = 'https://www.googleapis.com/oauth2/v2/userinfo'


class GoogleSheetOAuthController(http.Controller):

    @http.route('/google_sheet_connector/oauth/callback', type='http', auth='user', website=False)
    def oauth_callback(self, code=None, state=None, error=None, **kwargs):
        """Handle the OAuth2 callback from Google."""

        if error:
            return self._redirect_to_connection(
                state,
                error=_("Google OAuth error: %s") % error
            )

        if not code or not state:
            return request.redirect('/odoo/google-sheet-connector')

        try:
            connection_id = int(state)
        except (ValueError, TypeError):
            return request.redirect('/odoo/google-sheet-connector')

        conn = request.env['google.sheet.connection'].browse(connection_id)
        if not conn.exists():
            return request.redirect('/odoo/google-sheet-connector')

        settings = request.env['google.sheet.oauth.settings'].sudo().get_settings()
        redirect_uri = conn._get_oauth_redirect_uri()

        try:
            token_resp = requests.post(GOOGLE_TOKEN_URL, data={
                'code': code,
                'client_id': settings.client_id,
                'client_secret': settings.client_secret,
                'redirect_uri': redirect_uri,
                'grant_type': 'authorization_code',
            }, timeout=30)
            token_resp.raise_for_status()
            token_data = token_resp.json()
        except Exception as e:
            _logger.error("Google OAuth token exchange failed: %s", str(e))
            return self._redirect_to_connection(connection_id, error=str(e))

        try:
            userinfo_resp = requests.get(GOOGLE_USERINFO_URL, headers={
                'Authorization': 'Bearer ' + token_data.get('access_token', '')
            }, timeout=15)
            userinfo = userinfo_resp.json()
            google_email = userinfo.get('email', '')
        except Exception:
            google_email = ''

        conn.sudo().write({
            'oauth_access_token': token_data.get('access_token', ''),
            'oauth_refresh_token': token_data.get('refresh_token', conn.oauth_refresh_token),
            'oauth_token_expiry': self._expiry_datetime(token_data.get('expires_in', 3600)),
            'oauth_google_email': google_email,
            'auth_method': 'oauth',
            'state': 'confirmed',
        })

        return self._redirect_to_connection(connection_id, success=True, email=google_email)

    def _expiry_datetime(self, expires_in):
        from odoo.fields import Datetime
        from datetime import timedelta
        return Datetime.to_string(Datetime.now() + timedelta(seconds=int(expires_in) - 60))

    def _redirect_to_connection(self, connection_id, success=False, email='', error=''):
        # Odoo 19 uses /odoo/ URL scheme instead of /web#
        try:
            cid = int(connection_id)
            return request.redirect(f'/odoo/google-sheet-connector/{cid}')
        except (TypeError, ValueError):
            return request.redirect('/odoo/google-sheet-connector')
