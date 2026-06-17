import { json, loadData } from "./_common.js";

export async function onRequestGet({ request, env }) {
  return json(await loadData(env, request));
}
