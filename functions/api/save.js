import { json, saveData } from "./_common.js";

export async function onRequestPost({ request, env }) {
  try {
    const data = await request.json();
    await saveData(env, data);
    return json({ ok: true });
  } catch (error) {
    return json({ ok: false, error: error.message }, 400);
  }
}
