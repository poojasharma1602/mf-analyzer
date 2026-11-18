"""FastAPI application. All third-party requests go through this backend; the browser only talks to it."""
from __future__ import annotations

import asyncio
import logging
from contextlib import asynccontextmanager
from typing import Optional

import httpx
from fastapi import FastAPI, File, Form, HTTPException, Query, Request, UploadFile
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse, Response
from pydantic import BaseModel, Field, model_validator

from . import analytics as A
from . import benchmarks as B
from . import config, export
from .db import Database, utc_now_iso
from .methodology import SECTIONS
from .mfapi import MfApiClient, ProviderError, classify_scheme, quality_warnings
from .service import DataService, SchemeIndex

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s")
log = logging.getLogger("mf.api")


# ----------------------------------------------------------------------------
# Request models
# ----------------------------------------------------------------------------
class SettingsModel(BaseModel):
    rf_annual_pct: float = Field(6.0, ge=0, le=30, description="Annual risk-free rate in percent")
    mar_annual_pct: float = Field(0.0, ge=-10, le=30, description="Annual minimum acceptable return in percent")
    window_months: int = Field(36, ge=12, le=120)
    min_obs: int = Field(24, ge=6, le=120)

    @model_validator(mode="after")
    def _check(self):
        if self.min_obs > self.window_months:
            raise ValueError("min_obs cannot exceed window_months")
        return self

    def to_analysis(self) -> A.AnalysisSettings:
        return A.AnalysisSettings(
            rf_annual=self.rf_annual_pct / 100.0,
            mar_annual=self.mar_annual_pct / 100.0,
            window_months=self.window_months,
            min_obs=self.min_obs,
        )


class AnalyzeRequest(BaseModel):
    scheme_codes: list[int] = Field(..., min_length=1)
    settings: Optional[SettingsModel] = None


class SelectedFund(BaseModel):
    scheme_code: int
    scheme_name: str


class SelectionRequest(BaseModel):
    funds: list[SelectedFund]


class DefaultBenchmarkRequest(BaseModel):
    benchmark_name: Optional[str] = None


class OverrideRequest(BaseModel):
    scheme_code: int
    benchmark_name: Optional[str] = None


_STATUS = {"FUND_NOT_FOUND": 404, "NO_NAV_DATA": 404, "PROVIDER_RATE_LIMITED": 429}


# ----------------------------------------------------------------------------
def create_app(
    db_path=None,
    transport: Optional[httpx.AsyncBaseTransport] = None,
    base_url: Optional[str] = None,
    retry_backoff: float = 1.0,
    nav_ttl_hours: Optional[float] = None,
    schemes_ttl_hours: Optional[float] = None,
) -> FastAPI:
    @asynccontextmanager
    async def lifespan(app: FastAPI):
        db = Database(db_path or config.db_path())
        db.init()
        client = MfApiClient(base_url or config.mfapi_base_url(), transport=transport, backoff_seconds=retry_backoff)
        schemes = SchemeIndex(db, client, schemes_ttl_hours if schemes_ttl_hours is not None else config.schemes_ttl_hours())
        svc = DataService(db, client, schemes, nav_ttl_hours if nav_ttl_hours is not None else config.nav_ttl_hours())
        app.state.db, app.state.client, app.state.schemes, app.state.svc = db, client, schemes, svc
        log.info("Database: %s | provider: %s", db.path, client.base_url)
        yield
        await client.aclose()

    app = FastAPI(title="Indian Mutual Fund Analyzer", version=config.APP_VERSION, lifespan=lifespan)
    app.add_middleware(
        CORSMiddleware,
        allow_origins=config.cors_origins(),
        allow_methods=["GET", "POST", "PUT", "DELETE"],
        allow_headers=["Content-Type"],
    )

    @app.exception_handler(ProviderError)
    async def provider_error_handler(_: Request, exc: ProviderError):
        return JSONResponse(
            status_code=_STATUS.get(exc.code, exc.http_status),
            content={"error": {"code": exc.code, "message": exc.message}},
        )

    def S(request: Request) -> DataService:
        return request.app.state.svc

    def stored_settings(request: Request) -> SettingsModel:
        raw = request.app.state.db.get_settings()
        try:
            return SettingsModel(**raw) if raw else SettingsModel()
        except Exception:
            return SettingsModel()

    # -- health -------------------------------------------------------------------
    @app.get("/api/health")
    async def health(request: Request, probe: bool = False):
        st = request.app.state
        try:
            db_ok = await asyncio.to_thread(st.db.ping)
        except Exception as exc:  # pragma: no cover
            db_ok = False
            log.error("db ping failed: %s", exc)
        provider = st.client.status()
        provider["probe"] = await st.client.probe() if probe else None
        return {
            "status": "ok" if db_ok else "degraded",
            "time": utc_now_iso(),
            "version": config.APP_VERSION,
            "database": {"ok": db_ok, "path": str(st.db.path)},
            "provider": provider,
            "cache": {
                "schemes_fetched_at": st.schemes.fetched_at,
                "schemes_count": len(st.schemes._rows),
                "nav_cached_funds": await asyncio.to_thread(st.db.nav_cache_count),
            },
        }

    # -- schemes ---------------------------------------------------------------------
    @app.get("/api/schemes")
    async def schemes(
        request: Request,
        search: str = Query("", description="Space-separated words, or a scheme code prefix"),
        limit: int = Query(50, ge=1, le=200),
        growth_only: bool = False,
    ):
        idx: SchemeIndex = request.app.state.schemes
        await idx.ensure()
        results, total = idx.search(search, limit, growth_only)
        return {
            "results": results,
            "total_matches": total,
            "schemes_as_of": idx.fetched_at,
            "stale": idx.stale,
            "stale_reason": idx.stale_reason,
            "warning": idx.warning,
        }

    # -- single fund -------------------------------------------------------------------
    @app.get("/api/funds/{scheme_code}")
    async def fund(request: Request, scheme_code: int, refresh: bool = False, include_nav: bool = True):
        svc = S(request)
        data, status = await svc.get_nav(scheme_code, refresh=refresh)
        meta = data["meta"] or {}
        records = data["records"]
        name = meta.get("scheme_name") or request.app.state.schemes.name_for(scheme_code) or f"Scheme {scheme_code}"
        warnings = list(data.get("parse_warnings", [])) + quality_warnings(records)
        body = {
            "scheme_code": scheme_code,
            "scheme_name": name,
            "meta": meta,
            **classify_scheme(name),
            "nav_as_of": records[-1][0],
            "latest_nav": records[-1][1],
            "first_nav_date": records[0][0],
            "nav_points": len(records),
            "warnings": warnings,
            "data_status": status,
        }
        if include_nav:
            body["nav"] = records
        return body

    # -- analysis --------------------------------------------------------------------------
    async def _analysis(request: Request, body: AnalyzeRequest) -> dict:
        codes = list(dict.fromkeys(body.scheme_codes))
        if len(codes) > config.MAX_FUNDS:
            raise HTTPException(400, f"At most {config.MAX_FUNDS} funds can be analysed at once (got {len(codes)}).")
        settings = body.settings or stored_settings(request)
        try:
            await request.app.state.schemes.ensure()  # best effort: only used for fund names in error rows
        except ProviderError:
            pass
        return await S(request).analyze_many(codes, settings.to_analysis())

    @app.post("/api/analyze")
    async def analyze(request: Request, body: AnalyzeRequest):
        return await _analysis(request, body)

    @app.post("/api/export")
    async def export_results(request: Request, body: AnalyzeRequest, format: str = Query("csv", pattern="^(csv|xlsx)$")):
        analysis = await _analysis(request, body)
        stamp = analysis["generated_at"][:10]
        if format == "csv":
            return Response(
                export.to_csv_bytes(analysis),
                media_type="text/csv; charset=utf-8",
                headers={"Content-Disposition": f'attachment; filename="mf_comparison_{stamp}.csv"'},
            )
        return Response(
            export.to_xlsx_bytes(analysis),
            media_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
            headers={"Content-Disposition": f'attachment; filename="mf_comparison_{stamp}.xlsx"'},
        )

    # -- persisted selection / settings ---------------------------------------------------------
    @app.get("/api/selection")
    async def get_selection(request: Request):
        return {"funds": await asyncio.to_thread(request.app.state.db.get_selection)}

    @app.put("/api/selection")
    async def put_selection(request: Request, body: SelectionRequest):
        if len(body.funds) > config.MAX_FUNDS:
            raise HTTPException(400, f"At most {config.MAX_FUNDS} funds can be selected.")
        funds, seen = [], set()
        for f in body.funds:
            if f.scheme_code not in seen:
                seen.add(f.scheme_code)
                funds.append(f.model_dump())
        await asyncio.to_thread(request.app.state.db.set_selection, funds)
        return {"funds": funds}

    @app.get("/api/settings")
    async def get_settings(request: Request):
        return stored_settings(request).model_dump()

    @app.put("/api/settings")
    async def put_settings(request: Request, body: SettingsModel):
        await asyncio.to_thread(request.app.state.db.set_settings, body.model_dump())
        return body.model_dump()

    # -- benchmarks ------------------------------------------------------------------------------
    @app.get("/api/benchmarks")
    async def list_benchmarks(request: Request):
        db = request.app.state.db
        mapping = B.load_mapping()
        return {
            "benchmarks": await asyncio.to_thread(db.list_benchmarks),
            "mapping": B.public_mapping(mapping),
            "default_benchmark": await asyncio.to_thread(db.kv_get, "default_benchmark") or None,
            "overrides": [
                {"scheme_code": c, "benchmark_name": n} for c, n in (await asyncio.to_thread(db.get_overrides)).items()
            ],
        }

    @app.post("/api/benchmarks/import")
    async def import_benchmark(request: Request, name: str = Form(...), file: UploadFile = File(...)):
        name = " ".join(name.split())
        if not name or len(name) > 80:
            raise HTTPException(400, "Benchmark name is required (max 80 characters).")
        raw = await file.read()
        if len(raw) > 20 * 1024 * 1024:
            raise HTTPException(400, "File is larger than 20 MB.")
        try:
            parsed = B.parse_benchmark_csv(raw)
        except B.BenchmarkCsvError as exc:
            raise HTTPException(400, f"Benchmark CSV rejected: {exc}")
        # An NSE price-return (PR) file can be parsed, but it is not a TRI.
        # Warn explicitly; never silently label PR returns as total returns.
        import re
        filename = file.filename or ""
        if re.search(r"(?:^|[_\W])PR(?:[_\W]|$)|price[ _-]*return", filename, re.I) or re.search(r"\bPR\b|price[ _-]*return", name, re.I):
            parsed.warnings.append("PRICE RETURN (PR) DATA DETECTED: This is not a Total Return Index (TRI). Beta/alpha/information ratio versus PR are price-index-relative and are NOT comparable to TRI-relative results. Import the matching TRI series for standard mutual fund comparisons.")
        info = await asyncio.to_thread(request.app.state.db.upsert_benchmark, name, file.filename, parsed.points)
        return {"benchmark": info, "warnings": parsed.warnings}

    @app.delete("/api/benchmarks/{name}")
    async def delete_benchmark(request: Request, name: str):
        if not await asyncio.to_thread(request.app.state.db.delete_benchmark, name):
            raise HTTPException(404, "Benchmark not found.")
        return {"deleted": name}

    @app.put("/api/benchmarks/override")
    async def set_override(request: Request, body: OverrideRequest):
        await asyncio.to_thread(request.app.state.db.set_override, body.scheme_code, (body.benchmark_name or "").strip() or None)
        return {"scheme_code": body.scheme_code, "benchmark_name": (body.benchmark_name or "").strip() or None}

    @app.put("/api/benchmarks/default")
    async def set_default_benchmark(request: Request, body: DefaultBenchmarkRequest):
        db = request.app.state.db
        name = (body.benchmark_name or "").strip()
        if name:
            info = await asyncio.to_thread(db.get_benchmark_info, name)
            if not info:
                raise HTTPException(404, f"Benchmark '{name}' has not been imported.")
            name = info["name"]
        await asyncio.to_thread(db.kv_set, "default_benchmark", name)
        return {"default_benchmark": name or None}

    # -- methodology --------------------------------------------------------------------------------
    @app.get("/api/methodology")
    async def methodology():
        return {"version": config.METHODOLOGY_VERSION, "sections": SECTIONS}

    return app


app = create_app()
