"""CSV / Excel export of an analysis response."""
from __future__ import annotations

import io

import pandas as pd
from openpyxl import Workbook
from openpyxl.styles import Alignment, Font, PatternFill
from openpyxl.utils import get_column_letter

from .methodology import SECTIONS

NA = "N/A"


def _v(metric: dict, scale: float = 1.0, nd: int = 4):
    val = (metric or {}).get("value")
    return NA if val is None else round(val * scale, nd)


def _reason(metrics: dict) -> str:
    parts = [f"{k}: {m['reason']}" for k, m in metrics.items() if m.get("value") is None and m.get("reason")]
    return " | ".join(parts)


COLUMNS = [
    "Scheme Code",
    "Scheme Name",
    "Fund House",
    "Category",
    "Option (inferred)",
    "Plan (inferred)",
    "Benchmark",
    "Benchmark Source",
    "Benchmark Imported",
    "NAV As-Of Date",
    "Latest NAV",
    "3Y CAGR (%)",
    "Sharpe",
    "Sortino",
    "Jensen's Alpha (% p.a.)",
    "Beta",
    "Information Ratio",
    "Volatility (% p.a.)",
    "Max Drawdown (%)",
    "Tracking Error (% p.a.)",
    "Active Return (% p.a.)",
    "Fund Obs (months)",
    "Matched Obs (months)",
    "Ratio Period End",
    "Data Status",
    "Warnings",
    "N/A Reasons",
]


def build_rows(analysis: dict) -> list[list]:
    rows = []
    for r in analysis["results"]:
        if "error" in r:
            row = [r["scheme_code"], r.get("scheme_name")] + [""] * (len(COLUMNS) - 2)
            row[COLUMNS.index("Data Status")] = "ERROR"
            row[COLUMNS.index("N/A Reasons")] = f"{r['error']['code']}: {r['error']['message']}"
            rows.append(row)
            continue
        m, p, b = r["metrics"], r["periods"], r["benchmark"]
        rows.append(
            [
                r["scheme_code"],
                r["scheme_name"],
                r.get("fund_house") or "",
                r.get("category") or "",
                r["option"],
                r["plan"],
                b["name"] or "",
                b["source"],
                "yes" if b["imported"] else "no",
                r["nav_as_of"],
                r["latest_nav"],
                _v(m["cagr_3y"], 100, 2),
                _v(m["sharpe"], 1, 3),
                _v(m["sortino"], 1, 3),
                _v(m["jensen_alpha"], 100, 2),
                _v(m["beta"], 1, 3),
                _v(m["information_ratio"], 1, 3),
                _v(m["volatility"], 100, 2),
                _v(m["max_drawdown"], 100, 2),
                _v(m["tracking_error"], 100, 2),
                _v(m["active_return"], 100, 2),
                (p["fund"] or {}).get("n_obs", ""),
                (p["matched"] or {}).get("n_obs", ""),
                (p["fund"] or {}).get("end", ""),
                "stale cache" if r["data_status"]["stale"] else "ok",
                " | ".join(r["warnings"]),
                _reason(m),
            ]
        )
    return rows


def to_csv_bytes(analysis: dict) -> bytes:
    df = pd.DataFrame(build_rows(analysis), columns=COLUMNS)
    # utf-8-sig so that Excel on Windows opens the file with the correct encoding
    return df.to_csv(index=False).encode("utf-8-sig")


def to_xlsx_bytes(analysis: dict) -> bytes:
    wb = Workbook()
    ws = wb.active
    ws.title = "Comparison"
    ws.append(COLUMNS)
    head_fill = PatternFill("solid", fgColor="1F2937")
    for cell in ws[1]:
        cell.font = Font(bold=True, color="FFFFFF")
        cell.fill = head_fill
        cell.alignment = Alignment(wrap_text=True, vertical="center")
    for row in build_rows(analysis):
        ws.append(row)
    widths = {"Scheme Name": 52, "Fund House": 24, "Category": 30, "Benchmark": 26, "Warnings": 60, "N/A Reasons": 60}
    for i, name in enumerate(COLUMNS, start=1):
        ws.column_dimensions[get_column_letter(i)].width = widths.get(name, 14)
    ws.freeze_panes = "C2"
    ws.auto_filter.ref = ws.dimensions

    notes = wb.create_sheet("Settings & Methodology")
    s = analysis["settings"]
    notes.append(["Generated at (UTC)", analysis["generated_at"]])
    notes.append(["Methodology version", analysis["methodology_version"]])
    notes.append(["Risk-free rate (% p.a.)", s["rf_annual_pct"]])
    notes.append(["Minimum acceptable return (% p.a.)", s["mar_annual_pct"]])
    notes.append(["Analysis window (months)", s["window_months"]])
    notes.append(["Minimum observations", s["min_obs"]])
    notes.append([])
    notes.append(["Data source: mfapi.in NAV history (cached locally). Not investment advice; a single ratio does not show a fund is good or bad."])
    notes.append([])
    for sec in SECTIONS:
        notes.append([sec["title"]])
        notes.cell(row=notes.max_row, column=1).font = Font(bold=True)
        for para in sec["body"]:
            notes.append([para])
            notes.cell(row=notes.max_row, column=1).alignment = Alignment(wrap_text=True, vertical="top")
    notes.column_dimensions["A"].width = 120
    notes.column_dimensions["B"].width = 30

    buf = io.BytesIO()
    wb.save(buf)
    return buf.getvalue()
