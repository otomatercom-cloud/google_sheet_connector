# -*- coding: utf-8 -*-
from odoo import models, fields


class GoogleSheetSyncLog(models.Model):
    _name = 'google.sheet.sync.log'
    _description = 'Google Sheet Sync Log'
    _order = 'sync_date desc'

    connection_id = fields.Many2one(
        'google.sheet.connection',
        string='Connection',
        required=True,
        ondelete='cascade'
    )
    sync_date = fields.Datetime(string='Sync Date', default=fields.Datetime.now)
    records_created = fields.Integer(string='Created')
    records_updated = fields.Integer(string='Updated')
    records_skipped = fields.Integer(string='Skipped')
    status = fields.Selection([
        ('success', 'Success'),
        ('warning', 'Warning'),
        ('error', 'Error'),
    ], string='Status', default='success')
    message = fields.Text(string='Details')
