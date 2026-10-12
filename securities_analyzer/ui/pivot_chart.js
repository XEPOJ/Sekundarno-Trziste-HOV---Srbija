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

  // Group identity is the RAW dimension value (type included: 5 != "5", null != "null");
  // labels are for display only.
  const rawKey = (v) => (v === undefined ? "undefined" : JSON.stringify(v));
  const rawText = (v) => (v === undefined ? "undefined" : JSON.stringify(v));

  // One display-label table per dimension, decided across ALL rows so that labels agree between
  // currency panels. When two distinct raw values would share a label (Plotly category axes merge
  // identical strings), the label becomes "label [raw]".
  function groupLabels(result, labelFor) {
    return result.dimensions.map((dim, i) => {
      const raws = new Map();
      result.rows.forEach((r) => {
        const k = rawKey(r.dims[i]);
        if (!raws.has(k)) raws.set(k, r.dims[i]);
      });
      const base = new Map();
      const uses = new Map();
      raws.forEach((v, k) => {
        const label = String(labelFor ? labelFor(dim.id, v) : v);
        base.set(k, label);
        uses.set(label, (uses.get(label) || 0) + 1);
      });
      const labels = new Map();
      base.forEach((label, k) => labels.set(k, uses.get(label) > 1 ? `${label} [${rawText(raws.get(k))}]` : label));
      return {order: [...raws.keys()], labels};
    });
  }

  function panelTitle(text, r, c, nRows, nCols) {
    return {text, showarrow: false, xref: "paper", yref: "paper", x: (c + 0.5) / nCols,
            y: 1 - r / nRows, xanchor: "center", yanchor: "bottom", font: {size: 12}};
  }

  const gridOf = (rows, columns, xgap = 0.12) => ({rows, columns, pattern: "independent", xgap, ygap: 0.35});

  // Horizontal bars put long category labels to the left of every panel; Plotly's automargin does not
  // reserve room for them between subplots, so the grid gap must. xgap is a fraction of one cell's
  // width: solve gap_px = xgap * cell_w for a ~1000 px wide plot and ~6.5 px per label character.
  function horizontalGap(nCols, labels) {
    if (nCols < 2) return 0.12;
    const chars = Math.min(Math.max(0, ...labels.map((l) => String(l).length)), 40);
    const gapPx = chars * 6.5;
    const room = 1000 - (nCols - 1) * gapPx;
    const gap = room > 0 ? (gapPx * nCols) / room : 0.8;
    return Math.round(Math.min(Math.max(gap, 0.33), 0.8) * 100) / 100;
  }

  function barLine(result, config, h, currencies) {
    const groups = groupLabels(result, h.labelFor);
    const twoDims = result.dimensions.length === 2;
    const measureIdx = twoDims ? [0] : result.measures.map((_, i) => i);
    const nRows = measureIdx.length;
    const nCols = currencies.length;
    const isLine = config.type === "line";
    const horizontal = !!config.horizontal && !isLine;
    const data = [];
    const annotations = [];
    const xgap = horizontal ? horizontalGap(nCols, [...groups[0].labels.values()]) : 0.12;
    const layout = {grid: gridOf(nRows, nCols, xgap), annotations, barmode: "group", showlegend: twoDims};
    const seen = new Set();
    measureIdx.forEach((mi, r) => {
      const measure = result.measures[mi];
      currencies.forEach((cur, c) => {
        const k = r * nCols + c + 1;
        const rows = result.rows.filter((x) => x.currency === cur);
        const cats = uniq(rows.map((x) => rawKey(x.dims[0])));
        const series = twoDims ? uniq(rows.map((x) => rawKey(x.dims[1]))) : [null];
        const lookup = new Map();
        rows.forEach((x) => lookup.set(rawKey(x.dims[0]) + "\u0000" + (twoDims ? rawKey(x.dims[1]) : ""), x.values[mi]));
        series.forEach((sKey) => {
          const vals = cats.map((cat) => {
            const v = lookup.get(cat + "\u0000" + (twoDims ? sKey : ""));
            return v === undefined ? null : v;
          });
          const name = twoDims ? groups[1].labels.get(sKey) : measure.label;
          // Colour comes from the series' position in the GLOBAL order, so a series has the same
          // colour in every currency panel (the legend is shared across panels).
          const color = twoDims ? PALETTE[groups[1].order.indexOf(sKey) % PALETTE.length] : h.colorFor(cur);
          const trace = {
            type: isLine ? "scatter" : "bar", name, legendgroup: name,
            showlegend: twoDims && !seen.has(name), xaxis: axisRef("x", k), yaxis: axisRef("y", k),
          };
          if (isLine) { trace.mode = "lines+markers"; trace.line = {color}; } else { trace.marker = {color}; }
          const catLabels = cats.map((k) => groups[0].labels.get(k));
          if (horizontal) { trace.x = vals; trace.y = catLabels; trace.orientation = "h"; } else { trace.x = catLabels; trace.y = vals; }
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
    const groups = groupLabels(result, h.labelFor);
    const nCols = currencies.length;
    const data = [];
    const annotations = [];
    const layout = {grid: gridOf(1, nCols), annotations, showlegend: false};
    currencies.forEach((cur, c) => {
      const k = c + 1;
      const rows = result.rows.filter((x) => x.currency === cur);
      const hasSize = result.measures.length >= 3;
      // Size encodes magnitude, so negative values of the size measure are plotted by absolute value.
      const maxSize = hasSize ? Math.max(...rows.map((x) => Math.abs(x.values[2] || 0)), 0) || 1 : 1;
      data.push({
        type: "scatter", mode: "markers", name: cur,
        x: rows.map((x) => x.values[0]), y: rows.map((x) => x.values[1]),
        text: rows.map((x) => result.dimensions.map((_, i) => groups[i].labels.get(rawKey(x.dims[i]))).join(" · ")),
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
    const groups = groupLabels(result, h.labelFor);
    const nCols = currencies.length;
    const data = [];
    const annotations = [];
    const layout = {grid: gridOf(1, nCols), annotations, showlegend: false};
    currencies.forEach((cur, c) => {
      const k = c + 1;
      const rows = result.rows.filter((x) => x.currency === cur);
      const xs = uniq(rows.map((x) => rawKey(x.dims[0])));
      const ys = uniq(rows.map((x) => rawKey(x.dims[1])));
      const lookup = new Map();
      rows.forEach((x) => lookup.set(rawKey(x.dims[0]) + "\u0000" + rawKey(x.dims[1]), x.values[0]));
      data.push({
        type: "heatmap", name: cur,
        x: xs.map((k) => groups[0].labels.get(k)), y: ys.map((k) => groups[1].labels.get(k)),
        colorscale: "Blues", hoverongaps: false,
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
    if (!result || !config || !config.type) return null;
    const given = helpers || {};
    const h = {
      labelFor: typeof given.labelFor === "function" ? given.labelFor : null,
      colorFor: typeof given.colorFor === "function" ? given.colorFor : () => PALETTE[0],
    };
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
