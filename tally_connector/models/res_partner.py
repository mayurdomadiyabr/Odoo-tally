# -*- coding: utf-8 -*-
# Part of TallyPrime Connector. See LICENSE file for full copyright and licensing details.

import logging
from odoo import api, fields, models, _

_logger = logging.getLogger(__name__)


class TallyResPartner(models.Model):
    """
    Binding model for res.partner <-> Tally Ledger.
    Each record represents a link between an Odoo partner and a TallyPrime ledger.
    """
    _name = 'tally.res.partner'
    _description = 'Partner Tally Binding'
    _inherit = 'tally.binding'
    _rec_name = 'odoo_id'

    odoo_id = fields.Many2one(
        'res.partner',
        string='Partner',
        required=True,
        ondelete='cascade',
        index=True,
    )
    ledger_name = fields.Char(
        string='Tally Ledger Name',
        help="Name of the ledger in TallyPrime"
    )
    ledger_group = fields.Char(
        string='Ledger Group',
        help="Parent group in TallyPrime"
    )

    _sql_constraints = [
        ('unique_partner_backend', 'unique(odoo_id, backend_id)',
         'A partner can only have one binding per backend!'),
    ]

    def _get_ledger_xml(self):
        """Generate TallyPrime Ledger XML for this partner"""
        self.ensure_one()
        partner = self.odoo_id
        backend = self.backend_id
        
        # Determine ledger group based on partner type
        if partner.supplier_rank > partner.customer_rank:
            parent_group = backend.vendor_parent_group or 'Sundry Creditors'
        else:
            parent_group = backend.customer_parent_group or 'Sundry Debtors'
        
        # Build address
        address_parts = []
        if partner.street:
            address_parts.append(partner.street)
        if partner.street2:
            address_parts.append(partner.street2)
        if partner.city:
            address_parts.append(partner.city)
        if partner.state_id:
            address_parts.append(partner.state_id.name)
        if partner.zip:
            address_parts.append(partner.zip)
        
        address = ', '.join(filter(None, address_parts))
        
        # Use partner name or generate ledger name
        ledger_name = self.ledger_name or partner.name
        
        xml = f"""<?xml version="1.0" encoding="utf-8"?>
<ENVELOPE>
    <HEADER>
        <VERSION>1</VERSION>
        <TALLYREQUEST>Import</TALLYREQUEST>
        <TYPE>Data</TYPE>
        <ID>All Masters</ID>
    </HEADER>
    <BODY>
        <DESC>
            <STATICVARIABLES>
                <SVCURRENTCOMPANY>{backend.company_name}</SVCURRENTCOMPANY>
            </STATICVARIABLES>
        </DESC>
        <DATA>
            <TALLYMESSAGE>
                <LEDGER NAME="{self._escape_xml(ledger_name)}" ACTION="Create">
                    <NAME>{self._escape_xml(ledger_name)}</NAME>
                    <PARENT>{self._escape_xml(parent_group)}</PARENT>
                    <ADDRESS.LIST>
                        <ADDRESS>{self._escape_xml(address)}</ADDRESS>
                    </ADDRESS.LIST>
                    <COUNTRYNAME>{self._escape_xml(partner.country_id.name or '')}</COUNTRYNAME>
                    <LEDGERPHONE>{self._escape_xml(partner.phone or '')}</LEDGERPHONE>
                    <LEDGERMOBILE>{self._escape_xml(partner.mobile or '')}</LEDGERMOBILE>
                    <EMAIL>{self._escape_xml(partner.email or '')}</EMAIL>
                    <GSTREGISTRATIONTYPE>Regular</GSTREGISTRATIONTYPE>
                    <PARTYGSTIN>{self._escape_xml(partner.vat or '')}</PARTYGSTIN>
                </LEDGER>
            </TALLYMESSAGE>
        </DATA>
    </BODY>
</ENVELOPE>"""
        
        return xml

    def _escape_xml(self, text):
        """Escape special characters for XML"""
        if not text:
            return ''
        text = str(text)
        text = text.replace('&', '&amp;')
        text = text.replace('<', '&lt;')
        text = text.replace('>', '&gt;')
        text = text.replace('"', '&quot;')
        text = text.replace("'", '&apos;')
        return text

    def _export_to_tally(self):
        """Export this partner binding to TallyPrime"""
        self.ensure_one()
        
        xml_data = self._get_ledger_xml()
        result = self.backend_id._send_to_tally(xml_data)
        
        if result.get('success'):
            # Update ledger name if not set
            if not self.ledger_name:
                self.ledger_name = self.odoo_id.name
            self.mark_synced(tally_id=self.ledger_name)
            _logger.info(f"Successfully exported partner {self.odoo_id.name} to TallyPrime")
        else:
            self.mark_error(result.get('error', 'Unknown error'))
            _logger.error(f"Failed to export partner {self.odoo_id.name}: {result.get('error')}")


class ResPartner(models.Model):
    """Extend res.partner with Tally binding capabilities"""
    _inherit = 'res.partner'

    tally_bind_ids = fields.One2many(
        'tally.res.partner',
        'odoo_id',
        string='Tally Bindings',
    )
    tally_synced = fields.Boolean(
        string='Synced to Tally',
        compute='_compute_tally_synced',
        store=True,
    )

    @api.depends('tally_bind_ids', 'tally_bind_ids.sync_state')
    def _compute_tally_synced(self):
        for partner in self:
            partner.tally_synced = any(
                b.sync_state == 'synced' for b in partner.tally_bind_ids
            )

    def export_to_tally(self):
        """Export this partner to TallyPrime"""
        self.ensure_one()
        
        # Get backend from context or find default
        backend_id = self.env.context.get('tally_backend_id')
        if backend_id:
            backend = self.env['tally.backend'].browse(backend_id)
        else:
            backend = self.env['tally.backend'].search([
                ('active', '=', True),
                ('state', '=', 'connected'),
                ('sync_partners', '=', True),
                ('company_id', '=', self.env.company.id),
            ], limit=1)
        
        if not backend:
            return {
                'type': 'ir.actions.client',
                'tag': 'display_notification',
                'params': {
                    'title': _('No Backend'),
                    'message': _('No active TallyPrime backend found'),
                    'type': 'warning',
                    'sticky': False,
                }
            }
        
        # Find or create binding
        binding = self.env['tally.res.partner'].search([
            ('odoo_id', '=', self.id),
            ('backend_id', '=', backend.id),
        ], limit=1)
        
        if not binding:
            binding = self.env['tally.res.partner'].create({
                'odoo_id': self.id,
                'backend_id': backend.id,
            })
        
        binding._export_to_tally()
        
        if binding.sync_state == 'synced':
            return {
                'type': 'ir.actions.client',
                'tag': 'display_notification',
                'params': {
                    'title': _('Sync Successful'),
                    'message': _('Partner exported to TallyPrime'),
                    'type': 'success',
                    'sticky': False,
                }
            }
        else:
            return {
                'type': 'ir.actions.client',
                'tag': 'display_notification',
                'params': {
                    'title': _('Sync Failed'),
                    'message': binding.sync_error or _('Unknown error'),
                    'type': 'danger',
                    'sticky': True,
                }
            }

    @api.model_create_multi
    def create(self, vals_list):
        """Override create to auto-sync to Tally if enabled"""
        partners = super().create(vals_list)
        
        # Check if auto-sync is enabled
        backends = self.env['tally.backend'].search([
            ('active', '=', True),
            ('state', '=', 'connected'),
            ('auto_sync', '=', True),
            ('sync_partners', '=', True),
        ])
        
        for partner in partners:
            # Only sync customers and vendors
            if not (partner.customer_rank > 0 or partner.supplier_rank > 0):
                continue
                
            for backend in backends:
                if backend.company_id == partner.company_id or not partner.company_id:
                    # Create binding and queue for sync
                    self.env['tally.res.partner'].create({
                        'odoo_id': partner.id,
                        'backend_id': backend.id,
                        'sync_state': 'pending',
                    })
        
        return partners

    def write(self, vals):
        """Override write to auto-sync updates to Tally"""
        result = super().write(vals)
        
        # Fields that trigger a re-sync
        sync_trigger_fields = {
            'name', 'street', 'street2', 'city', 'state_id', 'zip',
            'country_id', 'phone', 'mobile', 'email', 'vat',
            'customer_rank', 'supplier_rank',
        }
        
        if any(f in vals for f in sync_trigger_fields):
            for partner in self:
                for binding in partner.tally_bind_ids:
                    if binding.backend_id.auto_sync and binding.backend_id.state == 'connected':
                        binding.sync_state = 'pending'
                        # Async export would be triggered by cron or queue_job
                        try:
                            binding._export_to_tally()
                        except Exception as e:
                            _logger.error(f"Auto-sync failed for partner {partner.id}: {e}")
        
        return result
