"use strict";
const $ = (id) => document.getElementById(id);
const esc = (s) => String(s).replace(/[&<>"']/g, (c) => ({"&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;"}[c]));
const fmt = (n, d = 0) => n == null ? "–" : Number(n).toLocaleString("sr-RS", {minimumFractionDigits: d, maximumFractionDigits: d});
const COLORS = {RSD: "#1f6feb", EUR: "#d9480f"};
const colorFor = (c) => COLORS[c] || "#6b7280";
const state = {tab: "time", sort: "trade_date", order: "desc", page: 1, pageSize: 100, total: 0, exSort: "trade_date", exOrder: "desc", emptyDb: false, loadError: ""};

async function api(path, {method, body} = {}) {
  const opts = body === undefined && !method ? {} :
    {method: method || "POST", headers: {"Content-Type": "application/json"}, body: body === undefined ? undefined : JSON.stringify(body)};
  const res = await fetch(path, opts);
  if (!res.ok) {
    let msg = res.statusText;
    try {
      const j = await res.json();
      msg = typeof j.detail === "string" ? j.detail : j.detail.map((d) => `${d.loc.slice(1).join(".")}: ${d.msg}`).join("; ");
    } catch (_) { /* keep status text */ }
    throw new Error(msg);
  }
  return res.json();
}

function showError(msg) { const e = $("error"); e.textContent = msg || ""; e.hidden = !msg; }

/* ---------- filter <-> form ---------- */
function readFilter() {
  const f = {};
  for (const id of ["date_from", "date_to"]) { const v = $(id).value; if (v) f[id] = v; }
  f.yield_basis = $("yield_basis").value;
  for (const fs of document.querySelectorAll("fieldset.range")) {
    const r = {};
    for (const inp of fs.querySelectorAll("[data-part]")) {
      const part = inp.dataset.part;
      if (inp.type === "checkbox") r[part] = inp.checked;
      else if (inp.value !== "") r[part] = Number(inp.value);
    }
    f[fs.dataset.range] = r;
  }
  const t = $("turnover_min").value;
  if (t !== "") f.turnover_min = Number(t);
  f.currency = [...document.querySelectorAll("input[name=currency]:checked")].map((i) => i.value);
  f.isin = [...$("isin").selectedOptions].map((o) => o.value);
  return f;
}

function writeFilter(f) {
  resetForm();
  for (const id of ["date_from", "date_to"]) if (f[id]) $(id).value = f[id];
  if (f.yield_basis) $("yield_basis").value = f.yield_basis;
  for (const fs of document.querySelectorAll("fieldset.range")) {
    const r = f[fs.dataset.range] || {};
    for (const inp of fs.querySelectorAll("[data-part]")) {
      const v = r[inp.dataset.part];
      if (inp.type === "checkbox") inp.checked = !!v; else if (v != null) inp.value = v;
    }
  }
  if (f.turnover_min != null) $("turnover_min").value = f.turnover_min;
  for (const c of document.querySelectorAll("input[name=currency]")) c.checked = (f.currency || []).includes(c.value);
  for (const o of $("isin").options) o.selected = (f.isin || []).includes(o.value);
}

function resetForm() {
  document.querySelectorAll("#filters input[type=number], #filters input[type=date]").forEach((i) => (i.value = ""));
  document.querySelectorAll("#filters input[type=checkbox]").forEach((i) => (i.checked = false));
  $("yield_basis").value = "avg";
  for (const o of $("isin").options) o.selected = false;
}

/* ---------- rendering ---------- */
function renderKpis(summary) {
  const el = $("kpis");
  if (!summary.kpis.length) { el.innerHTML = '<div class="kpi-empty">Nema rezultata za izabrane filtere.</div>'; return; }
  el.innerHTML = summary.kpis.map((k) => `
    <div class="kpi-card">
      <h3>${esc(k.currency)}</h3>
      <div class="kpi-grid">
        <div><span>Promet (${esc(k.currency)})</span><b>${fmt(k.turnover)}</b></div>
        <div><span>Ponderisani prinos</span><b>${k.weighted_yield_pct == null ? "–" : fmt(k.weighted_yield_pct, 2) + "%"}</b></div>
        <div><span>Količina</span><b>${fmt(k.quantity)}</b></div>
        <div><span>Transakcija</span><b>${fmt(k.transactions)}</b></div>
        <div><span>Hartija</span><b>${fmt(k.isins)}</b></div>
        <div><span>Dana</span><b>${fmt(k.active_days)}</b></div>
      </div>
    </div>`).join("") +
    (summary.quality_flagged ? `<div class="kpi-card"><h3>Kvalitet podataka</h3><b style="color:var(--warn)">${fmt(summary.quality_flagged)} označenih redova</b></div>` : "");
}

const ROW_COLS = [
  ["trade_date", "Datum", "l"], ["isin", "ISIN", "l"], ["currency", "Val.", "l"],
  ["coupon_pct", "Kupon %", 2], ["maturity_date", "Dospeće", "l"],
  ["remaining_maturity_days", "Preost. dana", 0], ["quantity", "Količina", 0],
  ["transaction_count", "Trans.", 0], ["wavg_price", "Pros. cena", 2],
  ["min_yield_pct", "Min %", 2], ["avg_yield_pct", "Prosek %", 2], ["max_yield_pct", "Max %", 2],
  ["turnover", "Promet", 2], ["quality_flag", "Kvalitet", "l"],
];

function renderRows(res) {
  state.total = res.total;
  const head = "<thead><tr>" + ROW_COLS.map(([k, label, kind]) =>
    `<th data-sort="${k}" class="${kind === "l" ? "l" : ""}">${label}${state.sort === k ? (state.order === "asc" ? " ▲" : " ▼") : ""}</th>`).join("") + "</tr></thead>";
  const body = "<tbody>" + res.rows.map((r) =>
    `<tr class="${r.quality_flag !== "OK" ? "flag" : ""}">` + ROW_COLS.map(([k, , kind]) =>
      `<td class="${kind === "l" ? "l" : ""}">${typeof kind === "number" ? fmt(r[k], kind) : esc(r[k])}</td>`).join("") + "</tr>").join("") + "</tbody>";
  $("rows").innerHTML = head + body;
  const pages = Math.max(1, Math.ceil(res.total / state.pageSize));
  $("page-info").textContent = `${fmt(res.total)} redova · strana ${state.page} / ${pages}`;
  $("prev").disabled = state.page <= 1;
  $("next").disabled = state.page >= pages;
  $("table-title").textContent = `Redovi (${fmt(res.total)})`;
}

// purge first: tabs use different axis layouts (e.g. the per-currency subplots) that must not leak between tabs
const plot = (traces, layout) => {
  Plotly.purge("chart");
  return Plotly.newPlot("chart", traces, Object.assign({
    margin: {l: 60, r: 20, t: 20, b: 50}, paper_bgcolor: "rgba(0,0,0,0)", plot_bgcolor: "rgba(0,0,0,0)",
    font: {color: getComputedStyle(document.body).color}, legend: {orientation: "h", y: -0.2},
  }, layout), {responsive: true, displaylogo: false});
};

const groupBy = (rows, key) => rows.reduce((m, r) => ((m[r[key]] = m[r[key]] || []).push(r), m), {});
const emptyChart = (msg) => plot([], {annotations: [{text: msg, showarrow: false, font: {size: 14}}], xaxis: {visible: false}, yaxis: {visible: false}});

function drawTime(rows) {
  if (!rows.length) return emptyChart("Nema podataka");
  const traces = Object.entries(groupBy(rows, "currency")).map(([cur, rs]) => ({
    type: "scatter", mode: "lines+markers", name: cur, x: rs.map((r) => r.period),
    y: rs.map((r) => r.weighted_yield_pct), line: {color: colorFor(cur)},
    hovertemplate: "%{x}<br>%{y:.2f}%<extra>" + cur + "</extra>",
  }));
  plot(traces, {yaxis: {title: "Ponderisani prosečni prinos (%)"}});
}

function drawScatter(rows) {
  if (!rows.length) return emptyChart("Nema podataka");
  const traces = Object.entries(groupBy(rows, "currency")).map(([cur, rs]) => {
    // scale bubbles per currency: turnovers in different currencies are not comparable
    const maxT = Math.max(...rs.map((r) => r.turnover)) || 1;
    return {
      type: "scattergl", mode: "markers", name: cur, x: rs.map((r) => r.remaining_maturity_days / 365),
      y: rs.map((r) => r.avg_yield_pct), text: rs.map((r) => `${r.isin} · ${r.trade_date}`),
      marker: {color: colorFor(cur), opacity: 0.6, size: rs.map((r) => Math.max(5, Math.sqrt(r.turnover / maxT) * 26))},
      hovertemplate: "%{text}<br>ročnost %{x:.2f} god · prinos %{y:.2f}%<extra>" + cur + "</extra>",
    };
  });
  plot(traces, {xaxis: {title: "Preostala ročnost (godine)"}, yaxis: {title: "Prosečni prinos (%)"}});
}

function drawBuckets(rows) {
  if (!rows.length) return emptyChart("Nema podataka");
  const curs = [...new Set(rows.map((r) => r.currency))];
  const traces = curs.map((cur, i) => {
    const rs = rows.filter((r) => r.currency === cur);
    return {type: "bar", name: cur, x: rs.map((r) => r.bucket), y: rs.map((r) => r.turnover),
            marker: {color: colorFor(cur)}, xaxis: "x" + (i + 1), yaxis: "y" + (i + 1)};
  });
  const layout = {grid: {rows: 1, columns: curs.length, pattern: "independent"}, annotations: []};
  curs.forEach((cur, i) => {
    layout["yaxis" + (i + 1)] = {title: `Promet (${cur})`};
    layout["xaxis" + (i + 1)] = {categoryorder: "array", categoryarray: ["0-1Y", "1-3Y", "3-5Y", "5-10Y", "10Y+"]};
  });
  plot(traces, layout);
}

// chartRows: all days in chronological order; tableRows: top rows in the user's chosen sort
function drawExtremes(chartRows, tableRows) {
  const tbl = $("extremes-table");
  if (!chartRows.length) { emptyChart("Nema podataka"); tbl.innerHTML = ""; return; }
  const chronological = [...chartRows].sort((a, b) => a.trade_date.localeCompare(b.trade_date));
  const traces = [];
  for (const [cur, rs] of Object.entries(groupBy(chronological, "currency"))) {
    traces.push({type: "scatter", mode: "lines", name: `${cur} najmanji`, x: rs.map((r) => r.trade_date),
                 y: rs.map((r) => r.lowest_pct), line: {color: colorFor(cur), width: 1}});
    traces.push({type: "scatter", mode: "lines", name: `${cur} najveći`, x: rs.map((r) => r.trade_date),
                 y: rs.map((r) => r.highest_pct), line: {color: colorFor(cur), width: 1},
                 fill: "tonexty", fillcolor: colorFor(cur) + "33"});
  }
  plot(traces, {yaxis: {title: "Prinos (%)"}});
  tbl.innerHTML = "<table><thead><tr><th class='l'>Datum</th><th class='l'>Val.</th><th>Najveći %</th><th class='l'>ISIN</th><th>Najmanji %</th><th class='l'>ISIN</th><th>Raspon</th></tr></thead><tbody>" +
    tableRows.map((r) => `<tr><td class="l">${esc(r.trade_date)}</td><td class="l">${esc(r.currency)}</td><td>${fmt(r.highest_pct, 2)}</td><td class="l">${esc(r.highest_isin)}</td><td>${fmt(r.lowest_pct, 2)}</td><td class="l">${esc(r.lowest_isin)}</td><td>${fmt(r.range_pct, 2)}</td></tr>`).join("") +
    "</tbody></table>";
}

/* ---------- data loading ---------- */
async function loadTab() {
  const filter = readFilter();
  $("gran-wrap").hidden = state.tab !== "time";
  $("exsort-wrap").hidden = state.tab !== "extremes";
  $("extremes-table").hidden = state.tab !== "extremes";
  if (state.tab === "time") drawTime(await api("/api/query/timeseries", {body: {filter, granularity: $("gran").value}}));
  else if (state.tab === "scatter") drawScatter(await api("/api/query/scatter", {body: {filter}}));
  else if (state.tab === "buckets") drawBuckets(await api("/api/query/buckets", {body: {filter}}));
  else {
    const [chartRows, tableRows] = await Promise.all([
      api("/api/query/extremes", {body: {filter, sort_by: "trade_date", order: "asc", limit: 5000}}),
      api("/api/query/extremes", {body: {filter, sort_by: state.exSort, order: state.exOrder, limit: 500}}),
    ]);
    drawExtremes(chartRows, tableRows);
  }
}

async function loadRows() {
  const res = await api("/api/query/rows", {body: {filter: readFilter(), sort: state.sort, order: state.order, page: state.page, page_size: state.pageSize}});
  renderRows(res);
}

async function refreshAll(resetPage = true) {
  if (resetPage) state.page = 1;
  let error = "";
  try {
    const filter = readFilter();
    const [summary] = await Promise.all([api("/api/query/summary", {body: {filter}}), loadRows(), loadTab()]);
    renderKpis(summary);
  } catch (e) { error = e.message; }
  // a fresh query error wins; otherwise keep showing the sticky load error / empty-database hint
  showError(error || state.loadError || (state.emptyDb ? EMPTY_DB_HINT : ""));
}

const EMPTY_DB_HINT = "Baza je prazna. Klikni „Update base“ da preuzmeš podatke sa NBS-a.";
let timer = null;
const debounced = () => { clearTimeout(timer); timer = setTimeout(() => refreshAll(true), 300); };

async function loadMeta() {
  const m = await api("/api/meta");
  const upd = m.last_update_utc ? new Date(m.last_update_utc).toLocaleString("sr-RS") : "nikad";
  $("meta").textContent = `Podaci: ${m.first_trade_date || "–"} → ${m.last_trade_date || "–"} · ${fmt(m.rows)} redova · poslednje ažuriranje: ${upd} · v${m.version}`;
  $("foot-range").textContent = `verzija ${m.version}`;
  state.emptyDb = !m.rows;
}

async function loadIsins() {
  const sel = await api("/api/securities");
  $("isin").innerHTML = sel.map((s) => `<option value="${esc(s.isin)}">${esc(s.isin)} · ${esc(s.currency)} · ${fmt(s.coupon_pct, 2)}% · ${esc(s.maturity_date)}</option>`).join("");
}

async function loadSaved() {
  const items = await api("/api/saved-queries");
  window.__saved = Object.fromEntries(items.map((i) => [i.name, i.filter]));
  $("saved").innerHTML = items.map((i) => `<option>${esc(i.name)}</option>`).join("");
}

/* ---------- update base ---------- */
async function runUpdate() {
  $("btn-update").disabled = true;
  $("update-panel").hidden = false;
  $("update-log").textContent = "Pokrećem ažuriranje…";
  try {
    await api("/api/update", {body: {}});
    for (;;) {
      await new Promise((r) => setTimeout(r, 800));
      const st = await api("/api/update/status");
      $("update-log").textContent = st.messages.join("\n");
      if (st.state === "running") continue;
      if (st.state === "error") $("update-log").textContent += `\nGREŠKA: ${st.error}`;
      else if (st.report && !st.report.ok) $("update-log").textContent += "\nNeke godine nisu ažurirane; postojeći podaci su sačuvani.";
      else $("update-log").textContent += "\nGotovo.";
      break;
    }
  } catch (e) { $("update-log").textContent = `GREŠKA: ${e.message}`; }
  $("btn-update").disabled = false;
  try { state.loadError = ""; await Promise.all([loadMeta(), loadIsins()]); } catch (e) { state.loadError = e.message; }
  await refreshAll();
}

/* ---------- export ---------- */
async function doExport(format) {
  try {
    const r = await api("/api/export", {body: {filter: readFilter(), format}});
    showError("");
    $("table-title").textContent = `Sačuvano (${fmt(r.rows)} redova): ${r.path}`;
  } catch (e) { showError(e.message); }
}

/* ---------- wiring ---------- */
document.querySelectorAll("#filters input, #filters select").forEach((el) => {
  if (el.id !== "saved") el.addEventListener("input", debounced);
});
$("btn-reset").onclick = () => { resetForm(); refreshAll(); };
$("btn-update").onclick = runUpdate;
$("btn-csv").onclick = () => doExport("csv");
$("btn-xlsx").onclick = () => doExport("xlsx");
$("prev").onclick = () => { state.page--; loadRows().catch((e) => showError(e.message)); };
$("next").onclick = () => { state.page++; loadRows().catch((e) => showError(e.message)); };
$("rows").addEventListener("click", (ev) => {
  const th = ev.target.closest("th[data-sort]");
  if (!th) return;
  state.order = state.sort === th.dataset.sort && state.order === "desc" ? "asc" : "desc";
  state.sort = th.dataset.sort;
  state.page = 1;
  loadRows().catch((e) => showError(e.message));
});
$("tabs").addEventListener("click", (ev) => {
  const b = ev.target.closest("button[data-tab]");
  if (!b) return;
  document.querySelectorAll("#tabs button").forEach((x) => x.classList.toggle("active", x === b));
  state.tab = b.dataset.tab;
  loadTab().catch((e) => showError(e.message));
});
$("gran").onchange = () => loadTab().catch((e) => showError(e.message));
$("exsort").onchange = () => {
  [state.exSort, state.exOrder] = $("exsort").value.split("|");
  loadTab().catch((e) => showError(e.message));
};
$("btn-save").onclick = async () => {
  const name = window.prompt("Naziv upita:");
  if (!name) return;
  try { await api("/api/saved-queries", {method: "PUT", body: {name, filter: readFilter()}}); await loadSaved(); $("saved").value = name; }
  catch (e) { showError(e.message); }
};
$("btn-load").onclick = () => { const f = (window.__saved || {})[$("saved").value]; if (f) { writeFilter(f); refreshAll(); } };
$("btn-delete").onclick = async () => {
  const name = $("saved").value;
  if (!name || !window.confirm(`Obrisati upit „${name}“?`)) return;
  try { await api("/api/saved-queries/" + encodeURIComponent(name), {method: "DELETE"}); await loadSaved(); }
  catch (e) { showError(e.message); }
};

(async function init() {
  try { await Promise.all([loadMeta(), loadIsins(), loadSaved()]); } catch (e) { state.loadError = e.message; }
  await refreshAll();
})();
