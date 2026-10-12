"use strict";
/* Pure helpers for the ISIN picker in the sidebar. No DOM: unit-tested with `node --test`. */
(function (root, factory) {
  if (typeof module === "object" && module.exports) module.exports = factory();
  else root.IsinFilter = factory();
})(typeof self !== "undefined" ? self : this, function () {
  // lower-case, and treat the decimal comma like a point so "7,00" and "7.00" both find a 7.00% coupon
  const norm = (s) => String(s == null ? "" : s).toLowerCase().replace(/,/g, ".");

  /**
   * True when every whitespace-separated word of `query` matches `label` (case-insensitive).
   * A word made only of letters must match the START of a word of the label, so "rsd" finds the
   * currency but not the "RSD" buried in every ISIN code (RSMFRSD…). A word containing a digit
   * matches anywhere ("58761", "2031", "7.00", "frsd5").
   */
  function matches(label, query) {
    const words = norm(query).split(/\s+/).filter(Boolean);
    if (!words.length) return true;
    const text = norm(label);
    const labelWords = text.split(/[^a-z0-9.]+/).filter(Boolean);
    return words.every((w) => (/^[a-z]+$/.test(w) ? labelWords.some((lw) => lw.startsWith(w)) : text.includes(w)));
  }

  /** Status line under the list. Nothing selected means "no ISIN filter", i.e. all ISINs apply. */
  function countLabel({selected, total, shown}) {
    if (!total) return "Nema hartija";
    const base = selected ? `Izabrano: ${selected} od ${total}` : `Nije izabrano ništa: važe svi ISIN-i (${total})`;
    return shown === total ? base : `${base} · prikazano ${shown}`;
  }

  return {matches, countLabel};
});
