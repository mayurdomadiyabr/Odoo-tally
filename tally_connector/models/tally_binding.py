# -*- coding: utf-8 -*-
# Part of TallyPrime Connector. See LICENSE file for full copyright and licensing details.

import logging
from odoo import api, fields, models, _

_logger = logging.getLogger(__name__)


class TallyBinding(models.AbstractModel):
    """
    Abstract base model for Tally bindings.
    All binding models should inherit from this to get common fields and methods.
    """
    _name = 'tally.binding'
    _description = 'Tally Binding (Abstract)'

    backend_id = fields.Many2one(
        'tally.backend',
        string='Tally Backend',
        required=True,
        ondelete='cascade',
        index=True,
    )
    tally_id = fields.Char(
        string='Tally ID',
        help="Master/GUID identifier in TallyPrime"
    )
    sync_state = fields.Selection([
        ('pending', 'Pending'),
        ('synced', 'Synced'),
        ('error', 'Error'),
    ], string='Sync Status', default='pending', index=True)
    sync_date = fields.Datetime(
        string='Last Sync Date',
        readonly=True,
    )
    sync_error = fields.Text(
        string='Last Sync Error',
        readonly=True,
    )

    def _export_to_tally(self):
        """
        Export this binding to TallyPrime.
        To be implemented by concrete binding models.
        """
        raise NotImplementedError("Subclasses must implement _export_to_tally")

    def _import_from_tally(self, tally_data):
        """
        Import/Update from TallyPrime data.
        To be implemented by concrete binding models.
        """
        raise NotImplementedError("Subclasses must implement _import_from_tally")

    def mark_synced(self, tally_id=None):
        """Mark this binding as successfully synced"""
        vals = {
            'sync_state': 'synced',
            'sync_date': fields.Datetime.now(),
            'sync_error': False,
        }
        if tally_id:
            vals['tally_id'] = tally_id
        self.write(vals)

    def mark_error(self, error_message):
        """Mark this binding as failed with error"""
        self.write({
            'sync_state': 'error',
            'sync_error': error_message,
        })

    def retry_sync(self):
        """Retry syncing this binding"""
        self.ensure_one()
        self.sync_state = 'pending'
        self._export_to_tally()
