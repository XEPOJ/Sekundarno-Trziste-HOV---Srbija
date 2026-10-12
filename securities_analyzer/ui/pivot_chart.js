"use strict";
/* Pure chart/table logic for the Analiza view. No DOM, no network: unit-tested with `node --test`. */
(function (root, factory) {
  if (typeof module === "object" && module.exports) module.exports = factory();
  else root.PivotChart = factory();
})(typeof self !== "undefined" ? self : this, function () {
  const PALETTE = ["#1f6feb", "#d9480f", "#2f9e44", "#9c36b5", "#e8590c", "#0c8599", "#c2255c", "#5f3dc4", "#868e96", "#f08c00"];

  const uniq = (values) => [...new Set(values)];
  const suffix = (k) => (k === 1 ? "" : String(k));
  const axisRef = (prefix, k) => prefix + suffix(k);       // trace.xaxis: "x", "x2", ...
  const axisKey = (prefix, k) => prefix + "axis" + suffix(k); // layout key: "xaxis", "xaxis2", ...

  function chartHint(type, nDims, nMeasures) {
    if (type === "table") return {ok: true, note: null};
    if (nMeasures < 1) return {ok: false, note: "Izaberi bar jednu meru."};
    if (type === "bar" || type === "line") {
      if (nDims < 1) return {ok: false, note: "Stubići i linija traže bar jedno grupisanje."};
      return {ok: true, note: nDims === 2 && nMeasures > 1 ? "Uz dva grupisanja crta se samo prva mera." : null};
    }
    if (type === "scatter") {
      if (nDims < 1) return {ok: false, note: "Tačkasti grafik traži bar jedno grupisanje (jedna tačka je jedna grupa)."};
      if (nMeasures < 2) return {ok: false, note: "Tačkasti grafik traži bar dve mere (x i y)."};
      return {ok: true, note: null};
    }
    if (type === "heatmap") {
      if (nDims !== 2) return {ok: false, note: "Toplotna mapa traži tačno dva grupisanja."};
      return {ok: true, note: nMeasures > 1 ? "Crta se samo prva mera." : null};
    }
    return {ok: false, note: "Nepoznata vrsta grafika."};
  }

  function defaultSort(firstDimKind, firstMeasureId) {
    if (firstDimKind === "category") return {sort_by: firstMeasureId, order: "desc"};
    return {sort_by: "group", order: "asc"};
  }

  function dimLabel(result, row, i, labelFor) {
    const id = result.dimensions[i].id;
    const v = row.dims[i];
    return String(labelFor ? labelFor(id, v) : v);
  }

  function panelTitle(text, r, c, nRows, nCols) {
    return {text, showarrow: false, xref: "paper", yref: "paper", x: (c + 0.5) / nCols,
            y: 1 - r / nRows, xanchor: "center", yanchor: "bottom", font: {size: 12}};
  }

  const gridOf = (rows, columns) => ({rows, columns, pattern: "independent", xgap: 0.12, ygap: 0.35});

  function barLine(result, config, h, currencies) {
    const twoDims = result.dimensions.length === 2;
    const measureIdx = twoDims ? [0] : result.measures.map((_, i) => i);
    const nRows = measureIdx.length;
    const nCols = currencies.length;
    const isLine = config.type === "line";
    const horizontal = !!config.horizontal && !isLine;
    const data = [];
    const annotations = [];
    const layout = {grid: gridOf(nRows, nCols), annotations, barmode: "group", showlegend: twoDims};
    const seen = new Set();
    measureIdx.forEach((mi, r) => {
      const measure = result.measures[mi];
      currencies.forEach((cur, c) => {
        const k = r * nCols + c + 1;
        const rows = result.rows.filter((x) => x.currency === cur);
        const cats = uniq(rows.map((x) => dimLabel(result, x, 0, h.labelFor)));
        const names = twoDims ? uniq(rows.map((x) => dimLabel(result, x, 1, h.labelFor))) : [measure.label];
        const lookup = new Map();
        rows.forEach((x) => {
          const key = dimLabel(result, x, 0, h.labelFor) + "\u0000" + (twoDims ? dimLabel(result, x, 1, h.labelFor) : "");
          lookup.set(key, x.values[mi]);
        });
        names.forEach((name, si) => {
          const vals = cats.map((cat) => {
            const v = lookup.get(cat + "\u0000" + (twoDims ? name : ""));
            return v === undefined ? null : v;
          });
          const color = twoDims ? PALETTE[si % PALETTE.length] : h.colorFor(cur);
          const trace = {
            type: isLine ? "scatter" : "bar", name, legendgroup: name,
            showlegend: twoDims && !seen.has(name), xaxis: axisRef("x", k), yaxis: axisRef("y", k),
          };
          if (isLine) { trace.mode = "lines+markers"; trace.line = {color}; } else { trace.marker = {color}; }
          if (horizontal) { trace.x = vals; trace.y = cats; trace.orientation = "h"; } else { trace.x = cats; trace.y = vals; }
          seen.add(name);
          data.push(trace);
        });
        layout[axisKey("x", k)] = horizontal ? {title: {text: measure.label}} : {type: "category"};
        layout[axisKey("y", k)] = horizontal
          ? {type: "category", autorange: "reversed", automargin: true}
          : {title: {text: measure.label}};
        annotations.push(panelTitle(nRows > 1 ? `${cur} · ${measure.label}` : cur, r, c, nRows, nCols));
      });
    });
    return {data, layout};
  }

  function scatter(result, h, currencies) {
    const nCols = currencies.length;
    const data = [];
    const annotations = [];
    const layout = {grid: gridOf(1, nCols), annotations, showlegend: false};
    currencies.forEach((cur, c) => {
      const k = c + 1;
      const rows = result.rows.filter((x) => x.currency === cur);
      const hasSize = result.measures.length >= 3;
      const maxSize = hasSize ? Math.max(...rows.map((x) => Math.abs(x.values[2] || 0)), 0) || 1 : 1;
      data.push({
        type: "scatter", mode: "markers", name: cur,
        x: rows.map((x) => x.values[0]), y: rows.map((x) => x.values[1]),
        text: rows.map((x) => result.dimensions.map((_, i) => dimLabel(result, x, i, h.labelFor)).join(" · ")),
        marker: {
          color: h.colorFor(cur), opacity: 0.7,
          size: rows.map((x) => (hasSize ? Math.max(6, Math.sqrt(Math.abs(x.values[2] || 0) / maxSize) * 28) : 10)),
        },
        xaxis: axisRef("x", k), yaxis: axisRef("y", k),
        hovertemplate: "%{text}<br>%{x}<br>%{y}<extra>" + cur + "</extra>",
      });
      layout[axisKey("x", k)] = {title: {text: result.measures[0].label}};
      layout[axisKey("y", k)] = {title: {text: result.measures[1].label}};
      annotations.push(panelTitle(cur, 0, c, 1, nCols));
    });
    return {data, layout};
  }

  function heatmap(result, h, currencies) {
    const nCols = currencies.length;
    const data = [];
    const annotations = [];
    const layout = {grid: gridOf(1, nCols), annotations, showlegend: false};
    currencies.forEach((cur, c) => {
      const k = c + 1;
      const rows = result.rows.filter((x) => x.currency === cur);
      const xs = uniq(rows.map((x) => dimLabel(result, x, 0, h.labelFor)));
      const ys = uniq(rows.map((x) => dimLabel(result, x, 1, h.labelFor)));
      const lookup = new Map();
      rows.forEach((x) => lookup.set(dimLabel(result, x, 0, h.labelFor) + "\u0000" + dimLabel(result, x, 1, h.labelFor), x.values[0]));
      data.push({
        type: "heatmap", name: cur, x: xs, y: ys, colorscale: "Blues", hoverongaps: false,
        z: ys.map((y) => xs.map((x) => { const v = lookup.get(x + "\u0000" + y); return v === undefined ? null : v; })),
        showscale: nCols === 1, xaxis: axisRef("x", k), yaxis: axisRef("y", k),
      });
      layout[axisKey("x", k)] = {type: "category"};
      layout[axisKey("y", k)] = {type: "category", autorange: "reversed"};
      annotations.push(panelTitle(cur, 0, c, 1, nCols));
    });
    return {data, layout};
  }

  function buildFigure(result, config, helpers) {
    const h = Object.assign({labelFor: null, colorFor: () => PALETTE[0]}, helpers || {});
    const hint = chartHint(config.type, result.dimensions.length, result.measures.length);
    if (config.type === "table" || !hint.ok || !result.rows.length) return null;
    const currencies = uniq(result.rows.map((r) => r.currency));
    if (config.type === "scatter") return scatter(result, h, currencies);
    if (config.type === "heatmap") return heatmap(result, h, currencies);
    return barLine(result, config, h, currencies);
  }

  function tableModel(result, labelFor) {
    const header = ["Valuta", ...result.dimensions.map((d) => d.label), ...result.measures.map((m) => m.label)];
    const rows = result.rows.map((r) => [
      r.currency,
      ...r.dims.map((v, i) => (labelFor ? labelFor(result.dimensions[i].id, v) : v)),
      ...r.values,
    ]);
    return {header, rows, units: result.measures.map((m) => m.unit)};
  }

  return {chartHint, defaultSort, buildFigure, tableModel};
});
