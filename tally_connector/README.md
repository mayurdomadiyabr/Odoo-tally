# TallyPrime Connector for Odoo 18

Real-time bidirectional synchronization between Odoo 18 Community and TallyPrime 7.0.

## Features

- ✅ **Partner ↔ Ledger Sync**: Automatically sync customers/vendors as Tally Ledgers
- ✅ **Product ↔ Stock Item Sync**: Sync products as Tally Stock Items
- ✅ **Invoice ↔ Voucher Sync**: Sync invoices as Tally Vouchers (Sales/Purchase)
- ✅ **Auto-Sync on Create/Update**: Records automatically sync when created or modified
- ✅ **Webhook Receiver**: Accept incoming data from TallyPrime for reverse-sync
- ✅ **Background Cron Processing**: Fallback sync for pending/failed records

## Requirements

- Odoo 18 Community Edition
- TallyPrime 7.0 with HTTP API enabled (default port: 9000)
- Python `requests` library (included with Odoo)

### Optional Dependencies

For high-volume production use, install OCA `queue_job` module:
```bash
# Clone queue_job from OCA
git clone https://github.com/OCA/queue.git --branch 18.0 /path/to/addons/queue
```

## Installation

1. **Copy module to Odoo addons path:**
   ```bash
   cp -r tally_connector /path/to/odoo/addons/
   ```

2. **Restart Odoo server:**
   ```bash
   sudo systemctl restart odoo
   ```

3. **Update module list:**
   - Go to Apps → Update Apps List
   - Search for "TallyPrime Connector"
   - Click Install

## Configuration

### 1. Enable TallyPrime HTTP API

In TallyPrime, enable the HTTP server:
- Press `F12` → `Advanced Configuration`
- Set `Enable TDP Server (ODL/OBJ)` to `Yes`
- Set port (default: 9000)
- Restart TallyPrime

### 2. Configure Backend in Odoo

1. Go to **TallyPrime → Configuration → Backends**
2. Click **Create** and fill in:
   - **Name**: Descriptive name (e.g., "Main Tally Server")
   - **TallyPrime Host**: IP address (e.g., `192.168.1.100`)
   - **TallyPrime Port**: `9000` (default)
   - **Tally Company Name**: Exact name of company in TallyPrime
3. Enable sync options:
   - ✅ Enable Auto Sync
   - ✅ Sync Partners
   - ✅ Sync Products
   - ✅ Sync Invoices
4. Click **Test Connection**

### 3. Ledger Group Mappings

Configure how Odoo partners map to Tally ledger groups:
- **Customer Parent Group**: Default `Sundry Debtors`
- **Vendor Parent Group**: Default `Sundry Creditors`

## Usage

### Automatic Sync

Once configured, sync happens automatically:
- Create a new customer/vendor → Automatically creates Ledger in Tally
- Create a new product → Automatically creates Stock Item in Tally
- Post an invoice → Automatically creates Voucher in Tally

### Manual Sync

Use the **"Sync to Tally"** button on:
- Partner form
- Product form
- Invoice form (only for posted invoices)

### Bulk Sync

From the Backend configuration:
- Click **Sync All Partners** to export all customers/vendors
- Click **Sync All Products** to export all products

### View Sync Status

Go to **TallyPrime → Sync Status** to view:
- Partner Bindings
- Product Bindings
- Invoice Bindings

Each binding shows sync state (Pending/Synced/Error) and last sync date.

## Webhook for Reverse-Sync

TallyPrime can push data to Odoo using webhooks.

**Endpoint:** `POST /tally/webhook/import`

**Request Format:**
```json
{
    "type": "LEDGER",
    "action": "CREATE",
    "data": {
        "NAME": "Customer Name",
        "PARENT": "Sundry Debtors",
        "EMAIL": "customer@example.com",
        "LEDGERPHONE": "1234567890"
    }
}
```

**Supported Types:** `LEDGER`, `STOCKITEM`, `VOUCHER`

## Troubleshooting

### Connection Failed

1. Verify TallyPrime HTTP server is running
2. Check firewall allows port 9000
3. Confirm company name exactly matches Tally

### Sync Errors

Check **TallyPrime → Sync Status** for error details:
- View binding record to see `sync_error` field
- Click **Retry** button to re-attempt sync

### Logs

Check Odoo logs for detailed sync information:
```bash
tail -f /var/log/odoo/odoo.log | grep -i tally
```

## XML Format Reference

The module generates TallyPrime-compatible XML for import. Example Ledger XML:

```xml
<?xml version="1.0" encoding="utf-8"?>
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
                <SVCURRENTCOMPANY>Your Company Name</SVCURRENTCOMPANY>
            </STATICVARIABLES>
        </DESC>
        <DATA>
            <TALLYMESSAGE>
                <LEDGER NAME="Customer Name" ACTION="Create">
                    <NAME>Customer Name</NAME>
                    <PARENT>Sundry Debtors</PARENT>
                    <ADDRESS.LIST>
                        <ADDRESS>123 Main St, City</ADDRESS>
                    </ADDRESS.LIST>
                    <EMAIL>customer@example.com</EMAIL>
                    <LEDGERPHONE>1234567890</LEDGERPHONE>
                </LEDGER>
            </TALLYMESSAGE>
        </DATA>
    </BODY>
</ENVELOPE>
```

## License

LGPL-3

## Author

Braincuber Technologies
