# -*- coding: utf-8 -*-
# Part of TallyPrime Connector. See LICENSE file for full copyright and licensing details.

import logging
from odoo import api, fields, models, _

_logger = logging.getLogger(__name__)


class TallyProductProduct(models.Model):
    """
    Binding model for product.product <-> Tally Stock Item.
    Each record represents a link between an Odoo product and a TallyPrime stock item.
    """
    _name = 'tally.product.product'
    _description = 'Product Tally Binding'
    _inherit = 'tally.binding'
    _rec_name = 'odoo_id'

    odoo_id = fields.Many2one(
        'product.product',
        string='Product',
        required=True,
        ondelete='cascade',
        index=True,
    )
    stock_item_name = fields.Char(
        string='Tally Stock Item Name',
        help="Name of the stock item in TallyPrime"
    )
    tally_category = fields.Char(
        string='Tally Category',
        help="Stock category in TallyPrime"
    )
    tally_unit = fields.Char(
        string='Tally Unit',
        help="Unit of measure in TallyPrime"
    )

    _sql_constraints = [
        ('unique_product_backend', 'unique(odoo_id, backend_id)',
         'A product can only have one binding per backend!'),
    ]

    def _get_stock_item_xml(self):
        """Generate TallyPrime Stock Item XML for this product"""
        self.ensure_one()
        product = self.odoo_id
        backend = self.backend_id
        
        # Use product name or stock item name
        item_name = self.stock_item_name or product.name
        category = self.tally_category or backend.stock_category or 'Primary'
        unit = self.tally_unit or backend.stock_unit or 'Nos'
        
        # Get opening stock and rate
        opening_qty = product.qty_available or 0
        cost_price = product.standard_price or 0
        sale_price = product.lst_price or 0
        
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
                <STOCKITEM NAME="{self._escape_xml(item_name)}" ACTION="Create">
                    <NAME>{self._escape_xml(item_name)}</NAME>
                    <PARENT>{self._escape_xml(category)}</PARENT>
                    <BASEUNITS>{self._escape_xml(unit)}</BASEUNITS>
                    <ADDITIONALUNITS>{self._escape_xml(unit)}</ADDITIONALUNITS>
                    <ISBATCHWISEON>No</ISBATCHWISEON>
                    <ISPERISHABLEON>No</ISPERISHABLEON>
                    <HASMFGDATE>No</HASMFGDATE>
                    <HASEXPIRYDATE>No</HASEXPIRYDATE>
                    <COSTINGMETHOD>Avg. Cost</COSTINGMETHOD>
                    <VALUATIONMETHOD>Avg. Cost</VALUATIONMETHOD>
                    <OPENINGBALANCE>{opening_qty} {unit}</OPENINGBALANCE>
                    <OPENINGRATE>{cost_price}</OPENINGRATE>
                    <OPENINGVALUE>{opening_qty * cost_price}</OPENINGVALUE>
                    <GSTAPPLICABLE>Applicable</GSTAPPLICABLE>
                    <DESCRIPTION>{self._escape_xml(product.description or '')}</DESCRIPTION>
                    <NARRATION>{self._escape_xml(product.description_sale or '')}</NARRATION>
                    <BATCHALLOCATIONS.LIST>
                        <BATCHNAME>Primary Batch</BATCHNAME>
                        <OPENINGBALANCE>{opening_qty} {unit}</OPENINGBALANCE>
                        <OPENINGRATE>{cost_price}</OPENINGRATE>
                        <OPENINGVALUE>{opening_qty * cost_price}</OPENINGVALUE>
                    </BATCHALLOCATIONS.LIST>
                </STOCKITEM>
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
        """Export this product binding to TallyPrime"""
        self.ensure_one()
        
        xml_data = self._get_stock_item_xml()
        result = self.backend_id._send_to_tally(xml_data)
        
        if result.get('success'):
            # Update stock item name if not set
            if not self.stock_item_name:
                self.stock_item_name = self.odoo_id.name
            self.mark_synced(tally_id=self.stock_item_name)
            _logger.info(f"Successfully exported product {self.odoo_id.name} to TallyPrime")
        else:
            self.mark_error(result.get('error', 'Unknown error'))
            _logger.error(f"Failed to export product {self.odoo_id.name}: {result.get('error')}")


class ProductProduct(models.Model):
    """Extend product.product with Tally binding capabilities"""
    _inherit = 'product.product'

    tally_bind_ids = fields.One2many(
        'tally.product.product',
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
        for product in self:
            product.tally_synced = any(
                b.sync_state == 'synced' for b in product.tally_bind_ids
            )

    def export_to_tally(self):
        """Export this product to TallyPrime"""
        self.ensure_one()
        
        # Get backend from context or find default
        backend_id = self.env.context.get('tally_backend_id')
        if backend_id:
            backend = self.env['tally.backend'].browse(backend_id)
        else:
            backend = self.env['tally.backend'].search([
                ('active', '=', True),
                ('state', '=', 'connected'),
                ('sync_products', '=', True),
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
        binding = self.env['tally.product.product'].search([
            ('odoo_id', '=', self.id),
            ('backend_id', '=', backend.id),
        ], limit=1)
        
        if not binding:
            binding = self.env['tally.product.product'].create({
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
                    'message': _('Product exported to TallyPrime'),
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
        products = super().create(vals_list)
        
        # Check if auto-sync is enabled
        backends = self.env['tally.backend'].search([
            ('active', '=', True),
            ('state', '=', 'connected'),
            ('auto_sync', '=', True),
            ('sync_products', '=', True),
        ])
        
        for product in products:
            # Only sync storable and consumable products
            if product.type not in ('product', 'consu'):
                continue
                
            for backend in backends:
                if backend.company_id == product.company_id or not product.company_id:
                    # Create binding and queue for sync
                    self.env['tally.product.product'].create({
                        'odoo_id': product.id,
                        'backend_id': backend.id,
                        'sync_state': 'pending',
                    })
        
        return products

    def write(self, vals):
        """Override write to auto-sync updates to Tally"""
        result = super().write(vals)
        
        # Fields that trigger a re-sync
        sync_trigger_fields = {
            'name', 'default_code', 'barcode', 'standard_price',
            'lst_price', 'description', 'description_sale', 'type',
        }
        
        if any(f in vals for f in sync_trigger_fields):
            for product in self:
                for binding in product.tally_bind_ids:
                    if binding.backend_id.auto_sync and binding.backend_id.state == 'connected':
                        binding.sync_state = 'pending'
                        try:
                            binding._export_to_tally()
                        except Exception as e:
                            _logger.error(f"Auto-sync failed for product {product.id}: {e}")
        
        return result
