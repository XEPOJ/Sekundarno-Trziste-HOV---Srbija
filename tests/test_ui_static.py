from fastapi.testclient import TestClient

from securities_analyzer.api.app import create_app


def test_ui_is_served_with_required_assets(db_path):
    c = TestClient(create_app(db_path), base_url="http://127.0.0.1")
    html = c.get("/").text
    assert "Podaci: Narodna banka Srbije" in html
    for asset in ("styles.css", "app.js", "vendor/plotly.min.js"):
        assert asset in html
        assert c.get("/" + asset).status_code == 200
