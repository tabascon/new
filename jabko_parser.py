#!/usr/bin/env python3
import argparse
import csv
import html
import json
import os
import re
import sys
import time
import urllib.error
import urllib.request
import xml.etree.ElementTree as ET
import zipfile
from concurrent.futures import ThreadPoolExecutor, as_completed
from xml.sax.saxutils import escape as xml_escape


DEFAULT_SITEMAP = "https://jabko.ua/sitemap-products-uk-1.xml"
MYGADGET_SITEMAP = "https://mygadget.ua/sitemap.xml"
DEFAULT_USER_AGENT = "Mozilla/5.0 (compatible; JabkoParser/1.0; +local-script)"
FIELDS = [
    "name",
    "price_uah",
]
COMPARE_FIELDS = [
    "match_key",
    "model",
    "storage",
    "color",
    "used",
    "condition_jabko",
    "condition_mygadget",
    "battery_jabko",
    "jabko_name",
    "jabko_price_uah",
    "mygadget_name",
    "mygadget_price_uah",
    "cheaper_store",
    "price_diff_uah",
    "match_score",
]
TEMPLATE_COMPARE_FIELDS = [
    "jabko_url",
    "jabko_name",
    "jabko_price_uah",
    "mygadget_url",
    "mygadget_name",
    "mygadget_price_uah",
]
BLOCKED_STOCK_IDS = {"8", "14"}
BLOCKED_STATUS_WORDS = {
    "передзамовлення",
    "архівнийтовар",
    "preorder",
    "outofstock",
    "немаєвнаявності",
    "уточнитинанаявність",
    "очікується",
}
ALLOWED_STATUS_WORDS = {
    "залишилосьмало",
    "instock",
    "внаявності",
}
MYGADGET_EXCLUDES = [
    "/znyato-z-virobnictva/",
    "index.php",
    "?route",
    "?search",
    "?sort",
    "?limit",
    "?mfp",
]
MYGADGET_TEMPLATE_CONTAINS = [
    "/kak-novyy/iphone/",
    "/b-us/b-u-iphone/",
    "/iphones/",
]
MYGADGET_REPORT_CONTAINS = [
    "/ipad/",
    "/mac/",
    "/watchs/",
    "/music/",
    "/accessories/",
    "/b-us/b-u-ipad/",
    "/b-us/b-u-mac-2/",
    "/b-us/b-u-votch/",
    "/znyato-z-virobnictva/",
]
MYGADGET_TECHNICAL_EXCLUDES = [
    "index.php",
    "?route",
    "?search",
    "?sort",
    "?limit",
    "?mfp",
]
COLOR_ALIASES = [
    ("black titanium", ["black titanium", "чорний титан"]),
    ("natural titanium", ["natural titanium", "натуральний титан"]),
    ("white titanium", ["white titanium", "білий титан"]),
    ("desert titanium", ["desert titanium", "пустельний титан"]),
    ("blue titanium", ["blue titanium", "синій титан"]),
    ("space black", ["space black", "space-black"]),
    ("space gray", ["space gray", "space grey", "space gary", "space-gray", "spacegrey"]),
    ("midnight green", ["midnight green", "midnight-green"]),
    ("deep purple", ["deep purple"]),
    ("graphite", ["graphite"]),
    ("ultramarine", ["ultramarine"]),
    ("midnight", ["midnight"]),
    ("starlight", ["starlight"]),
    ("sky blue", ["sky blue", "sky-blue"]),
    ("cloud white", ["cloud white", "cloud-white"]),
    ("light gold", ["light gold", "light-gold"]),
    ("purple", ["lavender"]),
    ("purple", ["purple"]),
    ("dark blue", ["dark blue", "dark-blue", "deep blue", "deep-blue", "mist blue", "mist-blue"]),
    ("teal", ["teal"]),
    ("orange", ["orange"]),
    ("gray", ["gray", "grey"]),
    ("black", ["black"]),
    ("white", ["white"]),
    ("silver", ["silver"]),
    ("gold", ["gold"]),
    ("blue", ["blue"]),
    ("green", ["green"]),
    ("yellow", ["yellow"]),
    ("red", ["red", "(product)red"]),
    ("pink", ["pink"]),
]


def fetch_text(url, timeout=30, user_agent=DEFAULT_USER_AGENT, retries=2):
    headers = {
        "User-Agent": user_agent,
        "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
        "Accept-Language": "uk-UA,uk;q=0.9,en;q=0.8",
    }
    request = urllib.request.Request(url, headers=headers)
    last_error = None

    for attempt in range(retries + 1):
        try:
            with urllib.request.urlopen(request, timeout=timeout) as response:
                raw = response.read()
                charset = response.headers.get_content_charset() or "utf-8"
                return raw.decode(charset, errors="replace")
        except (urllib.error.URLError, TimeoutError) as exc:
            last_error = exc
            if attempt < retries:
                time.sleep(1.5 * (attempt + 1))

    raise RuntimeError(f"Could not fetch {url}: {last_error}")


def sitemap_urls(sitemap_url, contains=None, limit=None, excludes=None):
    xml_text = fetch_text(sitemap_url, timeout=60)
    root = ET.fromstring(xml_text)
    namespace = {"sm": "http://www.sitemaps.org/schemas/sitemap/0.9"}
    urls = []
    excludes = [item.lower() for item in (excludes or [])]

    for loc in root.findall(".//sm:loc", namespace):
        url = (loc.text or "").strip()
        if not url:
            continue
        lowered_url = url.lower()
        if contains and contains.lower() not in lowered_url:
            continue
        if any(exclude in lowered_url for exclude in excludes):
            continue
        urls.append(url)
        if limit and len(urls) >= limit:
            break

    return urls


def clean_text(value):
    if value is None:
        return ""
    value = html.unescape(str(value))
    value = re.sub(r"<br\s*/?>", "; ", value, flags=re.I)
    value = re.sub(r"<[^>]+>", " ", value)
    value = re.sub(r"\s+", " ", value)
    return value.strip()


def decode_js_escapes(value):
    value = clean_text(value)
    if "\\u" not in value and "\\/" not in value:
        return value
    try:
        return json.loads(f'"{value}"')
    except json.JSONDecodeError:
        return value


def first_match(pattern, text, flags=re.I | re.S):
    match = re.search(pattern, text, flags)
    if not match:
        return ""
    return clean_text(match.group(1))


def meta_content(html_text, name):
    escaped = re.escape(name)
    patterns = [
        rf'<meta[^>]+property=["\']{escaped}["\'][^>]+content=["\']([^"\']*)["\']',
        rf'<meta[^>]+name=["\']{escaped}["\'][^>]+content=["\']([^"\']*)["\']',
        rf'<meta[^>]+content=["\']([^"\']*)["\'][^>]+(?:property|name)=["\']{escaped}["\']',
    ]
    for pattern in patterns:
        value = first_match(pattern, html_text)
        if value:
            return value
    return ""


def normalize_price(value):
    value = clean_text(value)
    if not value:
        return ""
    if not re.search(r"\d", value):
        return ""
    match = re.search(r"[\d\s]+(?:[.,]\d+)?", value)
    if not match:
        return ""
    number = match.group(0).replace(" ", "").replace(",", ".")
    try:
        amount = float(number)
    except ValueError:
        return value
    return str(int(amount + 0.5))


def price_number(value):
    value = normalize_price(value)
    if not value:
        return None
    try:
        return float(value)
    except ValueError:
        return None


def parse_json_ld_blocks(html_text):
    blocks = re.findall(
        r'<script[^>]+type=["\']application/ld\+json["\'][^>]*>(.*?)</script>',
        html_text,
        flags=re.I | re.S,
    )
    parsed = []
    for block in blocks:
        block = html.unescape(block).strip()
        if not block:
            continue
        try:
            parsed.append(json.loads(block))
        except json.JSONDecodeError:
            continue
    return parsed


def find_product_json(value):
    if isinstance(value, dict):
        item_type = value.get("@type")
        if item_type == "Product" or (isinstance(item_type, list) and "Product" in item_type):
            return value
        for key in ("@graph", "mainEntity", "itemListElement"):
            found = find_product_json(value.get(key))
            if found:
                return found
    elif isinstance(value, list):
        for item in value:
            found = find_product_json(item)
            if found:
                return found
    return None


def as_text_or_name(value):
    if isinstance(value, dict):
        return clean_text(value.get("name") or value.get("@id") or "")
    if isinstance(value, list):
        parts = [as_text_or_name(item) for item in value]
        return "; ".join(part for part in parts if part)
    return clean_text(value)


def parse_offer(product_json):
    offers = product_json.get("offers") if product_json else None
    if isinstance(offers, list):
        offers = offers[0] if offers else {}
    if not isinstance(offers, dict):
        offers = {}
    return {
        "price": normalize_price(offers.get("price")),
        "availability": clean_text(str(offers.get("availability", "")).split("/")[-1]),
    }


def normalize_url_for_match(value):
    value = clean_text(value)
    if not value:
        return ""
    return value.split("#", 1)[0].rstrip("/")


def swatch_matches_page_name(swatch_name, page_name):
    if not swatch_name or not page_name:
        return False

    swatch_features = {
        "model": extract_model(swatch_name),
        "storage": extract_storage(swatch_name),
        "color": extract_color(swatch_name),
        "condition": extract_condition(swatch_name),
        "used": detect_used(swatch_name),
    }
    page_features = {
        "model": extract_model(page_name),
        "storage": extract_storage(page_name),
        "color": extract_color(page_name),
        "condition": extract_condition(page_name),
        "used": detect_used(page_name),
    }

    for key in ("model", "storage", "color"):
        if not page_features[key] or swatch_features[key] != page_features[key]:
            return False
    if page_features["condition"] and swatch_features["condition"] != page_features["condition"]:
        return False
    return swatch_features["used"] == page_features["used"]


def decode_swatch_match(match):
    tag = match.group(0)
    raw = html.unescape(match.group(2))
    try:
        data = json.loads(raw)
    except json.JSONDecodeError:
        return None
    href = first_match(r'href=["\']([^"\']+)["\']', tag)
    return {
        "tag": tag,
        "href": href,
        "data": data,
    }


def parse_data_swatch(html_text, url="", page_name=""):
    matches = list(re.finditer(r"<[^>]+data-swatch=(['\"])(.*?)\1[^>]*>", html_text, flags=re.I | re.S))
    if not matches:
        return {}

    swatches = [item for item in (decode_swatch_match(match) for match in matches) if item]
    if not swatches:
        return {}

    normalized_url = normalize_url_for_match(url)
    if normalized_url:
        for swatch in swatches:
            if normalize_url_for_match(swatch["href"]) == normalized_url:
                return swatch["data"]

    for swatch in swatches:
        if swatch_matches_page_name(clean_text(swatch["data"].get("name")), page_name):
            return swatch["data"]

    for swatch in swatches:
        if re.search(r'class=["\'][^"\']*\bactive\b', swatch["tag"], flags=re.I):
            return swatch["data"]

    return swatches[0]["data"]


def parse_page_status(html_text):
    return first_match(
        r'class=["\'][^"\']*product-info__flex-status[^"\']*["\'][^>]*>(.*?)</div>',
        html_text,
    )


def marker_status(html_text):
    lowered = html_text.lower()
    if "archived-product-btn" in lowered:
        return "Архівний товар"
    if "preorder-btn" in lowered or 'data-preorder="true"' in lowered or "preorder=1" in lowered:
        return "Передзамовлення"
    return ""


def normalize_status(value):
    value = clean_text(value).lower()
    return re.sub(r"[\s_\-:/]+", "", value)


def status_label(product):
    return (
        product.get("_stock_status_name")
        or product.get("_page_status")
        or product.get("_availability")
        or product.get("_marker_status")
        or "unknown"
    )


def is_allowed_product(product, only_available=True):
    if not only_available:
        return True

    stock_id = clean_text(product.get("_stock_status_id"))
    if stock_id in BLOCKED_STOCK_IDS:
        return False

    primary_statuses = [
        product.get("_stock_status_name"),
        product.get("_page_status"),
        product.get("_availability"),
    ]
    normalized_statuses = {normalize_status(status) for status in primary_statuses if status}

    if normalized_statuses & BLOCKED_STATUS_WORDS:
        return False

    if stock_id == "9" or normalized_statuses & ALLOWED_STATUS_WORDS:
        return True

    marker = normalize_status(product.get("_marker_status"))
    if marker in BLOCKED_STATUS_WORDS:
        return False

    # If the site does not expose a clear status, keep the product instead of
    # dropping potentially valid data because of a layout change.
    return True


def output_row(product):
    return {field: product.get(field, "") for field in FIELDS}


def parse_product(url, html_text):
    json_ld_product = None
    for block in parse_json_ld_blocks(html_text):
        json_ld_product = find_product_json(block)
        if json_ld_product:
            break

    offer = parse_offer(json_ld_product or {})
    page_name = (
        clean_text((json_ld_product or {}).get("name"))
        or first_match(r'<h1[^>]*class=["\'][^"\']*product-info__title[^"\']*["\'][^>]*>(.*?)</h1>', html_text)
        or meta_content(html_text, "og:title").split(" — ")[0]
    )
    swatch = parse_data_swatch(html_text, url=url, page_name=page_name)
    page_status = parse_page_status(html_text)
    html_marker_status = marker_status(html_text)

    name = page_name or clean_text(swatch.get("name"))

    current_price = normalize_price(
        swatch.get("price_uah_no_currency")
        or swatch.get("price_uah")
        or offer["price"]
        or first_match(r'class=["\']price-new__uah["\'][^>]*>(.*?)</span>', html_text)
    )
    return enrich_product({
        "name": name,
        "price_uah": current_price,
        "_stock_status_id": clean_text(swatch.get("stock_status_id")),
        "_stock_status_name": clean_text(swatch.get("stock_status_name")),
        "_page_status": page_status,
        "_availability": offer["availability"],
        "_marker_status": html_marker_status,
    }, "jabko", url)


def parse_mygadget_status(html_text):
    status = first_match(
        r'class=["\'][^"\']*product-card_info-stock[^"\']*["\'][^>]*>(.*?)</(?:button|span)>',
        html_text,
    )
    if status:
        return status
    if "type=avail" in html_text:
        return "Уточнити наявність"
    if "product-card__pre-order" in html_text:
        return "Передзамовлення"
    return ""


def parse_schema_availability(html_text):
    availability = first_match(r'itemprop=["\']availability["\'][^>]+href=["\'][^"\']*/([^/"\']+)["\']', html_text)
    if availability:
        return availability
    return first_match(r'"availability"\s*:\s*"[^"]*/([^"/]+)"', html_text)


def parse_mygadget_price(html_text):
    patterns = [
        r'<meta[^>]+itemprop=["\']price["\'][^>]+content=["\']([^"\']+)["\']',
        r'<span[^>]+class=["\'][^"\']*priceC[^"\']*["\'][^>]*>(.*?)</span>',
        r'<div[^>]+class=["\'][^"\']*price__new[^"\']*["\'][^>]*>(.*?)</div>',
    ]
    for pattern in patterns:
        price = normalize_price(first_match(pattern, html_text))
        if price:
            return price
    return ""


def parse_mygadget_product(url, html_text):
    name = (
        meta_content(html_text, "og:title")
        or first_match(r'<h1[^>]*class=["\'][^"\']*product-article__title[^"\']*["\'][^>]*>(.*?)</h1>', html_text)
        or first_match(r"<title>(.*?)</title>", html_text).split(" купити ")[0]
    )
    page_status = parse_mygadget_status(html_text)
    availability = parse_schema_availability(html_text)
    price = parse_mygadget_price(html_text)

    return enrich_product({
        "name": name,
        "price_uah": price,
        "_stock_status_id": "",
        "_stock_status_name": page_status,
        "_page_status": page_status,
        "_availability": availability,
        "_marker_status": "",
    }, "mygadget", url)


def write_csv(rows, path, fieldnames=FIELDS):
    with open(path, "w", newline="", encoding="utf-8-sig") as file:
        writer = csv.DictWriter(file, fieldnames=fieldnames)
        writer.writeheader()
        writer.writerows(rows)


def excel_column_name(index):
    name = ""
    while index:
        index, remainder = divmod(index - 1, 26)
        name = chr(65 + remainder) + name
    return name


def xlsx_cell_xml(value, row_index, col_index):
    cell_ref = f"{excel_column_name(col_index)}{row_index}"
    if value is None:
        value = ""
    value = str(value)
    if value == "":
        return f'<c r="{cell_ref}"/>'
    return (
        f'<c r="{cell_ref}" t="inlineStr">'
        f'<is><t>{xml_escape(value)}</t></is>'
        f'</c>'
    )


def write_xlsx(rows, path, fieldnames=FIELDS):
    matrix = [fieldnames]
    matrix.extend([[row.get(field, "") for field in fieldnames] for row in rows])

    sheet_rows = []
    for row_index, row in enumerate(matrix, start=1):
        cells = "".join(
            xlsx_cell_xml(value, row_index, col_index)
            for col_index, value in enumerate(row, start=1)
        )
        sheet_rows.append(f'<row r="{row_index}">{cells}</row>')

    last_col = excel_column_name(len(fieldnames))
    dimension = f"A1:{last_col}{len(matrix)}"
    sheet_xml = f'''<?xml version="1.0" encoding="UTF-8" standalone="yes"?>
<worksheet xmlns="http://schemas.openxmlformats.org/spreadsheetml/2006/main"
 xmlns:r="http://schemas.openxmlformats.org/officeDocument/2006/relationships">
<dimension ref="{dimension}"/>
<sheetViews><sheetView tabSelected="1" workbookViewId="0"><pane ySplit="1" topLeftCell="A2" activePane="bottomLeft" state="frozen"/></sheetView></sheetViews>
<sheetFormatPr defaultRowHeight="15"/>
<cols>
<col min="1" max="1" width="48" customWidth="1"/>
<col min="2" max="2" width="58" customWidth="1"/>
<col min="3" max="3" width="16" customWidth="1"/>
<col min="4" max="4" width="58" customWidth="1"/>
<col min="5" max="5" width="58" customWidth="1"/>
<col min="6" max="6" width="18" customWidth="1"/>
</cols>
<sheetData>{''.join(sheet_rows)}</sheetData>
<autoFilter ref="{dimension}"/>
</worksheet>'''

    workbook_xml = '''<?xml version="1.0" encoding="UTF-8" standalone="yes"?>
<workbook xmlns="http://schemas.openxmlformats.org/spreadsheetml/2006/main"
 xmlns:r="http://schemas.openxmlformats.org/officeDocument/2006/relationships">
<sheets><sheet name="Price Compare" sheetId="1" r:id="rId1"/></sheets>
</workbook>'''
    workbook_rels = '''<?xml version="1.0" encoding="UTF-8" standalone="yes"?>
<Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships">
<Relationship Id="rId1" Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/worksheet" Target="worksheets/sheet1.xml"/>
<Relationship Id="rId2" Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/styles" Target="styles.xml"/>
</Relationships>'''
    root_rels = '''<?xml version="1.0" encoding="UTF-8" standalone="yes"?>
<Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships">
<Relationship Id="rId1" Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/officeDocument" Target="xl/workbook.xml"/>
</Relationships>'''
    content_types = '''<?xml version="1.0" encoding="UTF-8" standalone="yes"?>
<Types xmlns="http://schemas.openxmlformats.org/package/2006/content-types">
<Default Extension="rels" ContentType="application/vnd.openxmlformats-package.relationships+xml"/>
<Default Extension="xml" ContentType="application/xml"/>
<Override PartName="/xl/workbook.xml" ContentType="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet.main+xml"/>
<Override PartName="/xl/worksheets/sheet1.xml" ContentType="application/vnd.openxmlformats-officedocument.spreadsheetml.worksheet+xml"/>
<Override PartName="/xl/styles.xml" ContentType="application/vnd.openxmlformats-officedocument.spreadsheetml.styles+xml"/>
</Types>'''
    styles_xml = '''<?xml version="1.0" encoding="UTF-8" standalone="yes"?>
<styleSheet xmlns="http://schemas.openxmlformats.org/spreadsheetml/2006/main">
<fonts count="1"><font><sz val="11"/><name val="Calibri"/></font></fonts>
<fills count="1"><fill><patternFill patternType="none"/></fill></fills>
<borders count="1"><border><left/><right/><top/><bottom/><diagonal/></border></borders>
<cellStyleXfs count="1"><xf numFmtId="0" fontId="0" fillId="0" borderId="0"/></cellStyleXfs>
<cellXfs count="1"><xf numFmtId="0" fontId="0" fillId="0" borderId="0" xfId="0"/></cellXfs>
<cellStyles count="1"><cellStyle name="Normal" xfId="0" builtinId="0"/></cellStyles>
</styleSheet>'''

    with zipfile.ZipFile(path, "w", compression=zipfile.ZIP_DEFLATED) as archive:
        archive.writestr("[Content_Types].xml", content_types)
        archive.writestr("_rels/.rels", root_rels)
        archive.writestr("xl/workbook.xml", workbook_xml)
        archive.writestr("xl/_rels/workbook.xml.rels", workbook_rels)
        archive.writestr("xl/worksheets/sheet1.xml", sheet_xml)
        archive.writestr("xl/styles.xml", styles_xml)


def write_table(rows, path, fieldnames=FIELDS):
    if path.lower().endswith(".xlsx"):
        write_xlsx(rows, path, fieldnames=fieldnames)
    else:
        write_csv(rows, path, fieldnames=fieldnames)


def write_json(rows, path):
    with open(path, "w", encoding="utf-8") as file:
        json.dump(rows, file, ensure_ascii=False, indent=2)


def next_output_path(path):
    if not os.path.exists(path):
        return path

    folder, filename = os.path.split(path)
    stem, extension = os.path.splitext(filename)
    counter = 1

    while True:
        candidate = os.path.join(folder, f"{stem}_{counter}{extension}")
        if not os.path.exists(candidate):
            return candidate
        counter += 1


def clean_name_for_key(name):
    value = clean_text(name).lower()
    value = value.replace("ё", "е")
    value = re.sub(r"\bapple\b", " ", value)
    value = re.sub(r"\b(б/у|б\\у|бу|b/u|used)\b", " ", value)
    value = re.sub(r"\b[a-z]{2,4}\d{1,3}\b", " ", value)
    value = re.sub(r"\([^)]*\)", lambda m: " " + m.group(0).strip("()") + " ", value)
    value = re.sub(r"[^a-zа-яіїєґ0-9]+", " ", value, flags=re.I)
    value = re.sub(r"\s+", " ", value)
    return value.strip()


def detect_used(name, url=""):
    value = f"{name} {url}".lower()
    return bool(re.search(r"б/у|б\\у|\bбу\b|\bb-u\b|\bb-us\b|\bused\b|/b-u-|/b-us/", value))


def extract_model(name):
    value = clean_name_for_key(name)
    match = re.search(r"\biphone\s+\d{1,2}(?:e)?(?:\s+(?:pro\s+max|pro|max|plus|mini|air))?\b", value)
    if not match:
        return ""
    return re.sub(r"\s+", " ", match.group(0)).strip()


def extract_storage(name):
    value = clean_name_for_key(name)
    match = re.search(r"\b(\d+)\s*(gb|гб|tb|тб)\b", value)
    if not match:
        return ""
    amount = int(match.group(1))
    unit = match.group(2)
    return f"{amount}tb" if unit in {"tb", "тб"} else f"{amount}gb"


def extract_color(name):
    value = clean_name_for_key(name)
    for color, aliases in COLOR_ALIASES:
        for alias in aliases:
            if alias in value:
                return color
    return ""


def extract_condition(name):
    value = clean_name_for_key(name)
    if any(term in value for term in [
        "як новий",
        "yak novyi",
        "kak novyy",
        "idealnoe",
        "idealnyi",
        "ідеальний",
        "идеальний",
        "sostoyanie 10 10",
    ]):
        return "як новий"
    if any(term in value for term in [
        "відмінний",
        "vidminnij",
        "vidminnyi",
        "отличное",
        "otlichnoe",
        "відмінний стан",
        "100 batareya",
        "100 батарея",
        "used iphone",
        "used 11",
        "used 12",
        "used 13",
        "used 14",
        "used 15",
        "used 16",
        "9 10",
    ]):
        return "відмінний"
    if any(term in value for term in ["хороший", "horoshyi", "хорошее"]):
        return "хороший"
    if any(term in value for term in ["економ", "econom"]):
        return "економ"
    return ""


def extract_battery(name):
    value = clean_name_for_key(name)
    if any(term in value for term in ["стандартна батарея", "standartna batareya"]):
        return "стандартна"
    if any(term in value for term in ["нова батарея", "nova batareya"]):
        return "нова"
    return ""


def enrich_product(product, site, url):
    name = product.get("name", "")
    name_and_url = f"{name} {url}"
    model = extract_model(name_and_url)
    storage = extract_storage(name_and_url)
    color = extract_color(name) or extract_color(url)
    used = detect_used(name, url)
    condition = extract_condition(name_and_url)
    product.update({
        "site": site,
        "url": url,
        "_model": model,
        "_storage": storage,
        "_color": color,
        "_used": used,
        "_condition": condition,
        "_battery": extract_battery(name),
        "_match_key": f"{'used' if used else 'new'}|{model}|{storage}|{color}" if model and storage and color else "",
        "_loose_key": f"{'used' if used else 'new'}|{model}|{storage}" if model and storage else "",
        "_condition_match_key": f"{'used' if used else 'new'}|{model}|{storage}|{color}|{condition}" if model and storage and color and condition else "",
    })
    return product


def parser_for_site(site):
    return parse_mygadget_product if site == "mygadget" else parse_product


def sitemap_for_site(site):
    return MYGADGET_SITEMAP if site == "mygadget" else DEFAULT_SITEMAP


def excludes_for_site(site):
    return MYGADGET_EXCLUDES if site == "mygadget" else []


def fetch_and_parse(index, total, url, user_agent, parse_func):
    html_text = fetch_text(url, user_agent=user_agent)
    row = parse_func(url, html_text)
    return index, row


def parse_urls(urls, workers, delay, user_agent, only_available=True, parse_func=parse_product, public_rows=True):
    rows_by_index = {}
    workers = max(1, workers)

    if workers == 1:
        for index, url in enumerate(urls, start=1):
            print(f"[{index}/{len(urls)}] {url}", file=sys.stderr)
            try:
                _, row = fetch_and_parse(index, len(urls), url, user_agent, parse_func)
                if is_allowed_product(row, only_available=only_available):
                    rows_by_index[index] = output_row(row) if public_rows else row
                    print(f"  ok: {url}", file=sys.stderr)
                else:
                    print(f"  skip: {url} - {status_label(row)}", file=sys.stderr)
            except Exception as exc:
                print(f"  error: {exc}", file=sys.stderr)
            if index < len(urls):
                time.sleep(max(delay, 0))
    else:
        print(f"Parsing {len(urls)} products with {workers} workers", file=sys.stderr)
        with ThreadPoolExecutor(max_workers=workers) as executor:
            futures = {}
            for index, url in enumerate(urls, start=1):
                if delay > 0 and index > 1:
                    time.sleep(delay)
                future = executor.submit(fetch_and_parse, index, len(urls), url, user_agent, parse_func)
                futures[future] = (index, url)

            completed = 0
            for future in as_completed(futures):
                index, url = futures[future]
                completed += 1
                try:
                    _, row = future.result()
                    if is_allowed_product(row, only_available=only_available):
                        rows_by_index[index] = output_row(row) if public_rows else row
                        print(f"[{completed}/{len(urls)}] ok: {url}", file=sys.stderr)
                    else:
                        print(f"[{completed}/{len(urls)}] skip: {url} - {status_label(row)}", file=sys.stderr)
                except Exception as exc:
                    print(f"[{completed}/{len(urls)}] error: {url} - {exc}", file=sys.stderr)

    return [rows_by_index[index] for index in sorted(rows_by_index)]


def run_job(job, defaults):
    site = job.get("site", defaults.get("site", "jabko"))
    sitemap = job.get("sitemap") or defaults.get("sitemap") or sitemap_for_site(site)
    contains = job.get("contains", defaults.get("contains"))
    limit = int(job.get("limit", defaults.get("limit", 20)))
    delay = float(job.get("delay", defaults.get("delay", 1.0)))
    workers = int(job.get("workers", defaults.get("workers", 1)))
    output_format = job.get("format", defaults.get("format", "csv"))
    output = job.get("output") or defaults.get("output") or "jabko_products.csv"
    output = next_output_path(output)
    user_agent = job.get("user_agent", defaults.get("user_agent", DEFAULT_USER_AGENT))
    only_available = bool(job.get("only_available", defaults.get("only_available", True)))

    label = job.get("name") or contains or output
    print(f"\n=== {label} ===", file=sys.stderr)

    urls = sitemap_urls(sitemap, contains=contains, limit=limit, excludes=excludes_for_site(site))
    if not urls:
        print("No URLs found. Try another contains filter or sitemap.", file=sys.stderr)
        return 0

    rows = parse_urls(
        urls,
        workers=workers,
        delay=delay,
        user_agent=user_agent,
        only_available=only_available,
        parse_func=parser_for_site(site),
        public_rows=True,
    )

    if output_format == "json":
        write_json(rows, output)
    else:
        write_csv(rows, output)

    print(f"Saved {len(rows)} products to {output}", file=sys.stderr)
    return len(rows)


def run_config(path):
    with open(path, "r", encoding="utf-8") as file:
        config = json.load(file)

    defaults = config.get("defaults", {})
    categories = config.get("categories", [])
    if not categories:
        raise RuntimeError("Config must contain a non-empty categories list.")

    total = 0
    for category in categories:
        total += run_job(category, defaults)
    print(f"\nDone. Saved {total} products across {len(categories)} categories.", file=sys.stderr)


def collect_source_rows(source, defaults):
    site = source.get("site", defaults.get("site", "jabko"))
    sitemap = source.get("sitemap") or defaults.get("sitemap") or sitemap_for_site(site)
    contains = source.get("contains", defaults.get("contains"))
    limit = int(source.get("limit", defaults.get("limit", 20)))
    delay = float(source.get("delay", defaults.get("delay", 1.0)))
    workers = int(source.get("workers", defaults.get("workers", 1)))
    user_agent = source.get("user_agent", defaults.get("user_agent", DEFAULT_USER_AGENT))
    only_available = bool(source.get("only_available", defaults.get("only_available", True)))

    label = source.get("name") or f"{site}:{contains or sitemap}"
    print(f"\n=== {label} ===", file=sys.stderr)

    urls = sitemap_urls(sitemap, contains=contains, limit=limit, excludes=excludes_for_site(site))
    if not urls:
        print("No URLs found. Try another contains filter or sitemap.", file=sys.stderr)
        return []

    return parse_urls(
        urls,
        workers=workers,
        delay=delay,
        user_agent=user_agent,
        only_available=only_available,
        parse_func=parser_for_site(site),
        public_rows=False,
    )


def compare_price(jabko_product, mygadget_product, score):
    jabko_price = price_number(jabko_product.get("price_uah"))
    mygadget_price = price_number(mygadget_product.get("price_uah"))

    cheaper_store = ""
    price_diff = ""
    if jabko_price is not None and mygadget_price is not None:
        price_diff = str(int(abs(jabko_price - mygadget_price)))
        if jabko_price < mygadget_price:
            cheaper_store = "jabko"
        elif mygadget_price < jabko_price:
            cheaper_store = "mygadget"
        else:
            cheaper_store = "same"

    return {
        "match_key": jabko_product.get("_match_key") or mygadget_product.get("_match_key"),
        "model": jabko_product.get("_model") or mygadget_product.get("_model"),
        "storage": jabko_product.get("_storage") or mygadget_product.get("_storage"),
        "color": jabko_product.get("_color") or mygadget_product.get("_color"),
        "used": "yes" if jabko_product.get("_used") or mygadget_product.get("_used") else "no",
        "condition_jabko": jabko_product.get("_condition", ""),
        "condition_mygadget": mygadget_product.get("_condition", ""),
        "battery_jabko": jabko_product.get("_battery", ""),
        "jabko_name": jabko_product.get("name", ""),
        "jabko_price_uah": jabko_product.get("price_uah", ""),
        "mygadget_name": mygadget_product.get("name", ""),
        "mygadget_price_uah": mygadget_product.get("price_uah", ""),
        "cheaper_store": cheaper_store,
        "price_diff_uah": price_diff,
        "match_score": str(score),
    }


def build_comparison(jabko_rows, mygadget_rows, min_score=80):
    exact_mygadget = {}
    loose_mygadget = {}
    for product in mygadget_rows:
        if product.get("_match_key"):
            exact_mygadget.setdefault(product["_match_key"], []).append(product)
        if product.get("_loose_key"):
            loose_mygadget.setdefault(product["_loose_key"], []).append(product)

    compared = []
    used_mygadget_ids = set()
    for jabko_product in jabko_rows:
        candidates = []
        score = 0
        if jabko_product.get("_match_key") in exact_mygadget:
            candidates = exact_mygadget[jabko_product["_match_key"]]
            score = 100
        elif jabko_product.get("_loose_key") in loose_mygadget:
            candidates = loose_mygadget[jabko_product["_loose_key"]]
            score = 85

        if score < min_score:
            continue

        candidates = [item for item in candidates if id(item) not in used_mygadget_ids]
        if not candidates:
            continue

        mygadget_product = sorted(
            candidates,
            key=lambda item: (
                item.get("_color") != jabko_product.get("_color"),
                price_number(item.get("price_uah")) or 10**12,
            ),
        )[0]
        used_mygadget_ids.add(id(mygadget_product))
        compared.append(compare_price(jabko_product, mygadget_product, score))

    return compared


def run_compare_config(path, output_override=None):
    with open(path, "r", encoding="utf-8") as file:
        config = json.load(file)

    defaults = config.get("defaults", {})
    sources = config.get("sources", [])
    if not sources:
        raise RuntimeError("Compare config must contain a non-empty sources list.")

    jabko_rows = []
    mygadget_rows = []
    for source in sources:
        rows = collect_source_rows(source, defaults)
        site = source.get("site", defaults.get("site", "jabko"))
        if site == "mygadget":
            mygadget_rows.extend(rows)
        else:
            jabko_rows.extend(rows)

    comparison = config.get("comparison", {})
    min_score = int(comparison.get("min_match_score", 80))
    output = output_override or comparison.get("output", "price_compare.csv")
    output = next_output_path(output)
    rows = build_comparison(jabko_rows, mygadget_rows, min_score=min_score)
    write_csv(rows, output, fieldnames=COMPARE_FIELDS)
    print(f"\nSaved {len(rows)} compared products to {output}", file=sys.stderr)


def read_template(path):
    with open(path, "r", newline="", encoding="utf-8-sig") as file:
        reader = csv.DictReader(file)
        rows = []
        for row_number, row in enumerate(reader, start=2):
            active = clean_text(row.get("active", "1")).lower()
            jabko_url = clean_text(row.get("jabko_url"))
            mygadget_url = clean_text(row.get("mygadget_url"))
            note = clean_text(row.get("note"))
            if active in {"0", "false", "no", "ні", "off"}:
                continue
            if not jabko_url:
                continue
            rows.append({
                "row_number": row_number,
                "jabko_url": jabko_url,
                "mygadget_url": mygadget_url,
                "note": note,
            })
    return rows


def parse_template_jabko_rows(template_rows, workers, delay, user_agent):
    urls = [row["jabko_url"] for row in template_rows]
    parsed_by_url = {}
    workers = max(1, workers)

    if not urls:
        return parsed_by_url

    print(f"Parsing {len(urls)} Jabko template products with {workers} workers", file=sys.stderr)
    if workers == 1:
        for index, url in enumerate(urls, start=1):
            try:
                _, product = fetch_and_parse(index, len(urls), url, user_agent, parse_product)
                parsed_by_url[url] = product
                print(f"[{index}/{len(urls)}] ok: {url}", file=sys.stderr)
            except Exception as exc:
                parsed_by_url[url] = {"url": url, "name": "", "price_uah": "", "_template_error": str(exc)}
                print(f"[{index}/{len(urls)}] error: {url} - {exc}", file=sys.stderr)
            if index < len(urls):
                time.sleep(max(delay, 0))
        return parsed_by_url

    with ThreadPoolExecutor(max_workers=workers) as executor:
        futures = {}
        for index, url in enumerate(urls, start=1):
            if delay > 0 and index > 1:
                time.sleep(delay)
            future = executor.submit(fetch_and_parse, index, len(urls), url, user_agent, parse_product)
            futures[future] = (index, url)

        completed = 0
        for future in as_completed(futures):
            _, url = futures[future]
            completed += 1
            try:
                _, product = future.result()
                parsed_by_url[url] = product
                print(f"[{completed}/{len(urls)}] ok: {url}", file=sys.stderr)
            except Exception as exc:
                parsed_by_url[url] = {"url": url, "name": "", "price_uah": "", "_template_error": str(exc)}
                print(f"[{completed}/{len(urls)}] error: {url} - {exc}", file=sys.stderr)

    return parsed_by_url


def collect_mygadget_template_rows(required_keys, fallback_keys, limit, workers, delay, user_agent, only_available=False):
    urls = []
    for contains in MYGADGET_TEMPLATE_CONTAINS:
        urls.extend(sitemap_urls(
            MYGADGET_SITEMAP,
            contains=contains,
            excludes=MYGADGET_EXCLUDES,
        ))
    if required_keys:
        matched_urls = []
        for url in urls:
            product = enrich_product({"name": url}, "mygadget", url)
            exact_key = template_match_key(product)
            fallback_key = template_fallback_key(product)
            if (
                (exact_key in required_keys or fallback_key in fallback_keys)
                and is_template_source_allowed(product)
            ):
                matched_urls.append(url)
        urls = matched_urls
    urls = list(dict.fromkeys(urls))
    if limit:
        urls = urls[:limit]
    if not urls:
        return []
    print(f"Found {len(urls)} possible MyGadget matches in sitemap", file=sys.stderr)
    return parse_urls(
        urls,
        workers=workers,
        delay=delay,
        user_agent=user_agent,
        only_available=only_available,
        parse_func=parse_mygadget_product,
        public_rows=False,
    )


def build_template_mygadget_indexes(products):
    exact_index = {}
    fallback_index = {}
    for product in products:
        key = template_match_key(product)
        if key:
            exact_index.setdefault(key, []).append(product)
        fallback_key = template_fallback_key(product)
        if fallback_key:
            fallback_index.setdefault(fallback_key, []).append(product)
    for items in list(exact_index.values()) + list(fallback_index.values()):
        items.sort(key=lambda item: (
            mygadget_template_source_rank(item),
            price_number(item.get("price_uah")) or 10**12,
        ))
    return exact_index, fallback_index


def compare_template_prices(jabko_product, mygadget_product):
    jabko_price = price_number(jabko_product.get("price_uah"))
    mygadget_price = price_number(mygadget_product.get("price_uah")) if mygadget_product else None
    cheaper_store = ""
    price_diff = ""

    if jabko_price is not None and mygadget_price is not None:
        price_diff = str(int(abs(jabko_price - mygadget_price)))
        if jabko_price < mygadget_price:
            cheaper_store = "jabko"
        elif mygadget_price < jabko_price:
            cheaper_store = "mygadget"
        else:
            cheaper_store = "same"

    return cheaper_store, price_diff


def template_product_condition(product):
    if product.get("site") == "jabko":
        name_value = clean_name_for_key(product.get("name", ""))
        if "хороший" in name_value or "horoshyi" in name_value:
            return "хороший"
        if any(term in name_value for term in ["як новий", "idealnyi", "ідеальний"]):
            return "як новий"
    return product.get("_condition", "")


def template_condition_bucket(product):
    value = clean_name_for_key(f"{product.get('name', '')} {product.get('url', '')}")
    if product.get("site") == "mygadget":
        if "sostoyanie 10 10" in value or "kak novyy" in value or "як новий" in value:
            return "like_new"
        if any(term in value for term in [
            "відмінний",
            "vidminnij",
            "vidminnyi",
            "отличное",
            "otlichnoe",
            "ідеальний",
            "idealnoe",
            "sostoyanie 9 10",
            "used iphone",
        ]):
            return "excellent"

    condition = template_product_condition(product)
    if condition == "як новий":
        return "like_new"
    if product.get("site") == "jabko" and condition == "хороший":
        return "like_new"
    if condition == "відмінний":
        return "excellent"
    return condition


def template_match_key(product):
    if product.get("_used"):
        bucket = template_condition_bucket(product)
        if product.get("_model") and product.get("_storage") and product.get("_color") and bucket:
            return f"used|{product['_model']}|{product['_storage']}|{product['_color']}|{bucket}"
        return ""
    return product.get("_match_key", "")


def template_fallback_key(product):
    if product.get("_model") and product.get("_storage") and product.get("_color"):
        prefix = "used" if product.get("_used") else "new"
        return f"{prefix}|{product['_model']}|{product['_storage']}|{product['_color']}"
    return ""


def is_mygadget_b_us_10_10(product):
    url = product.get("url", "").lower()
    return "/b-us/b-u-iphone/" in url and "sostoyanie-10-10" in url


def is_mygadget_kak_new(product):
    return "/kak-novyy/iphone/" in product.get("url", "").lower()


def select_template_candidate(jabko_product, candidates):
    if not candidates:
        return None

    jabko_condition = template_product_condition(jabko_product)
    if jabko_product.get("_used") and jabko_condition == "хороший":
        b_us_10_10 = [candidate for candidate in candidates if is_mygadget_b_us_10_10(candidate)]
        return b_us_10_10[0] if b_us_10_10 else None

    if jabko_product.get("_used") and jabko_condition == "як новий":
        kak_new = [candidate for candidate in candidates if is_mygadget_kak_new(candidate)]
        if kak_new:
            return kak_new[0]
        b_us_10_10 = [candidate for candidate in candidates if is_mygadget_b_us_10_10(candidate)]
        return b_us_10_10[0] if b_us_10_10 else None

    return candidates[0]


def is_safe_template_fallback(jabko_product, mygadget_product):
    if not jabko_product.get("_used"):
        return not mygadget_product.get("_used")
    jabko_condition = template_product_condition(jabko_product)
    if jabko_condition == "хороший":
        return is_mygadget_b_us_10_10(mygadget_product)
    if jabko_condition == "як новий":
        return template_condition_bucket(mygadget_product) == "like_new"
    return template_condition_bucket(jabko_product) == template_condition_bucket(mygadget_product)


def mygadget_template_source_rank(product):
    url = product.get("url", "").lower()
    if not product.get("_used") and "/iphones/" in url:
        return 0
    if template_condition_bucket(product) == "like_new" and "/kak-novyy/iphone/" in url:
        return 0
    if template_condition_bucket(product) == "like_new" and "/b-us/b-u-iphone/" in url and "sostoyanie-10-10" in url:
        return 1
    if template_condition_bucket(product) == "excellent" and "/b-us/b-u-iphone/" in url:
        return 2
    if product.get("_used") and "/b-us/b-u-iphone/" in url:
        return 3
    return 4


def is_template_source_allowed(product):
    url = product.get("url", "").lower()
    if not product.get("_used"):
        return "/iphones/" in url
    if product.get("_condition") == "як новий":
        return "/kak-novyy/iphone/" in url or (
            "/b-us/b-u-iphone/" in url and "sostoyanie-10-10" in url
        )
    return "/b-us/b-u-iphone/" in url


def template_alias_note(jabko_product, mygadget_product):
    jabko_value = clean_name_for_key(jabko_product.get("name", ""))
    mygadget_value = clean_name_for_key(f"{mygadget_product.get('name', '')} {mygadget_product.get('url', '')}")
    if jabko_product.get("_model") == "iphone 17 air" and "iphone air" in mygadget_value:
        return "model alias match: jabko iphone 17 air -> mygadget iphone air"
    color_aliases = [
        ("sky blue", "sky blue"),
        ("cloud white", "cloud white"),
        ("light gold", "light gold"),
        ("lavender", "purple"),
    ]
    for jabko_color, mygadget_color in color_aliases:
        if jabko_color in jabko_value and mygadget_color in mygadget_value:
            return f"color alias match: jabko {jabko_color} -> mygadget {mygadget_color}"
    return ""


def build_template_compare_rows(template_rows, jabko_by_url, mygadget_exact_index, mygadget_fallback_index, user_agent):
    output_rows = []

    for template_row in template_rows:
        jabko_url = template_row["jabko_url"]
        jabko_product = jabko_by_url.get(jabko_url, {"url": jabko_url})
        match_note = clean_text(template_row.get("note"))
        mygadget_product = None
        match_score = "0"

        if template_row.get("mygadget_url"):
            mygadget_url = template_row["mygadget_url"]
            try:
                mygadget_product = parse_mygadget_product(mygadget_url, fetch_text(mygadget_url, user_agent=user_agent))
                match_score = "100"
                match_note = match_note or "manual mygadget url"
            except Exception as exc:
                match_note = f"manual mygadget error: {exc}"
        else:
            key = template_match_key(jabko_product)
            candidates = mygadget_exact_index.get(key, []) if key else []
            mygadget_product = select_template_candidate(jabko_product, candidates)
            if mygadget_product:
                match_score = "100"
                alias_note = template_alias_note(jabko_product, mygadget_product)
                if alias_note:
                    match_note = match_note or alias_note
                elif (
                    jabko_product.get("_used")
                    and mygadget_product.get("_condition")
                    and jabko_product.get("_condition") != mygadget_product.get("_condition")
                    and template_condition_bucket(jabko_product) == template_condition_bucket(mygadget_product)
                ):
                    match_note = match_note or (
                        f"condition mapped: jabko {jabko_product.get('_condition')} -> "
                        f"mygadget {template_condition_bucket(mygadget_product)}"
                    )
                else:
                    match_note = match_note or "exact mygadget match"
            else:
                fallback_key = template_fallback_key(jabko_product)
                fallback_candidates = mygadget_fallback_index.get(fallback_key, []) if fallback_key else []
                fallback_candidates = [
                    candidate
                    for candidate in fallback_candidates
                    if is_safe_template_fallback(jabko_product, candidate)
                ]
                mygadget_product = select_template_candidate(jabko_product, fallback_candidates)
                if mygadget_product:
                    match_score = "80"
                    match_note = match_note or "fallback match: same model/storage/color, condition not exact"
                else:
                    match_note = match_note or "no safe mygadget match"

        if jabko_product.get("_template_error"):
            match_note = f"jabko error: {jabko_product['_template_error']}"

        cheaper_store, price_diff = compare_template_prices(jabko_product, mygadget_product)
        output_rows.append({
            "jabko_url": jabko_url,
            "jabko_name": jabko_product.get("name", ""),
            "jabko_price_uah": jabko_product.get("price_uah", ""),
            "mygadget_url": mygadget_product.get("url", "") if mygadget_product else "",
            "mygadget_name": mygadget_product.get("name", "") if mygadget_product else "",
            "mygadget_price_uah": mygadget_product.get("price_uah", "") if mygadget_product else "",
        })

    return output_rows


def run_compare_template(template_path, output, workers, delay, user_agent, mygadget_limit=None, only_available=False):
    template_rows = read_template(template_path)
    if not template_rows:
        raise RuntimeError("Template must contain at least one active jabko_url row.")

    jabko_by_url = parse_template_jabko_rows(
        template_rows,
        workers=workers,
        delay=delay,
        user_agent=user_agent,
    )
    required_keys = {
        template_match_key(product)
        for product in jabko_by_url.values()
        if template_match_key(product)
    }
    fallback_keys = {
        template_fallback_key(product)
        for product in jabko_by_url.values()
        if template_fallback_key(product)
    }
    mygadget_rows = collect_mygadget_template_rows(
        required_keys=required_keys,
        fallback_keys=fallback_keys,
        limit=mygadget_limit,
        workers=workers,
        delay=delay,
        user_agent=user_agent,
        only_available=False,
    )
    mygadget_exact_index, mygadget_fallback_index = build_template_mygadget_indexes(mygadget_rows)

    rows = build_template_compare_rows(
        template_rows,
        jabko_by_url,
        mygadget_exact_index,
        mygadget_fallback_index,
        user_agent,
    )
    output = next_output_path(output or "template_price_compare.xlsx")
    write_table(rows, output, fieldnames=TEMPLATE_COMPARE_FIELDS)
    print(f"\nSaved {len(rows)} template compared products to {output}", file=sys.stderr)


def xlsx_column_index(cell_ref):
    match = re.match(r"([A-Z]+)", cell_ref or "")
    if not match:
        return 0
    index = 0
    for char in match.group(1):
        index = index * 26 + ord(char) - 64
    return index


def xlsx_shared_strings(archive):
    try:
        xml_text = archive.read("xl/sharedStrings.xml")
    except KeyError:
        return []
    root = ET.fromstring(xml_text)
    strings = []
    for item in root.findall("{http://schemas.openxmlformats.org/spreadsheetml/2006/main}si"):
        parts = []
        for text in item.findall(".//{http://schemas.openxmlformats.org/spreadsheetml/2006/main}t"):
            parts.append(text.text or "")
        strings.append("".join(parts))
    return strings


def xlsx_sheet_filename(archive, sheet_name):
    workbook = ET.fromstring(archive.read("xl/workbook.xml"))
    rels = ET.fromstring(archive.read("xl/_rels/workbook.xml.rels"))
    namespaces = {
        "main": "http://schemas.openxmlformats.org/spreadsheetml/2006/main",
        "rel": "http://schemas.openxmlformats.org/officeDocument/2006/relationships",
        "pkg": "http://schemas.openxmlformats.org/package/2006/relationships",
    }
    rel_targets = {
        rel.attrib.get("Id"): rel.attrib.get("Target")
        for rel in rels.findall("pkg:Relationship", namespaces)
    }
    for sheet in workbook.findall(".//main:sheet", namespaces):
        if sheet.attrib.get("name") == sheet_name:
            rel_id = sheet.attrib.get(f"{{{namespaces['rel']}}}id")
            target = rel_targets.get(rel_id, "")
            return "xl/" + target.lstrip("/")
    raise RuntimeError(f"Sheet not found: {sheet_name}")


def read_xlsx_rows(path, sheet_name):
    with zipfile.ZipFile(path) as archive:
        shared_strings = xlsx_shared_strings(archive)
        sheet_path = xlsx_sheet_filename(archive, sheet_name)
        root = ET.fromstring(archive.read(sheet_path))

    namespace = "{http://schemas.openxmlformats.org/spreadsheetml/2006/main}"
    rows = []
    for row in root.findall(f".//{namespace}row"):
        values = []
        for cell in row.findall(f"{namespace}c"):
            col_index = xlsx_column_index(cell.attrib.get("r"))
            while len(values) < col_index - 1:
                values.append(None)

            value = ""
            cell_type = cell.attrib.get("t")
            if cell_type == "inlineStr":
                parts = [
                    text.text or ""
                    for text in cell.findall(f".//{namespace}t")
                ]
                value = "".join(parts)
            else:
                value_node = cell.find(f"{namespace}v")
                value = value_node.text if value_node is not None else ""
                if cell_type == "s" and value != "":
                    value = shared_strings[int(value)]
            values.append(value)
        rows.append(values)
    return rows


def report_cell(row, index):
    return row[index] if index < len(row) else None


def read_report_rows(path):
    rows = []
    for row in read_xlsx_rows(path, "Деталі")[5:]:
        number = clean_text(report_cell(row, 0))
        name = clean_text(report_cell(row, 1))
        if not name:
            continue
        rrp = normalize_price(report_cell(row, 2))
        jabko_price = normalize_price(report_cell(row, 4)) or rrp
        jabko_url = clean_text(report_cell(row, 5))
        if not jabko_url.startswith("http"):
            jabko_url = ""
        rows.append({
            "row_number": number,
            "source_name": name,
            "source_price": jabko_price,
            "jabko_url": jabko_url,
        })
    return rows


def extract_skus(value):
    raw = clean_text(value)
    skus = set()
    for match in re.findall(r"\b[A-Z]{1,5}\d[A-Z0-9]{2,6}\b", raw):
        if any(char.isdigit() for char in match):
            skus.add(match.lower())
    for match in re.findall(r"\b[a-z]{1,5}\d[a-z0-9]{2,6}\b", raw.lower()):
        if any(char.isdigit() for char in match):
            skus.add(match)
    return skus


def report_product_group(value):
    text = clean_name_for_key(value)
    if "macbook air" in text:
        return "macbook air"
    if "macbook pro" in text:
        return "macbook pro"
    if "mac mini" in text:
        return "mac mini"
    if "imac" in text:
        return "imac"
    if "ipad pro" in text:
        return "ipad pro"
    if "ipad air" in text:
        return "ipad air"
    if "ipad mini" in text:
        return "ipad mini"
    if "ipad" in text or "planshet" in text or "планшет" in text:
        return "ipad"
    if "watch ultra" in text or "apple watch ultra" in text:
        return "apple watch ultra"
    if "watch se" in text or "series se" in text:
        return "apple watch se"
    if "apple watch" in text or "watch series" in text:
        return "apple watch"
    if "airpods max" in text:
        return "airpods max"
    if "airpods pro" in text:
        return "airpods pro"
    if "airpods" in text:
        return "airpods"
    if "homepod mini" in text or "home pod mini" in text:
        return "homepod mini"
    if "homepod" in text or "home pod" in text:
        return "homepod"
    if "apple pencil" in text or "pencil" in text or "стилус" in text:
        return "apple pencil"
    if "apple tv remote" in text or "tv remote" in text:
        return "apple tv remote"
    if "magic keyboard" in text:
        return "magic keyboard"
    if "magic mouse" in text:
        return "magic mouse"
    return ""


def extract_year(value):
    match = re.search(r"\b(20\d{2})\b", clean_text(value))
    return match.group(1) if match else ""


def extract_ram(value):
    text = clean_name_for_key(value)
    match = re.search(r"\b(\d+)\s*(?:gb\s*)?ram\b", text)
    if not match:
        match = re.search(r"\b(\d+)\s*gb\s*(?:unified\s*)?memory\b", text)
    return f"{int(match.group(1))}gb" if match else ""


def extract_chip(value):
    text = clean_name_for_key(value)
    match = re.search(r"\bm\d(?:\s+(?:pro|max|ultra))?\b", text)
    return re.sub(r"\s+", " ", match.group(0)) if match else ""


def extract_screen_size(value):
    text = clean_name_for_key(value)
    match = re.search(r"\b(10\s*2|10\s*5|10\s*9|11|12\s*9|13|13\s*6|14|15|16|24|27)\b", text)
    return match.group(1).replace(" ", ".") if match else ""


def extract_watch_size(value):
    text = clean_name_for_key(value)
    match = re.search(r"\b(40|41|42|44|45|46|49)\s*mm\b", text)
    return f"{match.group(1)}mm" if match else ""


def extract_connectivity(value):
    text = clean_name_for_key(value)
    if "lte" in text or "cellular" in text or "gps lte" in text or "wi fi lte" in text:
        return "lte"
    if "wi fi" in text or "wifi" in text:
        return "wifi"
    if "gps" in text:
        return "gps"
    return ""


def extract_airpods_case(value):
    text = clean_name_for_key(value)
    if "left" in text or "levyy" in text or "levij" in text or "лівий" in text:
        return "left"
    if "right" in text or "praviy" in text or "pravij" in text or "правий" in text:
        return "right"
    if "амбуш" in text or "ear tips" in text:
        return "tips"
    if (
        "зарядний кейс" in text
        or "зарядний keys" in text
        or "zaryadnyy keys" in text
        or "zaryadnyy keys" in text
        or "keys magsafe" in text
        or "keys lighting" in text
        or "кейс" in text
    ):
        return "case"
    if "active noise cancellation" in text or "anc" in text:
        return "anc"
    if "wireless charging" in text or "magsafe" in text:
        return "wireless"
    return ""


def extract_airpods_generation(value):
    text = clean_name_for_key(value)
    if "airpods pro 3" in text:
        return "airpods pro 3"
    if "airpods pro 2" in text:
        return "airpods pro 2"
    if "airpods pro" in text:
        return "airpods pro"
    match = re.search(r"\bairpods\s+(2|3|4)\b", text)
    if match:
        return f"airpods {match.group(1)}"
    return ""


def report_features(name, url=""):
    text = f"{name} {url}"
    return {
        "skus": extract_skus(text),
        "group": report_product_group(text),
        "storage": extract_storage(text),
        "ram": extract_ram(text),
        "chip": extract_chip(text),
        "screen": extract_screen_size(text),
        "watch_size": extract_watch_size(text),
        "year": extract_year(text),
        "connectivity": extract_connectivity(text),
        "color": extract_color(text),
        "airpods_case": extract_airpods_case(text),
        "airpods_generation": extract_airpods_generation(text),
    }


def report_group_compatible(left, right):
    if not left or not right:
        return False
    if left == right:
        return True
    compatible = {
        ("ipad", "ipad air"),
        ("ipad", "ipad pro"),
        ("ipad", "ipad mini"),
        ("apple watch", "apple watch ultra"),
        ("apple watch", "apple watch se"),
        ("airpods", "airpods pro"),
        ("airpods", "airpods max"),
        ("homepod", "homepod mini"),
    }
    return (left, right) in compatible or (right, left) in compatible


def report_feature_score(source, candidate):
    if report_group_compatible(source["group"], "airpods") and report_group_compatible(candidate["group"], "airpods"):
        source_part = source.get("airpods_case")
        candidate_part = candidate.get("airpods_case")
        physical_parts = {"case", "left", "right", "tips"}
        if source_part in physical_parts and candidate_part != source_part:
            return 0
        if candidate_part in physical_parts and source_part not in physical_parts:
            return 0
        if candidate_part in physical_parts and source_part in physical_parts and source_part != candidate_part:
            return 0
        source_generation = source.get("airpods_generation")
        candidate_generation = candidate.get("airpods_generation")
        if source_generation and candidate_generation and source_generation != candidate_generation:
            return 0

    if source["skus"] and candidate["skus"] and source["skus"] & candidate["skus"]:
        return 100
    if not report_group_compatible(source["group"], candidate["group"]):
        return 0

    exact_group = source["group"] == candidate["group"]
    sparse_groups = {
        "airpods",
        "airpods pro",
        "airpods max",
        "homepod",
        "homepod mini",
        "apple pencil",
        "apple tv remote",
        "magic keyboard",
        "magic mouse",
    }
    score = 55 if exact_group and source["group"] in sparse_groups else 35
    strong_checked = 0
    strong_matched = 0
    for key, points in [
        ("storage", 18),
        ("ram", 14),
        ("chip", 12),
        ("screen", 10),
        ("watch_size", 18),
        ("connectivity", 8),
        ("color", 8),
        ("airpods_case", 14),
        ("airpods_generation", 18),
        ("year", 6),
    ]:
        source_value = source.get(key)
        candidate_value = candidate.get(key)
        if not source_value:
            continue
        if key != "year":
            strong_checked += 1
        if source_value == candidate_value:
            if key != "year":
                strong_matched += 1
            score += points
        elif candidate_value and key in {"storage", "watch_size"}:
            return 0

    if strong_checked and strong_matched == 0:
        return 0
    if source["group"] != candidate["group"]:
        score -= 8
    return max(0, min(score, 99))


def is_report_mygadget_url_allowed(url):
    lowered = url.lower()
    if any(exclude in lowered for exclude in MYGADGET_TECHNICAL_EXCLUDES):
        return False
    return any(contains in lowered for contains in MYGADGET_REPORT_CONTAINS)


def report_source_rank(url):
    lowered = url.lower()
    if "/znyato-z-virobnictva/" in lowered:
        return 5
    if "/b-us/" in lowered:
        return 2
    return 0


def load_report_mygadget_candidates(report_products, limit=None):
    xml_text = fetch_text(MYGADGET_SITEMAP, timeout=60)
    root = ET.fromstring(xml_text)
    namespace = {"sm": "http://www.sitemaps.org/schemas/sitemap/0.9"}
    urls = []
    for loc in root.findall(".//sm:loc", namespace):
        url = (loc.text or "").strip()
        if url and is_report_mygadget_url_allowed(url):
            urls.append(url)
    urls = list(dict.fromkeys(urls))

    source_features = [item["_report_features"] for item in report_products]
    selected = {}
    for url in urls:
        candidate = {
            "url": url,
            "_report_features": report_features(url, url),
            "name": url,
            "price_uah": "",
        }
        best = max((report_feature_score(source, candidate["_report_features"]) for source in source_features), default=0)
        if best >= 58:
            selected[url] = best

    ranked_urls = [
        url for url, _score in sorted(
            selected.items(),
            key=lambda item: (-item[1], report_source_rank(item[0]), item[0]),
        )
    ]
    if limit:
        ranked_urls = ranked_urls[:limit]
    return ranked_urls


def parse_report_jabko_rows(report_rows, workers, delay, user_agent):
    urls = [row["jabko_url"] for row in report_rows if row.get("jabko_url")]
    parsed_by_url = parse_template_jabko_rows(
        [{"jabko_url": url} for url in urls],
        workers=workers,
        delay=delay,
        user_agent=user_agent,
    ) if urls else {}

    products = []
    for row in report_rows:
        url = row.get("jabko_url", "")
        parsed = parsed_by_url.get(url, {}) if url else {}
        name = parsed.get("name") or row["source_name"]
        price = parsed.get("price_uah") or row.get("source_price", "")
        product = {
            "url": url,
            "name": name,
            "price_uah": price,
            "_source_name": row["source_name"],
            "_source_price": row.get("source_price", ""),
            "_report_features": report_features(name, url or row["source_name"]),
        }
        products.append(product)
    return products


def fetch_report_mygadget_rows(urls, workers, delay, user_agent):
    if not urls:
        return []
    print(f"Parsing {len(urls)} MyGadget report candidates with {workers} workers", file=sys.stderr)
    return parse_urls(
        urls,
        workers=workers,
        delay=delay,
        user_agent=user_agent,
        only_available=False,
        parse_func=parse_mygadget_product,
        public_rows=False,
    )


def choose_report_mygadget_product(jabko_product, mygadget_products):
    source = jabko_product["_report_features"]
    scored = []
    for product in mygadget_products:
        candidate_features = product.get("_report_features") or report_features(product.get("name", ""), product.get("url", ""))
        score = report_feature_score(source, candidate_features)
        if score >= 58:
            scored.append((score, product))
    if not scored:
        return None
    scored.sort(key=lambda item: (
        -item[0],
        report_source_rank(item[1].get("url", "")),
        price_number(item[1].get("price_uah")) or 10**12,
    ))
    return scored[0][1]


def build_report_compare_rows(jabko_products, mygadget_products):
    for product in mygadget_products:
        product["_report_features"] = report_features(product.get("name", ""), product.get("url", ""))

    output_rows = []
    for jabko_product in jabko_products:
        mygadget_product = choose_report_mygadget_product(jabko_product, mygadget_products)
        output_rows.append({
            "jabko_url": jabko_product.get("url", ""),
            "jabko_name": jabko_product.get("name", ""),
            "jabko_price_uah": jabko_product.get("price_uah", ""),
            "mygadget_url": mygadget_product.get("url", "") if mygadget_product else "",
            "mygadget_name": mygadget_product.get("name", "") if mygadget_product else "",
            "mygadget_price_uah": mygadget_product.get("price_uah", "") if mygadget_product else "",
        })
    return output_rows


def paired_output_paths(output):
    output = output or "other_products_price_compare.xlsx"
    folder, filename = os.path.split(output)
    stem, extension = os.path.splitext(filename)
    if extension.lower() == ".csv":
        csv_path = output
        xlsx_path = os.path.join(folder, f"{stem}.xlsx")
    else:
        xlsx_path = output
        csv_path = os.path.join(folder, f"{stem}.csv")
    return xlsx_path, csv_path


def run_compare_report(report_path, output, workers, delay, user_agent, mygadget_limit=None):
    report_rows = read_report_rows(report_path)
    if not report_rows:
        raise RuntimeError("Report does not contain any product rows.")

    jabko_products = parse_report_jabko_rows(
        report_rows,
        workers=workers,
        delay=delay,
        user_agent=user_agent,
    )
    candidate_urls = load_report_mygadget_candidates(jabko_products, limit=mygadget_limit)
    print(f"Found {len(candidate_urls)} possible MyGadget report matches in sitemap", file=sys.stderr)
    mygadget_products = fetch_report_mygadget_rows(
        candidate_urls,
        workers=workers,
        delay=delay,
        user_agent=user_agent,
    )
    rows = build_report_compare_rows(jabko_products, mygadget_products)

    xlsx_path, csv_path = paired_output_paths(output)
    xlsx_path = next_output_path(xlsx_path)
    csv_path = next_output_path(csv_path)
    write_table(rows, xlsx_path, fieldnames=TEMPLATE_COMPARE_FIELDS)
    write_csv(rows, csv_path, fieldnames=TEMPLATE_COMPARE_FIELDS)
    matched = sum(1 for row in rows if row.get("mygadget_url"))
    print(f"\nSaved {len(rows)} report compared products to {xlsx_path}", file=sys.stderr)
    print(f"Saved {len(rows)} report compared products to {csv_path}", file=sys.stderr)
    print(f"Matched MyGadget rows: {matched}; blank: {len(rows) - matched}", file=sys.stderr)


def main():
    parser = argparse.ArgumentParser(description="Parse products from jabko.ua sitemap.")
    parser.add_argument("--compare", action="store_true", help="Build Jabko vs MyGadget price comparison from config")
    parser.add_argument("--compare-template", action="store_true", help="Build Jabko vs MyGadget comparison from products_template.csv")
    parser.add_argument("--compare-report", action="store_true", help="Build non-phone report comparison from monitoring XLSX")
    parser.add_argument("--config", help="JSON config with categories to parse")
    parser.add_argument("--template", default="products_template.csv", help="CSV template for --compare-template")
    parser.add_argument("--report", help="XLSX monitoring report for --compare-report")
    parser.add_argument("--sitemap", default=DEFAULT_SITEMAP, help=f"Sitemap URL. Default: {DEFAULT_SITEMAP}")
    parser.add_argument("--contains", help="Only parse product URLs containing this text, for example /iphone/")
    parser.add_argument("--limit", type=int, default=20, help="Maximum product pages to parse. Default: 20")
    parser.add_argument("--mygadget-limit", type=int, help="Maximum MyGadget URLs for --compare-template. Default: all")
    parser.add_argument("--delay", type=float, default=1.0, help="Delay between product requests in seconds. Default: 1.0")
    parser.add_argument("--workers", type=int, default=1, help="Parallel product requests. Use 5-10 for faster parsing. Default: 1")
    parser.add_argument("--format", choices=("csv", "json"), default="csv", help="Output format. Default: csv")
    parser.add_argument("--output", help="Output file path")
    parser.add_argument("--user-agent", default=DEFAULT_USER_AGENT, help="Custom User-Agent header")
    parser.add_argument(
        "--only-available",
        dest="only_available",
        action="store_true",
        default=True,
        help="Save only available products. Default: enabled",
    )
    parser.add_argument(
        "--include-unavailable",
        dest="only_available",
        action="store_false",
        help="Include archived, preorder, and out-of-stock products",
    )
    args = parser.parse_args()

    if args.compare_report:
        if not args.report:
            raise SystemExit("--compare-report requires --report monitoring.xlsx")
        run_compare_report(
            report_path=args.report,
            output=args.output,
            workers=args.workers,
            delay=args.delay,
            user_agent=args.user_agent,
            mygadget_limit=args.mygadget_limit,
        )
        return 0

    if args.compare_template:
        run_compare_template(
            template_path=args.template,
            output=args.output,
            workers=args.workers,
            delay=args.delay,
            user_agent=args.user_agent,
            mygadget_limit=args.mygadget_limit,
            only_available=args.only_available,
        )
        return 0

    if args.compare:
        if not args.config:
            raise SystemExit("--compare requires --config compare.example.json")
        run_compare_config(args.config, output_override=args.output)
        return 0

    if args.config:
        run_config(args.config)
        return 0

    run_job(vars(args), {})
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
