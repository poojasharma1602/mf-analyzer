"""Orchestration: caching with stale fallback, scheme search, benchmark resolution, analysis."""
from __future__ import annotations

import asyncio
import logging
from datetime import datetime, timezone
from typing import Optional

from . import analytics as A
from . import benchmarks as B
from .config import ANALYZE_CONCURRENCY, METHODOLOGY_VERSION
from .db import Database, utc_now_iso
from .mfapi import (
    MfApiClient,
    ProviderError,
    classify_scheme,
    quality_warnings,
    records_to_series,
)

log = logging.getLogger("mf.service")

MIN_EXPECTED_SCHEMES = 1000
IDCW_WARNING = (
    "IDCW / Dividend / Payout option (inferred from the name): NAV falls when distributions are paid and this tool does not add them back, "
    "so NAV-based returns understate total return. Prefer the Growth option for comparison."
)
UNKNOWN_OPTION_WARNING = "Could not tell from the name whether this is a Growth or IDCW option; verify before relying on NAV-based returns."


def _age_hours(iso: Optional[str]) -> Optional[float]:
    if not iso:
        return None
    return (datetime.now(timezone.utc) - datetime.fromisoformat(iso)).total_seconds() / 3600.0


# ----------------------------------------------------------------------------
class SchemeIndex:
    """In-memory searchable copy of the scheme list, backed by the SQLite cache."""

    def __init__(self, db: Database, client: MfApiClient, ttl_hours: float):
        self.db, self.client, self.ttl = db, client, ttl_hours
        self._rows: list[tuple[int, str, str, str, str]] = []  # code, name, lower, option, plan
        self._by_code: dict[int, str] = {}
        self.fetched_at: Optional[str] = None
        self.stale = False
        self.stale_reason: Optional[str] = None
        self.warning: Optional[str] = None
        self._lock = asyncio.Lock()

    def _load_rows(self, rows: list[tuple[int, str]], fetched_at: Optional[str]) -> None:
        out = []
        for code, name in rows:
            c = classify_scheme(name)
            out.append((code, name, name.lower(), c["option"], c["plan"]))
        self._rows = out
        self._by_code = {r[0]: r[1] for r in out}
        self.fetched_at = fetched_at
        self.warning = (
            f"The provider returned only {len(out)} schemes; the list may be incomplete or paginated."
            if len(out) < MIN_EXPECTED_SCHEMES
            else None
        )

    async def ensure(self, refresh: bool = False) -> None:
        async with self._lock:
            if not self._rows:
                cached = await asyncio.to_thread(self.db.load_schemes)
                if cached:
                    self._load_rows(cached, await asyncio.to_thread(self.db.schemes_fetched_at))
            age = _age_hours(self.fetched_at)
            if self._rows and not refresh and age is not None and age < self.ttl:
                self.stale = False
                return
            try:
                rows = await self.client.fetch_scheme_list()
            except ProviderError as err:
                if self._rows:
                    self.stale = True
                    self.stale_reason = err.message
                    return
                raise
            now = utc_now_iso()
            await asyncio.to_thread(self.db.replace_schemes, rows, now)
            self._load_rows(rows, now)
            self.stale = False
            self.stale_reason = None

    def name_for(self, code: int) -> Optional[str]:
        return self._by_code.get(code)

    def search(self, query: str, limit: int = 50, growth_only: bool = False) -> tuple[list[dict], int]:
        tokens = [t for t in query.lower().split() if t]
        if not tokens:
            return [], 0
        matches = []
        for code, name, low, option, plan in self._rows:
            if growth_only and option != "growth":
                continue
            if all((t in low) or (t.isdigit() and str(code).startswith(t)) for t in tokens):
                matches.append((code, name, option, plan))
        rank = {"growth": 0, "unknown": 1, "idcw": 2}
        matches.sort(key=lambda m: (rank[m[2]], len(m[1]), m[1]))
        total = len(matches)
        results = [
            {"scheme_code": c, "scheme_name": n, "option": o, "plan": p} for c, n, o, p in matches[:limit]
        ]
        return results, total


# ----------------------------------------------------------------------------
class DataService:
    def __init__(self, db: Database, client: MfApiClient, schemes: SchemeIndex, nav_ttl_hours: float):
        self.db, self.client, self.schemes, self.nav_ttl = db, client, schemes, nav_ttl_hours
        self._sem = asyncio.Semaphore(ANALYZE_CONCURRENCY)

    async def get_nav(self, code: int, refresh: bool = False) -> tuple[dict, dict]:
        """Return (nav_data, status). nav_data = {meta, records, parse_warnings}."""
        cached = await asyncio.to_thread(self.db.load_nav, code)
        age = _age_hours(cached["fetched_at"]) if cached else None
        if cached and not refresh and age is not None and age < self.nav_ttl:
            return cached, {"fetched_at": cached["fetched_at"], "from_cache": True, "stale": False, "stale_reason": None}
        try:
            parsed = await self.client.fetch_nav(code)
        except ProviderError as err:
            if cached and err.code not in ("FUND_NOT_FOUND", "NO_NAV_DATA"):
                return cached, {
                    "fetched_at": cached["fetched_at"],
                    "from_cache": True,
                    "stale": True,
                    "stale_reason": err.message,
                }
            raise
        now = utc_now_iso()
        await asyncio.to_thread(self.db.save_nav, code, now, parsed.meta, parsed.records, parsed.parse_warnings)
        data = {"meta": parsed.meta, "records": parsed.records, "parse_warnings": parsed.parse_warnings}
        return data, {"fetched_at": now, "from_cache": False, "stale": False, "stale_reason": None}

    # -- benchmark resolution ------------------------------------------------------------
    def resolve_benchmark(self, code: int, name: str, category: str, overrides: dict, mapping: dict) -> tuple[Optional[str], str]:
        if code in overrides:
            return overrides[code], "override"
        suggested = B.suggest_benchmark(name, category, mapping)
        return (suggested, "rule") if suggested else (None, "none")

    def fallback_benchmark(self) -> Optional[dict]:
        """Benchmark used when a fund's mapped one is not imported: the user's chosen default,
        else the only imported benchmark. With several imported and no default there is no silent guess."""
        imported = self.db.list_benchmarks()
        chosen = (self.db.kv_get("default_benchmark") or "").strip().lower()
        for b in imported:
            if chosen and b["name"].lower() == chosen:
                return b
        return imported[0] if len(imported) == 1 else None

    # -- analysis ------------------------------------------------------------------------
    def _analyze_sync(
        self,
        code: int,
        nav_data: dict,
        status: dict,
        settings: A.AnalysisSettings,
        bench_name: Optional[str],
        bench_source: str,
        bench_info: Optional[dict],
        bench_points: Optional[list],
        fallback_name: Optional[str],
    ) -> dict:
        meta = nav_data["meta"] or {}
        name = meta.get("scheme_name") or fallback_name or f"Scheme {code}"
        category = meta.get("scheme_category") or ""
        cls = classify_scheme(name)
        records = nav_data["records"]
        nav = records_to_series(records)

        bench_monthly = None
        reason = None
        if bench_name is None:
            reason = "No benchmark mapped for this scheme (choose one in the Benchmarks tab)"
        elif not bench_points:
            reason = f"Benchmark TRI '{bench_name}' has not been imported (Benchmarks tab -> import CSV)"
        else:
            bench_monthly = A.to_monthly(B.points_to_series(bench_points))
            if len(bench_monthly) < 2:
                reason = f"Benchmark '{bench_name}' has too few monthly points"
                bench_monthly = None

        result = A.compute_fund_metrics(nav, settings, bench_monthly, reason)

        warnings = list(nav_data.get("parse_warnings", [])) + quality_warnings(records)
        if cls["option"] == "idcw":
            warnings.append(IDCW_WARNING)
        elif cls["option"] == "unknown":
            warnings.append(UNKNOWN_OPTION_WARNING)
        if status["stale"]:
            warnings.append(f"Using cached data because the provider could not be reached: {status['stale_reason']}")

        return {
            "scheme_code": code,
            "scheme_name": name,
            "fund_house": meta.get("fund_house"),
            "category": category or None,
            "scheme_type": meta.get("scheme_type"),
            "option": cls["option"],
            "plan": cls["plan"],
            "nav_as_of": records[-1][0],
            "latest_nav": records[-1][1],
            "first_nav_date": records[0][0],
            "nav_points": len(records),
            "benchmark": {
                "name": bench_name,
                "source": bench_source,
                "imported": bool(bench_points),
                "first_date": bench_info["first_date"] if bench_info else None,
                "last_date": bench_info["last_date"] if bench_info else None,
            },
            "metrics": result["metrics"],
            "periods": result["periods"],
            "chart": result["chart"],
            "warnings": warnings,
            "data_status": status,
        }

    async def analyze_one(self, code: int, settings: A.AnalysisSettings, overrides: dict, mapping: dict) -> dict:
        fallback_name = self.schemes.name_for(code)
        try:
            async with self._sem:
                nav_data, status = await self.get_nav(code)
            meta = nav_data["meta"] or {}
            name = meta.get("scheme_name") or fallback_name or ""
            bench_name, source = self.resolve_benchmark(code, name, meta.get("scheme_category") or "", overrides, mapping)
            bench_info = bench_points = None
            fallback_warning = None
            if bench_name:
                bench_info = await asyncio.to_thread(self.db.get_benchmark_info, bench_name)
            if not bench_info and source != "override":
                fb = await asyncio.to_thread(self.fallback_benchmark)
                if fb:
                    fallback_warning = (
                        (f"Mapped benchmark '{bench_name}' has not been imported" if bench_name else "No benchmark is mapped for this scheme")
                        + f", so the imported '{fb['name']}' is used instead. This is not the fund's mapped benchmark; "
                        "beta, alpha and information ratio are relative to that index. Import the mapped TRI or pick an override to change it."
                    )
                    bench_name, source, bench_info = fb["name"], "default", fb
            if bench_info:
                bench_name = bench_info["name"]
                bench_points = await asyncio.to_thread(self.db.get_benchmark_points, bench_name)
            result = await asyncio.to_thread(
                self._analyze_sync, code, nav_data, status, settings, bench_name, source, bench_info, bench_points, fallback_name
            )
            if fallback_warning:
                result["warnings"].append(fallback_warning)
            return result
        except ProviderError as err:
            return {
                "scheme_code": code,
                "scheme_name": fallback_name or f"Scheme {code}",
                "error": {"code": err.code, "message": err.message},
            }
        except Exception as exc:  # never let one fund break the whole comparison
            log.exception("analysis failed for %s", code)
            return {
                "scheme_code": code,
                "scheme_name": fallback_name or f"Scheme {code}",
                "error": {"code": "ANALYSIS_FAILED", "message": f"Unexpected error while analysing this fund: {exc}"},
            }

    async def analyze_many(self, codes: list[int], settings: A.AnalysisSettings) -> dict:
        from .benchmarks import load_mapping

        mapping = load_mapping()
        overrides = await asyncio.to_thread(self.db.get_overrides)
        rows = await asyncio.gather(*(self.analyze_one(c, settings, overrides, mapping) for c in codes))
        return {
            "generated_at": utc_now_iso(),
            "methodology_version": METHODOLOGY_VERSION,
            "settings": {
                "rf_annual_pct": settings.rf_annual * 100,
                "mar_annual_pct": settings.mar_annual * 100,
                "window_months": settings.window_months,
                "min_obs": settings.min_obs,
            },
            "results": list(rows),
        }
