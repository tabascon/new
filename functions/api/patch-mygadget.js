import { json, loadData, saveData } from "./_common.js";

const FIELDS = ["mygadget_url", "mygadget_name", "mygadget_price_uah"];

export async function onRequestPost({ request, env }) {
  try {
    const payload = await request.json();
    const patches = Array.isArray(payload?.patches) ? payload.patches : [];
    const sectionKey = String(payload?.section || "");
    const data = await loadData(env, request);
    const section = data.sections.find((item) => item.key === sectionKey);

    if (!section) throw new Error("Section not found");
    if (!patches.length) throw new Error("No patches supplied");

    for (const patch of patches) {
      const index = Number(patch.index);
      if (!Number.isInteger(index) || index < 0 || index >= section.rows.length) {
        throw new Error(`Invalid row index: ${patch.index}`);
      }
      for (const field of FIELDS) {
        if (Object.hasOwn(patch, field)) {
          section.rows[index][field] = String(patch[field] ?? "");
        }
      }
    }

    await saveData(env, data);
    return json({ ok: true, updated: patches.length });
  } catch (error) {
    return json({ ok: false, error: error.message }, 400);
  }
}
