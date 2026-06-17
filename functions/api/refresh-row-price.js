import { json, refreshRow } from "./_common.js";

export async function onRequestPost({ request }) {
  const body = await request.json();
  return json(await refreshRow(body.row || {}));
}

