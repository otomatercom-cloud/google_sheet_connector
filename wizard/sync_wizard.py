# -*- coding: utf-8 -*-
from odoo import models, fields, api, _
from odoo.exceptions import UserError


class GoogleSheetSyncWizard(models.TransientModel):
    _name = 'google.sheet.sync.wizard'
    _description = 'Sync Google Sheet Wizard'

    connection_id = fields.Many2one(
        'google.sheet.connection',
        string='Connection',
        required=True,
        domain=[('state', '=', 'confirmed')]
    )
    incremental = fields.Boolean(
        string='Incremental Sync',
        default=False,
        help='If checked, only rows after the last synced row will be imported.'
    )
    reset_last_row = fields.Boolean(
        string='Reset & Import All Rows',
        default=True,
        help='Uncheck to continue from where the last sync stopped.'
    )

    result_message = fields.Text(string='Result', readonly=True)
    state = fields.Selection([('draft', 'Draft'), ('done', 'Done')], default='draft')

    def action_sync(self):
        self.ensure_one()
        conn = self.connection_id
        if self.reset_last_row:
            conn.last_sync_row = 0

        log = conn.do_sync(incremental=not self.reset_last_row)
        self.result_message = log.message
        self.state = 'done'

        return {
            'type': 'ir.actions.act_window',
            'res_model': self._name,
            'res_id': self.id,
            'view_mode': 'form',
            'target': 'new',
        }
