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

function escapeXml(value) {
  return String(value || "")
    .replaceAll("&", "&amp;")
    .replaceAll("<", "&lt;")
    .replaceAll(">", "&gt;")
    .replaceAll('"', "&quot;")
    .replaceAll("'", "&apos;");
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
  if (typeof fetch === "undefined") {
    return xhrJson(path, payload);
  }
  const response = await fetch(path, {
    method: payload ? "POST" : "GET",
    headers: payload ? { "Content-Type": "application/json" } : {},
    body: payload ? JSON.stringify(payload) : undefined,
  });
  if (!response.ok) throw new Error(await response.text());
  return response.json();
}

function xhrJson(path, payload) {
  return new Promise((resolve, reject) => {
    const request = new XMLHttpRequest();
    request.open(payload ? "POST" : "GET", path);
    request.setRequestHeader("cache-control", "no-store");
    if (payload) request.setRequestHeader("content-type", "application/json");
    request.onload = () => {
      if (request.status < 200 || request.status >= 300) {
        reject(new Error(request.responseText || `HTTP ${request.status}`));
        return;
      }
      try {
        resolve(JSON.parse(request.responseText));
      } catch (error) {
        reject(error);
      }
    };
    request.onerror = () => reject(new Error("Network error"));
    request.send(payload ? JSON.stringify(payload) : undefined);
  });
}

function xhrBlob(path, payload) {
  return new Promise((resolve, reject) => {
    const request = new XMLHttpRequest();
    request.open(payload ? "POST" : "GET", path);
    request.responseType = "blob";
    if (payload) request.setRequestHeader("content-type", "application/json");
    request.onload = () => {
      if (request.status < 200 || request.status >= 300) {
        reject(new Error(`HTTP ${request.status}`));
        return;
      }
      resolve(request.response);
    };
    request.onerror = () => reject(new Error("Network error"));
    request.send(payload ? JSON.stringify(payload) : undefined);
  });
}

async function loadData() {
  try {
    appData = await api("/api/data");
  } catch {
    appData = await api("/initial-data.json");
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

const CRC_TABLE = (() => {
  const table = [];
  for (let n = 0; n < 256; n += 1) {
    let c = n;
    for (let k = 0; k < 8; k += 1) c = c & 1 ? 0xedb88320 ^ (c >>> 1) : c >>> 1;
    table[n] = c >>> 0;
  }
  return table;
})();

function crc32(bytes) {
  let crc = 0xffffffff;
  for (const byte of bytes) crc = CRC_TABLE[(crc ^ byte) & 0xff] ^ (crc >>> 8);
  return (crc ^ 0xffffffff) >>> 0;
}

function dosDateTime(date = new Date()) {
  const time = (date.getHours() << 11) | (date.getMinutes() << 5) | Math.floor(date.getSeconds() / 2);
  const day = Math.max(1, date.getDate());
  const dosDate = ((date.getFullYear() - 1980) << 9) | ((date.getMonth() + 1) << 5) | day;
  return { time, date: dosDate };
}

function pushU16(out, value) {
  out.push(value & 0xff, (value >>> 8) & 0xff);
}

function pushU32(out, value) {
  out.push(value & 0xff, (value >>> 8) & 0xff, (value >>> 16) & 0xff, (value >>> 24) & 0xff);
}

function encodeUtf8(value) {
  const bytes = [];
  for (const char of String(value)) {
    const codePoint = char.codePointAt(0);
    if (codePoint <= 0x7f) {
      bytes.push(codePoint);
    } else if (codePoint <= 0x7ff) {
      bytes.push(0xc0 | (codePoint >> 6), 0x80 | (codePoint & 0x3f));
    } else if (codePoint <= 0xffff) {
      bytes.push(0xe0 | (codePoint >> 12), 0x80 | ((codePoint >> 6) & 0x3f), 0x80 | (codePoint & 0x3f));
    } else {
      bytes.push(
        0xf0 | (codePoint >> 18),
        0x80 | ((codePoint >> 12) & 0x3f),
        0x80 | ((codePoint >> 6) & 0x3f),
        0x80 | (codePoint & 0x3f),
      );
    }
  }
  return new Uint8Array(bytes);
}

function createZip(files) {
  const encoder = typeof TextEncoder === "undefined" ? { encode: encodeUtf8 } : new TextEncoder();
  const out = [];
  const central = [];
  const now = dosDateTime();
  let offset = 0;

  files.forEach((file) => {
    const nameBytes = encoder.encode(file.name);
    const data = typeof file.content === "string" ? encoder.encode(file.content) : file.content;
    const crc = crc32(data);
    const local = [];
    pushU32(local, 0x04034b50);
    pushU16(local, 20);
    pushU16(local, 0);
    pushU16(local, 0);
    pushU16(local, now.time);
    pushU16(local, now.date);
    pushU32(local, crc);
    pushU32(local, data.length);
    pushU32(local, data.length);
    pushU16(local, nameBytes.length);
    pushU16(local, 0);
    out.push(...local, ...nameBytes, ...data);

    const entry = [];
    pushU32(entry, 0x02014b50);
    pushU16(entry, 20);
    pushU16(entry, 20);
    pushU16(entry, 0);
    pushU16(entry, 0);
    pushU16(entry, now.time);
    pushU16(entry, now.date);
    pushU32(entry, crc);
    pushU32(entry, data.length);
    pushU32(entry, data.length);
    pushU16(entry, nameBytes.length);
    pushU16(entry, 0);
    pushU16(entry, 0);
    pushU16(entry, 0);
    pushU16(entry, 0);
    pushU32(entry, 0);
    pushU32(entry, offset);
    central.push(...entry, ...nameBytes);
    offset = out.length;
  });

  const centralOffset = out.length;
  out.push(...central);
  const end = [];
  pushU32(end, 0x06054b50);
  pushU16(end, 0);
  pushU16(end, 0);
  pushU16(end, files.length);
  pushU16(end, files.length);
  pushU32(end, central.length);
  pushU32(end, centralOffset);
  pushU16(end, 0);
  out.push(...end);
  return new Uint8Array(out);
}

function columnName(index) {
  let name = "";
  let n = index + 1;
  while (n > 0) {
    n -= 1;
    name = String.fromCharCode(65 + (n % 26)) + name;
    n = Math.floor(n / 26);
  }
  return name;
}

function sheetCell(value, rowIndex, columnIndex, style = "") {
  const ref = `${columnName(columnIndex)}${rowIndex + 1}`;
  const styleAttr = style ? ` s="${style}"` : "";
  if (typeof value === "number" && Number.isFinite(value)) {
    return `<c r="${ref}"${styleAttr}><v>${value}</v></c>`;
  }
  return `<c r="${ref}" t="inlineStr"${styleAttr}><is><t>${escapeXml(value)}</t></is></c>`;
}

function buildSheetXml(rows) {
  const columnWidths = [18, 48, 52, 15, 48, 52, 15, 15];
  const cols = columnWidths.map((width, index) => `<col min="${index + 1}" max="${index + 1}" width="${width}" customWidth="1"/>`).join("");
  const sheetRows = rows.map((row, rowIndex) => {
    const cells = row.map((cell, columnIndex) => sheetCell(cell, rowIndex, columnIndex, rowIndex === 0 ? "1" : ""));
    return `<row r="${rowIndex + 1}">${cells.join("")}</row>`;
  });
  return `<?xml version="1.0" encoding="UTF-8" standalone="yes"?>
<worksheet xmlns="http://schemas.openxmlformats.org/spreadsheetml/2006/main">
  <cols>${cols}</cols>
  <sheetData>${sheetRows.join("")}</sheetData>
</worksheet>`;
}

function createWorkbookBlob(rows) {
  const files = [
    {
      name: "[Content_Types].xml",
      content: `<?xml version="1.0" encoding="UTF-8" standalone="yes"?>
<Types xmlns="http://schemas.openxmlformats.org/package/2006/content-types">
  <Default Extension="rels" ContentType="application/vnd.openxmlformats-package.relationships+xml"/>
  <Default Extension="xml" ContentType="application/xml"/>
  <Override PartName="/xl/workbook.xml" ContentType="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet.main+xml"/>
  <Override PartName="/xl/worksheets/sheet1.xml" ContentType="application/vnd.openxmlformats-officedocument.spreadsheetml.worksheet+xml"/>
  <Override PartName="/xl/styles.xml" ContentType="application/vnd.openxmlformats-officedocument.spreadsheetml.styles+xml"/>
</Types>`,
    },
    {
      name: "_rels/.rels",
      content: `<?xml version="1.0" encoding="UTF-8" standalone="yes"?>
<Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships">
  <Relationship Id="rId1" Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/officeDocument" Target="xl/workbook.xml"/>
</Relationships>`,
    },
    {
      name: "xl/workbook.xml",
      content: `<?xml version="1.0" encoding="UTF-8" standalone="yes"?>
<workbook xmlns="http://schemas.openxmlformats.org/spreadsheetml/2006/main" xmlns:r="http://schemas.openxmlformats.org/officeDocument/2006/relationships">
  <sheets><sheet name="Price Compare" sheetId="1" r:id="rId1"/></sheets>
</workbook>`,
    },
    {
      name: "xl/_rels/workbook.xml.rels",
      content: `<?xml version="1.0" encoding="UTF-8" standalone="yes"?>
<Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships">
  <Relationship Id="rId1" Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/worksheet" Target="worksheets/sheet1.xml"/>
  <Relationship Id="rId2" Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/styles" Target="styles.xml"/>
</Relationships>`,
    },
    {
      name: "xl/styles.xml",
      content: `<?xml version="1.0" encoding="UTF-8" standalone="yes"?>
<styleSheet xmlns="http://schemas.openxmlformats.org/spreadsheetml/2006/main">
  <fonts count="2"><font><sz val="11"/><name val="Calibri"/></font><font><b/><sz val="11"/><name val="Calibri"/></font></fonts>
  <fills count="1"><fill><patternFill patternType="none"/></fill></fills>
  <borders count="1"><border><left/><right/><top/><bottom/><diagonal/></border></borders>
  <cellStyleXfs count="1"><xf numFmtId="0" fontId="0" fillId="0" borderId="0"/></cellStyleXfs>
  <cellXfs count="2"><xf numFmtId="0" fontId="0" fillId="0" borderId="0" xfId="0"/><xf numFmtId="0" fontId="1" fillId="0" borderId="0" xfId="0"/></cellXfs>
</styleSheet>`,
    },
    { name: "xl/worksheets/sheet1.xml", content: buildSheetXml(rows) },
  ];
  const zipBytes = createZip(files);
  return new Blob([zipBytes], { type: "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet" });
}

async function downloadXlsx() {
  syncAdminInputs();
  let blob;
  if (typeof fetch === "undefined") {
    blob = await xhrBlob("/api/download-xlsx", appData);
  } else {
    const response = await fetch("/api/download-xlsx", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(appData),
    });
    if (!response.ok) throw new Error(await response.text());
    blob = await response.blob();
  }
  const url = URL.createObjectURL(blob);
  const link = document.createElement("a");
  link.href = url;
  link.download = "price_compare.xlsx";
  link.style.display = "none";
  document.body.appendChild(link);
  link.click();
  link.remove();
  setTimeout(() => URL.revokeObjectURL(url), 1000);
}

document.addEventListener("click", async (event) => {
  const target = event.target;
  if (target.id === "save-button") await saveData();
  if (target.id === "refresh-all-button") await refreshRows();
  if (target.id === "download-button") {
    try {
      await downloadXlsx();
    } catch (error) {
      showNotice(`Не вдалося скачати XLSX: ${error.message}`, true);
    }
  }
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
