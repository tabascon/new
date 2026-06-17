const FIELD_NAMES = [
  "jabko_url",
  "jabko_name",
  "jabko_price_uah",
  "mygadget_url",
  "mygadget_name",
  "mygadget_price_uah",
];

let appData = { sections: [] };
let mode = window.location.pathname === "/admin" ? "admin" : "table";

const qs = (selector) => document.querySelector(selector);

function parsePrice(value) {
  const text = String(value || "").trim();
  if (!text) return null;
  const number = Number(text.replace(/[^\d-]/g, ""));
  return Number.isFinite(number) ? number : null;
}

function deviation(row) {
  const jabko = parsePrice(row.jabko_price_uah);
  const mygadget = parsePrice(row.mygadget_price_uah);
  if (jabko === null || mygadget === null) return "";
  return String(mygadget - jabko);
}

function money(value) {
  return String(value || "").trim() ? `${value} грн` : "";
}

function escapeHtml(value) {
  return String(value || "")
    .replaceAll("&", "&amp;")
    .replaceAll("<", "&lt;")
    .replaceAll(">", "&gt;")
    .replaceAll('"', "&quot;");
}

function linkedName(name, url) {
  if (!name) return '<span class="muted">-</span>';
  if (!url) return escapeHtml(name);
  return `<a href="${escapeHtml(url)}" target="_blank" rel="noopener">${escapeHtml(name)}</a>`;
}

function deviationHtml(row) {
  const value = deviation(row);
  if (value === "") return '<span class="muted">-</span>';
  const amount = Number(value);
  const sign = amount > 0 ? "+" : "";
  const css = amount > 0 ? "positive" : amount < 0 ? "negative" : "neutral";
  return `<span class="deviation ${css}">${sign}${amount} грн</span>`;
}

function rowAttrs(row, index) {
  return [
    'data-filter-row="1"',
    `data-original-index="${index}"`,
    `data-deviation="${escapeHtml(deviation(row) || "0")}"`,
    `data-has-jabko-url="${row.jabko_url ? 1 : 0}"`,
    `data-has-mygadget-url="${row.mygadget_url ? 1 : 0}"`,
    `data-has-jabko-price="${row.jabko_price_uah ? 1 : 0}"`,
    `data-has-mygadget-price="${row.mygadget_price_uah ? 1 : 0}"`,
  ].join(" ");
}

function rowText(row) {
  const fields = [...row.querySelectorAll("textarea, input")].map((item) => item.value || "");
  return `${row.textContent || ""} ${fields.join(" ")}`.toLowerCase();
}

function rowMatchesFilter(row, filter) {
  const diff = Number(row.dataset.deviation || "0");
  const hasJabkoUrl = row.dataset.hasJabkoUrl === "1";
  const hasMygadgetUrl = row.dataset.hasMygadgetUrl === "1";
  const hasJabkoPrice = row.dataset.hasJabkoPrice === "1";
  const hasMygadgetPrice = row.dataset.hasMygadgetPrice === "1";
  if (filter === "mygadget-cheaper") return diff < 0;
  if (filter === "jabko-cheaper") return diff > 0;
  if (filter === "missing-mygadget-url") return !hasMygadgetUrl;
  if (filter === "missing-price") return !hasJabkoPrice || !hasMygadgetPrice;
  if (filter === "problem") return !hasJabkoUrl || !hasMygadgetUrl || !hasJabkoPrice || !hasMygadgetPrice;
  return true;
}

function compareRows(a, b, sort) {
  const ad = Number(a.dataset.deviation || "0");
  const bd = Number(b.dataset.deviation || "0");
  if (sort === "diff-desc") return bd - ad;
  if (sort === "diff-asc") return ad - bd;
  if (sort === "diff-abs") return Math.abs(bd) - Math.abs(ad);
  if (sort === "name") return rowText(a).localeCompare(rowText(b), "uk");
  return Number(a.dataset.originalIndex || "0") - Number(b.dataset.originalIndex || "0");
}

function applyTableTools() {
  const search = (qs("#table-search")?.value || "").trim().toLowerCase();
  const filter = qs("#table-filter")?.value || "all";
  const sort = qs("#table-sort")?.value || "default";
  let shown = 0;
  let total = 0;

  document.querySelectorAll("tbody[data-filter-body]").forEach((tbody) => {
    const rows = [...tbody.querySelectorAll("tr[data-filter-row]")];
    rows.sort((a, b) => compareRows(a, b, sort)).forEach((row) => tbody.appendChild(row));
    rows.forEach((row) => {
      total += 1;
      const visible = (!search || rowText(row).includes(search)) && rowMatchesFilter(row, filter);
      row.classList.toggle("filtered-out", !visible);
      if (visible) shown += 1;
    });
  });

  const meta = qs("#filter-meta");
  if (meta) meta.textContent = `Показано ${shown} з ${total} рядків`;
}

function publicRow(row, index) {
  return `<tr ${rowAttrs(row, index)}>
    <td class="num">${index + 1}</td>
    <td class="name-col">${linkedName(row.jabko_name, row.jabko_url)}</td>
    <td class="price">${escapeHtml(money(row.jabko_price_uah))}</td>
    <td class="name-col">${linkedName(row.mygadget_name, row.mygadget_url)}</td>
    <td class="price">${escapeHtml(money(row.mygadget_price_uah))}</td>
    <td>${deviationHtml(row)}</td>
  </tr>`;
}

function adminRow(section, row, index) {
  const key = section.key;
  return `<tr ${rowAttrs(row, index)} data-section="${key}" data-index="${index}">
    <td class="num">${index + 1}</td>
    <td class="name-col"><textarea data-field="jabko_name">${escapeHtml(row.jabko_name)}</textarea></td>
    <td class="url-col"><textarea data-field="jabko_url">${escapeHtml(row.jabko_url)}</textarea></td>
    <td class="name-col"><textarea data-field="mygadget_name">${escapeHtml(row.mygadget_name)}</textarea></td>
    <td class="url-col"><textarea data-field="mygadget_url">${escapeHtml(row.mygadget_url)}</textarea></td>
    <td class="price" data-price-field="jabko_price_uah">${escapeHtml(money(row.jabko_price_uah))}</td>
    <td class="price" data-price-field="mygadget_price_uah">${escapeHtml(money(row.mygadget_price_uah))}</td>
    <td data-deviation-cell="1">${deviationHtml(row)}</td>
    <td><button class="button" type="button" data-action="refresh-row">Оновити</button></td>
  </tr>`;
}

function renderSection(section, open, isAdmin) {
  const rows = section.rows.map((row, index) => isAdmin ? adminRow(section, row, index) : publicRow(row, index)).join("");
  const head = isAdmin
    ? `<tr><th class="num">#</th><th>Імʼя товару Jabko</th><th>URL товару Jabko</th><th>Імʼя товару MyGadget</th><th>URL товару MyGadget</th><th>Ціна Jabko</th><th>Ціна MyGadget</th><th>Відхилення</th><th>Дії</th></tr>`
    : `<tr><th class="num">#</th><th>Товар Jabko</th><th>Ціна Jabko</th><th>Товар MyGadget</th><th>Ціна MyGadget</th><th>Відхилення</th></tr>`;
  const actions = isAdmin
    ? `<div class="section-actions"><button class="button" type="button" data-action="refresh-section" data-section="${section.key}">Оновити розділ</button><button class="button" type="button" data-action="add-row" data-section="${section.key}">Додати рядок</button></div>`
    : "";
  return `<details class="section" ${open ? "open" : ""}>
    <summary><span class="summary-left"><span class="summary-title">${escapeHtml(section.title)}</span><span class="summary-count">${section.rows.length} рядків</span></span><span>⌄</span></summary>
    <section class="table-shell">
      <table><thead>${head}</thead><tbody data-filter-body="1">${rows}</tbody></table>
      ${actions}
    </section>
  </details>`;
}

function syncAdminInputs() {
  document.querySelectorAll("tr[data-section][data-index]").forEach((tr) => {
    const section = appData.sections.find((item) => item.key === tr.dataset.section);
    const row = section?.rows[Number(tr.dataset.index)];
    if (!row) return;
    tr.querySelectorAll("textarea[data-field]").forEach((input) => {
      row[input.dataset.field] = input.value.trim();
    });
  });
}

function updateRowDom(tr, row) {
  tr.dataset.deviation = deviation(row) || "0";
  tr.dataset.hasJabkoUrl = row.jabko_url ? "1" : "0";
  tr.dataset.hasMygadgetUrl = row.mygadget_url ? "1" : "0";
  tr.dataset.hasJabkoPrice = row.jabko_price_uah ? "1" : "0";
  tr.dataset.hasMygadgetPrice = row.mygadget_price_uah ? "1" : "0";
  tr.querySelector('[data-price-field="jabko_price_uah"]').textContent = money(row.jabko_price_uah);
  tr.querySelector('[data-price-field="mygadget_price_uah"]').textContent = money(row.mygadget_price_uah);
  tr.querySelector("[data-deviation-cell]").innerHTML = deviationHtml(row);
}

function render() {
  const isAdmin = mode === "admin";
  const total = appData.sections.reduce((count, section) => count + section.rows.length, 0);
  qs("#page-title").textContent = isAdmin ? "Адмінка" : "Порівняння цін";
  qs("#page-meta").textContent = `${total} рядків у ${appData.sections.length} розділах`;
  qs("#save-button").classList.toggle("hidden", !isAdmin);
  qs("#refresh-all-button").classList.toggle("hidden", !isAdmin);
  qs("#sections").innerHTML = appData.sections.map((section, index) => renderSection(section, index === 0, isAdmin)).join("");
  qs("#view-table").classList.toggle("active", !isAdmin);
  qs("#view-admin").classList.toggle("active", isAdmin);
  applyTableTools();
}

function showNotice(message, error = false) {
  const box = qs("#notice");
  box.textContent = message;
  box.classList.toggle("error", error);
  box.classList.remove("hidden");
}

function setProgress(done, total, message) {
  const panel = qs("#progress");
  const percent = total ? Math.round((done / total) * 100) : 100;
  panel.classList.add("active");
  qs("#progress-fill").style.width = `${percent}%`;
  qs("#progress-percent").textContent = `${percent}%`;
  qs("#progress-detail").textContent = message || `${done} з ${total}`;
}

async function api(path, payload) {
  const response = await fetch(path, {
    method: payload ? "POST" : "GET",
    headers: payload ? { "Content-Type": "application/json" } : {},
    body: payload ? JSON.stringify(payload) : undefined,
  });
  if (!response.ok) throw new Error(await response.text());
  return response.json();
}

async function loadData() {
  try {
    appData = await api("/api/data");
  } catch {
    appData = await fetch("/initial-data.json").then((response) => response.json());
  }
  render();
}

async function saveData() {
  syncAdminInputs();
  await api("/api/save", appData);
  showNotice("Збережено в Cloudflare KV.");
}

async function refreshRow(sectionKey, index, button) {
  syncAdminInputs();
  const section = appData.sections.find((item) => item.key === sectionKey);
  const row = section.rows[index];
  button.disabled = true;
  button.textContent = "Оновлення...";
  try {
    const result = await api("/api/refresh-row-price", { row });
    Object.assign(row, result.row);
    const tr = document.querySelector(`tr[data-section="${sectionKey}"][data-index="${index}"]`);
    updateRowDom(tr, row);
    showNotice(`Рядок оновлено. Оновлено цін: ${result.updated}. Помилок: ${result.failed}.`, result.failed > 0);
  } finally {
    button.disabled = false;
    button.textContent = "Оновити";
  }
}

async function refreshRows(sectionKey = "") {
  syncAdminInputs();
  const rows = [];
  appData.sections.forEach((section) => {
    if (sectionKey && section.key !== sectionKey) return;
    section.rows.forEach((row, index) => rows.push({ section, row, index }));
  });
  let failed = 0;
  let updated = 0;
  setProgress(0, rows.length, "Старт оновлення...");
  for (let i = 0; i < rows.length; i += 1) {
    const item = rows[i];
    try {
      const result = await api("/api/refresh-row-price", { row: item.row });
      Object.assign(item.row, result.row);
      updated += result.updated;
      failed += result.failed;
    } catch {
      failed += 1;
    }
    setProgress(i + 1, rows.length, `${item.section.title}, рядок ${item.index + 1}`);
  }
  render();
  await saveData();
  showNotice(`Оновлення завершено. Оновлено цін: ${updated}. Помилок: ${failed}.`, failed > 0);
}

function addRow(sectionKey) {
  syncAdminInputs();
  const section = appData.sections.find((item) => item.key === sectionKey);
  section.rows.push(Object.fromEntries(FIELD_NAMES.map((field) => [field, ""])));
  render();
}

function downloadCsv() {
  syncAdminInputs();
  const rows = appData.sections.flatMap((section) => section.rows.map((row) => ({ section: section.title, ...row, deviation_uah: deviation(row) })));
  const fields = ["section", ...FIELD_NAMES, "deviation_uah"];
  const csv = [
    fields.join(","),
    ...rows.map((row) => fields.map((field) => `"${String(row[field] || "").replaceAll('"', '""')}"`).join(",")),
  ].join("\n");
  const blob = new Blob(["\ufeff", csv], { type: "text/csv;charset=utf-8" });
  const url = URL.createObjectURL(blob);
  const link = document.createElement("a");
  link.href = url;
  link.download = "price_compare.csv";
  link.click();
  URL.revokeObjectURL(url);
}

document.addEventListener("click", async (event) => {
  const target = event.target;
  if (target.id === "view-table") {
    mode = "table";
    window.history.pushState({}, "", "/");
    render();
  }
  if (target.id === "view-admin") {
    mode = "admin";
    window.history.pushState({}, "", "/admin");
    render();
  }
  if (target.id === "save-button") await saveData();
  if (target.id === "refresh-all-button") await refreshRows();
  if (target.id === "download-button") downloadCsv();
  if (target.dataset.action === "add-row") addRow(target.dataset.section);
  if (target.dataset.action === "refresh-section") await refreshRows(target.dataset.section);
  if (target.dataset.action === "refresh-row") {
    const tr = target.closest("tr");
    await refreshRow(tr.dataset.section, Number(tr.dataset.index), target);
  }
});

["table-search", "table-filter", "table-sort"].forEach((id) => {
  document.addEventListener("input", (event) => { if (event.target.id === id) applyTableTools(); });
  document.addEventListener("change", (event) => { if (event.target.id === id) applyTableTools(); });
});

loadData();
