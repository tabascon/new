import { json, saveData } from "./_common.js";

export async function onRequestPost({ request, env }) {
  const data = await request.json();
  await saveData(env, data);
  return json({ ok: true });
}

