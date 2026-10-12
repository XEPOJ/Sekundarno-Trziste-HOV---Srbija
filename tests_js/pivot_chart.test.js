"use strict";
const test = require("node:test");
const assert = require("node:assert/strict");
const PC = require("../securities_analyzer/ui/pivot_chart.js");

const colorFor = (c) => ({RSD: "#1f6feb", EUR: "#d9480f"}[c] || "#888");

const oneDim = {
  dimensions: [{id: "isin", label: "Hartija (ISIN)"}],
  measures: [
    {id: "turnover", label: "Promet", unit: "currency"},
    {id: "weighted_yield", label: "Ponderisani prinos", unit: "percent_points"},
  ],
  rows: [
    {currency: "EUR", dims: ["E1"], values: [50, 3.0]},
    {currency: "EUR", dims: ["E2"], values: [70, 2.0]},
    {currency: "RSD", dims: ["A"], values: [400, 5.5]},
    {currency: "RSD", dims: ["B"], values: [500, 5.0]},
  ],
  truncated_currencies: [],
};
const oneMeasure = {...oneDim, measures: [oneDim.measures[0]], rows: oneDim.rows.map((r) => ({...r, values: [r.values[0]]}))};

const twoDims = {
  dimensions: [{id: "date_year", label: "Godina"}, {id: "remaining_bucket", label: "Preostali rok (grupa)"}],
  measures: [{id: "weighted_yield", label: "Ponderisani prinos", unit: "percent_points"}],
  rows: [
    {currency: "RSD", dims: ["2020", "0-1Y"], values: [1.5]},
    {currency: "RSD", dims: ["2020", "1-3Y"], values: [2.0]},
    {currency: "RSD", dims: ["2021", "0-1Y"], values: [1.0]},
  ],
  truncated_currencies: [],
};

test("chartHint rules", () => {
  assert.deepEqual(PC.chartHint("table", 0, 1), {ok: true, note: null});
  assert.equal(PC.chartHint("bar", 0, 1).ok, false);
  assert.deepEqual(PC.chartHint("bar", 1, 2), {ok: true, note: null});
  assert.match(PC.chartHint("bar", 2, 2).note, /prva mera/);
  assert.equal(PC.chartHint("line", 0, 1).ok, false);
  assert.equal(PC.chartHint("scatter", 1, 1).ok, false);
  assert.equal(PC.chartHint("scatter", 0, 2).ok, false);
  assert.deepEqual(PC.chartHint("scatter", 1, 2), {ok: true, note: null});
  assert.equal(PC.chartHint("heatmap", 1, 1).ok, false);
  assert.equal(PC.chartHint("heatmap", 3, 1).ok, false);
  assert.deepEqual(PC.chartHint("heatmap", 2, 1), {ok: true, note: null});
  assert.equal(PC.chartHint("bar", 1, 0).ok, false);
  assert.equal(PC.chartHint("pie", 1, 1).ok, false);
});

test("defaultSort: category by measure, ordered kinds by group", () => {
  assert.deepEqual(PC.defaultSort("category", "turnover"), {sort_by: "turnover", order: "desc"});
  assert.deepEqual(PC.defaultSort("time", "turnover"), {sort_by: "group", order: "asc"});
  assert.deepEqual(PC.defaultSort("ordinal", "turnover"), {sort_by: "group", order: "asc"});
  assert.deepEqual(PC.defaultSort(undefined, "turnover"), {sort_by: "group", order: "asc"});
});

test("buildFigure returns null for table, invalid combos and empty results", () => {
  assert.equal(PC.buildFigure(oneDim, {type: "table"}, {colorFor}), null);
  assert.equal(PC.buildFigure(oneDim, {type: "heatmap"}, {colorFor}), null);
  assert.equal(PC.buildFigure({...oneDim, rows: []}, {type: "bar"}, {colorFor}), null);
});

test("vertical bars: one panel per currency, currency colour, titles", () => {
  const fig = PC.buildFigure(oneMeasure, {type: "bar", horizontal: false}, {colorFor});
  assert.equal(fig.data.length, 2);
  const [eur, rsd] = fig.data;
  assert.equal(eur.type, "bar");
  assert.deepEqual(eur.x, ["E1", "E2"]);
  assert.deepEqual(eur.y, [50, 70]);
  assert.equal(eur.marker.color, "#d9480f");
  assert.equal(eur.xaxis, "x");
  assert.equal(eur.yaxis, "y");
  assert.deepEqual(rsd.x, ["A", "B"]);
  assert.equal(rsd.xaxis, "x2");
  assert.equal(rsd.yaxis, "y2");
  assert.equal(fig.layout.grid.rows, 1);
  assert.equal(fig.layout.grid.columns, 2);
  assert.deepEqual(fig.layout.annotations.map((a) => a.text), ["EUR", "RSD"]);
  assert.equal(fig.layout.yaxis.title.text, "Promet");
});

test("horizontal bars swap axes and put the first category on top", () => {
  const fig = PC.buildFigure(oneMeasure, {type: "bar", horizontal: true}, {colorFor});
  const eur = fig.data[0];
  assert.equal(eur.orientation, "h");
  assert.deepEqual(eur.y, ["E1", "E2"]);
  assert.deepEqual(eur.x, [50, 70]);
  assert.equal(fig.layout.yaxis.autorange, "reversed");
  assert.equal(fig.layout.xaxis.title.text, "Promet");
});

test("horizontal multi-currency bars get a wide panel gap, everything else keeps 0.12", () => {
  const longLabel = (id, v) => `${v} · 5,00% · 2030 · long label`;
  const horiz = PC.buildFigure(oneMeasure, {type: "bar", horizontal: true}, {colorFor, labelFor: longLabel});
  assert.ok(horiz.layout.grid.xgap >= 0.33 && horiz.layout.grid.xgap <= 0.8, String(horiz.layout.grid.xgap));
  // longer labels never shrink the gap
  const short = PC.buildFigure(oneMeasure, {type: "bar", horizontal: true}, {colorFor});
  assert.ok(horiz.layout.grid.xgap >= short.layout.grid.xgap);
  assert.ok(short.layout.grid.xgap >= 0.33);
  const vert = PC.buildFigure(oneMeasure, {type: "bar", horizontal: false}, {colorFor, labelFor: longLabel});
  assert.equal(vert.layout.grid.xgap, 0.12);
  const line = PC.buildFigure(oneMeasure, {type: "line", horizontal: true}, {colorFor, labelFor: longLabel});
  assert.equal(line.layout.grid.xgap, 0.12);
  const oneCur = {...oneMeasure, rows: oneMeasure.rows.filter((r) => r.currency === "RSD")};
  const single = PC.buildFigure(oneCur, {type: "bar", horizontal: true}, {colorFor, labelFor: longLabel});
  assert.equal(single.layout.grid.xgap, 0.12);
});

test("several measures with one dimension get one row of panels per measure", () => {
  const fig = PC.buildFigure(oneDim, {type: "bar", horizontal: false}, {colorFor});
  assert.equal(fig.layout.grid.rows, 2);
  assert.equal(fig.layout.grid.columns, 2);
  assert.equal(fig.data.length, 4);
  assert.deepEqual(fig.layout.annotations.map((a) => a.text),
    ["EUR · Promet", "RSD · Promet", "EUR · Ponderisani prinos", "RSD · Ponderisani prinos"]);
  assert.deepEqual(fig.data[2].y, [3.0, 2.0]);
  assert.equal(fig.data[2].xaxis, "x3");
  assert.equal(fig.data[3].yaxis, "y4");
});

test("two dimensions: series per second dimension, null for missing cells, one legend entry each", () => {
  const fig = PC.buildFigure(twoDims, {type: "bar", horizontal: false}, {colorFor});
  assert.equal(fig.data.length, 2);
  const byName = Object.fromEntries(fig.data.map((t) => [t.name, t]));
  assert.deepEqual(byName["0-1Y"].x, ["2020", "2021"]);
  assert.deepEqual(byName["0-1Y"].y, [1.5, 1.0]);
  assert.deepEqual(byName["1-3Y"].y, [2.0, null]);
  assert.equal(fig.data.filter((t) => t.showlegend).length, 2);
  assert.equal(fig.layout.showlegend, true);
});

test("line charts use scatter traces with lines+markers", () => {
  const fig = PC.buildFigure(oneMeasure, {type: "line"}, {colorFor});
  assert.equal(fig.data[0].type, "scatter");
  assert.equal(fig.data[0].mode, "lines+markers");
  assert.equal(fig.data[0].line.color, "#d9480f");
});

test("scatter: x and y are the first two measures, size from the third", () => {
  const three = {
    ...oneDim,
    measures: [...oneDim.measures, {id: "quantity", label: "Količina", unit: "pieces"}],
    rows: [
      {currency: "RSD", dims: ["A"], values: [400, 5.5, 4]},
      {currency: "RSD", dims: ["B"], values: [500, 5.0, 1]},
    ],
  };
  const fig = PC.buildFigure(three, {type: "scatter"}, {colorFor, labelFor: (id, v) => `${id}:${v}`});
  assert.equal(fig.data.length, 1);
  const t = fig.data[0];
  assert.deepEqual(t.x, [400, 500]);
  assert.deepEqual(t.y, [5.5, 5.0]);
  assert.deepEqual(t.text, ["isin:A", "isin:B"]);
  assert.equal(t.marker.size[0], 28);
  assert.equal(t.marker.size[1], 14);
  assert.equal(fig.layout.xaxis.title.text, "Promet");
  assert.equal(fig.layout.yaxis.title.text, "Ponderisani prinos");
  const noSize = PC.buildFigure(oneDim, {type: "scatter"}, {colorFor});
  assert.equal(noSize.data[0].marker.size[0], 10);
});

test("heatmap: matrix of the first measure with null gaps", () => {
  const fig = PC.buildFigure(twoDims, {type: "heatmap"}, {colorFor});
  assert.equal(fig.data.length, 1);
  const t = fig.data[0];
  assert.equal(t.type, "heatmap");
  assert.deepEqual(t.x, ["2020", "2021"]);
  assert.deepEqual(t.y, ["0-1Y", "1-3Y"]);
  assert.deepEqual(t.z, [[1.5, 1.0], [2.0, null]]);
});

test("labelFor is applied to category labels", () => {
  const fig = PC.buildFigure(oneMeasure, {type: "bar"}, {colorFor, labelFor: (id, v) => `<${v}>`});
  assert.deepEqual(fig.data[1].x, ["<A>", "<B>"]);
});

test("tableModel header, rows and units", () => {
  const m = PC.tableModel(oneDim, (id, v) => `#${v}`);
  assert.deepEqual(m.header, ["Valuta", "Hartija (ISIN)", "Promet", "Ponderisani prinos"]);
  assert.deepEqual(m.rows[0], ["EUR", "#E1", 50, 3.0]);
  assert.deepEqual(m.units, ["currency", "percent_points"]);
});

// ---------------------------------------------------------------------------
// Fix round 1: stable colours, raw-value group identity, stronger coverage
// ---------------------------------------------------------------------------

const yieldMeasure = [{id: "weighted_yield", label: "Ponderisani prinos", unit: "percent_points"}];
const dimsYB = [{id: "date_year", label: "Godina"}, {id: "remaining_bucket", label: "Preostali rok (grupa)"}];

test("two dimensions: a series keeps the same colour in every currency panel", () => {
  const res = {
    dimensions: dimsYB, measures: yieldMeasure, truncated_currencies: [],
    rows: [
      {currency: "RSD", dims: ["2020", "0-1Y"], values: [1.5]},
      {currency: "RSD", dims: ["2020", "1-3Y"], values: [2.0]},
      {currency: "EUR", dims: ["2020", "1-3Y"], values: [3.0]},
    ],
  };
  const fig = PC.buildFigure(res, {type: "bar"}, {colorFor});
  const longs = fig.data.filter((t) => t.name === "1-3Y");
  const short = fig.data.find((t) => t.name === "0-1Y");
  assert.equal(longs.length, 2);
  assert.equal(longs[0].marker.color, longs[1].marker.color);
  assert.notEqual(longs[0].marker.color, short.marker.color);
  assert.equal(longs[0].xaxis, "x");
  assert.equal(longs[1].xaxis, "x2");
});

test("same display label for two raw values keeps two categories (bar)", () => {
  const res = {
    dimensions: [{id: "isin", label: "Hartija"}], measures: [oneDim.measures[0]], truncated_currencies: [],
    rows: [
      {currency: "RSD", dims: ["a"], values: [10]},
      {currency: "RSD", dims: ["b"], values: [20]},
      {currency: "EUR", dims: ["a"], values: [5]},
    ],
  };
  const fig = PC.buildFigure(res, {type: "bar"}, {colorFor, labelFor: () => "Same"});
  const [rsd, eur] = fig.data;
  assert.deepEqual(rsd.x, ['Same ["a"]', 'Same ["b"]']);
  assert.deepEqual(rsd.y, [10, 20]);
  // decided across all rows, so the EUR panel uses the same disambiguated label
  assert.deepEqual(eur.x, ['Same ["a"]']);
  assert.deepEqual(eur.y, [5]);
});

test("labels stay plain when no two raw values share a label", () => {
  const fig = PC.buildFigure(oneMeasure, {type: "bar"}, {colorFor, labelFor: (id, v) => `<${v}>`});
  assert.deepEqual(fig.data[0].x, ["<E1>", "<E2>"]);
});

test("same display label in the second dimension keeps two series (bar)", () => {
  const res = {
    dimensions: dimsYB, measures: yieldMeasure, truncated_currencies: [],
    rows: [
      {currency: "RSD", dims: ["2020", "x"], values: [1]},
      {currency: "RSD", dims: ["2020", "y"], values: [2]},
    ],
  };
  const fig = PC.buildFigure(res, {type: "bar"}, {colorFor, labelFor: (id, v) => (id === "remaining_bucket" ? "Same" : v)});
  assert.equal(fig.data.length, 2);
  assert.deepEqual(fig.data.map((t) => t.name), ['Same ["x"]', 'Same ["y"]']);
  assert.deepEqual(fig.data.map((t) => t.y), [[1], [2]]);
  assert.notEqual(fig.data[0].marker.color, fig.data[1].marker.color);
});

test("null and the string 'null' are separate groups (bar)", () => {
  const res = {
    dimensions: [{id: "isin", label: "Hartija"}], measures: [oneDim.measures[0]], truncated_currencies: [],
    rows: [
      {currency: "RSD", dims: [null], values: [1]},
      {currency: "RSD", dims: ["null"], values: [2]},
    ],
  };
  const t = PC.buildFigure(res, {type: "bar"}, {colorFor}).data[0];
  assert.equal(t.x.length, 2);
  assert.notEqual(t.x[0], t.x[1]);
  assert.deepEqual(t.y, [1, 2]);
});

test("5 and '5' are separate groups (bar)", () => {
  const res = {
    dimensions: [{id: "isin", label: "Hartija"}], measures: [oneDim.measures[0]], truncated_currencies: [],
    rows: [
      {currency: "RSD", dims: [5], values: [1]},
      {currency: "RSD", dims: ["5"], values: [2]},
    ],
  };
  const t = PC.buildFigure(res, {type: "bar"}, {colorFor}).data[0];
  assert.equal(t.x.length, 2);
  assert.notEqual(t.x[0], t.x[1]);
  assert.deepEqual(t.y, [1, 2]);
});

test("heatmap: same display label for two raw values stays two columns/rows", () => {
  const res = {
    dimensions: dimsYB, measures: yieldMeasure, truncated_currencies: [],
    rows: [
      {currency: "RSD", dims: ["a", "p"], values: [1]},
      {currency: "RSD", dims: ["b", "p"], values: [2]},
      {currency: "RSD", dims: ["a", "q"], values: [3]},
      {currency: "RSD", dims: ["b", "q"], values: [4]},
    ],
  };
  const t = PC.buildFigure(res, {type: "heatmap"}, {colorFor, labelFor: () => "Same"}).data[0];
  assert.equal(t.x.length, 2);
  assert.equal(t.y.length, 2);
  assert.notEqual(t.x[0], t.x[1]);
  assert.notEqual(t.y[0], t.y[1]);
  assert.deepEqual(t.z, [[1, 2], [3, 4]]);
});

test("heatmap: null and the string 'null' do not merge", () => {
  const res = {
    dimensions: dimsYB, measures: yieldMeasure, truncated_currencies: [],
    rows: [
      {currency: "RSD", dims: [null, "p"], values: [1]},
      {currency: "RSD", dims: ["null", "p"], values: [2]},
    ],
  };
  const t = PC.buildFigure(res, {type: "heatmap"}, {colorFor}).data[0];
  assert.equal(t.x.length, 2);
  assert.deepEqual(t.z, [[1, 2]]);
});

test("scatter hover text disambiguates points that share a label", () => {
  const res = {
    dimensions: [{id: "isin", label: "Hartija"}], measures: oneDim.measures, truncated_currencies: [],
    rows: [
      {currency: "RSD", dims: ["a"], values: [1, 2]},
      {currency: "RSD", dims: ["b"], values: [3, 4]},
    ],
  };
  const t = PC.buildFigure(res, {type: "scatter"}, {colorFor, labelFor: () => "Same"}).data[0];
  assert.deepEqual(t.text, ['Same ["a"]', 'Same ["b"]']);
});

const threeMeasures = [...oneDim.measures, {id: "quantity", label: "Kolicina", unit: "pieces"}];
const scatterRes = (rows) => ({dimensions: oneDim.dimensions, measures: threeMeasures, rows, truncated_currencies: []});

test("scatter: marker sizes are normalised per currency", () => {
  const res = scatterRes([
    {currency: "RSD", dims: ["A"], values: [1, 1, 1e9]},
    {currency: "RSD", dims: ["B"], values: [1, 1, 4e8]},
    {currency: "EUR", dims: ["E1"], values: [1, 1, 10]},
    {currency: "EUR", dims: ["E2"], values: [1, 1, 2.5]},
  ]);
  const [rsd, eur] = PC.buildFigure(res, {type: "scatter"}, {colorFor}).data;
  assert.equal(rsd.name, "RSD");
  assert.equal(rsd.marker.size[0], 28);
  assert.equal(eur.marker.size[0], 28);
  assert.ok(Math.abs(rsd.marker.size[1] - Math.sqrt(0.4) * 28) < 1e-9);
  assert.ok(Math.abs(eur.marker.size[1] - 14) < 1e-9);
});

test("scatter: null, undefined, zero and all-zero sizes never give NaN, zero or negative markers", () => {
  const mixed = scatterRes([
    {currency: "RSD", dims: ["A"], values: [1, 1, 100]},
    {currency: "RSD", dims: ["B"], values: [1, 1, null]},
    {currency: "RSD", dims: ["C"], values: [1, 1]},
    {currency: "RSD", dims: ["D"], values: [1, 1, 0]},
    {currency: "RSD", dims: ["E"], values: [1, 1, -100]},
  ]);
  const s = PC.buildFigure(mixed, {type: "scatter"}, {colorFor}).data[0].marker.size;
  assert.equal(s[0], 28);
  assert.deepEqual(s.slice(1, 4), [6, 6, 6]);
  assert.equal(s[4], 28); // size encodes magnitude, so -100 is as large as 100
  const zeros = scatterRes([
    {currency: "RSD", dims: ["A"], values: [1, 1, 0]},
    {currency: "RSD", dims: ["B"], values: [1, 1, null]},
  ]);
  for (const v of PC.buildFigure(zeros, {type: "scatter"}, {colorFor}).data[0].marker.size) {
    assert.ok(Number.isFinite(v) && v >= 6);
  }
});

test("scatter with two currencies: panels, axes, titles, layout keys, grid", () => {
  const fig = PC.buildFigure(oneDim, {type: "scatter"}, {colorFor});
  assert.equal(fig.data.length, 2);
  assert.deepEqual(fig.data.map((t) => [t.xaxis, t.yaxis]), [["x", "y"], ["x2", "y2"]]);
  assert.deepEqual(fig.layout.annotations.map((a) => a.text), ["EUR", "RSD"]);
  assert.equal(fig.layout.xaxis.title.text, "Promet");
  assert.equal(fig.layout.xaxis2.title.text, "Promet");
  assert.equal(fig.layout.yaxis2.title.text, "Ponderisani prinos");
  assert.equal(fig.layout.grid.pattern, "independent");
  assert.equal(fig.layout.grid.rows, 1);
  assert.equal(fig.layout.grid.columns, 2);
});

test("heatmap with two currencies: panels, titles, layout keys, scale only for a single currency", () => {
  const res = {
    dimensions: dimsYB, measures: yieldMeasure, truncated_currencies: [],
    rows: [
      {currency: "EUR", dims: ["2020", "0-1Y"], values: [3]},
      {currency: "RSD", dims: ["2020", "0-1Y"], values: [1]},
    ],
  };
  const fig = PC.buildFigure(res, {type: "heatmap"}, {colorFor});
  assert.deepEqual(fig.data.map((t) => [t.xaxis, t.yaxis, t.showscale]), [["x", "y", false], ["x2", "y2", false]]);
  assert.deepEqual(fig.layout.annotations.map((a) => a.text), ["EUR", "RSD"]);
  assert.equal(fig.layout.xaxis2.type, "category");
  assert.equal(fig.layout.yaxis2.autorange, "reversed");
  assert.equal(fig.layout.grid.pattern, "independent");
  assert.equal(fig.layout.grid.columns, 2);
  assert.equal(PC.buildFigure(twoDims, {type: "heatmap"}, {colorFor}).data[0].showscale, true);
});

test("layout: 2 measures x 2 currencies use axes 1-4 on an independent 2x2 grid", () => {
  const fig = PC.buildFigure(oneDim, {type: "bar"}, {colorFor});
  for (const key of ["xaxis", "xaxis2", "xaxis3", "xaxis4", "yaxis", "yaxis2", "yaxis3", "yaxis4"]) {
    assert.ok(fig.layout[key], `missing layout.${key}`);
  }
  assert.equal(fig.layout.yaxis3.title.text, "Ponderisani prinos");
  assert.equal(fig.layout.yaxis4.title.text, "Ponderisani prinos");
  assert.deepEqual(fig.data.map((t) => [t.xaxis, t.yaxis]), [["x", "y"], ["x2", "y2"], ["x3", "y3"], ["x4", "y4"]]);
  assert.equal(fig.layout.grid.pattern, "independent");
  assert.equal(fig.layout.grid.rows, 2);
  assert.equal(fig.layout.grid.columns, 2);
});

test("horizontal bars with two dimensions", () => {
  const fig = PC.buildFigure(twoDims, {type: "bar", horizontal: true}, {colorFor});
  const byName = Object.fromEntries(fig.data.map((t) => [t.name, t]));
  assert.equal(byName["0-1Y"].orientation, "h");
  assert.deepEqual(byName["0-1Y"].y, ["2020", "2021"]);
  assert.deepEqual(byName["0-1Y"].x, [1.5, 1.0]);
  assert.deepEqual(byName["1-3Y"].x, [2.0, null]);
  assert.equal(fig.layout.yaxis.autorange, "reversed");
  assert.equal(fig.layout.xaxis.title.text, "Ponderisani prinos");
  assert.equal(fig.layout.showlegend, true);
});

test("tableModel without labelFor keeps raw values", () => {
  const m = PC.tableModel(oneDim);
  assert.deepEqual(m.rows[2], ["RSD", "A", 400, 5.5]);
  assert.deepEqual(m.header, ["Valuta", "Hartija (ISIN)", "Promet", "Ponderisani prinos"]);
});

test("helpers with colorFor: undefined fall back to the default colour", () => {
  const fig = PC.buildFigure(oneMeasure, {type: "bar"}, {colorFor: undefined, labelFor: undefined});
  assert.match(fig.data[0].marker.color, /^#[0-9a-f]{6}$/);
  assert.ok(PC.buildFigure(oneMeasure, {type: "line"}, {colorFor: undefined}));
  assert.ok(PC.buildFigure(oneMeasure, {type: "bar"}));
});

test("buildFigure returns null (does not throw) for a missing config or type", () => {
  assert.equal(PC.buildFigure(oneDim, undefined, {colorFor}), null);
  assert.equal(PC.buildFigure(oneDim, null, {colorFor}), null);
  assert.equal(PC.buildFigure(oneDim, {}, {colorFor}), null);
});
