"use strict";
const test = require("node:test");
const assert = require("node:assert/strict");
const IsinFilter = require("../securities_analyzer/ui/isin_filter.js");

const LABEL = "RSMFRSD58761 · RSD · 7,00% · 2031-10-26";

test("an empty or blank query matches everything", () => {
  assert.equal(IsinFilter.matches(LABEL, ""), true);
  assert.equal(IsinFilter.matches(LABEL, "   "), true);
  assert.equal(IsinFilter.matches(LABEL, undefined), true);
  assert.equal(IsinFilter.matches(LABEL, null), true);
});

test("matching is case-insensitive substring search over the whole label", () => {
  assert.equal(IsinFilter.matches(LABEL, "rsmfrsd58761"), true);
  assert.equal(IsinFilter.matches(LABEL, "58761"), true);
  assert.equal(IsinFilter.matches(LABEL, "RSD"), true);
  assert.equal(IsinFilter.matches(LABEL, "2031"), true);
  assert.equal(IsinFilter.matches(LABEL, "eur"), false);
  assert.equal(IsinFilter.matches(LABEL, "2040"), false);
});

test("a currency word does not match inside every ISIN code (all ISINs contain RSD)", () => {
  const eur = "RSMFRSD51436 · EUR · 3,50% · 2040-01-31";
  assert.equal(IsinFilter.matches(eur, "rsd"), false);      // only the currency field counts
  assert.equal(IsinFilter.matches(eur, "eur"), true);
  assert.equal(IsinFilter.matches(LABEL, "rsd"), true);
  assert.equal(IsinFilter.matches(LABEL, "eur"), false);
  assert.equal(IsinFilter.matches(eur, "rsmf"), true);       // letters match the start of a word, e.g. the ISIN prefix
  assert.equal(IsinFilter.matches(eur, "rsmfrsd"), true);
  assert.equal(IsinFilter.matches(eur, "rsmfrsd51"), true);  // anything with a digit matches anywhere
  assert.equal(IsinFilter.matches(eur, "frsd51436"), true);
  assert.equal(IsinFilter.matches(eur, "51436"), true);
  assert.equal(IsinFilter.matches(eur, "rsd 2040"), false);
  assert.equal(IsinFilter.matches(LABEL, "rsd 2031"), true);
});

test("several words must all match, in any order", () => {
  assert.equal(IsinFilter.matches(LABEL, "rsd 2031"), true);
  assert.equal(IsinFilter.matches(LABEL, "2031 rsd"), true);
  assert.equal(IsinFilter.matches(LABEL, "  rsd   2031  "), true);
  assert.equal(IsinFilter.matches(LABEL, "rsd 2040"), false);
  assert.equal(IsinFilter.matches(LABEL, "eur 2031"), false);
});

test("a decimal comma or point in the query matches the displayed coupon", () => {
  assert.equal(IsinFilter.matches(LABEL, "7,00"), true);
  assert.equal(IsinFilter.matches(LABEL, "7.00"), true);
  assert.equal(IsinFilter.matches("RSX · EUR · 3.50% · 2040-01-31", "3,5"), true);
  assert.equal(IsinFilter.matches(LABEL, "7,5"), false);
});

test("regex characters in the query are plain text", () => {
  assert.equal(IsinFilter.matches(LABEL, "("), false);
  assert.equal(IsinFilter.matches(LABEL, ".*"), false);
  assert.equal(IsinFilter.matches(LABEL, "7,00%"), true);
});

test("countLabel says that no selection means all ISINs", () => {
  assert.equal(IsinFilter.countLabel({selected: 0, total: 72, shown: 72}), "Nije izabrano ništa: važe svi ISIN-i (72)");
});

test("countLabel shows how many are selected", () => {
  assert.equal(IsinFilter.countLabel({selected: 3, total: 72, shown: 72}), "Izabrano: 3 od 72");
  assert.equal(IsinFilter.countLabel({selected: 72, total: 72, shown: 72}), "Izabrano: 72 od 72");
});

test("countLabel adds the number of visible rows only while a search narrows the list", () => {
  assert.equal(IsinFilter.countLabel({selected: 3, total: 72, shown: 5}), "Izabrano: 3 od 72 · prikazano 5");
  assert.equal(IsinFilter.countLabel({selected: 0, total: 72, shown: 0}), "Nije izabrano ništa: važe svi ISIN-i (72) · prikazano 0");
});

test("countLabel copes with an empty list", () => {
  assert.equal(IsinFilter.countLabel({selected: 0, total: 0, shown: 0}), "Nema hartija");
});
