"""Regression: user imports ONE benchmark (NIFTY 500 TRI) while the rule maps the fund to another."""
from tests.conftest import BASE_CODE, make_benchmark_csv


def _import(client, name, seed=3):
    r = client.post("/api/benchmarks/import", data={"name": name}, files={"file": ("t.csv", make_benchmark_csv(seed), "text/csv")})
    assert r.status_code == 200, r.text


def test_single_imported_benchmark_is_used_as_fallback(client):
    _import(client, "NIFTY 500 TRI")
    # fund index 1 -> Mid Cap category -> rule says NIFTY MIDCAP 150 TRI (not imported)
    row = client.post("/api/analyze", json={"scheme_codes": [BASE_CODE + 1]}).json()["results"][0]
    assert row["benchmark"]["name"] == "NIFTY 500 TRI" and row["benchmark"]["source"] == "default"
    for k in ("beta", "jensen_alpha", "information_ratio"):
        assert row["metrics"][k]["value"] is not None, (k, row["metrics"][k])
    assert any("not the fund's mapped benchmark" in w for w in row["warnings"])


def test_explicit_default_wins_when_several_imported(client):
    _import(client, "NIFTY 500 TRI", 3)
    _import(client, "NIFTY 50 TRI", 4)
    row = client.post("/api/analyze", json={"scheme_codes": [BASE_CODE + 1]}).json()["results"][0]
    assert row["metrics"]["beta"]["value"] is None  # ambiguous -> no silent guess
    assert client.put("/api/benchmarks/default", json={"benchmark_name": "nifty 500 tri"}).status_code == 200
    row = client.post("/api/analyze", json={"scheme_codes": [BASE_CODE + 1]}).json()["results"][0]
    assert row["benchmark"]["name"] == "NIFTY 500 TRI" and row["metrics"]["beta"]["value"] is not None


def test_mapped_benchmark_still_preferred_when_imported(client):
    _import(client, "NIFTY 500 TRI", 3)
    _import(client, "NIFTY MIDCAP 150 TRI", 5)
    row = client.post("/api/analyze", json={"scheme_codes": [BASE_CODE + 1]}).json()["results"][0]
    assert row["benchmark"]["name"] == "NIFTY MIDCAP 150 TRI" and row["benchmark"]["source"] == "rule"
