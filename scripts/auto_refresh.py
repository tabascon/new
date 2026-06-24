#!/usr/bin/env python3

import base64
import json
import os
import sys
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import datetime
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
        "Accept-Language": "uk-UA,uk;q=0.9,en;q=0.8",
        "Cache-Control": "no-store",
        "User-Agent": (
            "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 "
            "(KHTML, like Gecko) Chrome/136.0.0.0 Safari/537.36"
        ),
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
        except (HTTPError, URLError, TimeoutError, OSError, json.JSONDecodeError) as error:
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


def due_slot(now_kyiv):
    due_hours = [hour for hour in TARGET_HOURS if now_kyiv.hour >= hour]
    if not due_hours:
        return None
    return f"{now_kyiv:%Y-%m-%d}T{max(due_hours):02d}"


def main():
    force = os.environ.get("FORCE_REFRESH", "").lower() in {"1", "true", "yes"}
    now_kyiv = datetime.now(KYIV)
    slot = due_slot(now_kyiv)

    data = request_json("/api/data")
    meta = data.setdefault("meta", {})

    if not force:
        if slot is None:
            print(f"Skip: Kyiv time is {now_kyiv:%H:%M}; the first slot is 12:00.")
            return 0
        if meta.get("last_auto_slot") == slot:
            print(f"Skip: slot {slot} was already completed.")
            return 0

    clock = request_json(
        "/api/update-clock",
        {"status": "running", "source": "manual workflow" if force else "automatic"},
    )
    clock_meta = clock["meta"]
    update_id = clock_meta["last_update_id"]
    meta.update(clock_meta)

    items = []
    for section_index, section in enumerate(data.get("sections", [])):
        for row_index, row in enumerate(section.get("rows", [])):
            items.append((section_index, row_index, row))

    started = time.monotonic()
    updated_prices = 0
    failed_prices = 0
    failed_rows = 0
    completed = 0

    try:
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

        total_errors = failed_prices + failed_rows
        duration_seconds = round(time.monotonic() - started)
        meta.update(
            {
                "last_updated_source": "manual workflow" if force else "automatic",
                "last_updated_rows": len(items),
                "last_updated_prices": updated_prices,
                "last_updated_errors": total_errors,
                "last_update_errors": total_errors,
                "last_update_duration_seconds": duration_seconds,
            }
        )
        try:
            exchange = request_json("/api/exchange-rate")
            rate = float(exchange.get("rate", 0))
            if rate > 0:
                meta["usd_rate_uah"] = f"{rate:.2f}"
                print(f"MyGadget USD rate: {rate:.2f}")
        except Exception as error:
            print(f"Warning: exchange rate was not updated: {error}")
        if not force:
            meta["last_auto_slot"] = slot

        request_json("/api/save", data)
        completed_clock = request_json(
            "/api/update-clock",
            {
                "status": "completed",
                "update_id": update_id,
                "errors": total_errors,
                "rows": len(items),
                "prices": updated_prices,
                "duration_seconds": duration_seconds,
            },
        )
        meta.update(completed_clock["meta"])
        print(
            "Saved: "
            f"rows={len(items)}, updated_prices={updated_prices}, "
            f"errors={total_errors}, time={meta['last_update_display_kyiv']}"
        )
        return 0
    except Exception:
        try:
            request_json(
                "/api/update-clock",
                {
                    "status": "failed",
                    "update_id": update_id,
                    "errors": max(1, failed_prices + failed_rows),
                    "rows": completed,
                    "prices": updated_prices,
                    "duration_seconds": round(time.monotonic() - started),
                },
            )
        except Exception as clock_error:
            print(f"Warning: failed to record update failure: {clock_error}")
        raise


if __name__ == "__main__":
    sys.exit(main())
