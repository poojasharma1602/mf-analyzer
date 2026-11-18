"""Client + response validation for the mfapi.in provider.

Only two provider endpoints are used (both taken from the project specification):
    GET {base}/mf            -> list of {schemeCode, schemeName}
    GET {base}/mf/{code}     -> {meta: {...}, data: [{date: 'dd-mm-yyyy', nav: '12.34'}, ...], status: 'SUCCESS'}
The parsers are deliberately strict: anything that does not match is reported as
PROVIDER_BAD_RESPONSE instead of being guessed at.
"""
from __future__ import annotations

import asyncio
import logging
import re
from dataclasses import dataclass, field
from datetime import date, datetime, timedelta, timezone
from typing import Any, Optional

import httpx
import pandas as pd

log = logging.getLogger("mf.provider")

NAV_DATE_FORMAT = "%d-%m-%Y"
STALE_NAV_DAYS = 10
JUMP_WARN_THRESHOLD = 0.25  # 25 % one-day move


class ProviderError(Exception):
    """Provider problem with a stable machine-readable code and a user-facing message."""

    def __init__(self, code: str, message: str, http_status: int = 502):
        super().__init__(message)
        self.code = code
        self.message = message
        self.http_status = http_status


# ----------------------------------------------------------------------------
# Scheme name classification
# ----------------------------------------------------------------------------
_IDCW_RE = re.compile(r"\b(idcw|dividend|payout|pay\s*out|reinvest\w*|bonus)\b", re.I)


def classify_scheme(name: str) -> dict:
    """Heuristic option/plan classification from the scheme name (labelled as heuristic in the UI)."""
    n = name or ""
    low = n.lower()
    if _IDCW_RE.search(n):
        option = "idcw"
    elif "growth" in low:
        option = "growth"
    else:
        option = "unknown"
    plan = "direct" if "direct" in low else "regular" if "regular" in low else "unknown"
    return {"option": option, "plan": plan}


# ----------------------------------------------------------------------------
# Parsing / validation
# ----------------------------------------------------------------------------
def parse_scheme_list(payload: Any) -> list[tuple[int, str]]:
    if isinstance(payload, dict):
        for key in ("data", "schemes"):
            if isinstance(payload.get(key), list):
                payload = payload[key]
                break
    if not isinstance(payload, list):
        raise ProviderError("PROVIDER_BAD_RESPONSE", "Scheme list response was not a JSON array as expected.")
    out: list[tuple[int, str]] = []
    seen: set[int] = set()
    for item in payload:
        if not isinstance(item, dict):
            continue
        try:
            code = int(item.get("schemeCode"))
        except (TypeError, ValueError):
            continue
        name = item.get("schemeName")
        if not isinstance(name, str) or not name.strip() or code in seen:
            continue
        seen.add(code)
        out.append((code, name.strip()))
    if not out:
        raise ProviderError(
            "PROVIDER_BAD_RESPONSE",
            "Scheme list response contained no valid {schemeCode, schemeName} entries.",
        )
    return out


@dataclass
class ParsedNav:
    meta: dict
    records: list  # [[ 'YYYY-MM-DD', nav ], ...] ascending
    parse_warnings: list = field(default_factory=list)


def parse_nav_payload(payload: Any, requested_code: int, today: Optional[date] = None) -> ParsedNav:
    today = today or date.today()
    if not isinstance(payload, dict):
        raise ProviderError("PROVIDER_BAD_RESPONSE", "NAV response was not a JSON object as expected.")
    status = payload.get("status")
    if isinstance(status, str) and status.upper() != "SUCCESS":
        raise ProviderError("FUND_NOT_FOUND", f"Provider returned status '{status}' for scheme {requested_code}.", 404)
    data = payload.get("data")
    if not isinstance(data, list):
        raise ProviderError("PROVIDER_BAD_RESPONSE", "NAV response has no 'data' array.")
    if not data:
        raise ProviderError("NO_NAV_DATA", f"Scheme {requested_code} has no NAV history at the provider.", 404)

    meta = payload.get("meta") if isinstance(payload.get("meta"), dict) else {}
    if "scheme_code" in meta:
        try:
            if int(meta["scheme_code"]) != int(requested_code):
                raise ProviderError(
                    "PROVIDER_BAD_RESPONSE",
                    f"Provider returned scheme {meta['scheme_code']} when {requested_code} was requested.",
                )
        except (TypeError, ValueError):
            pass

    warnings: list[str] = []
    parsed: dict[str, float] = {}
    bad = future = dupes = 0
    for row in data:
        try:
            d = datetime.strptime(str(row["date"]).strip(), NAV_DATE_FORMAT).date()
            v = float(str(row["nav"]).replace(",", "").strip())
        except (KeyError, TypeError, ValueError):
            bad += 1
            continue
        if not (v > 0) or v != v:
            bad += 1
            continue
        if d > today + timedelta(days=1):
            future += 1
            continue
        key = d.isoformat()
        if key in parsed:
            dupes += 1
        parsed[key] = v
    if not parsed:
        raise ProviderError("PROVIDER_BAD_RESPONSE", "No NAV row could be parsed (expected dd-mm-yyyy dates and positive NAVs).")
    if bad:
        warnings.append(f"{bad} NAV row(s) with an invalid date or non-positive/non-numeric NAV were ignored.")
    if future:
        warnings.append(f"{future} NAV row(s) dated in the future were ignored.")
    if dupes:
        warnings.append(f"{dupes} duplicate NAV date(s) were collapsed (last value kept).")
    records = [[k, parsed[k]] for k in sorted(parsed)]
    return ParsedNav(meta=meta, records=records, parse_warnings=warnings)


def quality_warnings(records: list, today: Optional[date] = None) -> list[str]:
    """Data-quality warnings computed at read time (staleness depends on today's date)."""
    today = today or date.today()
    out: list[str] = []
    if not records:
        return out
    last = date.fromisoformat(records[-1][0])
    age = (today - last).days
    if age > STALE_NAV_DAYS:
        out.append(
            f"Latest NAV is {age} days old ({last.isoformat()}). The scheme may be closed/merged or the provider may be lagging; "
            "metrics describe the period up to that date."
        )
    if len(records) > 1:
        s = pd.Series([r[1] for r in records], dtype=float)
        jumps = int((s.pct_change().abs() > JUMP_WARN_THRESHOLD).sum())
        if jumps:
            out.append(
                f"{jumps} NAV move(s) larger than {int(JUMP_WARN_THRESHOLD * 100)}% between consecutive NAV dates — possible data error "
                "or corporate action; metrics may be distorted."
            )
    return out


def records_to_series(records: list) -> pd.Series:
    return pd.Series(
        [r[1] for r in records], index=pd.to_datetime([r[0] for r in records]), dtype=float, name="nav"
    )


# ----------------------------------------------------------------------------
# HTTP client
# ----------------------------------------------------------------------------
class MfApiClient:
    def __init__(
        self,
        base_url: str,
        transport: Optional[httpx.AsyncBaseTransport] = None,
        max_retries: int = 3,
        backoff_seconds: float = 1.0,
    ):
        self.base_url = base_url.rstrip("/")
        self.max_retries = max_retries
        self.backoff = backoff_seconds
        self._client = httpx.AsyncClient(
            transport=transport,
            timeout=httpx.Timeout(connect=10.0, read=60.0, write=10.0, pool=10.0),
            headers={"User-Agent": "MF-Analyzer-Local/1.0", "Accept": "application/json"},
            follow_redirects=True,
        )
        self.last_success_at: Optional[str] = None
        self.last_error: Optional[dict] = None
        self.consecutive_failures = 0

    async def aclose(self) -> None:
        await self._client.aclose()

    # -- bookkeeping --------------------------------------------------------
    def _ok(self) -> None:
        self.last_success_at = datetime.now(timezone.utc).isoformat(timespec="seconds")
        self.consecutive_failures = 0

    def _fail(self, err: ProviderError) -> ProviderError:
        self.consecutive_failures += 1
        self.last_error = {
            "code": err.code,
            "message": err.message,
            "at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        }
        return err

    def status(self) -> dict:
        return {
            "base_url": self.base_url,
            "last_success_at": self.last_success_at,
            "last_error": self.last_error,
            "consecutive_failures": self.consecutive_failures,
        }

    # -- requests ------------------------------------------------------------
    async def _get_json(self, path: str, what: str, not_found_code: str = "FUND_NOT_FOUND") -> Any:
        url = f"{self.base_url}{path}"
        attempts = self.max_retries + 1
        last_exc: Optional[Exception] = None
        last_status: Optional[int] = None
        for attempt in range(1, attempts + 1):
            delay = self.backoff * (2 ** (attempt - 1))
            try:
                resp = await self._client.get(url)
            except (httpx.TimeoutException, httpx.TransportError) as exc:  # network level
                last_exc = exc
                log.warning("%s: attempt %d/%d failed: %r", what, attempt, attempts, exc)
                if attempt < attempts:
                    await asyncio.sleep(delay)
                    continue
                raise self._fail(
                    ProviderError(
                        "PROVIDER_UNREACHABLE",
                        f"Could not reach the data provider ({self.base_url}) while loading {what}: "
                        f"{type(exc).__name__}. Check your internet connection, firewall/proxy settings, "
                        "or whether the provider is down, then try again. Previously cached data is used when available.",
                        503,
                    )
                )
            last_status = resp.status_code
            if resp.status_code == 404:
                raise self._fail(ProviderError(not_found_code, f"The provider has no data for {what} (HTTP 404).", 404))
            if resp.status_code == 429 or resp.status_code >= 500:
                retry_after = resp.headers.get("Retry-After")
                wait = delay
                if retry_after and retry_after.isdigit():
                    wait = min(float(retry_after), 20.0)
                log.warning("%s: HTTP %s, attempt %d/%d", what, resp.status_code, attempt, attempts)
                if attempt < attempts:
                    await asyncio.sleep(wait)
                    continue
                if resp.status_code == 429:
                    raise self._fail(
                        ProviderError(
                            "PROVIDER_RATE_LIMITED",
                            f"The data provider is rate-limiting requests (HTTP 429) while loading {what}. "
                            "Wait a minute and retry; fewer simultaneous funds also helps.",
                            429,
                        )
                    )
                raise self._fail(
                    ProviderError(
                        "PROVIDER_HTTP_ERROR",
                        f"The data provider returned HTTP {resp.status_code} while loading {what}. It may be having an outage.",
                        503,
                    )
                )
            if resp.status_code >= 400:
                raise self._fail(
                    ProviderError("PROVIDER_HTTP_ERROR", f"The data provider returned HTTP {resp.status_code} for {what}.", 502)
                )
            try:
                payload = resp.json()
            except ValueError:
                raise self._fail(
                    ProviderError("PROVIDER_BAD_RESPONSE", f"The provider returned a non-JSON response for {what}.", 502)
                )
            self._ok()
            return payload
        raise self._fail(  # pragma: no cover - loop always returns/raises
            ProviderError("PROVIDER_UNREACHABLE", f"Unexpected failure loading {what}: {last_exc or last_status}", 503)
        )

    async def fetch_scheme_list(self) -> list[tuple[int, str]]:
        payload = await self._get_json("/mf", "the scheme list", "PROVIDER_HTTP_ERROR")
        try:
            return parse_scheme_list(payload)
        except ProviderError as err:
            raise self._fail(err)

    async def fetch_nav(self, code: int) -> ParsedNav:
        payload = await self._get_json(f"/mf/{int(code)}", f"scheme {code}")
        try:
            return parse_nav_payload(payload, code)
        except ProviderError as err:
            raise self._fail(err)

    async def probe(self) -> dict:
        """Cheap reachability check: any HTTP response (even 404) proves the host is reachable."""
        try:
            resp = await self._client.get(f"{self.base_url}/", timeout=10.0)
            return {"reachable": True, "http_status": resp.status_code}
        except (httpx.TimeoutException, httpx.TransportError) as exc:
            return {"reachable": False, "error": f"{type(exc).__name__}: {exc}"}
