# Price Compare Parser

Local price comparison site for Jabko and MyGadget products.

## Run

```bash
python3 site_app.py --host 127.0.0.1 --port 8080
```

Open:

- Site: http://127.0.0.1:8080/
- Admin: http://127.0.0.1:8080/admin

## Data

The site uses CSV files as editable data:

- `iphone_products.csv`
- `other_products.csv`

## Cloudflare Pages

This repo also includes a Cloudflare Pages version:

- Static frontend: `public/`
- Pages Functions API: `functions/api/`
- Initial data: `public/initial-data.json`

Cloudflare Pages settings:

- Framework preset: `None`
- Build command: leave empty
- Build output directory: `public`
- Root directory: repository root

For editable admin data, create a Workers KV namespace and bind it to the Pages
project with this exact variable name:

```text
PRICE_DATA
```

Without the `PRICE_DATA` binding, the site can show the initial table, but admin
changes cannot be saved permanently.
