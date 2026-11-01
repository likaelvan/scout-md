"""SQLite access: connection, schema setup, settings, and simple queries."""
from __future__ import annotations

import json
import sqlite3
from pathlib import Path
from typing import Any

SCHEMA_PATH = Path(__file__).with_name("schema.sql")
SCHEMA_VERSION = 2

DEFAULT_SETTINGS: dict[str, Any] = {
    "default_excluded_email_domains": [],
    "cache_max_age_days": 30,          # pages older than this get re-fetched
    "lead_stale_after_days": 30,       # leads older than this get re-verified
    "dedup_auto_merge_score": 95,
    "dedup_review_score": 85,
    "test_inbox": None,
    "register_max_age_days": 30,       # re-read the Medical Council register after this
    "max_candidates_per_run": 80,      # web-search budget per run (protects Serper credits)
}


def connect(db_path: Path | str) -> sqlite3.Connection:
    db_path = Path(db_path)
    if str(db_path) != ":memory:":
        db_path.parent.mkdir(parents=True, exist_ok=True)
    # check_same_thread=False: Streamlit reruns and background jobs use other threads.
    conn = sqlite3.connect(str(db_path), check_same_thread=False, timeout=30)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON")
    conn.execute("PRAGMA busy_timeout = 30000")
    if str(db_path) != ":memory:":
        conn.execute("PRAGMA journal_mode = WAL")  # readers don't block the writer
    return conn


def _migrate(conn: sqlite3.Connection) -> None:
    """Small in-place upgrades for databases created by older versions."""
    cols = {r["name"] for r in conn.execute("PRAGMA table_info(doctors)")}
    if cols and "register_address" not in cols:
        conn.execute("ALTER TABLE doctors ADD COLUMN register_address TEXT")


def init_db(conn: sqlite3.Connection) -> None:
    _migrate(conn)
    conn.executescript(SCHEMA_PATH.read_text(encoding="utf-8"))
    for key, value in DEFAULT_SETTINGS.items():
        conn.execute("INSERT OR IGNORE INTO settings (key, value) VALUES (?, ?)", (key, json.dumps(value)))
    conn.execute(f"PRAGMA user_version = {SCHEMA_VERSION}")
    conn.commit()


def get_setting(conn: sqlite3.Connection, key: str) -> Any:
    row = conn.execute("SELECT value FROM settings WHERE key = ?", (key,)).fetchone()
    return json.loads(row["value"]) if row else DEFAULT_SETTINGS.get(key)


def set_setting(conn: sqlite3.Connection, key: str, value: Any) -> None:
    conn.execute(
        "INSERT INTO settings (key, value) VALUES (?, ?) ON CONFLICT(key) DO UPDATE SET value = excluded.value",
        (key, json.dumps(value)),
    )
    conn.commit()


def all_settings(conn: sqlite3.Connection) -> dict[str, Any]:
    out = dict(DEFAULT_SETTINGS)
    out.update({r["key"]: json.loads(r["value"]) for r in conn.execute("SELECT key, value FROM settings")})
    return out


def table_counts(conn: sqlite3.Connection) -> dict[str, int]:
    tables = ["doctors", "sources", "emails", "review_queue", "outreach_log", "jobs", "search_log", "page_cache"]
    return {t: conn.execute(f"SELECT COUNT(*) FROM {t}").fetchone()[0] for t in tables}


def find_matching_doctors(conn: sqlite3.Connection, filters) -> list[sqlite3.Row]:
    """Database-first lookup: leads already stored that fit the filters.

    Rejected and merged records are skipped. Email rules (excluded domains,
    require_email) are applied per email by the caller, since a doctor may have
    several emails and only some are excluded.
    """
    sql = "SELECT * FROM doctors WHERE status NOT IN ('REJECTED','MERGED')"
    args: list[Any] = []
    if filters.specialty:
        sql += " AND specialty = ?"
        args.append(filters.specialty)
    if filters.country:
        sql += " AND country = ?"
        args.append(filters.country)
    if filters.region:
        sql += " AND region = ?"
        args.append(filters.region)
    # 'unknown' stays in: those doctors are waiting for review, not ruled out.
    if filters.hospital_type == "private":
        sql += " AND hospital_type IN ('private','clinic','unknown')"
    elif filters.hospital_type == "public":
        sql += " AND hospital_type IN ('public','unknown')"
    if filters.included_hospitals:
        sql += f" AND hospital IN ({','.join('?' * len(filters.included_hospitals))})"
        args += filters.included_hospitals
    if filters.excluded_hospitals:
        sql += f" AND COALESCE(hospital,'') NOT IN ({','.join('?' * len(filters.excluded_hospitals))})"
        args += filters.excluded_hospitals
    sql += " ORDER BY CASE status WHEN 'QUALIFIED' THEN 0 WHEN 'NEEDS_REVIEW' THEN 1 ELSE 2 END, last_verified_at DESC"
    return conn.execute(sql, args).fetchall()
