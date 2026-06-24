import { json, loadSchedule, saveSchedule } from "./_common.js";

const TIME_PATTERN = /^(?:[01]\d|2[0-3]):[0-5]\d$/;

function kyivNowParts(timestampMs = Date.now()) {
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

function addDays(dateText, days) {
  const [year, month, day] = dateText.split("-").map(Number);
  const date = new Date(Date.UTC(year, month - 1, day + days));
  return [
    date.getUTCFullYear(),
    String(date.getUTCMonth() + 1).padStart(2, "0"),
    String(date.getUTCDate()).padStart(2, "0"),
  ].join("-");
}

function normalizeTimes(value) {
  if (!Array.isArray(value) || value.length !== 3) {
    throw new Error("Потрібно передати рівно три поля часу");
  }
  const times = value.map((item) => String(item || "").trim());
  for (const time of times) {
    if (time && !TIME_PATTERN.test(time)) {
      throw new Error(`Некоректний формат часу: ${time}`);
    }
  }
  const active = times.filter(Boolean);
  if (new Set(active).size !== active.length) {
    throw new Error("Час автоматичного оновлення не повинен повторюватися");
  }
  return times;
}

export async function onRequestGet({ env }) {
  try {
    return json({ ok: true, schedule: await loadSchedule(env) });
  } catch (error) {
    return json({ ok: false, error: error.message }, 400);
  }
}

export async function onRequestPost({ request, env }) {
  try {
    const body = await request.json();
    const times = normalizeTimes(body.times);
    const current = await loadSchedule(env);
    const now = kyivNowParts();
    const slots = times.map((time, index) => {
      if (!time) return { time: "", active_from: "" };
      if (current.slots[index]?.time === time && current.slots[index]?.active_from) {
        return { time, active_from: current.slots[index].active_from };
      }
      return {
        time,
        active_from: time >= now.time ? now.date : addDays(now.date, 1),
      };
    });
    const schedule = { timezone: "Europe/Kyiv", slots };
    await saveSchedule(env, schedule);
    return json({ ok: true, schedule });
  } catch (error) {
    return json({ ok: false, error: error.message }, 400);
  }
}
