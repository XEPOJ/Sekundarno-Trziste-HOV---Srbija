from fastapi.testclient import TestClient

from securities_analyzer.api.app import create_app


def test_ui_is_served_with_required_assets(db_path):
    c = TestClient(create_app(db_path), base_url="http://127.0.0.1")
    html = c.get("/").text
    assert "Podaci: Narodna banka Srbije" in html
    for asset in ("styles.css", "app.js", "vendor/plotly.min.js"):
        assert asset in html
        assert c.get("/" + asset).status_code == 200


def test_ui_has_dynamic_currency_slot_and_no_settlement_lag_filter(db_path):
    c = TestClient(create_app(db_path), base_url="http://127.0.0.1")
    html = c.get("/").text
    assert 'data-range="settlement_lag_days"' not in html
    assert 'id="currency-list"' in html and 'value="RSD"' not in html


def test_sidebar_has_the_range_filters_and_the_per_security_table(db_path):
    c = TestClient(create_app(db_path), base_url="http://127.0.0.1")
    html = c.get("/").text
    for key in ("quantity", "turnover", "min_price", "max_price", "remaining_maturity_years", "yield_pct"):
        assert f'data-range="{key}"' in html, key
    for needle in ('id="rem-unit"', 'value="days"', 'id="sec-rows"', 'id="sec-section"'):
        assert needle in html, needle
    assert 'id="turnover_min"' not in html                    # replaced by "Ukupni promet" od-do
    js = c.get("/app.js").text
    assert "/api/query/securities" in js and "remaining_maturity_days" in js


def test_ui_script_sends_heartbeat(db_path):
    c = TestClient(create_app(db_path), base_url="http://127.0.0.1")
    assert "/api/heartbeat" in c.get("/app.js").text


def test_analysis_assets_and_mode_switch_are_served(db_path):
    c = TestClient(create_app(db_path), base_url="http://127.0.0.1")
    html = c.get("/").text
    for needle in ('id="mode-overview"', 'id="mode-analysis"', 'id="view-overview"',
                   'id="view-analysis"', "pivot_chart.js", "analysis.js"):
        assert needle in html, needle
    for asset in ("pivot_chart.js", "analysis.js"):
        r = c.get("/" + asset)
        assert r.status_code == 200 and len(r.text) > 500
    assert html.index("pivot_chart.js") < html.index("analysis.js") < html.index("app.js")


def test_isin_picker_markup_and_script_order(db_path):
    c = TestClient(create_app(db_path), base_url="http://127.0.0.1")
    html = c.get("/").text
    for needle in ('id="isin-search"', 'id="isin"', 'id="isin-all"', 'id="isin-none"', 'id="isin-count"', "isin_filter.js"):
        assert needle in html, needle
    r = c.get("/isin_filter.js")
    assert r.status_code == 200 and "IsinFilter" in r.text
    assert html.index("isin_filter.js") < html.index("app.js")
