# Query builder ("Analiza") — design spec

Date: 2026-10-12
Status: implemented on branch `feature/query-builder`; synced with the code (this document describes what was built)
Extends: `2026-10-12-securities-analyzer-design.md` (v0.1, branch `build/v0.1`). Everything in that spec stays valid; this adds one feature on top of it.

## 1. Why

v0.1 is a filter panel with four fixed views. The user can narrow rows but cannot choose what to group by or what to measure, so questions like "which securities traded most" cannot be answered. The goal is the useful core of Power BI: **pick the grouping, pick the measures, pick the chart**, on top of the existing filters.

"Sold securities" is not in the data: NBS publishes no buyer/seller side. The data supports *traded*: quantity, number of transactions and turnover per ISIN per day. "Most sold" is therefore answered as "most traded".

### In scope
- A new **Analiza** mode: choose up to 2 grouping dimensions, 1–4 measures, a chart type, sorting and "top N".
- Shared filters (the existing filter panel feeds both modes).
- Result as chart + table, export to CSV/XLSX, saving the whole view (filters + builder) as a saved query.

### Out of scope (v1 of the builder)
- Multi-visual dashboards, cross-filtering by clicking a chart, drill-through (a possible next step on the same API).
- User-defined formulas / calculated measures, joins with other data, forecasting.
- Per-transaction analysis (source is daily aggregates).

## 2. Concepts and rules

- **Dimension** = what to group by. **Measure** = what to compute per group. Both come from a fixed catalog served by the API; the frontend has no business knowledge.
- **Currency is always an implicit extra grouping.** RSD and EUR are never added together, whatever the user picks. Every result row carries its `currency`; charts show it as a separate series or panel; the user cannot switch this off. (Same rule as v0.1: no cross-currency sums or averages.)
- Filters (`FilterSpec`) are applied first, exactly as in v0.1, then rows are grouped.
- A group is built from the **daily aggregate rows**, not from individual trades. Measures that need weights use turnover as the weight.

## 3. Catalog

### Dimensions (`id` → grouping value → natural order)

| id | Label (sr) | Value | Order |
|---|---|---|---|
| `isin` | Hartija (ISIN) | ISIN | alphabetical |
| `date_day` | Dan | `trade_date` | chronological |
| `date_week` | Nedelja | Monday of the week (ISO date) | chronological |
| `date_month` | Mesec | first day of month | chronological |
| `date_quarter` | Kvartal | `YYYY-Qn` | chronological |
| `date_year` | Godina | `YYYY` | chronological |
| `remaining_bucket` | Preostali rok (grupa) | `0-1Y`, `1-3Y`, `3-5Y`, `5-10Y`, `10Y+` | **1…5, not alphabetical** |
| `remaining_years` | Preostala ročnost (cele godine) | `floor(remaining_days / 365)` | numeric |
| `original_years` | Originalna ročnost (godine) | `round(original_days / 365, 1)` | numeric |
| `coupon` | Kupon (%) | `coupon_pct` | numeric |
| `settlement_lag` | Dani do valutiranja | `settlement_lag_days` | numeric |

Each dimension has a `kind` in the catalog: `time` (the five date dimensions), `ordinal` (a naturally ordered scale: `remaining_bucket`, `remaining_years`, `original_years`, `coupon`, `settlement_lag`) or `category` (`isin`). The UI uses it for defaults and sorting (§7).

Each dimension has a *value expression* (what is shown) and a *sort expression* (natural order; for `remaining_bucket` it is the bucket number). Bucket edges are the same as in v0.1 (≤365, ≤1095, ≤1825, ≤3650, else 10Y+). Time dimensions use the same period expressions as the existing time series.

### Measures (`id` → formula over the filtered rows of the group → unit)

| id | Label (sr) | Formula | Unit |
|---|---|---|---|
| `turnover` | Promet | `SUM(turnover)` | currency |
| `quantity` | Količina | `SUM(quantity)` | pieces |
| `transactions` | Broj transakcija | `SUM(transaction_count)` | count |
| `active_days` | Dana trgovanja | `COUNT(DISTINCT trade_date)` | count |
| `isin_count` | Broj hartija | `COUNT(DISTINCT isin)` | count |
| `weighted_yield` | Ponderisani prinos | `SUM(avg_yield_pct * turnover) / SUM(turnover)` | % points |
| `yield_min` | Najmanji prinos | `MIN(min_yield_pct)` | % points |
| `yield_max` | Najveći prinos | `MAX(max_yield_pct)` | % points |
| `price_pct_nominal` | Cena (% nominale) | `100 * SUM(turnover) / SUM(quantity * nominal_per_unit)` | % |
| `avg_trade_size` | Promet po transakciji | `SUM(turnover) / SUM(transaction_count)` | currency |

Division by zero gives `null` (rendered "–"). Min/max yields are true extremes over the group and are never averaged.

## 4. Query semantics

- Request: `dimensions` (0–2 ids, no duplicates), `measures` (1–4 ids, no duplicates), `sort_by` (`"group"` or one of the selected measure ids), `order` (`asc`/`desc`, default `asc`), `limit` (1–5000, default 100), plus the `filter`.
- Zero dimensions is allowed: one row per currency (totals).
- **`limit` is per currency**: top N within RSD and top N within EUR. A single global top-N would let RSD's much larger numbers push EUR out entirely.
- Ordering: `sort_by = group` orders by the dimensions' sort expressions; a measure orders by that measure, `null`s last, then by the dimensions as tie-breaker (so results are deterministic).
- Truncation: the server fetches `limit + 1` per currency, returns `limit`, and lists the currencies that were cut in `truncated_currencies`. The UI shows "prikazano prvih N" for them.
- Default sort suggested by the UI: group-ascending when the first dimension is of kind `time` or `ordinal` (or there is no dimension), first measure descending when it is of kind `category` (ISIN). The defaults follow the first dimension until the user touches the control.
- All SQL is parameterized. Every identifier or expression comes from the catalog (dimension/measure ids are enums); nothing user-supplied reaches SQL text.

Shape of the SQL (illustrative):

```sql
WITH g AS (
  SELECT currency, <dim1 value> AS d1, <dim2 value> AS d2,
         <dim1 sort> AS s1, <dim2 sort> AS s2, <measure exprs> AS m1, ...
  FROM trades WHERE <filter> GROUP BY currency, <dim exprs>),
r AS (
  SELECT *, ROW_NUMBER() OVER (PARTITION BY currency
            ORDER BY <sort key> <dir>, s1, s2) AS rn FROM g)
SELECT ... FROM r WHERE rn <= :limit + 1 ORDER BY currency, rn
```

## 5. API

- `GET /api/pivot/catalog` → `{dimensions: [{id, label, kind}], measures: [{id, label, unit}], limits: {max_dimensions: 2, max_measures: 4, max_limit: 5000, default_limit: 100}}`.
- `POST /api/query/pivot` body `{filter, dimensions, measures, sort_by, order, limit}` →
  ```json
  {"dimensions": [{"id": "isin", "label": "Hartija (ISIN)"}],
   "measures":   [{"id": "turnover", "label": "Promet", "unit": "currency"}],
   "rows": [{"currency": "RSD", "dims": ["RSMFRSD58761"], "values": [121471327158.97]}],
   "truncated_currencies": []}
  ```
  Dimension values keep their natural type (numbers for numeric dimensions, ISO strings for dates, labels for buckets).
- `POST /api/export/pivot` body as above + `format` (`csv`/`xlsx`) → `{path, rows, truncated_currencies}`, written like the existing export (columns: currency, dimensions…, measures…). The export is cut by the same per-currency `limit` as the screen, so `truncated_currencies` tells the client which currencies were cut; the UI keeps the truncation notice visible after an export. Files are named `<stem>_<YYYYMMDD_HHMMSS>.<ext>`; on a same-second collision the file is created exclusively and gets a numeric suffix (`_2`, `_3`, …). The overview export (`POST /api/export`) shares the same helpers (`unique_export_path`, `write_table` in `api/exporting.py`). `write_table` guards against spreadsheet formula injection: text cells starting with `=`, `+`, `-`, `@`, tab or CR get a leading apostrophe (`sanitize_cell`); numbers, including negative ones, are written unchanged.
- Saved queries (`PUT /api/saved-queries`) accept an optional `pivot` object (`dimensions, measures, sort_by, order, limit, chart`) next to the filter; `GET` returns each item as `{name, filter, pivot}`, where `pivot` is `null` for legacy rows saved before the builder existed. Those keep working (they restore filters only).
- Invalid input → HTTP 422: unknown id, duplicates, more than 2 dimensions, 0 or more than 4 measures, `sort_by` that is not `"group"` or a selected measure, `limit` out of range.

The chart type is **not** part of the query: the server returns the same rows for every chart; chart choice lives in the client and in the saved `pivot.chart` (`{type, horizontal}`).

## 6. Storage

`saved_queries` gains a nullable `pivot_json TEXT` column. Fresh databases get it from the schema; existing databases are migrated in `init_schema` (check `PRAGMA table_info`, `ALTER TABLE … ADD COLUMN` if missing, bump `meta.schema_version` to `2`; `SCHEMA_VERSION = 2`). The migration is in place, so no data is rebuilt or re-imported. It is idempotent and never touches `trades`.

## 7. UI

- A mode switch in the header: **Pregled** (current view, unchanged) | **Analiza**. The filter panel on the left is shared by both modes; the "Sačuvaj" button saves filters plus (in Analiza mode) the builder state.
- Builder bar (Serbian Latin):
  - **Grupiši po**: two selectors (second optional), from the catalog.
  - **Mere**: checkboxes (1–4).
  - **Prikaz**: bar | line | scatter | heatmap | table; "Horizontalno" toggle for bars (default on when the first dimension is `isin`). The saved and restored `chart` config is `{type, horizontal}`.
  - **Sortiraj**: "po grupi" or by a selected measure, ↑/↓; **Prvih N po valuti**.
  - Updates automatically (debounced) as the user changes anything, like the filters.
- Which chart fits which selection (the UI explains it instead of failing):

| Chart | Needs | Drawing |
|---|---|---|
| bar | ≥1 dimension, ≥1 measure | x = dim1; series = dim2 if present, else one series per measure (dim2 present → first measure only) |
| line | same as bar | like bar, points joined, x ordered; meant for time dimensions |
| scatter | ≥1 dimension, ≥2 measures | x = measure 1, y = measure 2, size = measure 3 if present, one point per group, hover shows the group |
| heatmap | exactly 2 dimensions, 1 measure | x = dim1, y = dim2, colour = measure |
| table | any | result table only |

- Currency: one panel (subplot) per currency, with its own axis for money measures, so RSD and EUR are never on one scale. Colours per currency match the existing views. Horizontal bars with several currencies use a wider gap between the panels, sized from the longest category label, so the labels do not run into the neighbouring panel.
- Below the chart: the result table (currency, dimensions, measures), export buttons (CSV/XLSX), and a note when `truncated_currencies` is not empty (the note stays visible after an export).
- ISIN values are displayed as `ISIN · coupon % · maturity year`, enriched on the client from the already loaded `/api/securities` list (display only, not part of the query).
- Chart/axis construction lives in a small pure JS module (`ui/pivot_chart.js`) that is unit-tested with Node's built-in test runner (`node --test tests_js/pivot_chart.test.js`, files in `tests_js/`); DOM wiring lives in `ui/analysis.js` and `ui/app.js`. The Node tests run in CI (`ci.yml`) and in the release workflow before the seed database is built, so a failing JS test stops a release.

## 8. Errors and empty states

- No rows for the filters → "Nema rezultata za izabrane filtere."
- Invalid builder combination for the chosen chart (e.g. heatmap with one dimension) → inline hint, table still shown.
- No measure selected (0 measures) → the builder shows the hint "Izaberi bar jednu meru.", sends no query, clears the previous chart and table, and disables the CSV/XLSX export buttons.
- Server 422 → message shown in the existing error banner.
- Large results are cut by `limit`; stale responses are ignored (same request-token pattern as the existing views).

## 9. Testing

- **Service (hand-computed data):** each measure, each dimension (including week = Monday, quarter, bucket order, original-years rounding), zero dimensions, two dimensions, sort by group/measure, `null`s last, deterministic tie-break, per-currency `limit` with truncation, currency never merged.
- **Golden (real data, expected values computed independently in plain Python):** see §10.
- **API:** catalog, 422 matrix, response shape, export CSV/XLSX content, saved query with and without `pivot`, migration of a v1 database.
- **JS unit tests:** chart-validity rules and trace/axis building in `pivot_chart.js` (`tests_js/pivot_chart.test.js`, run in CI and before a release).
- **Manual checklist (browser):** the §10 examples, switching chart types, saving and restoring a view, export, mode switch keeps filters.

## 10. Acceptance examples (reference values computed from the 5,309-row seed)

A. **Most traded securities in 2024** — filter: trade date 2024-01-01…2024-12-31; dimensions `[isin]`; measures `[turnover, quantity, transactions, weighted_yield]`; sort by `turnover` desc; limit 5.
   - RSD: `RSMFRSD58761` 121,471,327,158.97 / 10,904,256 / 541 / 5.5628; `RSMFRSD86176` 105,048,689,266.66 / 11,105,945 / 685 / 5.4735; `RSMFRSD55940` 43,845,029,342.10 / 4,107,635 / 289 / 4.5509; `RSMFRSD89592` 28,305,748,426.46 / 2,799,899 / 185 / 4.6835; `RSMFRSD90335` 8,727,699,321.06 / 873,622 / 10 / 4.1348.
   - EUR (separate list): `RSMFRSD51436` 43,154,118.53 / 43,261 / 48 / 3.6302; `RSMFRSD66798` 38,485,549.00 / 41,120 / 19 / 2.4128; `RSMFRSD70022` 20,734,643.90 / 19,860 / 8 / 3.8982; `RSMFRSD84510` 19,348,117.50 / 19,000 / 7 / 3.5481; `RSMFRSD68802` 18,076,263.44 / 17,992 / 14 / 3.9726.

B. **Yield by year and remaining-maturity bucket** — filter: currency RSD, trade date up to 2022-12-31; dimensions `[date_year, remaining_bucket]`; measure `[weighted_yield]`; sort by group asc. First rows in natural bucket order: `2020 / 0-1Y` 1.5359, `2020 / 1-3Y` 2.0573, `2020 / 3-5Y` 2.3980, `2020 / 5-10Y` 2.9846, `2020 / 10Y+` 3.8285, `2021 / 0-1Y` 1.0443.

C. **Group counts** — worst case `[date_day, isin]` over the whole seed has 5,028 groups, so the 5000 per-currency cap is enough for the seed but can bind on long periods; truncation must be reported, never silent.

## 11. Assumptions to confirm

1. "Sold" is interpreted as "traded" (turnover, quantity, transactions); there is no buyer/seller side in the source.
2. `limit` ("top N") applies per currency.
3. Currency is always an implicit grouping and cannot be turned off.
4. Maximum 2 dimensions and 4 measures; no calculated measures in this version.
5. Saved queries store the builder state together with the filters.
6. Multi-visual dashboards and click-to-filter are a possible later step, not part of this one.
