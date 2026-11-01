from doctor_leads import db
from doctor_leads.filters import SearchFilters


def make():
    conn = db.connect(":memory:")
    db.init_db(conn)
    return conn


def test_init_is_idempotent():
    conn = make()
    db.init_db(conn)
    assert db.table_counts(conn)["doctors"] == 0


def test_settings_roundtrip():
    conn = make()
    assert db.get_setting(conn, "dedup_auto_merge_score") == 95
    db.set_setting(conn, "test_inbox", "me@example.com")
    assert db.get_setting(conn, "test_inbox") == "me@example.com"


def test_find_matching_doctors():
    conn = make()
    rows = [
        ("Dr A", "a", "Orthopaedics & Traumatology", "private", "QUALIFIED", "St. Paul's Hospital"),
        ("Dr B", "b", "Orthopaedics & Traumatology", "public", "QUALIFIED", "Queen Mary Hospital"),
        ("Dr C", "c", "Orthopaedics & Traumatology", "private", "REJECTED", "Union Hospital"),
        ("Dr D", "d", "Cardiology", "private", "QUALIFIED", "Union Hospital"),
        ("Dr E", "e", "Orthopaedics & Traumatology", "clinic", "NEEDS_REVIEW", None),
    ]
    conn.executemany(
        "INSERT INTO doctors (full_name, name_normalized, specialty, hospital_type, status, hospital) VALUES (?,?,?,?,?,?)", rows
    )
    f = SearchFilters(specialty="Orthopaedics & Traumatology", country="HK", hospital_type="private")
    names = [r["full_name"] for r in db.find_matching_doctors(conn, f)]
    assert names == ["Dr A", "Dr E"]  # qualified first; public, rejected and other specialty excluded
    f2 = f.model_copy(update={"included_hospitals": ["St. Paul's Hospital"]})
    assert [r["full_name"] for r in db.find_matching_doctors(conn, f2)] == ["Dr A"]
    f3 = f.model_copy(update={"excluded_hospitals": ["St. Paul's Hospital"]})
    assert [r["full_name"] for r in db.find_matching_doctors(conn, f3)] == ["Dr E"]


def test_status_constraint():
    import sqlite3
    import pytest
    conn = make()
    with pytest.raises(sqlite3.IntegrityError):
        conn.execute("INSERT INTO doctors (full_name, name_normalized, status) VALUES ('x','x','MAYBE')")
