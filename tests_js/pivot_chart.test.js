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
