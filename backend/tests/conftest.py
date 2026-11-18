"""Test fixtures.

IMPORTANT: the "provider" here is a MOCK built from synthetic random walks, injected through
httpx.MockTransport. These tests prove the application logic (validation, retries, caching,
fallbacks, endpoints, export). They do NOT prove that the real api.mfapi.in matches the
response shapes assumed here - that can only be verified with live network access.
"""
import io
from datetime import date, timedelta

import httpx
import numpy as np
import pandas as pd
import pytest
from fastapi.testclient import TestClient

from app.main import create_app

N_FUNDS = 25
BASE_CODE = 900000
CATEGORIES = [
    "Equity Scheme - Large Cap Fund",
    "Equity Scheme - Mid Cap Fund",
    "Equity Scheme - Small Cap Fund",
    "Equity Scheme - Flexi Cap Fund",
    "Equity Scheme - Large & Mid Cap Fund",
]


def business_days_ending_recently(years=5.5):
    end = pd.Timestamp(date.today()) - pd.Timedelta(days=1)
    # last business day not after yesterday, and make sure the last month is "complete" is NOT assumed
    end = pd.bdate_range(end=end, periods=1)[0]
    return pd.bdate_range(end=end, periods=int(252 * years))


def make_nav_series(seed: int, idx: pd.DatetimeIndex, drift=0.0004, vol=0.009):
    rng = np.random.default_rng(seed)
    rets = rng.normal(drift, vol, len(idx))
    return 10.0 * np.cumprod(1 + rets)


def scheme_list_payload():
    rows = []
    for i in range(N_FUNDS):
        opt = "Growth" if i % 5 else "IDCW"
        rows.append({"schemeCode": BASE_CODE + i, "schemeName": f"Testco Alpha Fund {i:02d} - Direct Plan - {opt}"})
    rows.append({"schemeCode": 800001, "schemeName": "Testco Bond Fund - Regular Plan - Growth"})
    return rows


def nav_payload(code: int):
    i = code - BASE_CODE
    idx = business_days_ending_recently()
    navs = make_nav_series(100 + i, idx)
    opt = "Growth" if i % 5 else "IDCW"
    return {
        "meta": {
            "fund_house": "Testco Mutual Fund",
            "scheme_type": "Open Ended Schemes",
            "scheme_category": CATEGORIES[i % len(CATEGORIES)],
            "scheme_code": code,
            "scheme_name": f"Testco Alpha Fund {i:02d} - Direct Plan - {opt}",
        },
        "data": [
            {"date": d.strftime("%d-%m-%Y"), "nav": f"{v:.5f}"} for d, v in zip(idx[::-1], navs[::-1])
        ],  # provider returns newest first
        "status": "SUCCESS",
    }


class MockProvider:
    """Callable httpx handler with switchable failure modes and a request log."""

    def __init__(self):
        self.mode = "ok"  # ok | down | rate_limit_once | bad_schema | server_error
        self.calls = []
        self._rate_limited = set()

    def __call__(self, request: httpx.Request) -> httpx.Response:
        path = request.url.path
        self.calls.append(path)
        if self.mode == "down":
            raise httpx.ConnectError("simulated: provider unreachable", request=request)
        if self.mode == "server_error":
            return httpx.Response(503, text="Service Unavailable")
        if self.mode == "rate_limit_once" and path not in self._rate_limited:
            self._rate_limited.add(path)
            return httpx.Response(429, headers={"Retry-After": "0"}, text="slow down")
        if self.mode == "bad_schema":
            return httpx.Response(200, json={"unexpected": True})
        if path == "/mf":
            return httpx.Response(200, json=scheme_list_payload())
        if path.startswith("/mf/"):
            try:
                code = int(path.split("/")[-1])
            except ValueError:
                return httpx.Response(404, json={"status": "ERROR"})
            if BASE_CODE <= code < BASE_CODE + N_FUNDS:
                return httpx.Response(200, json=nav_payload(code))
            return httpx.Response(404, json={"status": "ERROR"})
        return httpx.Response(404, text="not found")


@pytest.fixture
def provider():
    return MockProvider()


@pytest.fixture
def client(tmp_path, provider):
    app = create_app(
        db_path=tmp_path / "test.db",
        transport=httpx.MockTransport(provider),
        base_url="https://mock.invalid",
        retry_backoff=0.0,
    )
    with TestClient(app) as c:
        yield c


def make_benchmark_csv(codes_seed=999, years=5.5, fmt="%d-%m-%Y", header="Date,Index Value", month_end_only=True):
    idx = business_days_ending_recently(years)
    vals = make_nav_series(codes_seed, idx, drift=0.00045, vol=0.008) * 1000
    s = pd.Series(vals, index=idx)
    if month_end_only:
        # one row per month, dated on the last business day of that month
        values = list(s.groupby(s.index.to_period("M")).last().values)
        dates = list(pd.Series(idx, index=idx).groupby(idx.to_period("M")).last().values)
    else:
        dates, values = list(idx), list(vals)
    buf = io.StringIO()
    buf.write(header + "\n")
    for d, v in zip(dates, values):
        buf.write(f"{pd.Timestamp(d).strftime(fmt)},{v:.2f}\n")
    return buf.getvalue().encode("utf-8")
