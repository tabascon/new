import { json, loadData, saveData } from "./_common.js";

const VALID_STATUSES = new Set(["running", "completed", "failed"]);

function kyivDisplay(timestampMs) {
  const parts = new Intl.DateTimeFormat("uk-UA", {
    timeZone: "Europe/Kyiv",
    day: "2-digit",
    month: "2-digit",
    year: "numeric",
    hour: "2-digit",
    minute: "2-digit",
    hourCycle: "h23",
  }).formatToParts(new Date(timestampMs));
  const values = Object.fromEntries(parts.map((part) => [part.type, part.value]));
  return `${values.day}.${values.month}.${values.year}, ${values.hour}:${values.minute}`;
}

function clockMeta(meta) {
  return {
    last_update_started_at_ms: meta.last_update_started_at_ms,
    last_update_display_kyiv: meta.last_update_display_kyiv,
    last_update_status: meta.last_update_status,
    last_update_errors: meta.last_update_errors,
    last_update_id: meta.last_update_id,
    last_updated_at: meta.last_updated_at,
    last_updated_source: meta.last_updated_source,
    last_updated_rows: meta.last_updated_rows,
    last_updated_prices: meta.last_updated_prices,
    last_updated_errors: meta.last_updated_errors,
    last_update_duration_seconds: meta.last_update_duration_seconds,
  };
}

export async function onRequestPost({ request, env }) {
  try {
    const body = await request.json();
    const status = String(body.status || "");
    if (!VALID_STATUSES.has(status)) throw new Error("Invalid update status");

    const data = await loadData(env, request);
    const meta = data.meta || {};

    if (status === "running") {
      const timestampMs = Date.now();
      meta.last_update_started_at_ms = timestampMs;
      meta.last_update_display_kyiv = kyivDisplay(timestampMs);
      meta.last_update_status = "running";
      meta.last_update_errors = 0;
      meta.last_update_id = crypto.randomUUID();
      meta.last_updated_at = new Date(timestampMs).toISOString();
      meta.last_updated_source = String(body.source || "manual");
    } else {
      const updateId = String(body.update_id || "");
      if (!updateId || updateId !== meta.last_update_id) {
        return json({ ok: false, stale: true, error: "Update ID is no longer current" }, 409);
      }
      meta.last_update_status = status;
      meta.last_update_errors = Math.max(0, Number(body.errors || 0));
      meta.last_updated_errors = meta.last_update_errors;
      if (body.rows !== undefined) meta.last_updated_rows = Math.max(0, Number(body.rows || 0));
      if (body.prices !== undefined) meta.last_updated_prices = Math.max(0, Number(body.prices || 0));
      if (body.duration_seconds !== undefined) {
        meta.last_update_duration_seconds = Math.max(0, Number(body.duration_seconds || 0));
      }
    }

    data.meta = meta;
    await saveData(env, data);
    return json({ ok: true, meta: clockMeta(meta) });
  } catch (error) {
    return json({ ok: false, error: error.message }, 400);
  }
}
