import { parseMyGadgetExchangeRate } from "./_common.js";

export async function onRequestGet() {
  try {
    const rate = await parseMyGadgetExchangeRate();
    return new Response(JSON.stringify({ rate }), {
      headers: {
        "content-type": "application/json; charset=utf-8",
        "cache-control": "public, max-age=300, s-maxage=1800",
      },
    });
  } catch (error) {
    return new Response(JSON.stringify({ error: error.message }), {
      status: 502,
      headers: {
        "content-type": "application/json; charset=utf-8",
        "cache-control": "no-store",
      },
    });
  }
}
