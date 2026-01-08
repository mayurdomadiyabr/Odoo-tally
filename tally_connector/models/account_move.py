# -*- coding: utf-8 -*-
# Part of TallyPrime Connector. See LICENSE file for full copyright and licensing details.

import logging
from odoo import api, fields, models, _

_logger = logging.getLogger(__name__)


class TallyAccountMove(models.Model):
    """
    Binding model for account.move <-> Tally Voucher.
    Each record represents a link between an Odoo invoice and a TallyPrime voucher.
    """
    _name = 'tally.account.move'
    _description = 'Invoice Tally Binding'
    _inherit = 'tally.binding'
    _rec_name = 'odoo_id'

    odoo_id = fields.Many2one(
        'account.move',
        string='Invoice',
        required=True,
        ondelete='cascade',
        index=True,
    )
    voucher_number = fields.Char(
        string='Tally Voucher Number',
        help="Voucher number in TallyPrime"
    )
    voucher_type = fields.Char(
        string='Tally Voucher Type',
        help="Voucher type in TallyPrime (Sales, Purchase, etc.)"
    )

    _sql_constraints = [
        ('unique_move_backend', 'unique(odoo_id, backend_id)',
         'An invoice can only have one binding per backend!'),
    ]

    def _get_voucher_type(self):
        """Determine TallyPrime voucher type based on invoice type"""
        self.ensure_one()
        move = self.odoo_id
        
        if move.move_type == 'out_invoice':
            return 'Sales'
        elif move.move_type == 'out_refund':
            return 'Credit Note'
        elif move.move_type == 'in_invoice':
            return 'Purchase'
        elif move.move_type == 'in_refund':
            return 'Debit Note'
        else:
            return 'Journal'

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

    def _get_voucher_xml(self):
        """Generate TallyPrime Voucher XML for this invoice"""
        self.ensure_one()
        move = self.odoo_id
        backend = self.backend_id
        
        voucher_type = self._get_voucher_type()
        self.voucher_type = voucher_type
        
        # Format date as DD-MMM-YYYY (TallyPrime format)
        date_str = move.invoice_date.strftime('%Y%m%d') if move.invoice_date else ''
        
        # Get party ledger name
        party_name = move.partner_id.name if move.partner_id else 'Cash'
        
        # Determine if it's a sales or purchase voucher
        is_sales = move.move_type in ('out_invoice', 'out_refund')
        
        # Build inventory entries for line items
        inventory_entries = []
        ledger_entries = []
        
        for line in move.invoice_line_ids:
            if line.display_type != 'product':
                continue
            
            product_name = line.product_id.name if line.product_id else line.name
            qty = line.quantity
            rate = line.price_unit
            amount = line.price_subtotal
            
            if is_sales:
                # For sales, create inventory allocation with negative quantity
                inventory_entries.append(f"""
                    <INVENTORYENTRIESIN.LIST>
                        <STOCKITEMNAME>{self._escape_xml(product_name)}</STOCKITEMNAME>
                        <ISDEEMEDPOSITIVE>No</ISDEEMEDPOSITIVE>
                        <ISLASTDEEMEDPOSITIVE>No</ISLASTDEEMEDPOSITIVE>
                        <RATE>{rate}</RATE>
                        <AMOUNT>-{amount}</AMOUNT>
                        <ACTUALQTY>{qty}</ACTUALQTY>
                        <BILLEDQTY>{qty}</BILLEDQTY>
                        <BATCHALLOCATIONS.LIST>
                            <BATCHNAME>Primary Batch</BATCHNAME>
                            <AMOUNT>-{amount}</AMOUNT>
                            <ACTUALQTY>{qty}</ACTUALQTY>
                            <BILLEDQTY>{qty}</BILLEDQTY>
                        </BATCHALLOCATIONS.LIST>
                    </INVENTORYENTRIESIN.LIST>""")
            else:
                # For purchases, create inventory allocation with positive quantity
                inventory_entries.append(f"""
                    <INVENTORYENTRIESOUT.LIST>
                        <STOCKITEMNAME>{self._escape_xml(product_name)}</STOCKITEMNAME>
                        <ISDEEMEDPOSITIVE>Yes</ISDEEMEDPOSITIVE>
                        <ISLASTDEEMEDPOSITIVE>Yes</ISLASTDEEMEDPOSITIVE>
                        <RATE>{rate}</RATE>
                        <AMOUNT>{amount}</AMOUNT>
                        <ACTUALQTY>{qty}</ACTUALQTY>
                        <BILLEDQTY>{qty}</BILLEDQTY>
                        <BATCHALLOCATIONS.LIST>
                            <BATCHNAME>Primary Batch</BATCHNAME>
                            <AMOUNT>{amount}</AMOUNT>
                            <ACTUALQTY>{qty}</ACTUALQTY>
                            <BILLEDQTY>{qty}</BILLEDQTY>
                        </BATCHALLOCATIONS.LIST>
                    </INVENTORYENTRIESOUT.LIST>""")
        
        # Build tax entries
        tax_total = move.amount_tax
        if tax_total:
            tax_ledger = 'Output GST' if is_sales else 'Input GST'
            if is_sales:
                ledger_entries.append(f"""
                    <LEDGERENTRIES.LIST>
                        <LEDGERNAME>{self._escape_xml(tax_ledger)}</LEDGERNAME>
                        <ISDEEMEDPOSITIVE>No</ISDEEMEDPOSITIVE>
                        <AMOUNT>-{tax_total}</AMOUNT>
                    </LEDGERENTRIES.LIST>""")
            else:
                ledger_entries.append(f"""
                    <LEDGERENTRIES.LIST>
                        <LEDGERNAME>{self._escape_xml(tax_ledger)}</LEDGERNAME>
                        <ISDEEMEDPOSITIVE>Yes</ISDEEMEDPOSITIVE>
                        <AMOUNT>{tax_total}</AMOUNT>
                    </LEDGERENTRIES.LIST>""")
        
        # Main ledger entry (party ledger)
        total_amount = move.amount_total
        if is_sales:
            party_entry = f"""
                <LEDGERENTRIES.LIST>
                    <LEDGERNAME>{self._escape_xml(party_name)}</LEDGERNAME>
                    <ISDEEMEDPOSITIVE>Yes</ISDEEMEDPOSITIVE>
                    <AMOUNT>{total_amount}</AMOUNT>
                </LEDGERENTRIES.LIST>"""
        else:
            party_entry = f"""
                <LEDGERENTRIES.LIST>
                    <LEDGERNAME>{self._escape_xml(party_name)}</LEDGERNAME>
                    <ISDEEMEDPOSITIVE>No</ISDEEMEDPOSITIVE>
                    <AMOUNT>-{total_amount}</AMOUNT>
                </LEDGERENTRIES.LIST>"""
        
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
                <VOUCHER VCHTYPE="{voucher_type}" ACTION="Create">
                    <DATE>{date_str}</DATE>
                    <VOUCHERTYPENAME>{voucher_type}</VOUCHERTYPENAME>
                    <VOUCHERNUMBER>{self._escape_xml(move.name or '')}</VOUCHERNUMBER>
                    <REFERENCE>{self._escape_xml(move.ref or move.name or '')}</REFERENCE>
                    <PARTYLEDGERNAME>{self._escape_xml(party_name)}</PARTYLEDGERNAME>
                    <ISINVOICE>Yes</ISINVOICE>
                    <EFFECTIVEDATE>{date_str}</EFFECTIVEDATE>
                    <NARRATION>{self._escape_xml(move.narration or '')}</NARRATION>
                    {party_entry}
                    {''.join(ledger_entries)}
                    {''.join(inventory_entries)}
                </VOUCHER>
            </TALLYMESSAGE>
        </DATA>
    </BODY>
</ENVELOPE>"""
        
        return xml

    def _export_to_tally(self):
        """Export this invoice binding to TallyPrime"""
        self.ensure_one()
        
        # Only sync posted invoices
        if self.odoo_id.state != 'posted':
            _logger.info(f"Skipping non-posted invoice {self.odoo_id.name}")
            return
        
        xml_data = self._get_voucher_xml()
        result = self.backend_id._send_to_tally(xml_data)
        
        if result.get('success'):
            self.voucher_number = self.odoo_id.name
            self.mark_synced(tally_id=self.odoo_id.name)
            _logger.info(f"Successfully exported invoice {self.odoo_id.name} to TallyPrime")
        else:
            self.mark_error(result.get('error', 'Unknown error'))
            _logger.error(f"Failed to export invoice {self.odoo_id.name}: {result.get('error')}")


class AccountMove(models.Model):
    """Extend account.move with Tally binding capabilities"""
    _inherit = 'account.move'

    tally_bind_ids = fields.One2many(
        'tally.account.move',
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
        for move in self:
            move.tally_synced = any(
                b.sync_state == 'synced' for b in move.tally_bind_ids
            )

    def export_to_tally(self):
        """Export this invoice to TallyPrime"""
        self.ensure_one()
        
        if self.state != 'posted':
            return {
                'type': 'ir.actions.client',
                'tag': 'display_notification',
                'params': {
                    'title': _('Cannot Sync'),
                    'message': _('Only posted invoices can be synced to TallyPrime'),
                    'type': 'warning',
                    'sticky': False,
                }
            }
        
        # Get backend from context or find default
        backend_id = self.env.context.get('tally_backend_id')
        if backend_id:
            backend = self.env['tally.backend'].browse(backend_id)
        else:
            backend = self.env['tally.backend'].search([
                ('active', '=', True),
                ('state', '=', 'connected'),
                ('sync_invoices', '=', True),
                ('company_id', '=', self.company_id.id),
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
        binding = self.env['tally.account.move'].search([
            ('odoo_id', '=', self.id),
            ('backend_id', '=', backend.id),
        ], limit=1)
        
        if not binding:
            binding = self.env['tally.account.move'].create({
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
                    'message': _('Invoice exported to TallyPrime'),
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

    def action_post(self):
        """Override action_post to auto-sync posted invoices to Tally"""
        result = super().action_post()
        
        # Check if auto-sync is enabled for invoices
        backends = self.env['tally.backend'].search([
            ('active', '=', True),
            ('state', '=', 'connected'),
            ('auto_sync', '=', True),
            ('sync_invoices', '=', True),
        ])
        
        for move in self:
            # Only sync invoices and credit/debit notes
            if move.move_type not in ('out_invoice', 'out_refund', 'in_invoice', 'in_refund'):
                continue
                
            for backend in backends:
                if backend.company_id == move.company_id:
                    # Create binding and export
                    binding = self.env['tally.account.move'].search([
                        ('odoo_id', '=', move.id),
                        ('backend_id', '=', backend.id),
                    ], limit=1)
                    
                    if not binding:
                        binding = self.env['tally.account.move'].create({
                            'odoo_id': move.id,
                            'backend_id': backend.id,
                            'sync_state': 'pending',
                        })
                    
                    try:
                        binding._export_to_tally()
                    except Exception as e:
                        _logger.error(f"Auto-sync failed for invoice {move.name}: {e}")
        
        return result
