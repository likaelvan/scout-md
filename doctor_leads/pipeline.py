"""The research run: register -> candidates -> web enrichment -> verification -> storage.

Runs in a background thread with its own DB connection, writes progress to the
`jobs` row (the UI polls it), checkpoints each doctor in `run_state` so a run that
stops halfway can be resumed, and stops early when the target is reached.
"""
from __future__ import annotations

import json
import sqlite3
import threading
import traceback
from collections import deque

from . import db
from . import emails as em
from .classify import classify_address
from .config import Config
from .enrich import enrich
from .filters import SearchFilters
from .http import Fetcher, SourceUnavailable
from .names import parse_register_name
from .search import SearchError, SearchNotConfigured, SearchQuotaExceeded, SerperSearch
from .sources import mchk
from .verify import Decision, decide

_threads: dict[int, threading.Thread] = {}


def _alive(job_id: int) -> bool:
    """Is a worker thread running this job? Checks thread names, so it still works
    after Streamlit reloads this module (which would empty `_threads`)."""
    name = f"job-{job_id}"
    return any(t.name == name and t.is_alive() for t in threading.enumerate())


# ===================================================================== job records
def create_job(conn: sqlite3.Connection, filters: SearchFilters) -> int:
    cur = conn.execute(
        "INSERT INTO jobs (request_text, filters_json, filters_key, target_count, status) VALUES (?,?,?,?, 'queued')",
        (filters.summary(), filters.model_dump_json(), filters.filters_key(), filters.target_count),
    )
    conn.commit()
    return cur.lastrowid


def get_job(conn: sqlite3.Connection, job_id: int) -> dict | None:
    row = conn.execute("SELECT * FROM jobs WHERE id = ?", (job_id,)).fetchone()
    if not row:
        return None
    job = dict(row)
    job["progress"] = json.loads(job["progress_json"] or "{}")
    job["alive"] = _alive(job_id)
    return job


def cancel_job(conn: sqlite3.Connection, job_id: int) -> None:
    conn.execute("UPDATE jobs SET status = 'cancelled' WHERE id = ? AND status IN ('queued','running')", (job_id,))
    conn.commit()


def mark_orphans(conn: sqlite3.Connection) -> None:
    """Jobs left 'running' by a previous app session (closed window, crash) become resumable."""
    for row in conn.execute("SELECT id FROM jobs WHERE status IN ('queued','running')").fetchall():
        if not _alive(row["id"]):
            conn.execute("UPDATE jobs SET status='partial', error='Stopped before finishing (app closed or restarted). "
                         "Resume to continue where it left off.' WHERE id = ?", (row["id"],))
    conn.commit()


def start_job(cfg: Config, job_id: int) -> None:
    if _alive(job_id):
        return
    t = threading.Thread(target=run_job, args=(cfg, job_id), daemon=True, name=f"job-{job_id}")
    _threads[job_id] = t
    t.start()


# ===================================================================== counting
def qualified_with_email(conn: sqlite3.Connection, filters: SearchFilters) -> list[sqlite3.Row]:
    rows = [r for r in db.find_matching_doctors(conn, filters) if r["status"] == "QUALIFIED"]
    if not filters.require_email:
        return rows
    out = []
    for r in rows:
        emails = conn.execute("SELECT email FROM emails WHERE doctor_id = ? AND status = 'valid' AND excluded_domain = 0",
                              (r["id"],)).fetchall()
        if any(not em.check_email(e["email"], filters.excluded_email_domains, check_mx=False).excluded for e in emails):
            out.append(r)
    return out


# ===================================================================== storage
def save_doctor(conn: sqlite3.Connection, entry: sqlite3.Row, specialty: str, d: Decision, web, name) -> int:
    from .names import normalize_free_name
    existing = conn.execute("SELECT id FROM doctors WHERE mchk_reg_no = ?", (entry["reg_no"],)).fetchone()
    values = dict(
        full_name=name.display, name_normalized=normalize_free_name(entry["name_en"]), name_zh=entry["name_zh"],
        specialty=specialty, mchk_reg_no=entry["reg_no"], hospital=d.hospital,
        hospital_type=d.hospital_type if d.hospital_type in ("private", "public", "clinic") else "unknown",
        country="HK", region=d.region, profile_url=(web.profile_url if web else None),
        register_address=entry["address"], status=d.status, status_notes=d.summary,
    )
    if existing:
        doc_id = existing["id"]
        sets = ", ".join(f"{k} = :{k}" for k in values)
        conn.execute(f"UPDATE doctors SET {sets}, last_verified_at = datetime('now'), updated_at = datetime('now') "
                     f"WHERE id = :id", {**values, "id": doc_id})
    else:
        cols = ", ".join(values)
        conn.execute(f"INSERT INTO doctors ({cols}, last_verified_at) VALUES ({', '.join(':' + k for k in values)}, datetime('now'))",
                     values)
        doc_id = conn.execute("SELECT last_insert_rowid()").fetchone()[0]

    conn.execute("""INSERT INTO sources (doctor_id, url, source_type, priority, extracted_json, extraction_method)
                    VALUES (?, ?, 'mchk_register', 1, ?, 'rules') ON CONFLICT(doctor_id, url) DO UPDATE SET
                    extracted_json = excluded.extracted_json, fetched_at = datetime('now')""",
                 (doc_id, mchk.DETAIL_URL.format(reg_no=entry["reg_no"]), json.dumps(dict(entry), default=str)))
    for url in (web.strong_pages if web else []):
        stype = "hospital_directory" if url in (web.private_hospitals or {}).values() else "search_result"
        conn.execute("""INSERT INTO sources (doctor_id, url, source_type, priority, extraction_method)
                        VALUES (?, ?, ?, ?, 'rules') ON CONFLICT(doctor_id, url) DO UPDATE SET fetched_at = datetime('now')""",
                     (doc_id, url, stype, 2 if stype == "hospital_directory" else 4))
    for e in d.emails:
        conn.execute(
            """INSERT INTO emails (doctor_id, email, email_normalized, domain, source_url, kind, syntax_ok, mx_ok,
                                   excluded_domain, status, checked_at)
               VALUES (?,?,?,?,?,?,?,?,?,?, datetime('now'))
               ON CONFLICT(doctor_id, email_normalized) DO UPDATE SET kind=excluded.kind, mx_ok=excluded.mx_ok,
                   excluded_domain=excluded.excluded_domain, status=excluded.status, checked_at=excluded.checked_at""",
            (doc_id, e.email, e.email.lower(), e.check.domain, e.source_url,
             e.kind if e.kind in ("personal", "clinic_shared", "guessed", "unknown") else "unknown",
             int(e.check.syntax_ok), None if e.check.mx_ok is None else int(e.check.mx_ok), int(e.check.excluded),
             "valid" if e.usable else ("invalid" if e.check.status == "invalid" else "risky")),
        )
    for field_, a, src_a, b, src_b in d.conflicts:
        conn.execute("INSERT INTO field_conflicts (doctor_id, field, value_a, source_a, value_b, source_b, chosen_value) "
                     "VALUES (?,?,?,?,?,?,?)", (doc_id, field_, a, src_a, b, src_b, b))
    conn.execute("UPDATE review_queue SET status='resolved', resolution='superseded', resolved_at=datetime('now') "
                 "WHERE doctor_id = ? AND kind = 'lead' AND status = 'open'", (doc_id,))
    if d.status == "NEEDS_REVIEW":
        conn.execute("INSERT INTO review_queue (kind, doctor_id, reason) VALUES ('lead', ?, ?)", (doc_id, " · ".join(d.review)))
    conn.commit()
    return doc_id


# ===================================================================== the run
class _Progress:
    def __init__(self, conn: sqlite3.Connection, job_id: int):
        self.conn, self.job_id = conn, job_id
        self.state = {"stage": "starting", "message": "Starting…", "fraction": 0.0, "qualified": 0, "checked": 0,
                      "log": []}
        self._log = deque(maxlen=30)

    def update(self, message: str | None = None, fraction: float | None = None, log: str | None = None, **kw):
        if message is not None:
            self.state["message"] = message
        if fraction is not None:
            self.state["fraction"] = max(0.0, min(1.0, fraction))
        if log:
            self._log.appendleft(log)
            self.state["log"] = list(self._log)
        self.state.update(kw)
        self.conn.execute("UPDATE jobs SET progress_json = ? WHERE id = ?", (json.dumps(self.state), self.job_id))
        self.conn.commit()


def run_job(cfg: Config, job_id: int, *, fetcher: Fetcher | None = None, searcher=None, check_mx: bool = True) -> None:
    conn = db.connect(cfg.db_path)
    db.init_db(conn)
    p = _Progress(conn, job_id)
    job = conn.execute("SELECT * FROM jobs WHERE id = ?", (job_id,)).fetchone()
    filters = SearchFilters.model_validate_json(job["filters_json"])
    if job["status"] == "cancelled":
        conn.close()
        return
    conn.execute("UPDATE jobs SET status='running', error=NULL, started_at=COALESCE(started_at, datetime('now')) WHERE id=?",
                 (job_id,))
    conn.commit()

    def stopped() -> bool:
        return conn.execute("SELECT status FROM jobs WHERE id = ?", (job_id,)).fetchone()["status"] == "cancelled"

    settings = db.all_settings(conn)
    fetcher = fetcher or Fetcher(conn, min_interval=cfg.http_min_interval,
                                 cache_max_age_days=int(settings["cache_max_age_days"]))
    final_status, error = "done", None
    found_new = 0
    try:
        # 1. Medical Council register (monthly refresh)
        age = mchk.register_age_days(conn)
        if age is None or age > settings["register_max_age_days"]:
            p.update("Reading the Medical Council specialist register (first time takes a few minutes)…", 0.0,
                     stage="register", log="Refreshing Medical Council register")
            n = mchk.sync_register(conn, fetcher, progress=lambda m, f: p.update(m, f * 0.3), should_stop=stopped)
            p.update(log=f"Register: {n} entries read")
            if stopped():
                raise _Cancelled()

        # 2. Which register code is this specialty?
        p.update("Matching the specialty to the register…", 0.3, stage="specialty")
        prefix = mchk.prefix_for_specialty(conn, fetcher, filters.specialty, progress=lambda m, f: p.update(m))
        if not prefix:
            raise RuntimeError(f"Couldn't find {filters.specialty} on the Medical Council register.")
        p.update(log=f"{filters.specialty} = register code {prefix}")

        # 3. Candidates, best bets first; skip ones already verified recently
        entries = conn.execute("SELECT * FROM register_entries WHERE prefix = ? ORDER BY reg_no", (prefix,)).fetchall()
        fresh = {r["mchk_reg_no"] for r in conn.execute(
            "SELECT mchk_reg_no FROM doctors WHERE mchk_reg_no IS NOT NULL AND julianday('now') - julianday(last_verified_at) < ?",
            (settings["lead_stale_after_days"],))}
        done_keys = {r["item_key"] for r in conn.execute(
            "SELECT item_key FROM run_state WHERE job_id = ? AND stage = 'enrich' AND status IN ('done','skipped')", (job_id,))}
        order = {"private": 0, "clinic": 1, "unknown": 2, "public": 3}
        if filters.hospital_type == "public":
            order = {"public": 0, "unknown": 1, "clinic": 2, "private": 3}
        cands = []
        for e in entries:
            if e["reg_no"] in fresh or e["reg_no"] in done_keys:
                continue
            pr = classify_address(e["address"])
            if filters.hospital_type == "private" and pr.hospital_type == "public":
                continue   # don't spend searches on clear public-sector doctors
            if filters.hospital_type == "public" and pr.hospital_type in ("private", "clinic"):
                continue
            if filters.region and pr.region and pr.region != filters.region:
                continue
            if filters.included_hospitals and pr.hospital and pr.hospital not in filters.included_hospitals:
                continue
            cands.append((order.get(pr.hospital_type, 9), e, pr))
        cands.sort(key=lambda c: c[0])
        p.update(f"{len(entries)} {filters.specialty} specialists on the register, {len(cands)} worth checking",
                 0.35, stage="enrich", log=f"{len(cands)} candidates after filtering by register address")

        # 4. Enrich + verify until the target is met
        if searcher is None:
            try:
                searcher = SerperSearch(cfg.serper_api_key)
            except SearchNotConfigured as e:
                p.update(log=f"Web search off: {e}. Saving register details only.")
        shared = {r["email_normalized"] for r in conn.execute(
            "SELECT email_normalized FROM emails GROUP BY email_normalized HAVING COUNT(DISTINCT doctor_id) >= 1")}
        budget = int(settings["max_candidates_per_run"])
        have = len(qualified_with_email(conn, filters))
        checked = 0
        for _, entry, practice in cands:
            if have >= filters.target_count:
                p.update(log=f"Target reached: {have} qualified")
                break
            if checked >= budget:
                final_status = "partial"
                error = f"Stopped after checking {budget} doctors (search budget per run). Run again to continue."
                break
            if stopped():
                raise _Cancelled()
            name = parse_register_name(entry["name_en"], entry["name_zh"])
            p.update(f"Checking Dr {name.display} ({checked + 1} of up to {min(len(cands), budget)})…",
                     0.35 + 0.65 * (have / max(filters.target_count, 1)), checked=checked, qualified=have)
            web = None
            if searcher:
                try:
                    web = enrich(name, filters.specialty, searcher, fetcher)
                except SearchQuotaExceeded as e:
                    final_status, error = "partial", f"Web search stopped: {e}."
                    p.update(log=error)
                    break
                except SearchError as e:
                    p.update(log=f"Search failed for {name.display}: {e}")
            own = {em_ for em_ in shared}  # emails already stored for *other* doctors
            mine = {r["email_normalized"] for r in conn.execute(
                "SELECT e.email_normalized FROM emails e JOIN doctors d ON d.id = e.doctor_id WHERE d.mchk_reg_no = ?",
                (entry["reg_no"],))}
            d = decide(entry["reg_no"], filters.specialty, practice, web, filters, shared_emails=own - mine,
                       check_mx=check_mx)
            save_doctor(conn, entry, filters.specialty, d, web, name)
            for e in d.emails:
                shared.add(e.email.lower())
            conn.execute("INSERT OR REPLACE INTO run_state (job_id, stage, item_key, status, detail) VALUES (?, 'enrich', ?, 'done', ?)",
                         (job_id, entry["reg_no"], d.status))
            conn.commit()
            checked += 1
            found_new += 1
            if d.status == "QUALIFIED" and (d.best_email or not filters.require_email):
                have += 1
            icon = {"QUALIFIED": "✅", "NEEDS_REVIEW": "🟡", "REJECTED": "⛔"}[d.status]
            p.update(log=f"{icon} Dr {name.display}: {d.status.replace('_', ' ').lower()}"
                         + (f" ({(d.reject + d.review)[0]})" if d.reject or d.review else ""),
                     checked=checked, qualified=have)
        else:
            if have < filters.target_count:
                final_status = "partial"
                error = (f"Found {have} of {filters.target_count}: no more matching specialists to check"
                         + ("" if searcher else " (web search is off, so no emails were found)") + ".")
        p.update("Finished" if final_status == "done" else (error or "Stopped"), 1.0, stage="finished", qualified=have)
    except _Cancelled:
        final_status, error = "cancelled", "Stopped by you."
        p.update("Stopped", stage="finished")
    except (SourceUnavailable, mchk.RegisterFormatChanged) as e:
        final_status, error = ("partial" if found_new else "failed"), f"Medical Council website problem: {e}"
        p.update(error, stage="finished", log=error)
    except Exception as e:  # noqa: BLE001 - surface anything unexpected in the UI
        final_status, error = ("partial" if found_new else "failed"), f"{type(e).__name__}: {e}"
        p.update(error, stage="finished", log=error, traceback=traceback.format_exc()[-2000:])
    conn.execute("UPDATE jobs SET status=?, error=?, found_new=found_new+?, finished_at=datetime('now') WHERE id=?",
                 (final_status, error, found_new, job_id))
    conn.commit()
    conn.close()


class _Cancelled(Exception):
    pass
