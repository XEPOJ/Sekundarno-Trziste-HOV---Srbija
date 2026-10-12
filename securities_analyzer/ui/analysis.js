"use strict";
/* Analiza view: builder controls, chart, result table, export. Business rules live on the server;
   chart/axis logic lives in pivot_chart.js. Depends on window.App (app.js) and window.PivotChart. */
const Analysis = (function () {
  const $ = (id) => document.getElementById(id);
  const state = {
    catalog: null, dim1: "isin", dim2: "", measures: ["turnover"], sortBy: "turnover", order: "desc",
    limit: 25, chart: {type: "bar", horizontal: true},
    sortTouched: false, limitTouched: false, horizontalTouched: false,
    seq: 0, last: null, timer: null, active: false,
  };

  const dimIds = () => [state.dim1, state.dim2].filter(Boolean);
  const kindOf = (id) => ((state.catalog.dimensions.find((d) => d.id === id) || {}).kind);
  const measureLabel = (id) => (state.catalog.measures.find((m) => m.id === id) || {}).label || id;

  function labelFor(id, v) {
    if (id === "isin") {
      const s = App.securities()[v];
      return s ? `${v} · ${App.fmt(s.coupon_pct, 2)}% · ${String(s.maturity_date).slice(0, 4)}` : String(v);
    }
    if (id === "coupon") return `${App.fmt(v, 2)}%`;
    if (id === "remaining_years" || id === "original_years") return `${v} god.`;
    if (id === "settlement_lag") return `${v} d.`;
    return v;
  }

  // Untouched controls follow the first dimension / first measure; a sort column that is no longer
  // a selected measure falls back to the default again.
  function applyDefaults() {
    const dims = dimIds();
    const firstKind = dims.length ? kindOf(dims[0]) : undefined;
    const sortValid = state.sortBy === "group" || state.measures.includes(state.sortBy);
    if (!sortValid) state.sortTouched = false;
    if (!state.sortTouched) {
      const s = state.measures.length ? PivotChart.defaultSort(firstKind, state.measures[0]) : {sort_by: "group", order: "asc"};
      state.sortBy = s.sort_by;
      state.order = s.order;
    }
    if (!state.limitTouched) state.limit = firstKind === "category" ? 25 : 1000;
    if (!state.horizontalTouched) state.chart.horizontal = firstKind === "category";
  }

  function renderSortOptions() {
    const opts = [["group", "po grupi"], ...state.measures.map((m) => [m, `po meri: ${measureLabel(m)}`])];
    $("b-sort").innerHTML = opts.map(([v, t]) => `<option value="${App.esc(v)}">${App.esc(t)}</option>`).join("");
    $("b-sort").value = state.sortBy;
  }

  function syncControls() {
    $("b-dim1").value = state.dim1;
    $("b-dim2").value = state.dim2;
    document.querySelectorAll("input[name=b-measure]").forEach((i) => { i.checked = state.measures.includes(i.value); });
    updateMeasureLimits();
    $("b-chart").value = state.chart.type;
    $("b-horizontal").checked = !!state.chart.horizontal;
    renderSortOptions();
    $("b-order").value = state.order;
    $("b-limit").value = state.limit;
  }

  function updateMeasureLimits() {
    const max = state.catalog.limits.max_measures;
    document.querySelectorAll("input[name=b-measure]").forEach((i) => {
      i.disabled = !i.checked && state.measures.length >= max;
    });
  }

  function query() {
    return {filter: App.readFilter(), dimensions: dimIds(), measures: state.measures,
            sort_by: state.sortBy, order: state.order, limit: state.limit};
  }

  function schedule() {
    clearTimeout(state.timer);
    state.timer = setTimeout(refresh, 250);
  }

  function fmtValue(v, unit) {
    if (v === null || v === undefined) return "–";
    return App.fmt(v, unit === "pieces" || unit === "count" ? 0 : 2);
  }

  function drawTable(res) {
    const m = PivotChart.tableModel(res, labelFor);
    const nDims = res.dimensions.length;
    const head = "<thead><tr>" + m.header.map((h, i) => `<th class="${i <= nDims ? "l" : ""}">${App.esc(h)}</th>`).join("") + "</tr></thead>";
    const body = "<tbody>" + m.rows.map((row) => "<tr>" + row.map((v, i) =>
      i <= nDims ? `<td class="l">${App.esc(v)}</td>` : `<td>${App.esc(fmtValue(v, m.units[i - nDims - 1]))}</td>`).join("") + "</tr>").join("") + "</tbody>";
    $("a-rows").innerHTML = head + body;
    $("a-table-title").textContent = `Rezultat (${App.fmt(res.rows.length)} redova)`;
  }

  function drawChart(res, hint) {
    const fig = hint.ok ? PivotChart.buildFigure(res, state.chart, {labelFor, colorFor: App.colorFor}) : null;
    $("a-chart").hidden = !fig;
    if (fig) App.plot(fig.data, fig.layout, "a-chart");
    else if (window.Plotly) Plotly.purge("a-chart");
  }

  function drawNotice(res) {
    const parts = [];
    if (!res.rows.length) parts.push("Nema rezultata za izabrane filtere.");
    if (res.truncated_currencies.length) parts.push(`Prikazano prvih ${App.fmt(state.limit)} po valuti; ima još redova za: ${res.truncated_currencies.join(", ")}.`);
    $("a-notice").textContent = parts.join(" ");
  }

  async function refresh() {
    if (!state.active || !state.catalog) return;
    const token = ++state.seq;
    const hint = PivotChart.chartHint(state.chart.type, dimIds().length, state.measures.length);
    $("b-hint").textContent = hint.note || "";
    $("b-hint").classList.toggle("warn", !hint.ok);
    if (!state.measures.length) { $("a-chart").hidden = true; $("a-rows").innerHTML = ""; return; }
    try {
      const res = await App.api("/api/query/pivot", {body: query()});
      if (token !== state.seq) return;
      state.last = res;
      App.showError("");
      drawChart(res, hint);
      drawTable(res);
      drawNotice(res);
    } catch (e) {
      if (token === state.seq) App.showError(e.message);
    }
  }

  async function doExport(format) {
    if (!state.measures.length) return;
    try {
      const r = await App.api("/api/export/pivot", {body: {...query(), format}});
      App.showError("");
      $("a-notice").textContent = `Sačuvano (${App.fmt(r.rows)} redova): ${r.path}`;
    } catch (e) { App.showError(e.message); }
  }

  function getConfig() {
    return {dimensions: dimIds(), measures: [...state.measures], sort_by: state.sortBy, order: state.order,
            limit: state.limit, chart: {type: state.chart.type, horizontal: !!state.chart.horizontal}};
  }

  function setConfig(cfg) {
    if (!state.catalog || !cfg) return;
    const knownDims = new Set(state.catalog.dimensions.map((d) => d.id));
    const knownMeasures = new Set(state.catalog.measures.map((m) => m.id));
    const dims = (cfg.dimensions || []).filter((d) => knownDims.has(d));
    state.dim1 = dims[0] || "";
    state.dim2 = dims[1] || "";
    const ms = (cfg.measures || []).filter((m) => knownMeasures.has(m));
    state.measures = ms.length ? ms : ["turnover"];
    state.sortBy = cfg.sort_by === "group" || state.measures.includes(cfg.sort_by) ? cfg.sort_by : "group";
    state.order = cfg.order === "asc" ? "asc" : "desc";
    state.limit = Math.min(Math.max(parseInt(cfg.limit, 10) || 100, 1), state.catalog.limits.max_limit);
    state.chart = {type: (cfg.chart && cfg.chart.type) || "bar", horizontal: !!(cfg.chart && cfg.chart.horizontal)};
    state.sortTouched = state.limitTouched = state.horizontalTouched = true;
    syncControls();
    schedule();
  }

  function fillSelects() {
    const opts = state.catalog.dimensions.map((d) => `<option value="${App.esc(d.id)}">${App.esc(d.label)}</option>`).join("");
    $("b-dim1").innerHTML = `<option value="">(bez grupisanja)</option>` + opts;
    $("b-dim2").innerHTML = `<option value="">(bez)</option>` + opts;
    $("b-measures").innerHTML = `<legend>Mere (najviše ${state.catalog.limits.max_measures})</legend>` + state.catalog.measures.map((m) =>
      `<label><input type="checkbox" name="b-measure" value="${App.esc(m.id)}"> ${App.esc(m.label)}</label>`).join("");
    $("b-limit").max = state.catalog.limits.max_limit;
  }

  function wire() {
    $("b-dim1").onchange = () => { state.dim1 = $("b-dim1").value; if (state.dim2 === state.dim1) state.dim2 = ""; applyDefaults(); syncControls(); schedule(); };
    $("b-dim2").onchange = () => { state.dim2 = $("b-dim2").value; if (state.dim2 && state.dim2 === state.dim1) state.dim2 = ""; applyDefaults(); syncControls(); schedule(); };
    $("b-measures").addEventListener("change", () => {
      state.measures = [...document.querySelectorAll("input[name=b-measure]:checked")].map((i) => i.value);
      applyDefaults();
      syncControls();
      schedule();
    });
    $("b-chart").onchange = () => { state.chart.type = $("b-chart").value; schedule(); };
    $("b-horizontal").onchange = () => { state.chart.horizontal = $("b-horizontal").checked; state.horizontalTouched = true; schedule(); };
    $("b-sort").onchange = () => { state.sortBy = $("b-sort").value; state.sortTouched = true; schedule(); };
    $("b-order").onchange = () => { state.order = $("b-order").value; state.sortTouched = true; schedule(); };
    $("b-limit").oninput = () => {
      const n = parseInt($("b-limit").value, 10);
      if (n >= 1 && n <= state.catalog.limits.max_limit) { state.limit = n; state.limitTouched = true; schedule(); }
    };
    $("a-csv").onclick = () => doExport("csv");
    $("a-xlsx").onclick = () => doExport("xlsx");
  }

  async function init() {
    state.catalog = await App.api("/api/pivot/catalog");
    fillSelects();
    wire();
    applyDefaults();
    syncControls();
  }

  function setActive(flag) {
    state.active = !!flag;
    if (state.active) refresh();
  }

  return {init, setActive, getConfig, setConfig, onFilterChange: schedule};
})();
