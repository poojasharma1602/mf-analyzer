"""Unit tests for app.analytics using small series whose answers are verified by hand.

Hand calculations are shown next to each test so they can be re-checked independently.
"""
import math

import numpy as np
import pandas as pd
import pytest

from app import analytics as A
from app.analytics import AnalysisSettings, MetricError


# ----------------------------------------------------------------------------
# annual -> monthly conversion
# ----------------------------------------------------------------------------
def test_annual_to_monthly_round_trips():
    m = A.annual_to_monthly(0.12)
    assert (1 + m) ** 12 == pytest.approx(1.12, rel=1e-12)
    assert m == pytest.approx(0.009488792934583046, rel=1e-9)


def test_annual_to_monthly_zero_and_invalid():
    assert A.annual_to_monthly(0.0) == 0.0
    with pytest.raises(ValueError):
        A.annual_to_monthly(-1.0)


# ----------------------------------------------------------------------------
# CAGR
# ----------------------------------------------------------------------------
def _nav(points):
    return pd.Series([v for _, v in points], index=pd.to_datetime([d for d, _ in points]), dtype=float)


def test_cagr_known_value_four_years():
    # 2020-01-01 -> 2024-01-01 is exactly 1461 days = 4 x 365.25. NAV doubles => 2^(1/4) - 1.
    nav = _nav([("2020-01-01", 100.0), ("2022-01-01", 140.0), ("2024-01-01", 200.0)])
    res = A.cagr(nav, years=4)
    assert res.value == pytest.approx(2 ** 0.25 - 1, rel=1e-12)
    assert str(res.start_date.date()) == "2020-01-01"
    assert str(res.end_date.date()) == "2024-01-01"


def test_cagr_uses_actual_dates_not_year_count():
    # 3 years back from 2026-11-15 is 2023-11-15 (1096 days incl. 29-Feb-2024). 100 -> 133.1.
    nav = _nav([("2023-11-15", 100.0), ("2025-01-01", 115.0), ("2026-11-15", 133.1)])
    res = A.cagr(nav, years=3)
    assert res.value == pytest.approx(1.331 ** (365.25 / 1096) - 1, rel=1e-12)


def test_cagr_start_falls_back_to_previous_nav_within_tolerance():
    # target = 2023-11-15 (Wednesday); no NAV that day, last NAV on or before is 2023-11-13.
    nav = _nav([("2023-11-13", 100.0), ("2023-11-16", 101.0), ("2026-11-15", 150.0)])
    res = A.cagr(nav, years=3)
    assert str(res.start_date.date()) == "2023-11-13"
    days = (pd.Timestamp("2026-11-15") - pd.Timestamp("2023-11-13")).days
    assert res.value == pytest.approx(1.5 ** (365.25 / days) - 1, rel=1e-12)


def test_cagr_insufficient_history_is_na():
    nav = _nav([("2024-06-01", 100.0), ("2026-11-15", 150.0)])
    with pytest.raises(MetricError, match="after the 3-year start date"):
        A.cagr(nav, years=3)


def test_cagr_gap_before_target_is_na():
    # Only NAV before the target is 40 days earlier -> outside the 7-day tolerance.
    nav = _nav([("2023-10-01", 100.0), ("2024-01-01", 110.0), ("2026-11-15", 150.0)])
    with pytest.raises(MetricError, match="No NAV within"):
        A.cagr(nav, years=3)


# ----------------------------------------------------------------------------
# Sharpe
# ----------------------------------------------------------------------------
def test_sharpe_hand_calculated():
    # r = [1%, 3%, 2%, 4%], rf = 0.  mean = 2.5 %; deviations = -1.5,0.5,-0.5,1.5 (%)
    # sum sq = 5e-4, sample var = 5e-4/3, sd = 0.0129099.  Sharpe_m = 0.025/0.0129099 = 1.936492.
    # annualised = 1.936492 * sqrt(12) = 6.708204 (= 3 * sqrt(5)).
    r = [0.01, 0.03, 0.02, 0.04]
    assert A.sharpe_ratio(r, 0.0, min_obs=4) == pytest.approx(3 * math.sqrt(5), rel=1e-9)


def test_sharpe_subtracts_monthly_rf():
    r = np.array([0.01, 0.03, 0.02, 0.04])
    rf_m = 0.005
    ex = r - rf_m
    expected = ex.mean() / ex.std(ddof=1) * math.sqrt(12)
    assert A.sharpe_ratio(r, rf_m, min_obs=4) == pytest.approx(expected, rel=1e-12)
    # excess returns have mean 2%, same sd => 0.02/0.0129099*sqrt(12) = 5.366563
    assert expected == pytest.approx(5.3665631, rel=1e-6)


def test_sharpe_zero_volatility_and_insufficient():
    with pytest.raises(MetricError, match="Zero volatility"):
        A.sharpe_ratio([0.01] * 6, 0.0, min_obs=4)
    with pytest.raises(MetricError, match="Insufficient data"):
        A.sharpe_ratio([0.01, 0.02], 0.0, min_obs=24)


# ----------------------------------------------------------------------------
# Sortino
# ----------------------------------------------------------------------------
def test_sortino_hand_calculated():
    # r = [2%, -1%, 3%, -2%], MAR = 0. mean = 0.5 %.
    # shortfalls = [0,-1%,0,-2%]; mean sq over N=4 = (1e-4+4e-4)/4 = 1.25e-4; dd = 0.01118034.
    # Sortino_m = 0.005/0.01118034 = 0.4472136; annualised = *sqrt(12) = 1.549193 (= sqrt(2.4)).
    r = [0.02, -0.01, 0.03, -0.02]
    assert A.downside_deviation(r, 0.0) == pytest.approx(math.sqrt(1.25e-4), rel=1e-12)
    assert A.sortino_ratio(r, 0.0, min_obs=4) == pytest.approx(math.sqrt(2.4), rel=1e-9)


def test_sortino_uses_mar():
    r = np.array([0.02, -0.01, 0.03, -0.02])
    mar = 0.01
    sf = np.minimum(r - mar, 0)
    dd = math.sqrt(np.mean(sf ** 2))
    expected = (r.mean() - mar) / dd * math.sqrt(12)
    assert A.sortino_ratio(r, mar, min_obs=4) == pytest.approx(expected, rel=1e-12)


def test_sortino_no_downside_is_na():
    with pytest.raises(MetricError, match="zero downside"):
        A.sortino_ratio([0.01, 0.02, 0.03, 0.04], 0.0, min_obs=4)


# ----------------------------------------------------------------------------
# Beta / Jensen's alpha
# ----------------------------------------------------------------------------
BENCH = np.array([0.01, -0.02, 0.03, 0.00, 0.02])


def test_beta_exact_linear_relation():
    fund = 1.5 * BENCH + 0.001
    assert A.beta(fund, BENCH, min_obs=5) == pytest.approx(1.5, rel=1e-12)


def test_beta_matches_regression_slope():
    fund = np.array([0.02, -0.03, 0.05, 0.01, 0.015])
    slope = np.polyfit(BENCH, fund, 1)[0]
    assert A.beta(fund, BENCH, min_obs=5) == pytest.approx(slope, rel=1e-10)


def test_beta_zero_benchmark_variance_and_length_mismatch():
    with pytest.raises(MetricError, match="variance is zero"):
        A.beta([0.01, 0.02, 0.03, 0.01], [0.01] * 4, min_obs=4)
    with pytest.raises(MetricError, match="differ in length"):
        A.beta([0.01, 0.02, 0.03], [0.01, 0.02], min_obs=2)


def test_jensens_alpha_with_zero_rf():
    # fund = 0.001 + 1.5*bench  =>  beta 1.5, monthly alpha = 0.001, annual alpha = 0.012
    fund = 1.5 * BENCH + 0.001
    assert A.jensens_alpha(fund, BENCH, 0.0, min_obs=5) == pytest.approx(0.012, rel=1e-10)


def test_jensens_alpha_with_rf():
    # alpha_m = (mean(f)-rf) - beta*(mean(b)-rf) = 0.001 + (1-1.5)*(-rf)... verify numerically by hand:
    # mean(b) = 0.008; mean(f) = 1.5*0.008+0.001 = 0.013; rf_m = 0.004
    # alpha_m = (0.013-0.004) - 1.5*(0.008-0.004) = 0.009 - 0.006 = 0.003; annual = 0.036
    fund = 1.5 * BENCH + 0.001
    assert A.jensens_alpha(fund, BENCH, 0.004, min_obs=5) == pytest.approx(0.036, rel=1e-10)


# ----------------------------------------------------------------------------
# Information ratio
# ----------------------------------------------------------------------------
def test_information_ratio_hand_calculated():
    # active = [1%,2%,0%,1%,1%]: mean 1 %, deviations [0,1,-1,0,0]% => sum sq 2e-4, var 5e-5, sd 0.00707107
    # IR = (0.01*12)/(0.00707107*sqrt(12)) = 0.01/0.00707107*sqrt(12) = 4.898979 (= sqrt(24))
    active = np.array([0.01, 0.02, 0.0, 0.01, 0.01])
    fund = BENCH + active
    res = A.information_ratio(fund, BENCH, min_obs=5)
    assert res.value == pytest.approx(math.sqrt(24), rel=1e-9)
    assert res.active_return_annual == pytest.approx(0.12, rel=1e-12)
    assert res.tracking_error_annual == pytest.approx(0.00707107 * math.sqrt(12), rel=1e-6)


def test_information_ratio_zero_tracking_error():
    with pytest.raises(MetricError, match="Tracking error is zero"):
        A.information_ratio(BENCH + 0.01, BENCH, min_obs=5)


# ----------------------------------------------------------------------------
# Volatility / drawdown
# ----------------------------------------------------------------------------
def test_volatility_hand_calculated():
    # sd of [1,3,2,4]% = 0.0129099; * sqrt(12) = 0.0447214 (= sqrt(0.002))
    assert A.annualized_volatility([0.01, 0.03, 0.02, 0.04], min_obs=4) == pytest.approx(math.sqrt(0.002), rel=1e-9)


def test_max_drawdown_hand_calculated():
    # peak 120 -> trough 80 = -33.333 %; (earlier 120 -> 90 is only -25 %)
    assert A.max_drawdown([100, 120, 90, 110, 80, 130]) == pytest.approx(-1 / 3, rel=1e-12)


def test_max_drawdown_monotonic_rise_is_zero():
    assert A.max_drawdown([1, 2, 3, 4]) == 0.0


def test_max_drawdown_invalid():
    with pytest.raises(MetricError):
        A.max_drawdown([100])
    with pytest.raises(MetricError):
        A.max_drawdown([100, 0, 50])


# ----------------------------------------------------------------------------
# Monthly resampling / alignment
# ----------------------------------------------------------------------------
def _daily(start, end, f):
    idx = pd.bdate_range(start, end)
    return pd.Series([f(i) for i in range(len(idx))], index=idx, dtype=float)


def test_to_monthly_uses_last_observation_of_each_month():
    s = _nav([("2024-01-10", 1.0), ("2024-01-31", 2.0), ("2024-02-15", 3.0), ("2024-02-29", 4.0), ("2024-03-28", 5.0)])
    m = A.to_monthly(s)
    assert list(m.values) == [2.0, 4.0, 5.0]
    assert [str(p) for p in m.index] == ["2024-01", "2024-02", "2024-03"]


def test_to_monthly_drops_open_final_month():
    s = _nav([("2024-01-31", 2.0), ("2024-02-29", 4.0), ("2024-03-12", 5.0)])
    m = A.to_monthly(s)
    assert [str(p) for p in m.index] == ["2024-01", "2024-02"]
    m_keep = A.to_monthly(s, drop_incomplete=False)
    assert [str(p) for p in m_keep.index] == ["2024-01", "2024-02", "2024-03"]


def test_to_monthly_keeps_final_month_ending_on_last_business_days():
    # 2024-03-29 is a Friday (31st is a Sunday): within the 4-day grace => month is complete
    s = _nav([("2024-02-29", 4.0), ("2024-03-29", 5.0)])
    assert [str(p) for p in A.to_monthly(s).index] == ["2024-02", "2024-03"]


def test_window_returns_missing_month_yields_nan_not_bridge():
    m = pd.Series([100.0, 110.0, 132.0], index=pd.PeriodIndex(["2024-01", "2024-02", "2024-04"], freq="M"))
    r = A.window_returns(m, pd.Period("2024-04", "M"), 3)
    # months 2024-02, 03, 04 -> returns: Feb = 10 %, Mar = NaN (missing level), Apr = NaN (prev missing)
    assert r.iloc[0] == pytest.approx(0.10)
    assert r.iloc[1:].isna().all()


# ----------------------------------------------------------------------------
# End-to-end on a synthetic series
# ----------------------------------------------------------------------------
def _synthetic_monthly_nav(returns, start="2021-01-31"):
    """Daily NAV whose month-end values follow `returns` exactly (flat inside each month)."""
    ends = pd.date_range(start, periods=len(returns) + 1, freq="ME")
    lvl = [100.0]
    for r in returns:
        lvl.append(lvl[-1] * (1 + r))
    rows = []
    for i, e in enumerate(ends):
        mid = e - pd.Timedelta(days=10)
        rows.append((mid, lvl[i]))
        rows.append((e, lvl[i]))
    s = pd.Series([v for _, v in rows], index=[d for d, _ in rows], dtype=float)
    return s[~s.index.duplicated(keep="last")].sort_index()


def test_compute_fund_metrics_end_to_end_matches_direct_formulas():
    rng = np.random.default_rng(7)
    bench_r = rng.normal(0.012, 0.04, 40)
    fund_r = 0.9 * bench_r + 0.002 + rng.normal(0, 0.01, 40)
    nav = _synthetic_monthly_nav(fund_r)
    bench_nav = _synthetic_monthly_nav(bench_r)
    bench_m = A.to_monthly(bench_nav)
    st = AnalysisSettings(rf_annual=0.06, mar_annual=0.0, window_months=36, min_obs=24)

    out = A.compute_fund_metrics(nav, st, bench_m)
    m = out["metrics"]
    f36, b36 = fund_r[-36:], bench_r[-36:]
    assert out["periods"]["fund"]["n_obs"] == 36
    assert out["periods"]["matched"]["n_obs"] == 36
    assert m["sharpe"]["value"] == pytest.approx(A.sharpe_ratio(f36, st.rf_monthly, 24), rel=1e-9)
    assert m["sortino"]["value"] == pytest.approx(A.sortino_ratio(f36, st.mar_monthly, 24), rel=1e-9)
    assert m["beta"]["value"] == pytest.approx(A.beta(f36, b36, 24), rel=1e-9)
    assert m["jensen_alpha"]["value"] == pytest.approx(A.jensens_alpha(f36, b36, st.rf_monthly, 24), rel=1e-9)
    assert m["information_ratio"]["value"] == pytest.approx(A.information_ratio(f36, b36, 24).value, rel=1e-9)
    assert m["volatility"]["value"] == pytest.approx(A.annualized_volatility(f36, 24), rel=1e-9)
    assert m["beta"]["value"] == pytest.approx(0.9, abs=0.2)
    assert len(out["chart"]) == 37 and out["chart"][0][1] == pytest.approx(100.0)


def test_compute_fund_metrics_without_benchmark_is_na_with_reason():
    nav = _synthetic_monthly_nav(np.full(40, 0.01) + np.random.default_rng(1).normal(0, 0.02, 40))
    out = A.compute_fund_metrics(nav, AnalysisSettings(), None, "Benchmark 'X' has not been imported")
    for k in ("beta", "jensen_alpha", "information_ratio"):
        assert out["metrics"][k]["value"] is None
        assert "has not been imported" in out["metrics"][k]["reason"]
    assert out["metrics"]["sharpe"]["value"] is not None


def test_compute_fund_metrics_short_history_is_na():
    nav = _synthetic_monthly_nav(np.random.default_rng(2).normal(0.01, 0.03, 10))
    out = A.compute_fund_metrics(nav, AnalysisSettings(min_obs=24), None)
    assert out["metrics"]["sharpe"]["value"] is None
    assert "Insufficient data" in out["metrics"]["sharpe"]["reason"]
    assert out["metrics"]["cagr_3y"]["value"] is None


def test_matched_window_requires_overlap():
    rng = np.random.default_rng(3)
    nav = _synthetic_monthly_nav(rng.normal(0.01, 0.03, 40))
    # benchmark covers only the first 12 months -> end = bench end, matched obs < min_obs
    bench_nav = _synthetic_monthly_nav(rng.normal(0.01, 0.03, 12))
    out = A.compute_fund_metrics(nav, AnalysisSettings(min_obs=24), A.to_monthly(bench_nav))
    assert out["metrics"]["beta"]["value"] is None
    assert "matched monthly observations" in out["metrics"]["beta"]["reason"]
