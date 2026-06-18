#!/usr/bin/env python3

import base64
import json
import os
import sys
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import datetime, timezone
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen
from zoneinfo import ZoneInfo


BASE_URL = os.environ.get("PRICE_COMPARE_URL", "https://new-4zc.pages.dev").rstrip("/")
ADMIN_USER = os.environ["ADMIN_USER"]
ADMIN_PASSWORD = os.environ["ADMIN_PASSWORD"]
WORKERS = max(1, min(int(os.environ.get("REFRESH_WORKERS", "6")), 10))
KYIV = ZoneInfo("Europe/Kyiv")
TARGET_HOURS = {12, 17}


def auth_header():
    token = base64.b64encode(f"{ADMIN_USER}:{ADMIN_PASSWORD}".encode()).decode()
    return f"Basic {token}"


def request_json(path, payload=None, retries=3):
    body = None if payload is None else json.dumps(payload, ensure_ascii=False).encode()
    headers = {
        "Authorization": auth_header(),
        "Accept": "application/json",
        "Cache-Control": "no-store",
    }
    if body is not None:
        headers["Content-Type"] = "application/json"
    request = Request(
        f"{BASE_URL}{path}",
        data=body,
        headers=headers,
        method="POST" if body is not None else "GET",
    )
    last_error = None
    for attempt in range(retries):
        try:
            with urlopen(request, timeout=90) as response:
                return json.loads(response.read().decode())
        except (HTTPError, URLError, TimeoutError, json.JSONDecodeError) as error:
            last_error = error
            if attempt + 1 < retries:
                time.sleep(2 ** attempt)
    raise RuntimeError(f"{path}: {last_error}")


def refresh_item(item):
    section_index, row_index, row = item
    try:
        result = request_json("/api/refresh-row-price", {"row": row})
        return section_index, row_index, result, None
    except Exception as error:
        return section_index, row_index, None, str(error)


def main():
    force = os.environ.get("FORCE_REFRESH", "").lower() in {"1", "true", "yes"}
    now_kyiv = datetime.now(KYIV)
    slot = now_kyiv.strftime("%Y-%m-%dT%H")

    data = request_json("/api/data")
    meta = data.setdefault("meta", {})

    if not force:
        if now_kyiv.hour not in TARGET_HOURS:
            print(f"Skip: Kyiv time is {now_kyiv:%H:%M}, target hours are 12:00 and 17:00.")
            return 0
        if meta.get("last_auto_slot") == slot:
            print(f"Skip: slot {slot} was already completed.")
            return 0

    items = []
    for section_index, section in enumerate(data.get("sections", [])):
        for row_index, row in enumerate(section.get("rows", [])):
            items.append((section_index, row_index, row))

    started = time.monotonic()
    updated_prices = 0
    failed_prices = 0
    failed_rows = 0
    completed = 0

    print(f"Refreshing {len(items)} rows with {WORKERS} workers.")
    with ThreadPoolExecutor(max_workers=WORKERS) as executor:
        futures = [executor.submit(refresh_item, item) for item in items]
        for future in as_completed(futures):
            section_index, row_index, result, error = future.result()
            completed += 1
            if result is None:
                failed_rows += 1
                print(f"[{completed}/{len(items)}] failed row: {error}")
            else:
                data["sections"][section_index]["rows"][row_index] = result["row"]
                updated_prices += int(result.get("updated", 0))
                failed_prices += int(result.get("failed", 0))
            if completed % 25 == 0 or completed == len(items):
                print(f"Progress: {completed}/{len(items)}")

    finished_utc = datetime.now(timezone.utc)
    meta.update(
        {
            "last_updated_at": finished_utc.isoformat().replace("+00:00", "Z"),
            "last_updated_source": "manual workflow" if force else "automatic",
            "last_updated_rows": len(items),
            "last_updated_prices": updated_prices,
            "last_updated_errors": failed_prices + failed_rows,
            "last_update_duration_seconds": round(time.monotonic() - started),
        }
    )
    if not force:
        meta["last_auto_slot"] = slot

    request_json("/api/save", data)
    print(
        "Saved: "
        f"rows={len(items)}, updated_prices={updated_prices}, "
        f"errors={failed_prices + failed_rows}, time={meta['last_updated_at']}"
    )
    return 0


if __name__ == "__main__":
    sys.exit(main())
