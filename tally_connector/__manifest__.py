{
    "name": "TallyPrime Connector",
    "version": "18.0.1.0.0",
    "category": "Connector",
    "summary": "Real-time bidirectional sync between Odoo and TallyPrime 7.0",
    "description": """
TallyPrime Connector for Odoo 18
================================

This module provides real-time bidirectional synchronization between Odoo 18 
and TallyPrime 7.0 using push-based integration.

Features:
---------
* Automatic sync on record create/update/delete
* Background job queue processing
* Partner (Customer/Vendor) ↔ Ledger sync
* Product ↔ Stock Item sync  
* Invoice ↔ Voucher sync
* Webhook receiver for TallyPrime events
* Configurable sync settings per backend

Requirements:
------------
* TallyPrime 7.0 with HTTP API enabled
* queue_job module from OCA (optional but recommended)
    """,
    "author": "Braincuber Technologies",
    "website": "https://braincuber.com",
    "license": "LGPL-3",
    "depends": [
        "base",
        "mail",
        "account",
        "product",
        "contacts",
    ],
    "external_dependencies": {
        "python": ["requests"],
    },
    "data": [
        "security/tally_security.xml",
        "security/ir.model.access.csv",
        "views/tally_backend_views.xml",
        "views/res_partner_views.xml",
        "views/product_views.xml",
        "views/menus.xml",
        "data/cron.xml",
    ],
    "demo": [],
    "installable": True,
    "application": True,
    "auto_install": False,
    "assets": {},
}
