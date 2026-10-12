# Securities Analyzer — design spec

Date: 2026-10-12
Status: draft for review

## 1. Goal

A standalone Windows program for exploring the NBS secondary-market trading data
for Serbian government securities (2020 → today). It behaves like a small
Power BI report without needing Power BI: multi-dimensional filters, tables,
interactive charts, and an **Update base** button that pulls fresh data from NBS
onto the user's own machine.

Example query that must work end to end:

> yield > 3.5%, trade date 2023-02-02 … 2024-03-05, remaining maturity > 3 years

### Non-goals (v1)

- Android/iOS/macOS builds (see §12).
- Any server, account, cloud database or telemetry. Everything runs locally.
- Natural-language queries, forecasting, FX conversion, yield-curve fitting.
- Per-transaction analysis (the source only has daily aggregates).

## 2. Source data

Source: NBS web app, one CSV per year.

- Page: `https://webappcenter.nbs.rs/WebApp/Securities/GovermentSecuritySecondaryTrade/IndexArchive`
- Download: `GET https://webappcenter.nbs.rs/WebApp/Securities/GovermentSecuritySecondaryTrade/Download?Format=csv&Year=<YYYY>`
  (verified 2026-10-12: plain GET, no login/JS/CAPTCHA, `text/csv`, UTF-8 with BOM).

Facts established from the 7 local files (2020–2026, 5,309 rows):

- 18 columns, identical Cyrillic header in every file, with a leading space after
  each comma. Columns are mapped **by position** and the header is only validated
  (normalized: trimmed) against the expected Cyrillic names.
- Grain: one row = one ISIN × trade date × settlement date (daily aggregate, not a
  single trade). Business key `(trade_date, settlement_date, isin)` is unique across
  all files (verified: 5,309 distinct keys).
- Yearly files are bucketed by settlement year: each file starts with the last
  trading days of the previous year. **The year in the file name is a refresh unit,
  not a data attribute.**
- Yields are in percentage points (`5.14` = 5.14%).
- RSD and EUR securities coexist; turnover must never be summed across currencies.

Column map (position → DB column):

| # | Source header | DB column | Type |
|---|---|---|---|
| 0 | Датум трговања | `trade_date` | DATE |
| 1 | Датум салдирања | `settlement_date` | DATE |
| 2 | Датум доспећа | `maturity_date` | DATE |
| 3 | ISIN | `isin` | TEXT |
| 4 | Рочност у данима | `original_maturity_days` | INT |
| 5 | Валута | `currency` | TEXT (any 3 uppercase letters, e.g. RSD/EUR) |
| 6 | Купонска стопа | `coupon_pct` | REAL (`-` for zero-coupon T-bills is stored as `0.0`) |
| 7 | Преостала рочност у данима | `remaining_maturity_days` | INT |
| 8 | Количина | `quantity` | INT |
| 9 | Број трансакција | `transaction_count` | INT |
| 10 | Номинална цена по комаду | `nominal_per_unit` | REAL |
| 11 | Минимална цена | `min_price` | REAL |
| 12 | Максимална цена | `max_price` | REAL |
| 13 | Просечна пондерисана цена | `wavg_price` | REAL |
| 14 | Укупан промет | `turnover` | REAL |
| 15 | Минимални принос | `min_yield_pct` | REAL |
| 16 | Максимални принос | `max_yield_pct` | REAL |
| 17 | Просечни принос | `avg_yield_pct` | REAL |

## 3. Architecture

Python 3.13 backend, static web frontend, shown in a native window.

```
securities_analyzer/
  ingest/    parse + validate NBS CSV -> typed rows         (pure, no I/O besides file read)
  db/        SQLite schema, connection, upsert/replace      (only module that touches SQLite)
  query/     FilterSpec -> SQL -> result rows + aggregates  (pure given a connection)
  updater/   NBS download, year selection, atomic refresh   (only module that touches network)
  api/       FastAPI routes, thin JSON over query/updater
  ui/        static HTML/JS/CSS, vendored Plotly (no CDN)
  app.py     start server on 127.0.0.1:<port>, open window
tests/
CLI `python -m securities_analyzer build-seed|fetch-all`   (CSV folder -> seed.db; NBS -> CSV folder)
scripts/build_exe.ps1   PyInstaller one-folder build
.github/workflows/ci.yml        tests on push / pull request
.github/workflows/release.yml   tag build: tests -> seed -> exe -> artifact check -> zip -> release
```

Rules of the boundaries:

- `query` never does I/O except through the passed-in connection; `ingest` never
  touches the DB; `updater` never parses CSV itself (it hands bytes to `ingest`).
- The frontend only talks to `/api/*`. It contains no business rules, so another
  client (see §12) can reuse the same API shape and SQL.
- The server binds to `127.0.0.1` only and picks a free port at start. It also rejects
  requests whose `Host` header is not `127.0.0.1` or `localhost` (HTTP 400,
  `TrustedHostMiddleware`, `create_app(..., allowed_hosts=...)`) as a DNS-rebinding guard.
- Window: `pywebview`; if unavailable, fall back to the default browser. pywebview 6.x
  does not raise when the Microsoft Edge WebView2 runtime is missing (it silently
  switches to the IE11 engine), so `app._webview_usable()` checks
  `webview.platforms.winforms.renderer == "edgechromium"` and, if not, takes the browser
  fallback. If that internal attribute cannot be inspected, the window is attempted anyway.
- Browser-fallback lifetime: the windowed exe has no console, so the UI posts
  `POST /api/heartbeat` (`{"ok": true}`) on load and every 10 s. In fallback mode only, a
  watchdog stops the server when no heartbeat arrives for 60 s (180 s grace if none ever
  arrived), which ends the process about a minute after the tab is closed.

## 4. Database (SQLite, single file)

Location: `%APPDATA%\SecuritiesAnalyzer\data.db`. On first run it is copied from the
bundled `seed.db` (history 2020 → build date). An existing user DB is never
overwritten by a newer app version; **Update base** fills the gap.

Tables:

- `trades` — one row per source row, columns per §2 plus
  `source_year INT NOT NULL` (which yearly file it came from),
  `settlement_lag_days INT`, `quality_flag TEXT`.
  `UNIQUE (trade_date, settlement_date, isin)`.
  Indexes: `trade_date`, `isin`, `remaining_maturity_days`, `avg_yield_pct`.
- `securities` — view over `trades` (one row per ISIN: maturity, currency, coupon,
  nominal, original maturity). Static attributes are consistent per ISIN (verified
  for 2025).
- `meta` — `schema_version`, `last_update_utc`, `last_update_result`.
- `saved_queries` — `name`, `filter_json`. Stored in SQLite, **not** browser
  localStorage, because the origin (port) may change between runs.

Quality flags (carried over from the existing Power BI work): `min ≤ avg ≤ max` for
price and yield; `settlement ≥ trade`; `maturity ≥ settlement`; turnover vs
`quantity × wavg_price` within `quantity × 0.005 + 0.02`. Values: `OK` or a short
reason code. Flagged rows are **kept** and surfaced in the UI, never silently dropped.

## 5. Filters and semantics

`FilterSpec` (all optional, combined with AND):

| Field | Meaning |
|---|---|
| `date_from`, `date_to` | trade date, **inclusive** both ends |
| `yield_pct` | `Range`; bounds on the chosen yield basis, in percentage points |
| `yield_basis` | `avg` (default) / `min` / `max` → `avg_yield_pct` etc. |
| `remaining_maturity_years`, `original_maturity_years` | `Range`; years (UI) → days |
| `coupon_pct` | `Range`; percentage points |
| `settlement_lag_days` | `Range`; days |
| `currency` | list of 3-letter uppercase currency codes (any, e.g. `RSD`/`EUR`) |
| `isin` | list |
| `turnover_min` | in the row's own currency |

`Range` is `{min, max, min_exclusive, max_exclusive}` (all optional; the flags default
to `false`). It is used for yield, remaining/original maturity, coupon and settlement
lag.

Decisions:

- **"Longer than 3 years" defaults to remaining maturity** (user decision,
  2026-10-12); original maturity is a separate filter.
- Years → days uses **365 days/year** (`3 years = 1095 days`), consistent with the
  existing maturity buckets. Each bound has an `*_exclusive` flag (default
  inclusive): "more than" sets `min_exclusive` (strict `>`), "at least" leaves it off
  (`>=`); the UI labels which one each field uses. Maturity-year bounds are converted
  to days (x365) and rounded to 6 decimals to avoid floating-point noise.
- Remaining maturity is the value stored **on each row** (it shrinks day by day), so
  the filter is evaluated per row, not per security.
- Yield filters apply to the row's daily aggregate. A row whose *average* yield is
  3.6% but *min* 3.2% passes `avg > 3.5`. The basis is user-selectable and shown in
  the result header.
- UI date input accepts `dd.mm.yyyy`; API uses ISO `yyyy-mm-dd`.
- Currency codes are validated as any 3 uppercase letters (not only RSD/EUR), so a
  new currency on NBS never blocks an update.
- All SQL is parameterized; `FilterSpec` is validated (types, ranges, enum values)
  before SQL is built. Unknown fields are rejected.

## 6. Results and aggregates

For a `FilterSpec` the API returns:

1. **Rows** (paged, sortable): trade date, ISIN, currency, coupon, maturity, remaining
   maturity, quantity, transactions, avg price, avg/min/max yield, turnover, flag.
2. **KPIs, always split by currency** (never mixed): turnover, quantity, transaction
   count, active ISINs, active days, **turnover-weighted average yield**
   (`Σ(avg_yield × turnover) / Σ turnover`). Min/max prices and yields are never
   summed or averaged across days.
3. **Chart series**:
   - Weighted yield over time by day/week/month, one line per currency (a per-ISIN
     series is **not in v1**, see §13) — the "graphical expression of the change".
   - Scatter: remaining maturity (x) vs avg yield (y), size = turnover, colour =
     currency, hover = ISIN. This is realised trades, not an official yield curve.
   - Turnover by maturity bucket (0–1Y, 1–3Y, 3–5Y, 5–10Y, 10Y+), per currency.
4. **Daily extremes** (highest / lowest yield per day): for every trade date in the
   selection, per currency: `highest = MAX(max_yield_pct)` with its ISIN,
   `lowest = MIN(min_yield_pct)` with its ISIN, and the daily range. Ties are broken
   by larger turnover, then by ISIN. Views: a table (sortable, so "the day with the
   highest/lowest yield in the period" is one click) and a band chart (lowest–highest
   per day with the weighted average line). Top-N lookup: "N days with the highest /
   lowest yield" within the selection. Extremes honour all other filters (maturity,
   ISIN, currency…), so "highest yield per day among securities longer than 3 years"
   works. Note: `max_yield_pct` / `min_yield_pct` are already extremes of that
   ISIN's trades that day; no cross-day aggregation of them is ever averaged.
5. **Data quality**: count of flagged rows within the selection.

The daily-extremes chart makes its own request (newest first, limit 5000, reversed
client-side) so that, should the cap ever bind, only the oldest days are dropped, while the
extremes table uses the user's chosen sort (limit 500). The weighted-average line comes
from `POST /api/query/timeseries` with `granularity: "day"`. The result header names the
yield basis ("Prinos: prosečni/minimalni/maksimalni (osnova)").

Exports: results table → CSV/XLSX; charts → PNG (Plotly built-in).

## 7. UI (Serbian, Latin script)

Single page, Power BI-like: left filter panel, top KPI strip, centre chart tabs,
bottom results table. Charts and table react to the same filter state (debounced).
Saved queries and a "Reset" action. Plotly is vendored so the app works offline
(except Update).

Saved queries use `GET/PUT /api/saved-queries` and
`DELETE /api/saved-queries/{name:path}` (the `path` converter allows `/` in names).

Footer: "Poslednje ažuriranje: …", "Podaci: Narodna banka Srbije" (attribution),
data range in the DB, app version.

## 8. Update base

Trigger: button in the UI → `POST /api/update` → progress via polling/SSE.

Algorithm:

1. `current_year = today.year`; `last = max(source_year)` from the DB.
2. Years to refresh = `range(min(last, current_year - 1), current_year + 1)` —
   i.e. always the last two years, plus any gap if the app was unused for longer.
3. For each year, sequentially: `GET` Download URL (timeout, 3 retries with
   backoff, identifying `User-Agent: SecuritiesAnalyzer/<version>`), save to a temp file.
4. Validate with `ingest`: header matches the expected 18 columns, every row parses,
   ≥ 1 row, business keys unique within the file. On any failure: skip that year,
   report it, keep existing data. **January rule:** a file with 0 rows for the *current*
   year while nothing is stored for that year yet is not an error (status `ok`, added 0,
   message "Još nema podataka za tekuću godinu"); any other 0-row file is an error.
5. Guard: if the new file has < 50% of the rows currently stored for that
   `source_year`, abort that year and warn (protects against a truncated download).
6. Apply in **one transaction per year**: delete `trades` where
   `source_year = Y`, insert the new rows. A key collision with a *different*
   `source_year` aborts the transaction.
7. Update `meta`; return a summary: per year `+added / −removed / unchanged`,
   new data end date, any errors. `last_attempt_utc` and `last_update_result` are written
   on every run; `last_update_utc` means the last **success** and is written only when at
   least one year ended `ok`. `/api/meta` returns both `last_update_utc` and
   `last_attempt_utc`; the footer's "Poslednje ažuriranje" uses the former.

Properties: idempotent, safe to interrupt (transactions), never destroys data on
network or format errors, no more traffic than 2–3 small files per click.

Optional (v1.1, no server needed): check GitHub Releases API for a newer app version
and show a notice.

## 9. Error handling

- Offline / NBS down / HTTP error → clear message, DB untouched.
- Header or column-count change → "NBS format changed, update the app" (the main
  external risk; fixed by shipping a new release).
- Corrupt or locked DB → message with DB path; never auto-delete the user DB.
- Fatal startup errors are shown in a native message dialog (the windowed exe has no
  console) and the process exits with a non-zero code.
- Invalid filter → field-level error in the UI (HTTP 422 from the API).

## 10. Testing (TDD, pytest)

- `ingest`: fixtures from real rows (Cyrillic header, leading spaces, BOM, `.00`
  decimals); malformed rows; header change.
- `db`: schema, unique key, replace-by-`source_year` atomicity (injected failure
  rolls back).
- `query`: one test per filter field, boundary inclusivity, currency separation,
  weighted-yield maths on hand-computed data, and the **golden test** from §1 run
  against the real 7-file seed (result pinned after a manual cross-check in
  Python, independent of the SQL).
- `updater`: against a local fake HTTP server (success, truncated file, 500, format
  change, gap of several years). No live network in the test suite; one manual
  smoke test against NBS before each release.
- `api`: contract tests with FastAPI `TestClient`. The `dev` extra includes `httpx2`
  because Starlette's `TestClient` prefers it.
- UI: manual checklist for v1 (filters ↔ charts ↔ table consistent; layout at
  common window sizes).

## 11. Packaging and distribution

- PyInstaller, **one-folder** build (fewer antivirus false positives and faster
  start than one-file), zipped. `seed.db` is built in CI from the CSVs by the CLI
  (`python -m securities_analyzer fetch-all`, then `build-seed`) and bundled.
  `scripts/build_exe.ps1` runs PyInstaller locally and in CI.
- The release workflow downloads the data from NBS in CI; no NBS data is committed to
  the repo.
- GitHub Actions on version tag: run tests → build seed → build exe → attach zip to
  the GitHub Release. Users download from Releases. No hosting.
- Known friction: unsigned binary triggers Windows SmartScreen; documented in the
  README. Running from source (`python -m securities_analyzer`) is the alternative.
- Before publishing the seed DB: confirm NBS terms of use; keep the attribution
  footer. If terms are unclear, ship without seed and download all years on first
  run (same code path as Update).

## 12. Future: Android (out of v1 scope)

The `.exe` does not run on Android. A viable later path that still needs no server:
a static web app on GitHub Pages that loads the SQLite file in the browser
(sql.js/WASM) and reuses the same filter semantics and the existing `ui/` assets;
a scheduled GitHub Action refreshes the data file from NBS daily (the browser cannot
call NBS directly because of CORS). v1 keeps this open by (a) keeping the frontend
static and API-driven and (b) documenting `FilterSpec → SQL` as the single source of
query semantics. Requires its own spec.

## 13. Deviations from this design and v1 limits

- Numeric filters are `Range {min, max, min_exclusive, max_exclusive}` (§5).
- `scripts/build_seed.py` is replaced by the CLI subcommands `build-seed` / `fetch-all`;
  both `build-seed` and `build_seed()` fail (non-zero exit) on zero CSVs or zero rows.
- The release workflow downloads the data from NBS in CI and verifies the built
  artifact (non-empty `seed.db`, `index.html`, `plotly.min.js`) before zipping.
- Currency codes are any 3 uppercase letters; filter list sizes are bounded (50 currencies,
  500 ISINs) and `page` is capped at 1,000,000 (HTTP 422 beyond that).
- Saved-query names are trimmed; empty, `.`, `..` and names with control characters
  are rejected (HTTP 422).
- **Not in v1:** the per-ISIN time series mentioned (as optional) in §6.3.

## 14. Assumptions to confirm

1. 365-day years for maturity filters (consistent with existing buckets).
2. Default yield basis = daily average yield (`avg_yield_pct`).
3. Totals and weighted yields are always shown per currency, never mixed.
4. Windows-only for v1; UI in Serbian Latin.
5. Seed database is bundled in the release (subject to NBS terms, §11).
