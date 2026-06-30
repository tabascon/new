const DATA_URL = "https://new-4zc.pages.dev/api/data";
const DISPATCH_URL = "https://api.github.com/repos/tabascon/new/actions/workflows/refresh-prices.yml/dispatches";
const DAILY_TIMES = ["10:00", "14:00", "18:00"];

export function kyivNow(timestampMs = Date.now()) {
  const parts = new Intl.DateTimeFormat("en-CA", {
    timeZone: "Europe/Kyiv",
    year: "numeric",
    month: "2-digit",
    day: "2-digit",
    hour: "2-digit",
    minute: "2-digit",
    hourCycle: "h23",
  }).formatToParts(new Date(timestampMs));
  const values = Object.fromEntries(parts.map((part) => [part.type, part.value]));
  return {
    date: `${values.year}-${values.month}-${values.day}`,
    time: `${values.hour}:${values.minute}`,
  };
}

export function dueSlot(now, lastAutoSlot = "") {
  const candidates = DAILY_TIMES
    .filter((time) => time <= now.time)
    .map((time) => `${now.date}T${time}`)
    .filter((slot) => slot > lastAutoSlot);
  return candidates.at(-1) || "";
}

async function loadLastAutoSlot() {
  const response = await fetch(`${DATA_URL}?scheduler=${Date.now()}`, {
    headers: { "Cache-Control": "no-store" },
  });
  if (!response.ok) throw new Error(`Data API returned HTTP ${response.status}`);
  const data = await response.json();
  return String(data?.meta?.last_auto_slot || "");
}

async function dispatchRefresh(token, slot) {
  const response = await fetch(DISPATCH_URL, {
    method: "POST",
    headers: {
      "Accept": "application/vnd.github+json",
      "Authorization": `Bearer ${token}`,
      "Content-Type": "application/json",
      "User-Agent": "price-compare-scheduler",
      "X-GitHub-Api-Version": "2022-11-28",
    },
    body: JSON.stringify({ ref: "main", inputs: { scheduled_slot: slot } }),
  });
  if (response.status !== 204) {
    throw new Error(`GitHub dispatch returned HTTP ${response.status}: ${await response.text()}`);
  }
}

export async function runScheduler(env, timestampMs = Date.now()) {
  if (!env.GITHUB_TOKEN) throw new Error("GITHUB_TOKEN secret is not configured");
  const now = kyivNow(timestampMs);
  const lastAutoSlot = await loadLastAutoSlot();
  const slot = dueSlot(now, lastAutoSlot);
  if (!slot) {
    console.log(`No due slot at ${now.date} ${now.time}; last=${lastAutoSlot || "none"}`);
    return { dispatched: false, now, lastAutoSlot };
  }
  await dispatchRefresh(env.GITHUB_TOKEN, slot);
  console.log(`Dispatched GitHub refresh for ${slot}; last=${lastAutoSlot || "none"}`);
  return { dispatched: true, slot, now, lastAutoSlot };
}

export default {
  async scheduled(controller, env, ctx) {
    ctx.waitUntil(runScheduler(env, controller.scheduledTime));
  },

  async fetch() {
    return Response.json({
      ok: true,
      service: "price-compare-scheduler",
      timezone: "Europe/Kyiv",
      times: DAILY_TIMES,
    });
  },
};
