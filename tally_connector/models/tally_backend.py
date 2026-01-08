# -*- coding: utf-8 -*-
# Part of TallyPrime Connector. See LICENSE file for full copyright and licensing details.

import logging
import requests
import json
from datetime import datetime, timedelta

from odoo import api, fields, models, _
from odoo.exceptions import UserError, ValidationError

_logger = logging.getLogger(__name__)


class TallyBackend(models.Model):
    """
    Backend configuration for TallyPrime connection.
    Each backend represents a connection to a TallyPrime instance/company.
    """
    _name = 'tally.backend'
    _description = 'TallyPrime Backend'
    _inherit = ['mail.thread', 'mail.activity.mixin']

    name = fields.Char(
        string='Name',
        required=True,
        tracking=True,
        help="A descriptive name for this TallyPrime connection"
    )
    active = fields.Boolean(default=True)
    company_id = fields.Many2one(
        'res.company',
        string='Company',
        required=True,
        default=lambda self: self.env.company
    )
    
    # Connection Settings
    tally_host = fields.Char(
        string='TallyPrime Host',
        default='localhost',
        required=True,
        help="IP address or hostname of TallyPrime server"
    )
    tally_port = fields.Integer(
        string='TallyPrime Port',
        default=9000,
        required=True,
        help="HTTP API port configured in TallyPrime (default: 9000)"
    )
    company_name = fields.Char(
        string='Tally Company Name',
        required=True,
        help="Name of the company in TallyPrime to sync with"
    )
    
    # Sync Settings
    auto_sync = fields.Boolean(
        string='Enable Auto Sync',
        default=True,
        help="Automatically sync records on create/update"
    )
    sync_partners = fields.Boolean(
        string='Sync Partners',
        default=True,
        help="Sync customers and vendors as Ledgers"
    )
    sync_products = fields.Boolean(
        string='Sync Products',
        default=True,
        help="Sync products as Stock Items"
    )
    sync_invoices = fields.Boolean(
        string='Sync Invoices',
        default=True,
        help="Sync invoices as Vouchers"
    )
    sync_deletions = fields.Boolean(
        string='Sync Deletions',
        default=False,
        help="Sync record deletions to TallyPrime (use with caution)"
    )
    
    # Status
    state = fields.Selection([
        ('draft', 'Draft'),
        ('connected', 'Connected'),
        ('error', 'Error'),
    ], string='Status', default='draft', tracking=True)
    last_sync = fields.Datetime(
        string='Last Sync',
        readonly=True
    )
    connection_error = fields.Text(
        string='Last Error',
        readonly=True
    )
    
    # Ledger Group Mappings
    customer_parent_group = fields.Char(
        string='Customer Parent Group',
        default='Sundry Debtors',
        help="TallyPrime ledger group for customers"
    )
    vendor_parent_group = fields.Char(
        string='Vendor Parent Group',
        default='Sundry Creditors',
        help="TallyPrime ledger group for vendors"
    )
    
    # Stock Item Mappings
    stock_category = fields.Char(
        string='Default Stock Category',
        default='Primary',
        help="Default TallyPrime stock category for products"
    )
    stock_unit = fields.Char(
        string='Default Stock Unit',
        default='Nos',
        help="Default unit of measure in TallyPrime"
    )

    def _get_tally_url(self):
        """Get the full TallyPrime API URL"""
        self.ensure_one()
        return f"http://{self.tally_host}:{self.tally_port}"

    def test_connection(self):
        """Test connection to TallyPrime"""
        self.ensure_one()
        
        # Build a simple test request to fetch company info
        xml_request = f"""<?xml version="1.0" encoding="utf-8"?>
<ENVELOPE>
    <HEADER>
        <VERSION>1</VERSION>
        <TALLYREQUEST>Export</TALLYREQUEST>
        <TYPE>Data</TYPE>
        <ID>List of Companies</ID>
    </HEADER>
    <BODY>
        <DESC>
            <STATICVARIABLES>
                <SVEXPORTFORMAT>$$SysName:XML</SVEXPORTFORMAT>
            </STATICVARIABLES>
        </DESC>
    </BODY>
</ENVELOPE>"""

        try:
            response = requests.post(
                self._get_tally_url(),
                data=xml_request,
                headers={'Content-Type': 'application/xml'},
                timeout=10
            )
            
            if response.status_code == 200:
                # Check if company exists in response
                if self.company_name.upper() in response.text.upper():
                    self.write({
                        'state': 'connected',
                        'connection_error': False,
                        'last_sync': fields.Datetime.now(),
                    })
                    return {
                        'type': 'ir.actions.client',
                        'tag': 'display_notification',
                        'params': {
                            'title': _('Connection Successful'),
                            'message': _('Successfully connected to TallyPrime!'),
                            'type': 'success',
                            'sticky': False,
                        }
                    }
                else:
                    self.write({
                        'state': 'error',
                        'connection_error': f'Company "{self.company_name}" not found in TallyPrime',
                    })
                    return {
                        'type': 'ir.actions.client',
                        'tag': 'display_notification',
                        'params': {
                            'title': _('Connection Failed'),
                            'message': _('Company not found in TallyPrime'),
                            'type': 'warning',
                            'sticky': False,
                        }
                    }
            else:
                raise Exception(f"HTTP {response.status_code}")
                
        except requests.exceptions.ConnectionError:
            error_msg = f"Cannot connect to TallyPrime at {self._get_tally_url()}"
            self.write({
                'state': 'error',
                'connection_error': error_msg,
            })
            raise UserError(_(error_msg))
        except requests.exceptions.Timeout:
            error_msg = "Connection timeout - TallyPrime not responding"
            self.write({
                'state': 'error',
                'connection_error': error_msg,
            })
            raise UserError(_(error_msg))
        except Exception as e:
            error_msg = str(e)
            self.write({
                'state': 'error',
                'connection_error': error_msg,
            })
            raise UserError(_('Connection failed: %s') % error_msg)

    def sync_all_partners(self):
        """Manually trigger sync for all partners"""
        self.ensure_one()
        partners = self.env['res.partner'].search([
            '|',
            ('customer_rank', '>', 0),
            ('supplier_rank', '>', 0),
        ])
        
        synced = 0
        for partner in partners:
            try:
                partner.with_context(tally_backend_id=self.id).export_to_tally()
                synced += 1
            except Exception as e:
                _logger.error(f"Failed to sync partner {partner.name}: {e}")
        
        self.last_sync = fields.Datetime.now()
        
        return {
            'type': 'ir.actions.client',
            'tag': 'display_notification',
            'params': {
                'title': _('Sync Complete'),
                'message': _('%d partners synced to TallyPrime') % synced,
                'type': 'success',
                'sticky': False,
            }
        }

    def sync_all_products(self):
        """Manually trigger sync for all products"""
        self.ensure_one()
        products = self.env['product.product'].search([
            ('type', 'in', ['product', 'consu']),
        ])
        
        synced = 0
        for product in products:
            try:
                product.with_context(tally_backend_id=self.id).export_to_tally()
                synced += 1
            except Exception as e:
                _logger.error(f"Failed to sync product {product.name}: {e}")
        
        self.last_sync = fields.Datetime.now()
        
        return {
            'type': 'ir.actions.client',
            'tag': 'display_notification',
            'params': {
                'title': _('Sync Complete'),
                'message': _('%d products synced to TallyPrime') % synced,
                'type': 'success',
                'sticky': False,
            }
        }

    def _send_to_tally(self, xml_data):
        """
        Send XML data to TallyPrime
        
        Args:
            xml_data: XML string to send
            
        Returns:
            dict with 'success' bool and 'response' or 'error'
        """
        self.ensure_one()
        
        try:
            response = requests.post(
                self._get_tally_url(),
                data=xml_data.encode('utf-8'),
                headers={
                    'Content-Type': 'application/xml; charset=utf-8',
                },
                timeout=30
            )
            
            if response.status_code == 200:
                # Check for errors in response
                response_text = response.text
                if 'LINEERROR' in response_text or 'ERROR' in response_text:
                    return {
                        'success': False,
                        'error': response_text,
                    }
                return {
                    'success': True,
                    'response': response_text,
                }
            else:
                return {
                    'success': False,
                    'error': f'HTTP Error {response.status_code}',
                }
                
        except Exception as e:
            _logger.error(f"Tally send error: {e}")
            return {
                'success': False,
                'error': str(e),
            }

    @api.model
    def _cron_sync_pending(self):
        """Cron job to sync any pending records"""
        backends = self.search([
            ('active', '=', True),
            ('state', '=', 'connected'),
            ('auto_sync', '=', True),
        ])
        
        for backend in backends:
            # Sync pending partner bindings
            pending_partners = self.env['tally.res.partner'].search([
                ('backend_id', '=', backend.id),
                ('sync_state', 'in', ['pending', 'error']),
            ], limit=100)
            
            for binding in pending_partners:
                try:
                    binding._export_to_tally()
                except Exception as e:
                    _logger.error(f"Cron sync error for partner binding {binding.id}: {e}")
            
            # Sync pending product bindings
            pending_products = self.env['tally.product.product'].search([
                ('backend_id', '=', backend.id),
                ('sync_state', 'in', ['pending', 'error']),
            ], limit=100)
            
            for binding in pending_products:
                try:
                    binding._export_to_tally()
                except Exception as e:
                    _logger.error(f"Cron sync error for product binding {binding.id}: {e}")
            
            backend.last_sync = fields.Datetime.now()
