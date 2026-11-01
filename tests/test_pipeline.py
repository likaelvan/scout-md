"""Full research run against offline fakes: register -> candidates -> web -> verify -> store."""
import pytest

from doctor_leads import db, emails, pipeline
from doctor_leads.config import load_config
from doctor_leads.filters import SearchFilters
from tests.fakes import FakeFetcher, FakeSearch

ORTHO = "Orthopaedics & Traumatology"


@pytest.fixture
def env(tmp_path, monkeypatch):
    monkeypatch.setenv("DATA_DIR", str(tmp_path))
    monkeypatch.setenv("SERPER_API_KEY", "")
    monkeypatch.setattr(emails, "mx_ok", lambda domain: True)  # no real DNS in tests
    cfg = load_config()
    conn = db.connect(cfg.db_path)
    db.init_db(conn)
    return cfg, conn


def run(cfg, conn, filters, search=None):
    job_id = pipeline.create_job(conn, filters)
    fetcher, searcher = FakeFetcher(), search or FakeSearch()
    pipeline.run_job(cfg, job_id, fetcher=fetcher, searcher=searcher)
    return pipeline.get_job(conn, job_id), fetcher, searcher


def statuses(conn):
    return {r["mchk_reg_no"]: r for r in conn.execute("SELECT * FROM doctors")}


def test_stops_when_target_reached(env):
    cfg, conn = env
    job, _, searcher = run(cfg, conn, SearchFilters(specialty=ORTHO, target_count=2, excluded_email_domains=["hku.hk"]))
    assert job["status"] == "done", job["error"]
    docs = statuses(conn)
    # Private-hospital and private-clinic doctors are checked first; both qualify, so it stops.
    assert docs["S08-9005"]["status"] == "QUALIFIED" and docs["S08-9005"]["hospital"] == "St. Paul's Hospital"
    assert docs["S08-9002"]["status"] == "QUALIFIED"
    assert "S08-9006" not in docs                      # never needed
    assert "S08-9004" not in docs                      # public-sector doctor never searched
    assert len(searcher.queries) == 2
    assert conn.execute("SELECT COUNT(*) FROM register_entries").fetchone()[0] == 7
    assert conn.execute("SELECT prefix FROM specialty_codes WHERE specialty = ?", (ORTHO,)).fetchone()[0] == "S08"


def test_full_run_flags_and_excludes(env):
    cfg, conn = env
    job, _, _ = run(cfg, conn, SearchFilters(specialty=ORTHO, target_count=10, excluded_email_domains=["hku.hk"]))
    assert job["status"] == "partial" and "Found 2 of 10" in job["error"]
    docs = statuses(conn)
    wong = docs["S08-9006"]   # private (HKSH via web) but only an HKU email -> excluded -> needs review
    assert wong["status"] == "NEEDS_REVIEW" and wong["hospital"] == "Hong Kong Sanatorium & Hospital"
    assert "excluded domain" in wong["status_notes"] and "No email found" in wong["status_notes"]
    joyce = docs["S08-9003"]  # only "Dr Joyce Fung" online -> partial name match
    assert joyce["status"] == "NEEDS_REVIEW" and "partial name match" in joyce["status_notes"]
    assert docs["S08-9007"]["status"] == "NEEDS_REVIEW"   # nothing found at all
    open_reviews = conn.execute("SELECT COUNT(*) FROM review_queue WHERE status = 'open'").fetchone()[0]
    assert open_reviews == 3
    # The excluded HKU email is stored but marked excluded, never used.
    row = conn.execute("SELECT excluded_domain FROM emails WHERE email = 'staff.wong@hku.hk'").fetchone()
    assert row["excluded_domain"] == 1


def test_second_run_reuses_database(env):
    cfg, conn = env
    run(cfg, conn, SearchFilters(specialty=ORTHO, target_count=2))
    f = SearchFilters(specialty=ORTHO, target_count=2, excluded_email_domains=["hku.hk"])
    assert len(pipeline.qualified_with_email(conn, f)) == 2
    job, fetcher, searcher = run(cfg, conn, f)
    assert searcher.queries == []                             # nothing new needed
    assert not any("list.php" in u for u in fetcher.calls)    # register not re-read (fresh)


def test_search_credits_run_out(env):
    cfg, conn = env

    class NoSearch:
        def search(self, q, num=10):
            from doctor_leads.search import SearchQuotaExceeded
            raise SearchQuotaExceeded("Serper credits used up")

    job, _, _ = run(cfg, conn, SearchFilters(specialty=ORTHO, target_count=5), search=NoSearch())
    assert job["status"] == "partial" and "credits" in job["error"]


def test_cancel_marks_job(env):
    cfg, conn = env
    job_id = pipeline.create_job(conn, SearchFilters(specialty=ORTHO, target_count=5))
    pipeline.cancel_job(conn, job_id)  # cancelled before the worker starts
    fetcher = FakeFetcher()
    pipeline.run_job(cfg, job_id, fetcher=fetcher, searcher=FakeSearch())
    assert pipeline.get_job(conn, job_id)["status"] == "cancelled"
    assert fetcher.calls == []


def test_no_serper_key_saves_register_details(env, monkeypatch):
    cfg, conn = env
    job_id = pipeline.create_job(conn, SearchFilters(specialty=ORTHO, target_count=3))
    pipeline.run_job(cfg, job_id, fetcher=FakeFetcher(), searcher=None)   # cfg has no SERPER_API_KEY
    job = pipeline.get_job(conn, job_id)
    assert job["status"] == "partial" and "web search is off" in job["error"]
    docs = statuses(conn)
    assert docs["S08-9005"]["hospital"] == "St. Paul's Hospital"
    assert docs["S08-9005"]["status"] == "NEEDS_REVIEW" and "No email found" in docs["S08-9005"]["status_notes"]


def test_unknown_practice_doctors_listed_for_review(env):
    cfg, conn = env
    run(cfg, conn, SearchFilters(specialty=ORTHO, target_count=10, excluded_email_domains=["hku.hk"]))
    f = SearchFilters(specialty=ORTHO)
    listed = {r["mchk_reg_no"]: r["status"] for r in db.find_matching_doctors(conn, f)}
    assert listed["S08-9007"] == "NEEDS_REVIEW"     # practice unknown -> still listed, for review
    assert "S08-9004" not in listed                 # public sector -> never stored as a private lead


def test_excluded_email_never_displayed(env):
    from doctor_leads.ui_common import leads_dataframe
    cfg, conn = env
    run(cfg, conn, SearchFilters(specialty=ORTHO, target_count=10, excluded_email_domains=["hku.hk"]))
    wong = conn.execute("SELECT id FROM doctors WHERE mchk_reg_no = 'S08-9006'").fetchone()["id"]
    df = leads_dataframe(conn, [wong], [])   # even with no exclusions picked in the form
    assert df.iloc[0]["Email"] is None and df.iloc[0]["Email status"] == "none found"
