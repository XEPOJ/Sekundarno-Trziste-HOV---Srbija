# Query builder ("Analiza") — rulings and open follow-ups

Date: 2026-10-12. Written when the subagent-driven build of the feature was closed and its (git-ignored) workspace was deleted.
Spec: `../specs/2026-10-12-query-builder-design.md`. Plan: `../plans/2026-10-12-query-builder.md`.

State at close: `main` = v0.1 + Analiza (fast-forward merge), 208 pytest + 31 Node tests green. Every task was reviewed after implementation; the whole branch got a final review plus one fix wave and a scoped re-review. The UI was checked by hand in a browser (overview golden values, examples A and B, chart switching, save/load, CSV/XLSX export).

## Rulings made while building

1. Commit trailer = the `Co-Authored-By` line each committing agent's own harness specifies (mixed trailers accepted). Cosmetic.
2. Implementers call `.venv\Scripts\python.exe -m ...` directly and never activate the venv.
3. Work stayed on `feature/query-builder`; `build/v0.1` was merged into `main` first, then the feature branch (both fast-forward, branches deleted).
4. Task 4 fix round: atomic exclusive-create of the export file name, write to `<name>.part` then `os.replace`, cleanup on failure, xlsx saved through `io.BytesIO` (the open-handle approach leaked a ZipFile on Windows). The pivot export response additionally carries `truncated_currencies` so truncation is never silent.
5. One final fix wave: example C golden bounded to `date_to=2025-12-31` (RSD 3563 / EUR 1048; the unbounded count would have failed the release workflow when NBS publishes a new trading day), populated-v1 migration test, UI race guards, default limit for time/ordinal first dimension = catalog `max_limit`, `schema_version` stamp never downgrades, non-vacuous tie-break test.
6. Spreadsheet formula injection: first left open, then fixed on request (`sanitize_cell` in `api/exporting.py`, leading apostrophe on text cells starting with `= + - @ TAB CR`). **Still not done:** ISIN validation at ingest (`^[A-Z0-9]{12}$`) — it could silently drop real rows if NBS ever uses another format.

## Open follow-ups (none is a known bug; all were rated Minor)

### Backend and tests
- Catalog: label/unit tables only partly pinned by tests; `remaining_years` CAST floors only non-negative values (column is non-negative); catalog dicts are mutable; `sort_sql` is computed twice when identical to `value_sql`.
- `run_pivot` tests: the NULL-last half of the descending test proves nothing; two-dimension orderings (descending, sort by measure) and zero-dimension measure sort are untested; no catalog invariant test (`sort_sql` functionally dependent on `value_sql`).
- `ensure_user_db`: the branch that copies the seed to a missing user DB is untested.
- API: no 422 test for a bad `format` on the export routes; saving from Analiza with 0 measures returns a technical pydantic 422 instead of the UI hint; inline `openpyxl` import left in `tests/test_exporting.py`; per-file independence of the cleanup `unlink` is not pinned by a test and a swallowed unlink failure is silent.

### Chart logic (`ui/pivot_chart.js`)
- A disambiguated label `x [raw]` can still equal another genuine label (cheap fix: final uniqueness pass appending `#<index>`); `rawKey` maps NaN/±Infinity to `"null"` (unreachable from JSON); `rawKey` and `rawText` are identical functions; `catLabels` is recomputed inside the series loop; `Math.max(...rows)` spreads the whole array (use `reduce` for very large row counts).
- Heatmap has no colour bar with more than one currency; panel titles ignore `xgap`/`ygap`; line charts keep server row order (caller must sort group-ascending for time dimensions); palette wraps after 10 series; scatter silently ignores a 4th measure; `hovertemplate` concatenates the currency unescaped.
- `horizontalGap` assumes about 1000 px plot width and 6.5 px per character, so label overlap can return at about 800 px or with 4+ currencies; its test is weak (add `xgap(horizontal) > xgap(short)` and the 0.8 clamp).
- Missing tests: cross-currency label collision, non-function `colorFor`.

### UI (`ui/analysis.js`, `ui/app.js`)
- Banner handling: a stale Pregled error stays visible in Analiza after a successful query; the zero-measure branch does not clear Analiza's own error; clearing Analiza's error can hide the sticky load-error or empty-database hint; a catalog init failure overwrites an earlier `state.loadError`; an export in flight when leaving Analiza can still write to the banner.
- Startup: `await Analysis.init()` runs before the first `refreshAll()`; clicking Analiza during that await lets `refreshAll()` run in analysis mode (guard with `state.mode === "overview"`); if the catalog never loads, Analiza is an inert empty shell with no message of its own, and init could run in parallel with the first Pregled load.
- Request handling: the config is read at response time, not request time; changing the chart type refetches although it is not part of the query; an invalid limit value is ignored without feedback; `setConfig` does not cap measures at `max_measures` or validate `chart.type`; null dimension values render as "null".
- Defaults: the horizontal checkbox stays enabled for line and heatmap (ignored there); the export notice starts with "Prikazano prvih N po valuti…" (accurate, slightly odd for an export); the 5000 default limit for time/ordinal dimensions can make the table and plot heavy for fine combinations such as day × ISIN.
- Accessibility: `#b-order` has no accessible name; mode buttons lack `aria-pressed`; `#a-notice` lacks `aria-live`; `th { cursor: pointer }` also applies to the non-sortable `#a-rows` header.
- No unit tests for `analysis.js` (only checked in the browser); consider extracting its pure parts so `node --test` can cover them.

## Known and accepted

- `POST /api/update` has no body, so a web page open in the user's browser can trigger a data update on the local server (it must guess the random loopback port). Impact is limited to downloading public NBS data into the user's own local database; no data can be read or changed. Decided not to add an `Origin` check (2026-10-12). Every other state-changing route takes a JSON body and rejects cross-site simple requests (422); the server only answers loopback `Host` headers (DNS-rebinding guard) and sends no CORS headers.

## Project-level items still open

- The GitHub workflows (`ci.yml`, `release.yml`) have never run; the YAML was only parsed.
- NBS terms of use for the bundled seed database are unchecked. Decided 2026-10-12: releases keep shipping the seed database (`data/seed.db` inside the zip); the commit history keeps the original author e-mail.
- A pinned dependency constraints file is deferred until just before the first public tag.
- Publishing (public GitHub repo + tag `v0.1.0`) needs an explicit decision; nothing has been pushed and there is no remote.
- Manual-check recipe for browser verification: copy `data/seed.db` to a scratch folder, run `ensure_user_db(path, None)` on the copy (the raw seed is schema v1; skipping this makes `/api/saved-queries` return 500), serve it with `create_app(path, export_dir=...)` on `127.0.0.1`, and compare against the examples in spec §10.
