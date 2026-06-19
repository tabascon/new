const DATA_KEY = "price_compare_data";

export function isValidPriceData(data) {
  if (!data || !Array.isArray(data.sections) || data.sections.length === 0) return false;
  return data.sections.every((section) => (
    section &&
    typeof section.key === "string" &&
    typeof section.title === "string" &&
    Array.isArray(section.rows)
  ));
}

export async function loadData(env, request) {
  if (env.PRICE_DATA) {
    const saved = await env.PRICE_DATA.get(DATA_KEY, "json");
    if (isValidPriceData(saved)) return saved;
  }
  const assetUrl = new URL("/initial-data.json", request.url);
  const response = await env.ASSETS.fetch(new Request(assetUrl));
  return response.json();
}

export async function saveData(env, data) {
  if (!env.PRICE_DATA) {
    throw new Error("KV binding PRICE_DATA is not configured");
  }
  if (!isValidPriceData(data)) {
    throw new Error("Invalid price table data");
  }
  await env.PRICE_DATA.put(DATA_KEY, JSON.stringify(data));
}

export function json(data, status = 200) {
  return new Response(JSON.stringify(data), {
    status,
    headers: {
      "content-type": "application/json; charset=utf-8",
      "cache-control": "no-store",
    },
  });
}

export function normalizePrice(value) {
  const text = String(value || "").replace(/<[^>]+>/g, " ").replace(/\s+/g, " ").trim();
  const match = text.match(/[\d\s]+(?:[.,]\d+)?/);
  if (!match) return "";
  const amount = Number(match[0].replace(/\s/g, "").replace(",", "."));
  return Number.isFinite(amount) ? String(Math.round(amount)) : "";
}

function firstMatch(pattern, text) {
  const match = text.match(pattern);
  return match ? match[1].replace(/<[^>]+>/g, " ").replace(/\s+/g, " ").trim() : "";
}

function decodeHtmlAttribute(value) {
  return String(value || "")
    .replaceAll("&quot;", '"')
    .replaceAll("&#34;", '"')
    .replaceAll("&#039;", "'")
    .replaceAll("&apos;", "'")
    .replaceAll("&amp;", "&");
}

function normalizeUrl(value) {
  try {
    return new URL(value).href.replace(/\/$/, "");
  } catch {
    return String(value || "").replace(/\/$/, "");
  }
}

function tagAttribute(tag, name) {
  const match = tag.match(new RegExp(`${name}=([\"'])(.*?)\\1`, "is"));
  return match ? decodeHtmlAttribute(match[2]) : "";
}

function swatchPrice(swatchText) {
  let swatch = null;
  try {
    swatch = JSON.parse(swatchText);
  } catch {
    swatch = null;
  }
  const value = swatch?.price_uah_no_currency || swatch?.price_uah || "";
  return normalizePrice(value);
}

function parseJabkoSwatchPrice(html, url) {
  const currentUrl = normalizeUrl(url);
  const tags = [...html.matchAll(/<a\b[^>]*data-swatch=(["']).*?\1[^>]*>/gis)].map((match) => match[0]);
  const exact = tags.find((tag) => normalizeUrl(tagAttribute(tag, "href")) === currentUrl);
  if (exact) {
    const price = swatchPrice(tagAttribute(exact, "data-swatch"));
    if (price) return price;
  }

  const active = tags.find((tag) => /\bactive\b/i.test(tagAttribute(tag, "class")));
  if (active) {
    const price = swatchPrice(tagAttribute(active, "data-swatch"));
    if (price) return price;
  }

  const anySwatch = [...html.matchAll(/data-swatch=(["'])(.*?)\1/gis)];
  for (const item of anySwatch) {
    const price = swatchPrice(decodeHtmlAttribute(item[2]));
    if (price) return price;
  }
  return "";
}

async function fetchHtml(url) {
  const response = await fetch(url, {
    headers: {
      "user-agent": "Mozilla/5.0 PriceCompareBot/1.0",
      "accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
      "accept-language": "uk-UA,uk;q=0.9,en;q=0.8",
    },
  });
  if (!response.ok) throw new Error(`HTTP ${response.status}`);
  return response.text();
}

export async function parseJabkoPrice(url) {
  if (!url) return "";
  if (!url.includes("jabko.ua")) throw new Error("URL не з jabko.ua");
  const html = await fetchHtml(url);
  return (
    parseJabkoSwatchPrice(html, url) ||
    normalizePrice(firstMatch(/class=["'][^"']*price-new__uah[^"']*["'][^>]*>(.*?)<\/span>/is, html)) ||
    normalizePrice(firstMatch(/data-price=["']([^"']+)/i, html))
  );
}

export async function parseMyGadgetPrice(url) {
  if (!url) return "";
  if (!url.includes("mygadget.ua")) throw new Error("URL не з mygadget.ua");
  const html = await fetchHtml(url);
  return (
    normalizePrice(firstMatch(/<meta[^>]+itemprop=["']price["'][^>]+content=["']([^"']+)/i, html)) ||
    normalizePrice(firstMatch(/<span[^>]+class=["'][^"']*priceC[^"']*["'][^>]*>(.*?)<\/span>/is, html)) ||
    normalizePrice(firstMatch(/<div[^>]+class=["'][^"']*price__new[^"']*["'][^>]*>(.*?)<\/div>/is, html))
  );
}

export async function parseMyGadgetExchangeRate() {
  const html = await fetchHtml("https://mygadget.ua/");
  const exchangeText = firstMatch(
    /<div[^>]+class=["'][^"']*header__row-exchange[^"']*["'][^>]*>(.*?)<\/div>/is,
    html,
  );
  const match = exchangeText.match(/USD\s*([\d]+(?:[.,]\d+)?)/i);
  if (!match) throw new Error("Курс USD не знайдено");
  const rate = Number(match[1].replace(",", "."));
  if (!Number.isFinite(rate) || rate <= 0) throw new Error("Некоректний курс USD");
  return rate.toFixed(2);
}

export async function refreshRow(row) {
  const output = { ...row };
  let updated = 0;
  let failed = 0;
  const errors = [];

  if (!output.jabko_url) {
    output.jabko_price_uah = "";
  } else {
    try {
      output.jabko_price_uah = await parseJabkoPrice(output.jabko_url);
      if (!output.jabko_price_uah) throw new Error("Ціну не знайдено");
      updated += 1;
    } catch (error) {
      failed += 1;
      errors.push(`Jabko: ${error.message}`);
    }
  }

  if (!output.mygadget_url) {
    output.mygadget_price_uah = "";
  } else {
    try {
      output.mygadget_price_uah = await parseMyGadgetPrice(output.mygadget_url);
      if (!output.mygadget_price_uah) throw new Error("Ціну не знайдено");
      updated += 1;
    } catch (error) {
      failed += 1;
      errors.push(`MyGadget: ${error.message}`);
    }
  }

  return { row: output, updated, failed, errors };
}
