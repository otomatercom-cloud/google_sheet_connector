# -*- coding: utf-8 -*-
{
    'name': 'Google Sheet Connector',
    'version': '19.0.2.1.0',
    'category': 'Tools',
    'summary': 'Connect multiple Google Sheets to any Odoo model with field mapping',
    'description': """
Google Sheet Connector for Odoo 19
====================================
- Connect multiple Google Sheets to any Odoo model
- Google OAuth2 login (Login with Google)
- Public sheet CSV export (no credentials needed)
- API Key and Service Account support
- Configure Sheet Name, Worksheet (tab), and field mappings
- Manual sync or scheduled automatic import
- Sync logs for tracking import history
    """,
    'author': 'Custom',
    'depends': ['base', 'crm', 'contacts', 'mail', 'web'],
    'data': [
        'security/ir.model.access.csv',
        'controllers/cron_data.xml',
        'views/oauth_settings_views.xml',
        'views/sheet_connection_views.xml',
        'views/sheet_field_mapping_views.xml',
        'views/sync_log_views.xml',
        'views/menu_views.xml',
        'wizard/sync_wizard_views.xml',
    ],
    'installable': True,
    'application': True,
    'license': 'LGPL-3',
}
