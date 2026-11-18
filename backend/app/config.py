"""Runtime configuration. Everything can be overridden with environment variables."""
from __future__ import annotations

import os
from pathlib import Path

BASE_DIR = Path(__file__).resolve().parent.parent
CONFIG_DIR = BASE_DIR / "config"
BENCHMARK_MAPPING_FILE = CONFIG_DIR / "benchmark_mapping.json"

APP_VERSION = "1.0.0"
METHODOLOGY_VERSION = "1.0"

MAX_FUNDS = 20
ANALYZE_CONCURRENCY = 4  # polite parallelism towards the free provider


def data_dir() -> Path:
    return Path(os.getenv("MF_DATA_DIR", BASE_DIR / "data"))


def db_path() -> Path:
    return Path(os.getenv("MF_DB_PATH", data_dir() / "mf_analyzer.db"))


def mfapi_base_url() -> str:
    return os.getenv("MFAPI_BASE_URL", "https://api.mfapi.in").rstrip("/")


def cors_origins() -> list[str]:
    raw = os.getenv("MF_CORS_ORIGINS")
    if raw:
        return [o.strip() for o in raw.split(",") if o.strip()]
    # Only the local Vite dev server may call the backend from a browser.
    return [
        "http://localhost:5173",
        "http://127.0.0.1:5173",
        "http://localhost:4173",
        "http://127.0.0.1:4173",
    ]


def schemes_ttl_hours() -> float:
    return float(os.getenv("MF_SCHEMES_TTL_HOURS", "24"))


def nav_ttl_hours() -> float:
    return float(os.getenv("MF_NAV_TTL_HOURS", "6"))
