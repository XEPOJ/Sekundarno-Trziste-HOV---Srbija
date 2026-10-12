# Securities Analyzer

Standalone Windows program for exploring NBS secondary-market trading of Serbian
government securities (2020 → today): multi-dimensional filters, interactive charts,
daily highest/lowest yields, CSV/XLSX export and an **Update base** button that pulls
fresh data from NBS onto your own machine. No server, no account.

**Analiza** mode is a small query builder on top of the same filters: group by up to 2 dimensions (security, day/week/month/quarter/year, maturity group, coupon, ...), pick up to 4 measures (turnover, quantity, transactions, weighted yield, ...), and show them as a bar, line, scatter, heatmap or table, optionally limited to the top N per currency. Currencies are never mixed: every result is split per currency. Results export to CSV/XLSX and the whole view (filters plus builder) can be saved and restored.

## Install (users)
1. Download `SecuritiesAnalyzer-windows.zip` from the latest GitHub Release and unzip it.
2. Run `SecuritiesAnalyzer.exe`.
3. Windows SmartScreen may warn about an unsigned app: "More info" → "Run anyway".
4. Press **Update base** from time to time. Your data lives in `%APPDATA%\SecuritiesAnalyzer\`.

The app needs the Microsoft Edge WebView2 runtime for its own window (it ships with Windows 11 and Edge). Without it, the app opens in your default browser instead and exits about 3 minutes after you close the browser tab.

## Run from source
    python -m venv .venv && .venv\Scripts\activate
    pip install -e ".[dev,desktop]"
    python -m securities_analyzer fetch-all data/raw
    python -m securities_analyzer build-seed data/raw data/seed.db
    python -m securities_analyzer
Without `data/seed.db` the app starts empty; press **Update base** to download everything.

## Develop
    python -m pytest -q     # real-data tests run when SA_RAW_DIR points at the yearly CSVs
    node --test tests_js/pivot_chart.test.js   # chart logic unit tests
The `httpx2` dev dependency exists because Starlette's TestClient prefers it.

## Notes
- Source: Narodna banka Srbije (webappcenter.nbs.rs). Check NBS terms of use before redistributing data.
- Each row is a *daily aggregate* per ISIN, not a single trade. Totals and weighted yields are always shown per currency.
- Plotly's PNG button may not save inside the app window; it works when the app falls back to the browser.
