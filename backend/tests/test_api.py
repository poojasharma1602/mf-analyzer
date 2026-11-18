"""API-level tests against a MOCK provider (see conftest.py). Covers the acceptance flows end to end."""
import io

import httpx
import pytest
from fastapi.testclient import TestClient
from openpyxl import load_workbook

from app.main import create_app
from tests.conftest import BASE_CODE, MockProvider, make_benchmark_csv

CODES = [BASE_CODE + i for i in range(20)]


# --- acceptance 1: search -------------------------------------------------------
def test_search_finds_funds_growth_first(client):
    r = client.get("/api/schemes", params={"search": "testco alpha"})
    assert r.status_code == 200
    body = r.json()
    assert body["total_matches"] == 25
    opts = [x["option"] for x in body["results"]]
    assert opts == sorted(opts, key=lambda o: {"growth": 0, "unknown": 1, "idcw": 2}[o])
    assert body["results"][0]["scheme_code"] and body["schemes_as_of"]
    assert body["warning"]  # only 26 schemes -> "list may be incomplete" warning is raised


def test_search_by_code_and_growth_only(client):
    r = client.get("/api/schemes", params={"search": str(BASE_CODE + 7)}).json()
    assert [x["scheme_code"] for x in r["results"]] == [BASE_CODE + 7]
    g = client.get("/api/schemes", params={"search": "alpha", "growth_only": True}).json()
    assert g["total_matches"] == 20 and all(x["option"] == "growth" for x in g["results"])


# --- acceptance 2: NAV via FastAPI ------------------------------------------------
def test_fund_endpoint_returns_validated_nav(client):
    r = client.get(f"/api/funds/{BASE_CODE + 1}")
    assert r.status_code == 200
    b = r.json()
    assert b["nav_points"] == len(b["nav"]) > 1000
    dates = [row[0] for row in b["nav"]]
    assert dates == sorted(dates)  # ascending after normalisation (provider sent newest-first)
    assert b["nav_as_of"] == dates[-1] and b["option"] == "growth"
    assert b["data_status"]["from_cache"] is False


def test_fund_not_found_is_404(client):
    r = client.get("/api/funds/1")
    assert r.status_code == 404 and r.json()["error"]["code"] == "FUND_NOT_FOUND"


def test_second_request_served_from_cache(client, provider):
    client.get(f"/api/funds/{BASE_CODE}")
    n = len(provider.calls)
    r = client.get(f"/api/funds/{BASE_CODE}")
    assert r.json()["data_status"]["from_cache"] is True and len(provider.calls) == n


# --- acceptance 3: NAV-based metrics ---------------------------------------------------
def test_analyze_single_fund_nav_metrics_and_benchmark_na(client):
    r = client.post("/api/analyze", json={"scheme_codes": [BASE_CODE + 1]})
    assert r.status_code == 200
    row = r.json()["results"][0]
    m = row["metrics"]
    for k in ("cagr_3y", "sharpe", "sortino", "volatility", "max_drawdown"):
        assert m[k]["value"] is not None, k
    for k in ("beta", "jensen_alpha", "information_ratio"):
        assert m[k]["value"] is None and "has not been imported" in m[k]["reason"]
    assert row["benchmark"]["source"] == "rule" and row["benchmark"]["imported"] is False
    assert row["periods"]["fund"]["n_obs"] == 36


def test_idcw_fund_gets_warning(client):
    row = client.post("/api/analyze", json={"scheme_codes": [BASE_CODE]}).json()["results"][0]  # i=0 -> IDCW
    assert row["option"] == "idcw" and any("IDCW" in w for w in row["warnings"])


# --- acceptance 4: 20 funds ----------------------------------------------------------------
def test_analyze_20_funds_and_limit(client):
    r = client.post("/api/analyze", json={"scheme_codes": CODES})
    assert r.status_code == 200
    res = r.json()["results"]
    assert len(res) == 20 and all("error" not in x for x in res)
    assert client.post("/api/analyze", json={"scheme_codes": CODES + [BASE_CODE + 20]}).status_code == 400


def test_one_bad_fund_does_not_break_comparison(client):
    res = client.post("/api/analyze", json={"scheme_codes": [BASE_CODE + 1, 12345]}).json()["results"]
    assert "metrics" in res[0] and res[1]["error"]["code"] == "FUND_NOT_FOUND"


# --- acceptance 5: benchmark import -----------------------------------------------------------
def test_benchmark_import_enables_beta_alpha_ir(client):
    csv = make_benchmark_csv()
    r = client.post(
        "/api/benchmarks/import",
        data={"name": "NIFTY 100 TRI"},
        files={"file": ("tri.csv", csv, "text/csv")},
    )
    assert r.status_code == 200, r.text
    assert r.json()["benchmark"]["n_points"] > 60
    # fund 0 is "Large Cap" category -> rule maps to NIFTY 100 TRI
    row = client.post("/api/analyze", json={"scheme_codes": [BASE_CODE]}).json()["results"][0]
    assert row["benchmark"] == {**row["benchmark"], "name": "NIFTY 100 TRI", "imported": True}
    m = row["metrics"]
    for k in ("beta", "jensen_alpha", "information_ratio", "tracking_error"):
        assert m[k]["value"] is not None, (k, m[k])
    assert row["periods"]["matched"]["n_obs"] >= 24


def test_benchmark_override_changes_mapping(client):
    client.post("/api/benchmarks/import", data={"name": "My Custom TRI"}, files={"file": ("t.csv", make_benchmark_csv(5), "text/csv")})
    assert client.put("/api/benchmarks/override", json={"scheme_code": BASE_CODE + 1, "benchmark_name": "my custom tri"}).status_code == 200
    row = client.post("/api/analyze", json={"scheme_codes": [BASE_CODE + 1]}).json()["results"][0]
    assert row["benchmark"]["source"] == "override" and row["benchmark"]["name"] == "My Custom TRI"
    assert row["metrics"]["beta"]["value"] is not None
    lst = client.get("/api/benchmarks").json()
    assert lst["benchmarks"][0]["name"] == "My Custom TRI" and lst["overrides"]


@pytest.mark.parametrize(
    "csv_text, expect",
    [
        (b"", "empty"),
        (b"Date,Index Value\n01-01-2024,abc\n", "Non-numeric"),
        (b"Date,Index Value\nnot-a-date,100\n", "parse every date"),
        (b"Foo,Bar,Baz\n1,2,3\n", "Expected columns"),
        (b"Date,Index Value\n01-01-2024,100\n02-01-2024,101\n", "at least 13"),
        (b"Date,Index Value\n01-01-2999,100\n", "future"),
    ],
)
def test_bad_benchmark_csv_is_rejected_with_clear_message(client, csv_text, expect):
    r = client.post("/api/benchmarks/import", data={"name": "X"}, files={"file": ("x.csv", csv_text, "text/csv")})
    assert r.status_code == 400 and expect.lower() in r.json()["detail"].lower()


@pytest.mark.parametrize("fmt", ["%Y-%m-%d", "%d/%m/%Y", "%d-%b-%Y"])
def test_benchmark_csv_date_formats(client, fmt):
    csv = make_benchmark_csv(fmt=fmt)
    r = client.post("/api/benchmarks/import", data={"name": "T"}, files={"file": ("t.csv", csv, "text/csv")})
    assert r.status_code == 200, r.text


def test_benchmark_csv_alternate_headers_and_thousands_separator(client):
    rows = ["Date,Close"] + [f"{(2023 + (m - 1) // 12)}-{((m - 1) % 12) + 1:02d}-28,\"{10000 + m * 37:,}.5\"" for m in range(1, 20)]
    r = client.post("/api/benchmarks/import", data={"name": "H"}, files={"file": ("h.csv", "\n".join(rows).encode(), "text/csv")})
    assert r.status_code == 200, r.text


# --- acceptance 6: export ---------------------------------------------------------------------------
def test_export_csv_and_xlsx(client):
    client.post("/api/benchmarks/import", data={"name": "NIFTY 100 TRI"}, files={"file": ("t.csv", make_benchmark_csv(), "text/csv")})
    body = {"scheme_codes": CODES[:6]}
    c = client.post("/api/export", params={"format": "csv"}, json=body)
    assert c.status_code == 200 and "attachment" in c.headers["content-disposition"]
    text = c.content.decode("utf-8-sig")
    assert text.splitlines()[0].startswith("Scheme Code,Scheme Name") and len(text.splitlines()) == 7

    x = client.post("/api/export", params={"format": "xlsx"}, json=body)
    assert x.status_code == 200
    wb = load_workbook(io.BytesIO(x.content))
    assert wb.sheetnames == ["Comparison", "Settings & Methodology"]
    ws = wb["Comparison"]
    headers = [c.value for c in ws[1]]
    assert "3Y CAGR (%)" in headers and "Jensen's Alpha (% p.a.)" in headers
    assert ws.max_row == 7


# --- acceptance 7: provider failures ---------------------------------------------------------------------
def test_provider_down_gives_helpful_error_and_no_cache(client, provider):
    provider.mode = "down"
    r = client.get("/api/schemes", params={"search": "alpha"})
    assert r.status_code == 503
    err = r.json()["error"]
    assert err["code"] == "PROVIDER_UNREACHABLE" and "internet connection" in err["message"]
    h = client.get("/api/health").json()
    assert h["provider"]["consecutive_failures"] >= 1 and h["provider"]["last_error"]["code"] == "PROVIDER_UNREACHABLE"


def test_analyze_with_provider_down_reports_per_fund_errors(client, provider):
    provider.mode = "down"
    r = client.post("/api/analyze", json={"scheme_codes": CODES[:2]})
    assert r.status_code == 200
    assert all(x["error"]["code"] == "PROVIDER_UNREACHABLE" for x in r.json()["results"])


def test_stale_cache_served_when_provider_goes_down(tmp_path, provider):
    app = create_app(db_path=tmp_path / "s.db", transport=httpx.MockTransport(provider), retry_backoff=0.0, nav_ttl_hours=0.0, schemes_ttl_hours=0.0)
    with TestClient(app) as c:
        assert c.get("/api/schemes", params={"search": "alpha"}).status_code == 200
        assert c.post("/api/analyze", json={"scheme_codes": [BASE_CODE + 1]}).json()["results"][0]["data_status"]["stale"] is False
        provider.mode = "down"
        s = c.get("/api/schemes", params={"search": "alpha"}).json()
        assert s["stale"] is True and s["results"]
        row = c.post("/api/analyze", json={"scheme_codes": [BASE_CODE + 1]}).json()["results"][0]
        assert row["data_status"]["stale"] is True and row["metrics"]["sharpe"]["value"] is not None
        assert any("cached data" in w for w in row["warnings"])


def test_rate_limit_is_retried(client, provider):
    provider.mode = "rate_limit_once"
    r = client.get(f"/api/funds/{BASE_CODE + 2}")
    assert r.status_code == 200
    assert provider.calls.count(f"/mf/{BASE_CODE + 2}") == 2


def test_persistent_server_error_and_bad_schema(client, provider):
    provider.mode = "server_error"
    r = client.get(f"/api/funds/{BASE_CODE + 3}")
    assert r.status_code == 503 and r.json()["error"]["code"] == "PROVIDER_HTTP_ERROR"
    provider.mode = "bad_schema"
    r = client.get(f"/api/funds/{BASE_CODE + 4}")
    assert r.status_code == 502 and r.json()["error"]["code"] == "PROVIDER_BAD_RESPONSE"


# --- persistence --------------------------------------------------------------------------------------------
def test_selection_and_settings_persist_across_restart(tmp_path, provider):
    kw = dict(db_path=tmp_path / "p.db", transport=httpx.MockTransport(provider), retry_backoff=0.0)
    with TestClient(create_app(**kw)) as c:
        assert c.put("/api/selection", json={"funds": [{"scheme_code": 1, "scheme_name": "A"}, {"scheme_code": 2, "scheme_name": "B"}]}).status_code == 200
        assert c.put("/api/settings", json={"rf_annual_pct": 7.25, "mar_annual_pct": 1.0, "window_months": 48, "min_obs": 30}).status_code == 200
    with TestClient(create_app(**kw)) as c2:
        assert [f["scheme_code"] for f in c2.get("/api/selection").json()["funds"]] == [1, 2]
        assert c2.get("/api/settings").json()["rf_annual_pct"] == 7.25


def test_settings_validation(client):
    assert client.put("/api/settings", json={"rf_annual_pct": 6, "mar_annual_pct": 0, "window_months": 24, "min_obs": 30}).status_code == 422
    assert client.put("/api/settings", json={"rf_annual_pct": -1, "mar_annual_pct": 0, "window_months": 36, "min_obs": 24}).status_code == 422
    too_many = [{"scheme_code": i, "scheme_name": "x"} for i in range(21)]
    assert client.put("/api/selection", json={"funds": too_many}).status_code == 400


def test_settings_change_results(client):
    a = client.post("/api/analyze", json={"scheme_codes": [BASE_CODE + 1], "settings": {"rf_annual_pct": 0, "mar_annual_pct": 0, "window_months": 36, "min_obs": 24}}).json()
    b = client.post("/api/analyze", json={"scheme_codes": [BASE_CODE + 1], "settings": {"rf_annual_pct": 10, "mar_annual_pct": 0, "window_months": 36, "min_obs": 24}}).json()
    assert a["results"][0]["metrics"]["sharpe"]["value"] > b["results"][0]["metrics"]["sharpe"]["value"]
    # minimum sample threshold -> N/A
    c = client.post("/api/analyze", json={"scheme_codes": [BASE_CODE + 1], "settings": {"rf_annual_pct": 6, "mar_annual_pct": 0, "window_months": 12, "min_obs": 12}}).json()
    assert c["results"][0]["periods"]["fund"]["n_obs"] == 12


def test_health_and_methodology(client):
    h = client.get("/api/health").json()
    assert h["status"] == "ok" and h["database"]["ok"] is True
    assert client.get("/api/methodology").json()["sections"]


def test_cors_only_for_local_frontend(client):
    ok = client.options("/api/health", headers={"Origin": "http://localhost:5173", "Access-Control-Request-Method": "GET"})
    assert ok.headers.get("access-control-allow-origin") == "http://localhost:5173"
    bad = client.options("/api/health", headers={"Origin": "https://evil.example", "Access-Control-Request-Method": "GET"})
    assert "access-control-allow-origin" not in bad.headers


def test_name_rules_map_index_etfs():
    from app import benchmarks as B
    m = B.load_mapping()
    assert B.suggest_benchmark("HDFC NIFTY Midcap 150 ETF - Growth Option", "Other Scheme - Other ETFs", m) == "NIFTY MIDCAP 150 TRI"
    assert B.suggest_benchmark("X Nifty 500 Index Fund", "Other Scheme - Index Funds", m) == "NIFTY 500 TRI"
    assert B.suggest_benchmark("X Nifty 50 Index Fund", "", m) == "NIFTY 50 TRI"
    assert B.suggest_benchmark("X Nifty Next 50 Index", "", m) == "NIFTY NEXT 50 TRI"
