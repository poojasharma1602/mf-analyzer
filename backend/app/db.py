"""SQLite persistence: scheme list cache, NAV cache, selected funds, settings, benchmarks."""
from __future__ import annotations

import json
import sqlite3
import zlib
from contextlib import contextmanager
from datetime import datetime, timezone
from pathlib import Path
from typing import Iterable, Optional

SCHEMA = """
CREATE TABLE IF NOT EXISTS schemes (code INTEGER PRIMARY KEY, name TEXT NOT NULL);
CREATE TABLE IF NOT EXISTS kv (key TEXT PRIMARY KEY, value TEXT NOT NULL);
CREATE TABLE IF NOT EXISTS nav_cache (
    scheme_code INTEGER PRIMARY KEY,
    fetched_at TEXT NOT NULL,
    payload BLOB NOT NULL
);
CREATE TABLE IF NOT EXISTS selected_funds (
    scheme_code INTEGER PRIMARY KEY,
    scheme_name TEXT NOT NULL,
    position INTEGER NOT NULL
);
CREATE TABLE IF NOT EXISTS benchmarks (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    name TEXT NOT NULL UNIQUE COLLATE NOCASE,
    source_filename TEXT,
    imported_at TEXT NOT NULL,
    n_points INTEGER NOT NULL,
    first_date TEXT,
    last_date TEXT
);
CREATE TABLE IF NOT EXISTS benchmark_points (
    benchmark_id INTEGER NOT NULL REFERENCES benchmarks(id) ON DELETE CASCADE,
    date TEXT NOT NULL,
    value REAL NOT NULL,
    PRIMARY KEY (benchmark_id, date)
);
CREATE TABLE IF NOT EXISTS scheme_benchmark_override (
    scheme_code INTEGER PRIMARY KEY,
    benchmark_name TEXT NOT NULL
);
"""


def utc_now_iso() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


class Database:
    def __init__(self, path: Path | str):
        self.path = Path(path)

    # -- connection handling -------------------------------------------------
    @contextmanager
    def conn(self):
        c = sqlite3.connect(self.path, timeout=30)
        c.row_factory = sqlite3.Row
        c.execute("PRAGMA foreign_keys=ON")
        try:
            yield c
            c.commit()
        except Exception:
            c.rollback()
            raise
        finally:
            c.close()

    def init(self) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        with self.conn() as c:
            c.execute("PRAGMA journal_mode=WAL")
            c.executescript(SCHEMA)

    def ping(self) -> bool:
        with self.conn() as c:
            c.execute("SELECT 1").fetchone()
        return True

    # -- key/value -------------------------------------------------------------
    def kv_get(self, key: str) -> Optional[str]:
        with self.conn() as c:
            row = c.execute("SELECT value FROM kv WHERE key=?", (key,)).fetchone()
        return row["value"] if row else None

    def kv_set(self, key: str, value: str) -> None:
        with self.conn() as c:
            c.execute(
                "INSERT INTO kv(key,value) VALUES(?,?) ON CONFLICT(key) DO UPDATE SET value=excluded.value",
                (key, value),
            )

    # -- scheme list ------------------------------------------------------------
    def replace_schemes(self, rows: Iterable[tuple[int, str]], fetched_at: str) -> None:
        with self.conn() as c:
            c.execute("DELETE FROM schemes")
            c.executemany("INSERT INTO schemes(code,name) VALUES(?,?)", rows)
            c.execute(
                "INSERT INTO kv(key,value) VALUES('schemes_fetched_at',?) "
                "ON CONFLICT(key) DO UPDATE SET value=excluded.value",
                (fetched_at,),
            )

    def load_schemes(self) -> list[tuple[int, str]]:
        with self.conn() as c:
            return [(r["code"], r["name"]) for r in c.execute("SELECT code,name FROM schemes")]

    def schemes_fetched_at(self) -> Optional[str]:
        return self.kv_get("schemes_fetched_at")

    # -- NAV cache ----------------------------------------------------------------
    def save_nav(self, code: int, fetched_at: str, meta: dict, records: list, parse_warnings: list[str]) -> None:
        blob = zlib.compress(
            json.dumps({"meta": meta, "records": records, "parse_warnings": parse_warnings}).encode("utf-8"), 6
        )
        with self.conn() as c:
            c.execute(
                "INSERT INTO nav_cache(scheme_code,fetched_at,payload) VALUES(?,?,?) "
                "ON CONFLICT(scheme_code) DO UPDATE SET fetched_at=excluded.fetched_at, payload=excluded.payload",
                (code, fetched_at, blob),
            )

    def load_nav(self, code: int) -> Optional[dict]:
        with self.conn() as c:
            row = c.execute("SELECT fetched_at,payload FROM nav_cache WHERE scheme_code=?", (code,)).fetchone()
        if not row:
            return None
        data = json.loads(zlib.decompress(row["payload"]).decode("utf-8"))
        data["fetched_at"] = row["fetched_at"]
        return data

    def nav_cache_count(self) -> int:
        with self.conn() as c:
            return c.execute("SELECT COUNT(*) AS n FROM nav_cache").fetchone()["n"]

    # -- selected funds --------------------------------------------------------------
    def get_selection(self) -> list[dict]:
        with self.conn() as c:
            rows = c.execute("SELECT scheme_code,scheme_name FROM selected_funds ORDER BY position").fetchall()
        return [{"scheme_code": r["scheme_code"], "scheme_name": r["scheme_name"]} for r in rows]

    def set_selection(self, funds: list[dict]) -> None:
        with self.conn() as c:
            c.execute("DELETE FROM selected_funds")
            c.executemany(
                "INSERT INTO selected_funds(scheme_code,scheme_name,position) VALUES(?,?,?)",
                [(f["scheme_code"], f["scheme_name"], i) for i, f in enumerate(funds)],
            )

    # -- settings ----------------------------------------------------------------------
    def get_settings(self) -> Optional[dict]:
        raw = self.kv_get("settings")
        if not raw:
            return None
        try:
            return json.loads(raw)
        except json.JSONDecodeError:
            return None

    def set_settings(self, settings: dict) -> None:
        self.kv_set("settings", json.dumps(settings))

    # -- benchmarks ------------------------------------------------------------------------
    def upsert_benchmark(self, name: str, source_filename: Optional[str], points: list[tuple[str, float]]) -> dict:
        with self.conn() as c:
            c.execute("DELETE FROM benchmarks WHERE name=?", (name,))  # cascades to points
            cur = c.execute(
                "INSERT INTO benchmarks(name,source_filename,imported_at,n_points,first_date,last_date) VALUES(?,?,?,?,?,?)",
                (name, source_filename, utc_now_iso(), len(points), points[0][0], points[-1][0]),
            )
            bid = cur.lastrowid
            c.executemany(
                "INSERT INTO benchmark_points(benchmark_id,date,value) VALUES(?,?,?)",
                [(bid, d, v) for d, v in points],
            )
        return self.get_benchmark_info(name)

    def list_benchmarks(self) -> list[dict]:
        with self.conn() as c:
            rows = c.execute(
                "SELECT name,source_filename,imported_at,n_points,first_date,last_date FROM benchmarks ORDER BY name"
            ).fetchall()
        return [dict(r) for r in rows]

    def get_benchmark_info(self, name: str) -> Optional[dict]:
        with self.conn() as c:
            row = c.execute(
                "SELECT name,source_filename,imported_at,n_points,first_date,last_date FROM benchmarks WHERE name=?",
                (name,),
            ).fetchone()
        return dict(row) if row else None

    def get_benchmark_points(self, name: str) -> list[tuple[str, float]]:
        with self.conn() as c:
            rows = c.execute(
                "SELECT p.date AS d, p.value AS v FROM benchmark_points p JOIN benchmarks b ON b.id=p.benchmark_id "
                "WHERE b.name=? ORDER BY p.date",
                (name,),
            ).fetchall()
        return [(r["d"], r["v"]) for r in rows]

    def delete_benchmark(self, name: str) -> bool:
        with self.conn() as c:
            cur = c.execute("DELETE FROM benchmarks WHERE name=?", (name,))
        return cur.rowcount > 0

    # -- per-scheme benchmark overrides ----------------------------------------------------------
    def get_overrides(self) -> dict[int, str]:
        with self.conn() as c:
            rows = c.execute("SELECT scheme_code,benchmark_name FROM scheme_benchmark_override").fetchall()
        return {r["scheme_code"]: r["benchmark_name"] for r in rows}

    def set_override(self, scheme_code: int, benchmark_name: Optional[str]) -> None:
        with self.conn() as c:
            if benchmark_name:
                c.execute(
                    "INSERT INTO scheme_benchmark_override(scheme_code,benchmark_name) VALUES(?,?) "
                    "ON CONFLICT(scheme_code) DO UPDATE SET benchmark_name=excluded.benchmark_name",
                    (scheme_code, benchmark_name),
                )
            else:
                c.execute("DELETE FROM scheme_benchmark_override WHERE scheme_code=?", (scheme_code,))
