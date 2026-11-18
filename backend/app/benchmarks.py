"""Benchmark TRI CSV import + scheme -> benchmark mapping.

No public benchmark TRI API is wired in on purpose: I could not verify a reliable, legally
usable, key-free source for NSE/BSE total-return indices, and this project does not scrape
restricted sites or invent endpoints. Benchmark data therefore comes from CSV files you
export/download from a source you are licensed to use (e.g. the index provider's website).
"""
from __future__ import annotations

import io
import json
import re
from dataclasses import dataclass, field
from datetime import date
from pathlib import Path
from typing import Optional

import pandas as pd

from .config import BENCHMARK_MAPPING_FILE

MIN_BENCHMARK_POINTS = 13  # need at least 12 monthly returns
DATE_FORMATS = [
    "%Y-%m-%d",
    "%d-%m-%Y",
    "%d/%m/%Y",
    "%d-%b-%Y",
    "%d-%B-%Y",
    "%d %b %Y",
    "%d %B %Y",
    "%d-%b-%y",
    "%d/%m/%y",
    "%Y/%m/%d",
]
DATE_COLUMNS = {"date", "dates", "asondate", "indexdate", "tradingdate"}
VALUE_COLUMNS = {
    "indexvalue",
    "value",
    "close",
    "closingvalue",
    "closingindexvalue",
    "indexlevel",
    "tri",
    "totalreturnindex",
    "level",
}


class BenchmarkCsvError(ValueError):
    pass


@dataclass
class ParsedBenchmark:
    points: list  # [(iso_date, value)] ascending
    warnings: list = field(default_factory=list)


def _norm(col: str) -> str:
    return re.sub(r"[^a-z0-9]", "", str(col).lower())


def parse_benchmark_csv(content: bytes | str, today: Optional[date] = None) -> ParsedBenchmark:
    """Parse a CSV with Date and Index Value columns. Strict: ambiguous or malformed input is rejected."""
    today = today or date.today()
    if isinstance(content, bytes):
        try:
            text = content.decode("utf-8-sig")
        except UnicodeDecodeError:
            text = content.decode("latin-1")
    else:
        text = content
    if not text.strip():
        raise BenchmarkCsvError("The file is empty.")
    try:
        df = pd.read_csv(io.StringIO(text), sep=None, engine="python", dtype=str, skip_blank_lines=True)
    except Exception as exc:  # pandas raises several parser error types
        raise BenchmarkCsvError(f"Could not read the file as CSV: {exc}") from exc

    warnings: list[str] = []
    cols = {c: _norm(c) for c in df.columns}
    date_col = next((c for c, n in cols.items() if n in DATE_COLUMNS), None)
    value_col = next((c for c, n in cols.items() if n in VALUE_COLUMNS), None)
    if date_col is None or value_col is None:
        if len(df.columns) == 2:
            date_col, value_col = df.columns[0], df.columns[1]
            warnings.append(
                f"Columns '{date_col}' and '{value_col}' were used as Date and Index Value (expected headers 'Date' and 'Index Value')."
            )
        else:
            raise BenchmarkCsvError(
                "Expected columns named 'Date' and 'Index Value'. Found: " + ", ".join(map(str, df.columns))
            )

    sub = df[[date_col, value_col]].copy()
    sub.columns = ["d", "v"]
    sub = sub.dropna(how="all")
    sub["d"] = sub["d"].astype(str).str.strip()
    sub["v"] = sub["v"].astype(str).str.strip()
    sub = sub[(sub["d"] != "") & (sub["d"].str.lower() != "nan")]
    if sub.empty:
        raise BenchmarkCsvError("No data rows found.")

    parsed_dates = None
    for fmt in DATE_FORMATS:
        attempt = pd.to_datetime(sub["d"], format=fmt, errors="coerce")
        if attempt.notna().all():
            parsed_dates = attempt
            break
    if parsed_dates is None:
        # pandas timestamps cannot represent dates in years such as 2999;
        # still report these as future dates rather than misleading format errors.
        from datetime import datetime
        for raw_date in sub["d"]:
            for fmt in DATE_FORMATS:
                try:
                    candidate = datetime.strptime(raw_date, fmt).date()
                except ValueError:
                    continue
                if candidate > today:
                    raise BenchmarkCsvError(f"The file contains dates in the future ({raw_date}).")
                break
        bad = sub["d"][pd.to_datetime(sub["d"], format="%Y-%m-%d", errors="coerce").isna()].iloc[0]
        raise BenchmarkCsvError(
            f"Could not parse every date (example: '{bad}'). Use YYYY-MM-DD, DD-MM-YYYY, DD/MM/YYYY or DD-Mon-YYYY (day first)."
        )

    values = pd.to_numeric(sub["v"].str.replace(",", "", regex=False), errors="coerce")
    if values.isna().any():
        bad = sub["v"][values.isna()].iloc[0]
        raise BenchmarkCsvError(f"Non-numeric index value found (example: '{bad}').")
    if (values <= 0).any():
        raise BenchmarkCsvError("Index values must be positive.")

    out = pd.Series(values.to_numpy(dtype=float), index=parsed_dates.to_numpy())
    if out.index.max().date() > today:
        raise BenchmarkCsvError(f"The file contains dates in the future ({out.index.max().date()}).")
    if out.index.duplicated().any():
        n = int(out.index.duplicated().sum())
        warnings.append(f"{n} duplicate date(s) found; the last value for each date was kept.")
        out = out[~out.index.duplicated(keep="last")]
    out = out.sort_index()
    if len(out) < MIN_BENCHMARK_POINTS:
        raise BenchmarkCsvError(f"Only {len(out)} data point(s); at least {MIN_BENCHMARK_POINTS} are required.")

    gaps = out.index.to_series().diff().dt.days.dropna()
    if len(gaps) and gaps.max() > 45:
        warnings.append(f"Largest gap between observations is {int(gaps.max())} days; months without data are excluded from matching.")
    jumps = int((out.pct_change().abs() > 0.2).sum())
    if jumps:
        warnings.append(f"{jumps} observation-to-observation move(s) larger than 20% — check the file for errors or unit changes.")
    points = [(ts.date().isoformat(), float(v)) for ts, v in out.items()]
    return ParsedBenchmark(points=points, warnings=warnings)


def points_to_series(points: list) -> pd.Series:
    return pd.Series([p[1] for p in points], index=pd.to_datetime([p[0] for p in points]), dtype=float)


# ----------------------------------------------------------------------------
# Mapping configuration
# ----------------------------------------------------------------------------
def load_mapping(path: Path = BENCHMARK_MAPPING_FILE) -> dict:
    with open(path, "r", encoding="utf-8") as fh:
        cfg = json.load(fh)
    for rule in cfg.get("rules", []):
        rule["_re"] = re.compile(rule["pattern"], re.I)
    return cfg


def suggest_benchmark(scheme_name: str, category: str, mapping: dict) -> Optional[str]:
    """First matching rule wins (category and name checked according to the rule's 'field')."""
    for rule in mapping.get("rules", []):
        target = {"name": scheme_name or "", "category": category or ""}.get(rule.get("field", "category"), "")
        if rule["_re"].search(target):
            return rule["benchmark"]
    return None


def public_mapping(mapping: dict) -> dict:
    return {
        "note": mapping.get("note"),
        "rules": [{k: v for k, v in r.items() if k != "_re"} for r in mapping.get("rules", [])],
    }
