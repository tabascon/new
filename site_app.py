#!/usr/bin/env python3
import csv
import json
import os
import shutil
import tempfile
import threading
from concurrent.futures import ThreadPoolExecutor, as_completed
from html import escape
from http import HTTPStatus
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from urllib.parse import parse_qs, urlparse

from jabko_parser import (
    TEMPLATE_COMPARE_FIELDS,
    fetch_text,
    parse_mygadget_product,
    parse_product,
    write_xlsx,
)


BASE_DIR = os.path.dirname(os.path.abspath(__file__))
DATASETS = [
    {
        "key": "iphone",
        "title": "iPhone",
        "file": os.path.join(BASE_DIR, "iphone_products.csv"),
        "source": os.path.join(BASE_DIR, "template_price_compare.csv"),
    },
    {
        "key": "other",
        "title": "MacBook/iPad/iMac",
        "file": os.path.join(BASE_DIR, "other_products.csv"),
        "source": os.path.join(BASE_DIR, "other_products_price_compare.csv"),
    },
]
DOWNLOAD_NAME = "price_compare.xlsx"
EDIT_BACKUP_FILE = os.path.join(BASE_DIR, "site_edit_backup.csv")
BASE_FIELDS = list(TEMPLATE_COMPARE_FIELDS)
DOWNLOAD_FIELDS = BASE_FIELDS + ["deviation_uah"]
REFRESH_WORKERS = 5
REFRESH_LOCK = threading.Lock()
REFRESH_JOB = {
    "running": False,
    "done": False,
    "current": 0,
    "total": 0,
    "percent": 0,
    "message": "",
    "result": None,
}

EDITABLE_FIELDS = [
    "jabko_name",
    "jabko_url",
    "mygadget_name",
    "mygadget_url",
]

FIELD_LABELS = {
    "jabko_url": "URL Jabko",
    "jabko_name": "Товар Jabko",
    "jabko_price_uah": "Ціна Jabko",
    "mygadget_url": "URL MyGadget",
    "mygadget_name": "Товар MyGadget",
    "mygadget_price_uah": "Ціна MyGadget",
    "deviation_uah": "Відхилення",
}


def ensure_data_file():
    for dataset in DATASETS:
        if os.path.exists(dataset["file"]):
            continue
        if os.path.exists(dataset["source"]):
            shutil.copyfile(dataset["source"], dataset["file"])
            continue
        with open(dataset["file"], "w", encoding="utf-8-sig", newline="") as file:
            writer = csv.DictWriter(file, fieldnames=BASE_FIELDS)
            writer.writeheader()


def read_section_rows(dataset):
    ensure_data_file()
    with open(dataset["file"], encoding="utf-8-sig", newline="") as file:
        reader = csv.DictReader(file)
        rows = []
        for row in reader:
            rows.append({field: row.get(field, "") for field in BASE_FIELDS})
        return rows


def read_sections():
    return [
        {
            "key": dataset["key"],
            "title": dataset["title"],
            "rows": read_section_rows(dataset),
        }
        for dataset in DATASETS
    ]


def dataset_by_key(section_key):
    for dataset in DATASETS:
        if dataset["key"] == section_key:
            return dataset
    return None


def write_section_rows(dataset, rows):
    with open(dataset["file"], "w", encoding="utf-8-sig", newline="") as file:
        writer = csv.DictWriter(file, fieldnames=BASE_FIELDS)
        writer.writeheader()
        writer.writerows(rows)


def write_edit_backup():
    fieldnames = ["section"] + BASE_FIELDS
    with open(EDIT_BACKUP_FILE, "w", encoding="utf-8-sig", newline="") as file:
        writer = csv.DictWriter(file, fieldnames=fieldnames)
        writer.writeheader()
        for dataset in DATASETS:
            for row in read_section_rows(dataset):
                backup_row = {"section": dataset["key"]}
                backup_row.update({field: row.get(field, "") for field in BASE_FIELDS})
                writer.writerow(backup_row)


def fetch_exact_price(url, site):
    url = str(url or "").strip()
    if not url:
        return ""

    lowered_url = url.lower()
    if site == "jabko":
        if "jabko.ua" not in lowered_url:
            raise ValueError("URL не з jabko.ua")
        product = parse_product(url, fetch_text(url, timeout=20, retries=1))
    elif site == "mygadget":
        if "mygadget.ua" not in lowered_url:
            raise ValueError("URL не з mygadget.ua")
        product = parse_mygadget_product(url, fetch_text(url, timeout=20, retries=1))
    else:
        raise ValueError("Невідомий сайт")

    price = str(product.get("price_uah", "") or "").strip()
    if not price:
        raise ValueError("Ціну не знайдено")
    return price


def refresh_changed_prices(row, old_row, section_title, row_number, result):
    targets = [
        ("jabko", "jabko_url", "jabko_price_uah", "Jabko"),
        ("mygadget", "mygadget_url", "mygadget_price_uah", "MyGadget"),
    ]
    for site, url_field, price_field, label in targets:
        new_url = row.get(url_field, "").strip()
        old_url = old_row.get(url_field, "").strip()
        if not new_url:
            if old_url or row.get(price_field, "").strip():
                row[price_field] = ""
            continue
        if new_url == old_url:
            continue
        try:
            row[price_field] = fetch_exact_price(new_url, site)
            result["updated"] += 1
        except Exception as exc:
            result["failed"] += 1
            result["errors"].append(f"{section_title}, рядок {row_number}, {label}: {exc}")


def refresh_row_prices(row, section_title, row_number):
    result = {"title": "Рядок оновлено", "updated": 0, "failed": 0, "errors": []}
    for site, url_field, price_field, label in [
        ("jabko", "jabko_url", "jabko_price_uah", "Jabko"),
        ("mygadget", "mygadget_url", "mygadget_price_uah", "MyGadget"),
    ]:
        url = row.get(url_field, "").strip()
        if not url:
            row[price_field] = ""
            continue
        try:
            row[price_field] = fetch_exact_price(url, site)
            result["updated"] += 1
        except Exception as exc:
            result["failed"] += 1
            result["errors"].append(f"{section_title}, рядок {row_number}, {label}: {exc}")
    return result


def parse_price(value):
    text = str(value or "").strip()
    if not text:
        return None
    digits = "".join(ch for ch in text if ch.isdigit() or ch == "-")
    if not digits or digits == "-":
        return None
    try:
        return int(digits)
    except ValueError:
        return None


def deviation_value(row):
    jabko_price = parse_price(row.get("jabko_price_uah"))
    mygadget_price = parse_price(row.get("mygadget_price_uah"))
    if jabko_price is None or mygadget_price is None:
        return ""
    return str(mygadget_price - jabko_price)


def row_with_deviation(row):
    enriched = {field: row.get(field, "") for field in BASE_FIELDS}
    enriched["deviation_uah"] = deviation_value(row)
    return enriched


def money(value):
    value = str(value or "").strip()
    if not value:
        return ""
    return f"{value} грн"


def render_deviation(row):
    value = deviation_value(row)
    if value == "":
        return '<span class="muted">-</span>'
    amount = int(value)
    sign = "+" if amount > 0 else ""
    css_class = "positive" if amount > 0 else "negative" if amount < 0 else "neutral"
    return f'<span class="deviation {css_class}">{sign}{amount} грн</span>'


def render_url(value, label=None):
    value = str(value or "").strip()
    if not value:
        return '<span class="muted">-</span>'
    text = label or value
    return f'<a href="{escape(value)}" target="_blank" rel="noopener">{escape(text)}</a>'


def render_linked_name(name, url):
    name = str(name or "").strip()
    if not name:
        return '<span class="muted">-</span>'
    url = str(url or "").strip()
    if not url:
        return escape(name)
    return f'<a href="{escape(url)}" target="_blank" rel="noopener">{escape(name)}</a>'


def table_row_attrs(row):
    deviation = deviation_value(row)
    return (
        f'data-filter-row="1" '
        f'data-deviation="{escape(deviation or "0")}" '
        f'data-has-jabko-url="{1 if row.get("jabko_url", "").strip() else 0}" '
        f'data-has-mygadget-url="{1 if row.get("mygadget_url", "").strip() else 0}" '
        f'data-has-jabko-price="{1 if row.get("jabko_price_uah", "").strip() else 0}" '
        f'data-has-mygadget-price="{1 if row.get("mygadget_price_uah", "").strip() else 0}"'
    )


def render_filter_controls():
    return """
    <section class="filter-panel">
      <div class="filter-grid">
        <label>
          <span>Пошук</span>
          <input id="table-search" type="text" placeholder="Назва або URL">
        </label>
        <label>
          <span>Фільтр</span>
          <select id="table-filter">
            <option value="all">Всі товари</option>
            <option value="mygadget-cheaper">MyGadget дешевший</option>
            <option value="jabko-cheaper">Jabko дешевший</option>
            <option value="missing-mygadget-url">Без MyGadget URL</option>
            <option value="missing-price">Без ціни</option>
            <option value="problem">Проблемні рядки</option>
          </select>
        </label>
        <label>
          <span>Сортування</span>
          <select id="table-sort">
            <option value="default">Як у таблиці</option>
            <option value="diff-desc">Відхилення: більше зверху</option>
            <option value="diff-asc">Відхилення: менше зверху</option>
            <option value="diff-abs">Найбільша різниця</option>
            <option value="name">Назва A-Z</option>
          </select>
        </label>
      </div>
      <div id="filter-meta" class="filter-meta"></div>
    </section>"""


def page_shell(title, active, body):
    nav = [
        ("Таблиця", "/", "table"),
        ("Адмінка", "/admin", "admin"),
    ]
    links = "\n".join(
        f'<a class="nav-link {"active" if key == active else ""}" href="{href}">{label}</a>'
        for label, href, key in nav
    )
    return f"""<!doctype html>
<html lang="uk">
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width, initial-scale=1">
  <title>{escape(title)}</title>
  <style>
    :root {{
      color-scheme: light;
      --bg: #f7f7f4;
      --panel: #ffffff;
      --text: #171717;
      --muted: #6f6f68;
      --line: #deded8;
      --soft: #efefeb;
      --accent: #10a37f;
      --accent-dark: #087a5f;
      --shadow: 0 18px 50px rgba(0, 0, 0, 0.07);
    }}
    * {{ box-sizing: border-box; }}
    body {{
      margin: 0;
      background: var(--bg);
      color: var(--text);
      font: 14px/1.45 -apple-system, BlinkMacSystemFont, "Segoe UI", sans-serif;
    }}
    a {{ color: var(--accent-dark); text-decoration: none; }}
    a:hover {{ text-decoration: underline; }}
    .topbar {{
      position: sticky;
      top: 0;
      z-index: 5;
      background: rgba(247, 247, 244, 0.9);
      border-bottom: 1px solid var(--line);
      backdrop-filter: blur(16px);
    }}
    .topbar-inner {{
      max-width: 1440px;
      margin: 0 auto;
      padding: 14px 24px;
      display: flex;
      align-items: center;
      justify-content: space-between;
      gap: 16px;
    }}
    .brand {{
      display: flex;
      align-items: center;
      gap: 10px;
      font-weight: 700;
      letter-spacing: 0;
    }}
    .mark {{
      width: 28px;
      height: 28px;
      border-radius: 7px;
      background: var(--text);
      display: grid;
      place-items: center;
      color: #fff;
      font-size: 13px;
    }}
    .nav {{
      display: flex;
      gap: 6px;
      align-items: center;
      flex-wrap: wrap;
      justify-content: flex-end;
    }}
    .nav-link, .button {{
      border: 1px solid var(--line);
      background: var(--panel);
      color: var(--text);
      min-height: 36px;
      display: inline-flex;
      align-items: center;
      justify-content: center;
      gap: 8px;
      border-radius: 8px;
      padding: 8px 12px;
      font-weight: 650;
      text-decoration: none;
      cursor: pointer;
      white-space: nowrap;
    }}
    .nav-link.active, .button.primary {{
      background: var(--text);
      border-color: var(--text);
      color: #fff;
    }}
    .button.green {{
      background: var(--accent);
      border-color: var(--accent);
      color: #fff;
    }}
    .wrap {{
      max-width: 1440px;
      margin: 0 auto;
      padding: 24px;
    }}
    .toolbar {{
      display: flex;
      align-items: center;
      justify-content: space-between;
      gap: 14px;
      margin-bottom: 16px;
      flex-wrap: wrap;
    }}
    h1 {{
      margin: 0;
      font-size: 24px;
      line-height: 1.2;
      letter-spacing: 0;
    }}
    .meta {{
      color: var(--muted);
      font-size: 13px;
      margin-top: 4px;
    }}
    .filter-panel {{
      background: var(--panel);
      border: 1px solid var(--line);
      border-radius: 8px;
      box-shadow: var(--shadow);
      padding: 14px;
      margin-bottom: 16px;
    }}
    .filter-grid {{
      display: grid;
      grid-template-columns: minmax(220px, 1.5fr) minmax(180px, 1fr) minmax(220px, 1fr);
      gap: 12px;
      align-items: end;
    }}
    .filter-grid label {{
      display: grid;
      gap: 6px;
      color: var(--muted);
      font-size: 12px;
      font-weight: 750;
      text-transform: uppercase;
    }}
    select {{
      width: 100%;
      border: 1px solid var(--line);
      background: #fff;
      color: var(--text);
      border-radius: 7px;
      padding: 9px 10px;
      font: inherit;
      min-height: 38px;
    }}
    .filter-meta {{
      color: var(--muted);
      font-size: 13px;
      margin-top: 10px;
    }}
    .table-shell {{
      background: var(--panel);
      border: 1px solid var(--line);
      border-radius: 8px;
      box-shadow: var(--shadow);
      overflow: auto;
      margin-bottom: 18px;
    }}
    details.section {{
      margin-bottom: 18px;
    }}
    details.section > summary {{
      list-style: none;
      display: flex;
      align-items: center;
      justify-content: space-between;
      gap: 16px;
      padding: 16px 18px;
      background: var(--panel);
      border: 1px solid var(--line);
      border-radius: 8px;
      box-shadow: var(--shadow);
      cursor: pointer;
      font-weight: 750;
    }}
    details.section > summary::-webkit-details-marker {{ display: none; }}
    details.section[open] > summary {{
      border-bottom-left-radius: 0;
      border-bottom-right-radius: 0;
      border-bottom-color: transparent;
    }}
    details.section .table-shell {{
      border-top-left-radius: 0;
      border-top-right-radius: 0;
      box-shadow: var(--shadow);
    }}
    .summary-left {{
      display: flex;
      align-items: baseline;
      gap: 10px;
      flex-wrap: wrap;
    }}
    .summary-title {{
      font-size: 17px;
    }}
    .summary-count {{
      color: var(--muted);
      font-size: 13px;
      font-weight: 650;
    }}
    .chevron {{
      color: var(--muted);
      font-size: 18px;
      transition: transform 0.16s ease;
    }}
    details.section[open] .chevron {{ transform: rotate(180deg); }}
    table {{
      width: 100%;
      border-collapse: separate;
      border-spacing: 0;
      min-width: 960px;
    }}
    th, td {{
      border-bottom: 1px solid var(--line);
      padding: 12px;
      text-align: left;
      vertical-align: top;
    }}
    th {{
      top: 65px;
      background: #fbfbf8;
      z-index: 2;
      font-size: 12px;
      color: #44443f;
      text-transform: uppercase;
      letter-spacing: 0;
    }}
    tr:last-child td {{ border-bottom: 0; }}
    tbody tr:hover td {{ background: #fafaf7; }}
    tr.filtered-out {{ display: none; }}
    .price {{
      font-weight: 750;
      white-space: nowrap;
    }}
    .deviation {{
      display: inline-flex;
      align-items: center;
      justify-content: flex-end;
      min-width: 88px;
      border-radius: 7px;
      padding: 4px 8px;
      font-weight: 800;
      white-space: nowrap;
    }}
    .deviation.positive {{
      color: #087a5f;
      background: #e7f7f1;
    }}
    .deviation.negative {{
      color: #b42318;
      background: #feeceb;
    }}
    .deviation.neutral {{
      color: #55554f;
      background: var(--soft);
    }}
    .muted {{ color: var(--muted); }}
    .num {{
      width: 52px;
      color: var(--muted);
      text-align: right;
    }}
    .name-col {{ min-width: 280px; }}
    .url-col {{ min-width: 280px; }}
    input[type="text"], textarea {{
      width: 100%;
      border: 1px solid var(--line);
      background: #fff;
      color: var(--text);
      border-radius: 7px;
      padding: 9px 10px;
      font: inherit;
      min-height: 38px;
      outline: none;
    }}
    textarea {{
      resize: vertical;
      min-height: 58px;
    }}
    input[type="text"]:focus, textarea:focus {{
      border-color: var(--accent);
      box-shadow: 0 0 0 3px rgba(16, 163, 127, 0.14);
    }}
    .admin-table th {{ top: 65px; }}
    .actions {{
      display: flex;
      gap: 8px;
      align-items: center;
      flex-wrap: wrap;
    }}
    .notice {{
      border: 1px solid #b8e2d6;
      background: #ecfaf5;
      color: #0b5d49;
      border-radius: 8px;
      padding: 10px 12px;
      margin-bottom: 14px;
      font-weight: 650;
    }}
    .notice.error {{
      border-color: #f5c2c0;
      background: #fff0ef;
      color: #8f1d15;
    }}
    .notice ul {{
      margin: 8px 0 0;
      padding-left: 18px;
      font-weight: 500;
    }}
    .section-actions {{
      display: flex;
      justify-content: flex-end;
      gap: 8px;
      padding: 12px;
      border-top: 1px solid var(--line);
      background: #fbfbf8;
    }}
    .progress-panel {{
      display: none;
      border: 1px solid var(--line);
      background: var(--panel);
      border-radius: 8px;
      box-shadow: var(--shadow);
      padding: 14px;
      margin-bottom: 16px;
    }}
    .progress-panel.active {{ display: block; }}
    .progress-top {{
      display: flex;
      align-items: center;
      justify-content: space-between;
      gap: 12px;
      margin-bottom: 10px;
      font-weight: 750;
    }}
    .progress-track {{
      height: 12px;
      overflow: hidden;
      border-radius: 999px;
      background: var(--soft);
      border: 1px solid var(--line);
    }}
    .progress-fill {{
      width: 0%;
      height: 100%;
      background: var(--accent);
      transition: width 0.2s ease;
    }}
    .progress-detail {{
      color: var(--muted);
      font-size: 13px;
      margin-top: 8px;
    }}
    @media (max-width: 760px) {{
      .topbar-inner, .wrap {{ padding-left: 14px; padding-right: 14px; }}
      .topbar-inner {{ align-items: flex-start; flex-direction: column; }}
      .filter-grid {{ grid-template-columns: 1fr; }}
      th {{ top: 106px; }}
      h1 {{ font-size: 21px; }}
    }}
  </style>
</head>
<body>
  <header class="topbar">
    <div class="topbar-inner">
      <div class="brand"><span class="mark">AI</span><span>Price Compare</span></div>
      <nav class="nav">{links}</nav>
    </div>
  </header>
  <main class="wrap">{body}</main>
  <script>
    function addAdminRow(sectionKey) {{
      const countInput = document.querySelector(`[name="${{sectionKey}}__row_count"]`);
      const tbody = document.querySelector(`[data-section-body="${{sectionKey}}"]`);
      if (!countInput || !tbody) return;

      const index = Number(countInput.value || "0");
      const rowNumber = index + 1;
      const tr = document.createElement("tr");
      tr.innerHTML = `
        <td class="num">${{rowNumber}}</td>
        <td class="name-col"><textarea name="${{sectionKey}}__jabko_name__${{index}}"></textarea></td>
        <td class="url-col"><textarea name="${{sectionKey}}__jabko_url__${{index}}"></textarea></td>
        <td class="name-col"><textarea name="${{sectionKey}}__mygadget_name__${{index}}"></textarea></td>
        <td class="url-col"><textarea name="${{sectionKey}}__mygadget_url__${{index}}"></textarea></td>
        <td class="price"></td>
        <td class="price"></td>
        <td><span class="muted">-</span></td>
        <td><button class="button" type="button" onclick="refreshAdminRow('${{sectionKey}}', ${{index}}, this)">Оновити</button></td>
      `;
      tr.dataset.filterRow = "1";
      tr.dataset.deviation = "0";
      tr.dataset.hasJabkoUrl = "0";
      tr.dataset.hasMygadgetUrl = "0";
      tr.dataset.hasJabkoPrice = "0";
      tr.dataset.hasMygadgetPrice = "0";
      tbody.appendChild(tr);
      countInput.value = String(rowNumber);
      const firstInput = tr.querySelector("textarea");
      if (firstInput) firstInput.focus();
      applyTableTools();
    }}

    function rowText(row) {{
      const fields = [...row.querySelectorAll("textarea, input")].map((item) => item.value || "");
      return `${{row.textContent || ""}} ${{fields.join(" ")}}`.toLowerCase();
    }}

    function rowMatchesFilter(row, mode) {{
      const deviation = Number(row.dataset.deviation || "0");
      const hasJabkoUrl = row.dataset.hasJabkoUrl === "1";
      const hasMygadgetUrl = row.dataset.hasMygadgetUrl === "1";
      const hasJabkoPrice = row.dataset.hasJabkoPrice === "1";
      const hasMygadgetPrice = row.dataset.hasMygadgetPrice === "1";
      if (mode === "mygadget-cheaper") return deviation < 0;
      if (mode === "jabko-cheaper") return deviation > 0;
      if (mode === "missing-mygadget-url") return !hasMygadgetUrl;
      if (mode === "missing-price") return !hasJabkoPrice || !hasMygadgetPrice;
      if (mode === "problem") return !hasJabkoUrl || !hasMygadgetUrl || !hasJabkoPrice || !hasMygadgetPrice;
      return true;
    }}

    function compareRows(a, b, mode) {{
      const ad = Number(a.dataset.deviation || "0");
      const bd = Number(b.dataset.deviation || "0");
      if (mode === "diff-desc") return bd - ad;
      if (mode === "diff-asc") return ad - bd;
      if (mode === "diff-abs") return Math.abs(bd) - Math.abs(ad);
      if (mode === "name") return rowText(a).localeCompare(rowText(b), "uk");
      return Number(a.dataset.originalIndex || "0") - Number(b.dataset.originalIndex || "0");
    }}

    function applyTableTools() {{
      const search = (document.getElementById("table-search")?.value || "").trim().toLowerCase();
      const filter = document.getElementById("table-filter")?.value || "all";
      const sort = document.getElementById("table-sort")?.value || "default";
      let shown = 0;
      let total = 0;

      document.querySelectorAll("tbody[data-filter-body], tbody[data-section-body]").forEach((tbody) => {{
        const rows = [...tbody.querySelectorAll("tr[data-filter-row]")];
        rows.forEach((row, index) => {{
          if (!row.dataset.originalIndex) row.dataset.originalIndex = String(index);
        }});
        rows.sort((a, b) => compareRows(a, b, sort)).forEach((row) => tbody.appendChild(row));
        rows.forEach((row) => {{
          total += 1;
          const visible = (!search || rowText(row).includes(search)) && rowMatchesFilter(row, filter);
          row.classList.toggle("filtered-out", !visible);
          if (visible) shown += 1;
        }});
      }});

      const meta = document.getElementById("filter-meta");
      if (meta) meta.textContent = `Показано ${{shown}} з ${{total}} рядків`;
    }}

    function updateRowDom(row, data) {{
      if (!row || !data || !data.row) return;
      const item = data.row;
      row.dataset.deviation = data.deviation || "0";
      row.dataset.hasJabkoUrl = item.jabko_url ? "1" : "0";
      row.dataset.hasMygadgetUrl = item.mygadget_url ? "1" : "0";
      row.dataset.hasJabkoPrice = item.jabko_price_uah ? "1" : "0";
      row.dataset.hasMygadgetPrice = item.mygadget_price_uah ? "1" : "0";
      const prices = row.querySelectorAll("[data-price-field]");
      prices.forEach((cell) => {{
        const field = cell.dataset.priceField;
        cell.textContent = item[field] ? `${{item[field]}} грн` : "";
      }});
      const deviationCell = row.querySelector("[data-deviation-cell]");
      if (deviationCell) deviationCell.innerHTML = data.deviation_html || '<span class="muted">-</span>';
      applyTableTools();
    }}

    async function refreshAdminRow(sectionKey, index, button) {{
      const row = button.closest("tr");
      if (!row) return;
      button.disabled = true;
      button.textContent = "Оновлення...";
      const data = new URLSearchParams();
      data.set("section", sectionKey);
      data.set("index", String(index));
      ["jabko_name", "jabko_url", "mygadget_name", "mygadget_url"].forEach((field) => {{
        const input = row.querySelector(`[name="${{sectionKey}}__${{field}}__${{index}}"]`);
        data.set(field, input ? input.value : "");
      }});
      try {{
        const response = await fetch("/refresh-row", {{
          method: "POST",
          body: data,
          headers: {{ "Content-Type": "application/x-www-form-urlencoded;charset=UTF-8" }},
        }});
        updateRowDom(row, await response.json());
      }} finally {{
        button.disabled = false;
        button.textContent = "Оновити";
      }}
    }}

    function setProgressState(state) {{
      const panel = document.getElementById("refresh-progress");
      const fill = document.getElementById("refresh-progress-fill");
      const percent = document.getElementById("refresh-progress-percent");
      const detail = document.getElementById("refresh-progress-detail");
      if (!panel || !fill || !percent || !detail) return;

      const value = Math.max(0, Math.min(100, Number(state.percent || 0)));
      panel.classList.add("active");
      fill.style.width = `${{value}}%`;
      percent.textContent = `${{value}}%`;
      detail.textContent = state.message || `${{state.current || 0}} з ${{state.total || 0}}`;
    }}

    async function pollRefreshStatus() {{
      const response = await fetch("/refresh-status", {{ cache: "no-store" }});
      const state = await response.json();
      setProgressState(state);
      if (state.running) {{
        window.setTimeout(pollRefreshStatus, 800);
        return;
      }}
      if (state.done) {{
        window.setTimeout(() => window.location.href = "/admin?refresh_done=1", 900);
      }}
    }}

    async function startRefreshAll(event) {{
      return startRefreshJob(event, "");
    }}

    async function startRefreshSection(event, sectionKey) {{
      return startRefreshJob(event, sectionKey);
    }}

    async function startRefreshJob(event, sectionKey) {{
      event.preventDefault();
      const form = event.currentTarget.closest("form");
      if (!form) return;
      const button = event.currentTarget;
      button.disabled = true;
      setProgressState({{ percent: 0, current: 0, total: 0, message: "Старт оновлення..." }});

      const data = new FormData(form);
      data.set("action", "refresh_all");
      if (sectionKey) data.set("section", sectionKey);
      const response = await fetch("/refresh-start", {{
        method: "POST",
        body: new URLSearchParams(data),
        headers: {{ "Content-Type": "application/x-www-form-urlencoded;charset=UTF-8" }},
      }});
      const state = await response.json();
      setProgressState(state);
      if (state.running) {{
        pollRefreshStatus();
      }} else {{
        button.disabled = false;
      }}
    }}

    ["table-search", "table-filter", "table-sort"].forEach((id) => {{
      document.addEventListener("input", (event) => {{
        if (event.target && event.target.id === id) applyTableTools();
      }});
      document.addEventListener("change", (event) => {{
        if (event.target && event.target.id === id) applyTableTools();
      }});
    }});
    document.addEventListener("DOMContentLoaded", applyTableTools);
  </script>
</body>
</html>"""


def render_public_section(section, open_section=False):
    table_rows = []
    for index, row in enumerate(section["rows"], start=1):
        table_rows.append(f"""
        <tr {table_row_attrs(row)}>
          <td class="num">{index}</td>
          <td class="name-col">{render_linked_name(row.get("jabko_name", ""), row.get("jabko_url", ""))}</td>
          <td class="price">{escape(money(row.get("jabko_price_uah", "")))}</td>
          <td class="name-col">{render_linked_name(row.get("mygadget_name", ""), row.get("mygadget_url", ""))}</td>
          <td class="price">{escape(money(row.get("mygadget_price_uah", "")))}</td>
          <td>{render_deviation(row)}</td>
        </tr>""")

    open_attr = " open" if open_section else ""
    return f"""
    <details class="section"{open_attr}>
      <summary>
        <span class="summary-left">
          <span class="summary-title">{escape(section["title"])}</span>
          <span class="summary-count">{len(section["rows"])} товарів</span>
        </span>
        <span class="chevron">⌄</span>
      </summary>
      <section class="table-shell">
        <table>
          <thead>
            <tr>
              <th class="num">#</th>
              <th>Товар Jabko</th>
              <th>Ціна Jabko</th>
              <th>Товар MyGadget</th>
              <th>Ціна MyGadget</th>
              <th>Відхилення</th>
            </tr>
          </thead>
          <tbody data-filter-body="1">{''.join(table_rows)}</tbody>
        </table>
      </section>
    </details>"""


def render_public(sections):
    total_rows = sum(len(section["rows"]) for section in sections)
    section_html = "\n".join(
        render_public_section(section, open_section=index == 0)
        for index, section in enumerate(sections)
    )
    body = f"""
    <section class="toolbar">
      <div>
        <h1>Порівняння цін</h1>
        <div class="meta">{total_rows} товарів у {len(sections)} розділах</div>
      </div>
      <div class="actions">
        <a class="button green" href="/download.xlsx">Скачати XLSX</a>
      </div>
    </section>
    {render_filter_controls()}
    {section_html}"""
    return page_shell("Порівняння цін", "table", body)


def render_admin_section(section, open_section=False):
    table_rows = []
    section_key = section["key"]
    for index, row in enumerate(section["rows"]):
        table_rows.append(f"""
        <tr {table_row_attrs(row)}>
          <td class="num">{index + 1}</td>
          <td class="name-col"><textarea name="{section_key}__jabko_name__{index}">{escape(row.get("jabko_name", ""))}</textarea></td>
          <td class="url-col"><textarea name="{section_key}__jabko_url__{index}">{escape(row.get("jabko_url", ""))}</textarea></td>
          <td class="name-col"><textarea name="{section_key}__mygadget_name__{index}">{escape(row.get("mygadget_name", ""))}</textarea></td>
          <td class="url-col"><textarea name="{section_key}__mygadget_url__{index}">{escape(row.get("mygadget_url", ""))}</textarea></td>
          <td class="price" data-price-field="jabko_price_uah">{escape(money(row.get("jabko_price_uah", "")))}</td>
          <td class="price" data-price-field="mygadget_price_uah">{escape(money(row.get("mygadget_price_uah", "")))}</td>
          <td data-deviation-cell="1">{render_deviation(row)}</td>
          <td><button class="button" type="button" onclick="refreshAdminRow('{escape(section_key)}', {index}, this)">Оновити</button></td>
        </tr>""")

    open_attr = " open" if open_section else ""
    return f"""
    <details class="section"{open_attr}>
      <summary>
        <span class="summary-left">
          <span class="summary-title">{escape(section["title"])}</span>
          <span class="summary-count">{len(section["rows"])} рядків</span>
        </span>
        <span class="chevron">⌄</span>
      </summary>
      <input type="hidden" name="{section_key}__row_count" value="{len(section["rows"])}">
      <section class="table-shell">
        <table class="admin-table">
          <thead>
            <tr>
              <th class="num">#</th>
              <th>Імʼя товару Jabko</th>
              <th>URL товару Jabko</th>
              <th>Імʼя товару MyGadget</th>
              <th>URL товару MyGadget</th>
              <th>Ціна Jabko</th>
              <th>Ціна MyGadget</th>
              <th>Відхилення</th>
              <th>Дії</th>
            </tr>
          </thead>
          <tbody data-section-body="{escape(section_key)}">{''.join(table_rows)}</tbody>
        </table>
        <div class="section-actions">
          <button class="button" type="button" onclick="startRefreshSection(event, '{escape(section_key)}')">Оновити розділ</button>
          <button class="button" type="button" onclick="addAdminRow('{escape(section_key)}')">Додати рядок</button>
        </div>
      </section>
    </details>"""


def render_save_notice(saved=False, result=None):
    if not saved:
        return ""
    result = result or {"updated": 0, "failed": 0, "errors": []}
    title = result.get("title", "Збережено")
    notice = (
        f'<div class="notice">{escape(title)}. Оновлено цін: {result.get("updated", 0)}. '
        f'Помилок: {result.get("failed", 0)}.</div>'
    )
    errors = result.get("errors", [])
    if not errors:
        return notice
    visible_errors = "".join(f"<li>{escape(error)}</li>" for error in errors[:8])
    extra = len(errors) - 8
    if extra > 0:
        visible_errors += f"<li>І ще {extra} помилок.</li>"
    return notice + f'<div class="notice error">Не вдалося оновити деякі URL:<ul>{visible_errors}</ul></div>'


def render_admin(sections, saved=False, save_result=None):
    total_rows = sum(len(section["rows"]) for section in sections)
    section_html = "\n".join(
        render_admin_section(section, open_section=index == 0)
        for index, section in enumerate(sections)
    )
    notice = render_save_notice(saved=saved, result=save_result)
    body = f"""
    <form method="post" action="/admin">
    <section class="toolbar">
      <div>
        <h1>Адмінка</h1>
        <div class="meta">{total_rows} рядків у {len(sections)} розділах</div>
      </div>
      <div class="actions">
        <button class="button primary" type="submit" name="action" value="save">Зберегти</button>
        <button class="button" type="submit" name="action" value="refresh_all" onclick="startRefreshAll(event)">Оновити ціни</button>
        <a class="button green" href="/download.xlsx">Скачати XLSX</a>
      </div>
    </section>
    <section id="refresh-progress" class="progress-panel">
      <div class="progress-top">
        <span>Оновлення цін</span>
        <span id="refresh-progress-percent">0%</span>
      </div>
      <div class="progress-track">
        <div id="refresh-progress-fill" class="progress-fill"></div>
      </div>
      <div id="refresh-progress-detail" class="progress-detail">Очікування...</div>
    </section>
    {render_filter_controls()}
    {notice}
      {section_html}
    </form>"""
    return page_shell("Адмінка", "admin", body)


def update_rows_from_form(body, refresh_changed=True):
    params = parse_qs(body, keep_blank_values=True)
    result = {"title": "Збережено", "updated": 0, "failed": 0, "errors": []}
    write_edit_backup()
    for dataset in DATASETS:
        current_rows = read_section_rows(dataset)
        prefix = dataset["key"]
        row_count = int(params.get(f"{prefix}__row_count", [len(current_rows)])[0] or 0)
        rows = []

        for index in range(row_count):
            is_new_row = index >= len(current_rows)
            old_row = current_rows[index] if not is_new_row else {}
            row = dict(old_row)
            for field in EDITABLE_FIELDS:
                row[field] = params.get(f"{prefix}__{field}__{index}", [""])[0].strip()

            if is_new_row and not any(row.get(field, "") for field in EDITABLE_FIELDS):
                continue

            if refresh_changed:
                refresh_changed_prices(row, old_row, dataset["title"], index + 1, result)
            rows.append({field: row.get(field, "") for field in BASE_FIELDS})

        write_section_rows(dataset, rows)
    return result


def update_refresh_job(**updates):
    with REFRESH_LOCK:
        REFRESH_JOB.update(updates)
        return dict(REFRESH_JOB)


def refresh_job_snapshot():
    with REFRESH_LOCK:
        return dict(REFRESH_JOB)


def collect_refresh_tasks(sections, section_key=None):
    tasks = []
    for dataset_index, section in enumerate(sections):
        if section_key and section["key"] != section_key:
            continue
        for row_index, row in enumerate(section["rows"]):
            for site, url_field, price_field, label in [
                ("jabko", "jabko_url", "jabko_price_uah", "Jabko"),
                ("mygadget", "mygadget_url", "mygadget_price_uah", "MyGadget"),
            ]:
                url = row.get(url_field, "").strip()
                if not url:
                    row[price_field] = ""
                    continue
                tasks.append({
                    "dataset_index": dataset_index,
                    "section_title": section["title"],
                    "row_index": row_index,
                    "row_number": row_index + 1,
                    "site": site,
                    "url": url,
                    "price_field": price_field,
                    "label": label,
                })
    return tasks


def fetch_refresh_task(task):
    return task, fetch_exact_price(task["url"], task["site"])


def refresh_all_prices(progress_callback=None, section_key=None):
    result = {"title": "Оновлення завершено", "updated": 0, "failed": 0, "errors": []}
    write_edit_backup()
    sections = read_sections()
    tasks = collect_refresh_tasks(sections, section_key=section_key)
    total = len(tasks)
    current = 0
    if progress_callback:
        progress_callback(current, total, f"Підготовка... Потоків: {REFRESH_WORKERS}")

    with ThreadPoolExecutor(max_workers=REFRESH_WORKERS) as executor:
        futures = {executor.submit(fetch_refresh_task, task): task for task in tasks}
        for future in as_completed(futures):
            current += 1
            try:
                task, price = future.result()
                sections[task["dataset_index"]]["rows"][task["row_index"]][task["price_field"]] = price
                result["updated"] += 1
                message = f"{task['section_title']}, рядок {task['row_number']}, {task['label']}"
            except Exception as exc:
                task = futures[future]
                result["failed"] += 1
                message = f"{task['section_title']}, рядок {task['row_number']}, {task['label']}"
                result["errors"].append(f"{message}: {exc}")
            if progress_callback:
                progress_callback(current, total, message)

    for dataset, section in zip(DATASETS, sections):
        write_section_rows(dataset, section["rows"])
    if progress_callback:
        progress_callback(total, total, "Готово")
    return result


def run_refresh_job(body, section_key=None):
    def progress(current, total, message):
        percent = int((current / total) * 100) if total else 100
        update_refresh_job(current=current, total=total, percent=percent, message=message)

    try:
        update_rows_from_form(body, refresh_changed=False)
        result = refresh_all_prices(progress_callback=progress, section_key=section_key)
        update_refresh_job(
            running=False,
            done=True,
            percent=100,
            message=f"Готово. Оновлено: {result['updated']}. Помилок: {result['failed']}.",
            result=result,
        )
    except Exception as exc:
        update_refresh_job(
            running=False,
            done=True,
            message=f"Помилка оновлення: {exc}",
            result={"title": "Помилка оновлення", "updated": 0, "failed": 1, "errors": [str(exc)]},
        )


def start_refresh_job(body, section_key=None):
    with REFRESH_LOCK:
        if REFRESH_JOB.get("running"):
            return dict(REFRESH_JOB)
        REFRESH_JOB.update({
            "running": True,
            "done": False,
            "current": 0,
            "total": 0,
            "percent": 0,
            "message": "Старт оновлення...",
            "result": None,
        })
    thread = threading.Thread(target=run_refresh_job, args=(body, section_key), daemon=True)
    thread.start()
    return refresh_job_snapshot()


class SiteHandler(BaseHTTPRequestHandler):
    def send_html(self, html_text, status=HTTPStatus.OK):
        payload = html_text.encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "text/html; charset=utf-8")
        self.send_header("Content-Length", str(len(payload)))
        self.end_headers()
        self.wfile.write(payload)

    def send_json(self, data, status=HTTPStatus.OK):
        payload = json.dumps(data, ensure_ascii=False).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(payload)))
        self.end_headers()
        self.wfile.write(payload)

    def redirect(self, location):
        self.send_response(HTTPStatus.SEE_OTHER)
        self.send_header("Location", location)
        self.end_headers()

    def do_GET(self):
        path = urlparse(self.path).path
        if path == "/":
            self.send_html(render_public(read_sections()))
            return
        if path == "/admin":
            query = parse_qs(urlparse(self.path).query)
            saved = query.get("saved", ["0"])[0] == "1"
            if query.get("refresh_done", ["0"])[0] == "1":
                snapshot = refresh_job_snapshot()
                self.send_html(render_admin(read_sections(), saved=True, save_result=snapshot.get("result")))
            else:
                self.send_html(render_admin(read_sections(), saved=saved))
            return
        if path == "/refresh-status":
            self.send_json(refresh_job_snapshot())
            return
        if path == "/download.xlsx":
            self.send_xlsx()
            return
        self.send_html(page_shell("Не знайдено", "table", "<h1>Сторінку не знайдено</h1>"), HTTPStatus.NOT_FOUND)

    def do_POST(self):
        path = urlparse(self.path).path
        if path == "/refresh-start":
            length = int(self.headers.get("Content-Length", "0") or 0)
            body = self.rfile.read(length).decode("utf-8")
            params = parse_qs(body, keep_blank_values=True)
            section_key = params.get("section", [""])[0] or None
            self.send_json(start_refresh_job(body, section_key=section_key))
            return
        if path == "/refresh-row":
            length = int(self.headers.get("Content-Length", "0") or 0)
            body = self.rfile.read(length).decode("utf-8")
            params = parse_qs(body, keep_blank_values=True)
            section_key = params.get("section", [""])[0]
            index = int(params.get("index", ["0"])[0] or 0)
            dataset = dataset_by_key(section_key)
            if not dataset:
                self.send_json({"error": "Розділ не знайдено"}, HTTPStatus.BAD_REQUEST)
                return

            rows = read_section_rows(dataset)
            while len(rows) <= index:
                rows.append({field: "" for field in BASE_FIELDS})
            row = dict(rows[index])
            for field in EDITABLE_FIELDS:
                row[field] = params.get(field, [""])[0].strip()
            result = refresh_row_prices(row, dataset["title"], index + 1)
            rows[index] = {field: row.get(field, "") for field in BASE_FIELDS}
            write_edit_backup()
            write_section_rows(dataset, rows)
            self.send_json({
                "row": rows[index],
                "deviation": deviation_value(rows[index]),
                "deviation_html": render_deviation(rows[index]),
                "result": result,
            })
            return
        if path != "/admin":
            self.send_html(page_shell("Не знайдено", "table", "<h1>Сторінку не знайдено</h1>"), HTTPStatus.NOT_FOUND)
            return
        length = int(self.headers.get("Content-Length", "0") or 0)
        body = self.rfile.read(length).decode("utf-8")
        params = parse_qs(body, keep_blank_values=True)
        action = params.get("action", ["save"])[0]
        if action == "refresh_all":
            update_rows_from_form(body, refresh_changed=False)
            result = refresh_all_prices()
        else:
            result = update_rows_from_form(body, refresh_changed=True)
        self.send_html(render_admin(read_sections(), saved=True, save_result=result))

    def send_xlsx(self):
        rows = []
        for section in read_sections():
            rows.extend(row_with_deviation(row) for row in section["rows"])
        xlsx_fields = [FIELD_LABELS.get(field, field) for field in DOWNLOAD_FIELDS]
        xlsx_rows = [
            {FIELD_LABELS.get(field, field): row.get(field, "") for field in DOWNLOAD_FIELDS}
            for row in rows
        ]
        with tempfile.NamedTemporaryFile(suffix=".xlsx", delete=False) as temp:
            temp_path = temp.name
        try:
            write_xlsx(xlsx_rows, temp_path, fieldnames=xlsx_fields)
            with open(temp_path, "rb") as file:
                payload = file.read()
        finally:
            if os.path.exists(temp_path):
                os.unlink(temp_path)

        self.send_response(HTTPStatus.OK)
        self.send_header("Content-Type", "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet")
        self.send_header("Content-Disposition", f'attachment; filename="{DOWNLOAD_NAME}"')
        self.send_header("Content-Length", str(len(payload)))
        self.end_headers()
        self.wfile.write(payload)

    def log_message(self, format, *args):
        print(f"{self.address_string()} - {format % args}")


def main():
    import argparse

    parser = argparse.ArgumentParser(description="Local price comparison website.")
    parser.add_argument("--host", default="127.0.0.1")
    parser.add_argument("--port", type=int, default=8080)
    args = parser.parse_args()

    ensure_data_file()
    server = ThreadingHTTPServer((args.host, args.port), SiteHandler)
    print(f"Site: http://{args.host}:{args.port}")
    print(f"Admin: http://{args.host}:{args.port}/admin")
    server.serve_forever()


if __name__ == "__main__":
    main()
