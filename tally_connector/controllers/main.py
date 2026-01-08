# -*- coding: utf-8 -*-
# Part of TallyPrime Connector. See LICENSE file for full copyright and licensing details.

import logging
import json
from odoo import http
from odoo.http import request

_logger = logging.getLogger(__name__)


class TallyWebhookController(http.Controller):
    """
    Webhook receiver for TallyPrime events.
    Handles incoming data pushes from TallyPrime for reverse-sync.
    """

    @http.route('/tally/webhook/import', type='json', auth='public', 
                methods=['POST'], csrf=False)
    def tally_webhook_import(self, **kwargs):
        """
        Receive data from TallyPrime and import into Odoo.
        
        Expected JSON format:
        {
            "type": "LEDGER" | "STOCKITEM" | "VOUCHER",
            "action": "CREATE" | "UPDATE" | "DELETE",
            "data": { ... tally record data ... }
        }
        """
        try:
            data = request.jsonrequest
            record_type = data.get('type', '').upper()
            action = data.get('action', 'CREATE').upper()
            record_data = data.get('data', {})
            
            _logger.info(f"Received Tally webhook: type={record_type}, action={action}")
            
            if not record_type or not record_data:
                return {
                    'status': '0',
                    'error': 'Missing type or data in request'
                }
            
            # Find active backend to process import
            backend = request.env['tally.backend'].sudo().search([
                ('active', '=', True),
                ('state', '=', 'connected'),
            ], limit=1)
            
            if not backend:
                return {
                    'status': '0',
                    'error': 'No active TallyPrime backend configured'
                }
            
            # Route to appropriate handler based on type
            result = None
            if record_type == 'LEDGER':
                result = self._import_ledger(backend, record_data, action)
            elif record_type == 'STOCKITEM':
                result = self._import_stock_item(backend, record_data, action)
            elif record_type == 'VOUCHER':
                result = self._import_voucher(backend, record_data, action)
            else:
                return {
                    'status': '0',
                    'error': f'Unknown record type: {record_type}'
                }
            
            return result
            
        except Exception as e:
            _logger.error(f"Tally webhook error: {e}", exc_info=True)
            return {
                'status': '0',
                'error': str(e)
            }

    def _import_ledger(self, backend, data, action):
        """Import a Ledger from TallyPrime as a Partner"""
        try:
            name = data.get('NAME', data.get('name', ''))
            parent = data.get('PARENT', data.get('parent', ''))
            
            if not name:
                return {'status': '0', 'error': 'Ledger name is required'}
            
            # Determine partner type based on parent group
            is_customer = 'debtor' in parent.lower() or 'receivable' in parent.lower()
            is_vendor = 'creditor' in parent.lower() or 'payable' in parent.lower()
            
            # Search existing binding by tally_id
            binding = request.env['tally.res.partner'].sudo().search([
                ('backend_id', '=', backend.id),
                ('tally_id', '=', name),
            ], limit=1)
            
            partner_vals = {
                'name': name,
                'street': data.get('ADDRESS', data.get('address', '')),
                'email': data.get('EMAIL', data.get('email', '')),
                'phone': data.get('LEDGERPHONE', data.get('phone', '')),
                'mobile': data.get('LEDGERMOBILE', data.get('mobile', '')),
                'vat': data.get('PARTYGSTIN', data.get('gstin', '')),
                'customer_rank': 1 if is_customer else 0,
                'supplier_rank': 1 if is_vendor else 0,
            }
            
            if binding and binding.odoo_id:
                # Update existing partner
                binding.odoo_id.sudo().write(partner_vals)
                binding.mark_synced()
                _logger.info(f"Updated partner from Tally: {name}")
            else:
                # Create new partner
                partner = request.env['res.partner'].sudo().create(partner_vals)
                
                # Create binding
                request.env['tally.res.partner'].sudo().create({
                    'odoo_id': partner.id,
                    'backend_id': backend.id,
                    'tally_id': name,
                    'ledger_name': name,
                    'ledger_group': parent,
                    'sync_state': 'synced',
                })
                _logger.info(f"Created partner from Tally: {name}")
            
            return {'status': '1', 'message': f'Ledger {name} imported successfully'}
            
        except Exception as e:
            _logger.error(f"Ledger import error: {e}")
            return {'status': '0', 'error': str(e)}

    def _import_stock_item(self, backend, data, action):
        """Import a Stock Item from TallyPrime as a Product"""
        try:
            name = data.get('NAME', data.get('name', ''))
            
            if not name:
                return {'status': '0', 'error': 'Stock item name is required'}
            
            # Search existing binding
            binding = request.env['tally.product.product'].sudo().search([
                ('backend_id', '=', backend.id),
                ('tally_id', '=', name),
            ], limit=1)
            
            product_vals = {
                'name': name,
                'type': 'product',
                'description': data.get('DESCRIPTION', data.get('description', '')),
            }
            
            # Get pricing if available
            if data.get('OPENINGRATE'):
                product_vals['standard_price'] = float(data.get('OPENINGRATE', 0))
            
            if binding and binding.odoo_id:
                # Update existing product
                binding.odoo_id.sudo().write(product_vals)
                binding.mark_synced()
                _logger.info(f"Updated product from Tally: {name}")
            else:
                # Create new product
                product = request.env['product.product'].sudo().create(product_vals)
                
                # Create binding
                request.env['tally.product.product'].sudo().create({
                    'odoo_id': product.id,
                    'backend_id': backend.id,
                    'tally_id': name,
                    'stock_item_name': name,
                    'tally_category': data.get('PARENT', 'Primary'),
                    'sync_state': 'synced',
                })
                _logger.info(f"Created product from Tally: {name}")
            
            return {'status': '1', 'message': f'Stock item {name} imported successfully'}
            
        except Exception as e:
            _logger.error(f"Stock item import error: {e}")
            return {'status': '0', 'error': str(e)}

    def _import_voucher(self, backend, data, action):
        """Import a Voucher from TallyPrime as an Invoice"""
        try:
            voucher_number = data.get('VOUCHERNUMBER', data.get('vouchernumber', ''))
            voucher_type = data.get('VOUCHERTYPENAME', data.get('vouchertype', ''))
            
            if not voucher_number:
                return {'status': '0', 'error': 'Voucher number is required'}
            
            _logger.info(f"Received voucher import request: {voucher_number} ({voucher_type})")
            
            # Voucher import is complex - log for manual review for now
            # Full implementation would create account.move from voucher data
            
            return {
                'status': '1', 
                'message': f'Voucher {voucher_number} received - manual review required'
            }
            
        except Exception as e:
            _logger.error(f"Voucher import error: {e}")
            return {'status': '0', 'error': str(e)}

    @http.route('/tally/webhook/status', type='http', auth='public', 
                methods=['GET'], csrf=False)
    def tally_webhook_status(self):
        """Health check endpoint for TallyPrime webhook"""
        return request.make_json_response({
            'status': 'ok',
            'message': 'TallyPrime webhook endpoint is active'
        })
