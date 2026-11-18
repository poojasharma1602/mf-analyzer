"""Pure analytics functions (no network, no database).

Conventions (see methodology.py for the user-facing text):
  * Monthly series use the LAST available observation in each calendar month.
    The final calendar month is dropped if its last observation is more than
    INCOMPLETE_MONTH_GRACE_DAYS before month end (i.e. the month is still open).
  * Monthly return r_t = V_t / V_{t-1} - 1 for consecutive calendar months only.
    A missing month produces no return (it is never filled or bridged).
  * Annualisation: ratios x sqrt(12); alpha and active return x 12 (arithmetic).
  * Annual -> monthly rate conversion is geometric: (1 + R)^(1/12) - 1.
  * Sample (ddof=1) standard deviation / variance / covariance everywhere,
    except Sortino downside deviation which uses the conventional
    sqrt(mean(min(r - MAR, 0)^2)) over all N observations.
All metrics return None + a reason (via MetricError) instead of guessing.
"""
from __future__ import annotations

import math
from dataclasses import dataclass
from typing import Callable, Optional, Sequence

import numpy as np
import pandas as pd

MONTHS_PER_YEAR = 12
SQRT_12 = math.sqrt(12.0)
DAYS_PER_YEAR = 365.25
INCOMPLETE_MONTH_GRACE_DAYS = 4
CAGR_START_TOLERANCE_DAYS = 7
MIN_ABSOLUTE_OBS = 3  # std/variance need at least this many points to mean anything


class MetricError(Exception):
    """A metric cannot be computed; the message is shown to the user as the N/A reason."""


@dataclass(frozen=True)
class AnalysisSettings:
    rf_annual: float = 0.06  # decimal, e.g. 0.06 == 6 %
    mar_annual: float = 0.0  # minimum acceptable return, decimal
    window_months: int = 36
    min_obs: int = 24

    @property
    def rf_monthly(self) -> float:
        return annual_to_monthly(self.rf_annual)

    @property
    def mar_monthly(self) -> float:
        return annual_to_monthly(self.mar_annual)


def annual_to_monthly(annual_rate: float) -> float:
    if annual_rate <= -1:
        raise ValueError("annual rate must be greater than -100 %")
    return (1.0 + annual_rate) ** (1.0 / MONTHS_PER_YEAR) - 1.0


# ----------------------------------------------------------------------------
# Series helpers
# ----------------------------------------------------------------------------
def to_monthly(series: pd.Series, drop_incomplete: bool = True) -> pd.Series:
    """Daily/irregular series (DatetimeIndex) -> last observation per calendar month (PeriodIndex)."""
    if series is None or len(series) == 0:
        return pd.Series(dtype=float, index=pd.PeriodIndex([], freq="M"))
    s = series.sort_index()
    periods = s.index.to_period("M")
    df = pd.DataFrame({"v": s.to_numpy(dtype=float), "d": s.index}, index=periods)
    last = df.groupby(level=0).last()
    monthly = last["v"].astype(float)
    if drop_incomplete:
        final_date = last["d"].iloc[-1]
        month_end = monthly.index[-1].end_time.normalize()
        if (month_end - final_date.normalize()).days > INCOMPLETE_MONTH_GRACE_DAYS:
            monthly = monthly.iloc[:-1]
    return monthly


def window_returns(monthly: pd.Series, end: pd.Period, window: int) -> pd.Series:
    """Simple monthly returns for the `window` months ending at `end` (NaN where a month is missing)."""
    levels = monthly.reindex(pd.period_range(end - window, end, freq="M"))
    rets = levels / levels.shift(1) - 1.0
    rets = rets.replace([np.inf, -np.inf], np.nan)
    return rets.iloc[1:]


def _require(n: int, min_obs: int, what: str = "monthly observations") -> None:
    need = max(int(min_obs), MIN_ABSOLUTE_OBS)
    if n < need:
        raise MetricError(f"Insufficient data: {n} {what} (minimum {need})")


def _arr(x) -> np.ndarray:
    a = np.asarray(x, dtype=float)
    if a.ndim != 1:
        raise MetricError("expected a one-dimensional return series")
    if not np.all(np.isfinite(a)):
        raise MetricError("return series contains non-finite values")
    return a


def _finite(v: float, what: str) -> float:
    if v is None or not np.isfinite(v):
        raise MetricError(f"{what} is not finite")
    return float(v)


# ----------------------------------------------------------------------------
# Individual metrics
# ----------------------------------------------------------------------------
@dataclass(frozen=True)
class CagrResult:
    value: float
    start_date: pd.Timestamp
    end_date: pd.Timestamp
    start_nav: float
    end_nav: float


def cagr(nav: pd.Series, years: int = 3, tolerance_days: int = CAGR_START_TOLERANCE_DAYS) -> CagrResult:
    """CAGR from actual dates: (end/start)^(365.25/days) - 1.

    The start observation is the last NAV on or before (latest date - `years` years)
    and must lie within `tolerance_days` of that target date.
    """
    if nav is None or len(nav) < 2:
        raise MetricError("Insufficient NAV history")
    s = nav.sort_index()
    idx = s.index
    end_date = idx[-1]
    end_nav = float(s.iloc[-1])
    target = end_date - pd.DateOffset(years=int(years))
    pos = int(idx.searchsorted(target, side="right")) - 1
    if pos < 0:
        raise MetricError(
            f"NAV history starts {idx[0].date()}, after the {years}-year start date {target.date()}"
        )
    start_date = idx[pos]
    if (target - start_date).days > tolerance_days:
        raise MetricError(
            f"No NAV within {tolerance_days} days before {target.date()} (nearest earlier NAV: {start_date.date()})"
        )
    start_nav = float(s.iloc[pos])
    days = (end_date - start_date).days
    if days <= 0:
        raise MetricError("Start and end dates coincide")
    if start_nav <= 0 or end_nav <= 0:
        raise MetricError("Non-positive NAV encountered")
    value = _finite((end_nav / start_nav) ** (DAYS_PER_YEAR / days) - 1.0, "CAGR")
    return CagrResult(value, start_date, end_date, start_nav, end_nav)


def sharpe_ratio(returns, rf_monthly: float, min_obs: int) -> float:
    r = _arr(returns)
    _require(len(r), min_obs)
    ex = r - rf_monthly
    sd = ex.std(ddof=1)
    if not np.isfinite(sd) or sd <= 1e-12:
        raise MetricError("Zero volatility of excess returns")
    return _finite(ex.mean() / sd * SQRT_12, "Sharpe ratio")


def downside_deviation(returns, mar_monthly: float) -> float:
    r = _arr(returns)
    shortfall = np.minimum(r - mar_monthly, 0.0)
    return float(math.sqrt(np.mean(shortfall ** 2)))


def sortino_ratio(returns, mar_monthly: float, min_obs: int) -> float:
    r = _arr(returns)
    _require(len(r), min_obs)
    dd = downside_deviation(r, mar_monthly)
    if dd <= 1e-12:
        raise MetricError("No monthly returns below the minimum acceptable return (zero downside deviation)")
    return _finite((r.mean() - mar_monthly) / dd * SQRT_12, "Sortino ratio")


def beta(fund_returns, bench_returns, min_obs: int) -> float:
    f, b = _arr(fund_returns), _arr(bench_returns)
    if len(f) != len(b):
        raise MetricError("Fund and benchmark return series differ in length")
    _require(len(f), min_obs, "matched monthly observations")
    var_b = b.var(ddof=1)
    if not np.isfinite(var_b) or var_b <= 1e-14:
        raise MetricError("Benchmark variance is zero")
    cov = np.cov(f, b, ddof=1)[0, 1]
    return _finite(cov / var_b, "Beta")


def jensens_alpha(fund_returns, bench_returns, rf_monthly: float, min_obs: int) -> float:
    """Annualised Jensen's alpha = 12 x [(mean(Rf) - rf) - beta x (mean(Rb) - rf)] (monthly CAPM, arithmetic annualisation)."""
    f, b = _arr(fund_returns), _arr(bench_returns)
    bt = beta(f, b, min_obs)
    alpha_m = (f.mean() - rf_monthly) - bt * (b.mean() - rf_monthly)
    return _finite(alpha_m * MONTHS_PER_YEAR, "Jensen's alpha")


@dataclass(frozen=True)
class InfoRatioResult:
    value: float
    active_return_annual: float
    tracking_error_annual: float


def information_ratio(fund_returns, bench_returns, min_obs: int) -> InfoRatioResult:
    f, b = _arr(fund_returns), _arr(bench_returns)
    if len(f) != len(b):
        raise MetricError("Fund and benchmark return series differ in length")
    _require(len(f), min_obs, "matched monthly observations")
    active = f - b
    te_m = active.std(ddof=1)
    if not np.isfinite(te_m) or te_m <= 1e-12:
        raise MetricError("Tracking error is zero")
    active_ann = active.mean() * MONTHS_PER_YEAR
    te_ann = te_m * SQRT_12
    return InfoRatioResult(_finite(active_ann / te_ann, "Information ratio"), float(active_ann), float(te_ann))


def annualized_volatility(returns, min_obs: int) -> float:
    r = _arr(returns)
    _require(len(r), min_obs)
    return _finite(r.std(ddof=1) * SQRT_12, "Volatility")


def max_drawdown(levels: Sequence[float]) -> float:
    """Largest peak-to-trough decline of a level series, as a negative fraction (e.g. -0.25)."""
    a = np.asarray(levels, dtype=float)
    if len(a) < 2:
        raise MetricError("Insufficient data for drawdown")
    if not np.all(np.isfinite(a)) or np.any(a <= 0):
        raise MetricError("Non-positive or non-finite level in series")
    peaks = np.maximum.accumulate(a)
    return float((a / peaks - 1.0).min())


# ----------------------------------------------------------------------------
# Orchestration
# ----------------------------------------------------------------------------
def _metric(fn: Callable[[], float]) -> dict:
    try:
        return {"value": float(fn()), "reason": None}
    except MetricError as exc:
        return {"value": None, "reason": str(exc)}


def _na(reason: str) -> dict:
    return {"value": None, "reason": reason}


METRIC_KEYS = [
    "cagr_3y",
    "sharpe",
    "sortino",
    "jensen_alpha",
    "beta",
    "information_ratio",
    "volatility",
    "max_drawdown",
    "tracking_error",
    "active_return",
]


def compute_fund_metrics(
    nav: pd.Series,
    settings: AnalysisSettings,
    bench_monthly: Optional[pd.Series] = None,
    bench_missing_reason: Optional[str] = None,
) -> dict:
    """Compute every metric for one fund.

    nav            daily NAV series with a DatetimeIndex (ascending)
    bench_monthly  monthly benchmark TRI (PeriodIndex) or None
    bench_missing_reason  why there is no benchmark (shown as the N/A reason)
    """
    metrics = {k: _na("Not computed") for k in METRIC_KEYS}
    periods: dict = {"fund": None, "matched": None, "cagr": None}
    chart: list = []

    # --- CAGR (daily NAV, actual dates) -------------------------------------
    try:
        c = cagr(nav, years=3)
        metrics["cagr_3y"] = {"value": c.value, "reason": None}
        periods["cagr"] = {"start": str(c.start_date.date()), "end": str(c.end_date.date())}
    except MetricError as exc:
        metrics["cagr_3y"] = _na(str(exc))

    # --- Fund-only monthly metrics ------------------------------------------
    monthly = to_monthly(nav)
    if len(monthly) >= 2:
        end = monthly.index[-1]
        rets = window_returns(monthly, end, settings.window_months).dropna()
        n = len(rets)
        periods["fund"] = {
            "start": str(rets.index[0]) if n else None,
            "end": str(end),
            "n_obs": n,
            "window_months": settings.window_months,
        }
        metrics["sharpe"] = _metric(lambda: sharpe_ratio(rets.to_numpy(), settings.rf_monthly, settings.min_obs))
        metrics["sortino"] = _metric(lambda: sortino_ratio(rets.to_numpy(), settings.mar_monthly, settings.min_obs))
        metrics["volatility"] = _metric(lambda: annualized_volatility(rets.to_numpy(), settings.min_obs))

        levels = monthly.reindex(pd.period_range(end - settings.window_months, end, freq="M")).dropna()
        def _mdd() -> float:
            _require(len(levels), settings.min_obs, "monthly NAV points")
            return max_drawdown(levels.to_numpy())

        metrics["max_drawdown"] = _metric(_mdd)
        if len(levels) >= 2:
            rebased = levels / levels.iloc[0] * 100.0
            chart = [[str(p), round(float(v), 4)] for p, v in rebased.items()]
    else:
        reason = "Insufficient NAV history for monthly analysis"
        for k in ("sharpe", "sortino", "volatility", "max_drawdown"):
            metrics[k] = _na(reason)

    # --- Benchmark-relative metrics -----------------------------------------
    bench_keys = ("jensen_alpha", "beta", "information_ratio", "tracking_error", "active_return")
    if bench_monthly is None or len(bench_monthly) < 2:
        reason = bench_missing_reason or "No benchmark TRI available"
        for k in bench_keys:
            metrics[k] = _na(reason)
    elif len(monthly) < 2:
        for k in bench_keys:
            metrics[k] = _na("Insufficient NAV history for monthly analysis")
    else:
        end = min(monthly.index[-1], bench_monthly.index[-1])
        rf_ = window_returns(monthly, end, settings.window_months)
        rb_ = window_returns(bench_monthly, end, settings.window_months)
        both = pd.concat([rf_, rb_], axis=1, keys=["f", "b"]).dropna()
        n = len(both)
        periods["matched"] = {
            "start": str(both.index[0]) if n else None,
            "end": str(end),
            "n_obs": n,
            "window_months": settings.window_months,
        }
        f_arr, b_arr = both["f"].to_numpy(), both["b"].to_numpy()
        # Make the actual blocker visible, rather than reporting an unexplained N/A.
        if n < max(settings.min_obs, MIN_ABSOLUTE_OBS):
            reason = (f"Insufficient data: {n} matched monthly observations; at least {max(settings.min_obs, MIN_ABSOLUTE_OBS)} "
                      f"required. Import longer benchmark history covering the fund NAV dates, "
                      f"or adjust Analysis settings (window/minimum observations).")
            for k in bench_keys:
                metrics[k] = _na(reason)
            return {"metrics": metrics, "periods": periods, "chart": chart}
        metrics["beta"] = _metric(lambda: beta(f_arr, b_arr, settings.min_obs))
        metrics["jensen_alpha"] = _metric(lambda: jensens_alpha(f_arr, b_arr, settings.rf_monthly, settings.min_obs))
        try:
            ir = information_ratio(f_arr, b_arr, settings.min_obs)
            metrics["information_ratio"] = {"value": ir.value, "reason": None}
            metrics["tracking_error"] = {"value": ir.tracking_error_annual, "reason": None}
            metrics["active_return"] = {"value": ir.active_return_annual, "reason": None}
        except MetricError as exc:
            for k in ("information_ratio", "tracking_error", "active_return"):
                metrics[k] = _na(str(exc))

    return {"metrics": metrics, "periods": periods, "chart": chart}
