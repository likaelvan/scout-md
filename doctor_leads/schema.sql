-- Doctor Leads schema (SQLite). Safe to run repeatedly.

CREATE TABLE IF NOT EXISTS doctors (
    id                INTEGER PRIMARY KEY,
    full_name         TEXT NOT NULL,
    name_normalized   TEXT NOT NULL,            -- for dedup: no titles/credentials, lowercase, sorted tokens
    name_zh           TEXT,
    specialty         TEXT,                     -- canonical (taxonomy.SPECIALTIES)
    mchk_reg_no       TEXT UNIQUE,              -- Medical Council registration no. (strongest identity key)
    hospital          TEXT,
    hospital_type     TEXT CHECK (hospital_type IN ('private','public','clinic','unknown')) DEFAULT 'unknown',
    country           TEXT DEFAULT 'HK',
    region            TEXT,
    profile_url       TEXT,
    register_address  TEXT,                     -- address published on the Medical Council register
    status            TEXT NOT NULL DEFAULT 'NEW'
                      CHECK (status IN ('NEW','QUALIFIED','NEEDS_REVIEW','REJECTED','MERGED')),
    status_notes      TEXT,                     -- human-readable reasons for the status
    merged_into_id    INTEGER REFERENCES doctors(id),
    last_verified_at  TEXT,
    created_at        TEXT NOT NULL DEFAULT (datetime('now')),
    updated_at        TEXT NOT NULL DEFAULT (datetime('now'))
);
CREATE INDEX IF NOT EXISTS ix_doctors_lookup ON doctors (specialty, country, hospital_type, status);
CREATE INDEX IF NOT EXISTS ix_doctors_name ON doctors (name_normalized);

-- Every page a doctor was seen on, and what each source said (provenance).
CREATE TABLE IF NOT EXISTS sources (
    id               INTEGER PRIMARY KEY,
    doctor_id        INTEGER NOT NULL REFERENCES doctors(id) ON DELETE CASCADE,
    url              TEXT NOT NULL,
    source_type      TEXT NOT NULL CHECK (source_type IN ('mchk_register','hospital_directory','clinic_site','search_result','manual','other')),
    priority         INTEGER NOT NULL,          -- lower = more trusted
    extracted_json   TEXT,                      -- fields as extracted from this source
    extraction_method TEXT CHECK (extraction_method IN ('rules','llm','manual')),
    fetched_at       TEXT NOT NULL DEFAULT (datetime('now')),
    UNIQUE (doctor_id, url)
);

CREATE TABLE IF NOT EXISTS emails (
    id                INTEGER PRIMARY KEY,
    doctor_id         INTEGER NOT NULL REFERENCES doctors(id) ON DELETE CASCADE,
    email             TEXT NOT NULL,
    email_normalized  TEXT NOT NULL,
    domain            TEXT NOT NULL,
    source_url        TEXT,                     -- where it was found; NULL = guessed
    kind              TEXT NOT NULL DEFAULT 'unknown' CHECK (kind IN ('personal','clinic_shared','guessed','unknown')),
    syntax_ok         INTEGER,
    mx_ok             INTEGER,
    excluded_domain   INTEGER NOT NULL DEFAULT 0,
    status            TEXT NOT NULL DEFAULT 'unverified' CHECK (status IN ('unverified','valid','invalid','risky')),
    checked_at        TEXT,
    UNIQUE (doctor_id, email_normalized)
);
CREATE INDEX IF NOT EXISTS ix_emails_norm ON emails (email_normalized);

-- When two sources disagree on a field, keep both and record what was chosen.
CREATE TABLE IF NOT EXISTS field_conflicts (
    id             INTEGER PRIMARY KEY,
    doctor_id      INTEGER NOT NULL REFERENCES doctors(id) ON DELETE CASCADE,
    field          TEXT NOT NULL,
    value_a        TEXT, source_a TEXT,
    value_b        TEXT, source_b TEXT,
    chosen_value   TEXT,
    created_at     TEXT NOT NULL DEFAULT (datetime('now'))
);

CREATE TABLE IF NOT EXISTS review_queue (
    id           INTEGER PRIMARY KEY,
    kind         TEXT NOT NULL CHECK (kind IN ('lead','duplicate','email','conflict')),
    doctor_id    INTEGER REFERENCES doctors(id) ON DELETE CASCADE,
    other_id     INTEGER REFERENCES doctors(id) ON DELETE CASCADE,  -- for duplicates
    reason       TEXT NOT NULL,
    score        REAL,
    status       TEXT NOT NULL DEFAULT 'open' CHECK (status IN ('open','resolved')),
    resolution   TEXT,
    created_at   TEXT NOT NULL DEFAULT (datetime('now')),
    resolved_at  TEXT
);

CREATE TABLE IF NOT EXISTS outreach_log (
    id            INTEGER PRIMARY KEY,
    doctor_id     INTEGER NOT NULL REFERENCES doctors(id),
    email         TEXT NOT NULL,
    subject       TEXT,
    body          TEXT,
    facts_json    TEXT,                         -- the facts the draft was allowed to use
    status        TEXT NOT NULL DEFAULT 'draft' CHECK (status IN ('draft','approved','rejected','sent','failed')),
    test_mode     INTEGER NOT NULL DEFAULT 1,
    sent_to       TEXT,                         -- actual recipient (test inbox in TEST_MODE)
    error         TEXT,
    created_at    TEXT NOT NULL DEFAULT (datetime('now')),
    approved_at   TEXT,
    sent_at       TEXT
);

CREATE TABLE IF NOT EXISTS jobs (
    id               INTEGER PRIMARY KEY,
    request_text     TEXT NOT NULL,
    filters_json     TEXT NOT NULL,
    filters_key      TEXT NOT NULL,
    target_count     INTEGER NOT NULL,
    status           TEXT NOT NULL DEFAULT 'queued' CHECK (status IN ('queued','running','done','partial','failed','cancelled')),
    found_existing   INTEGER DEFAULT 0,
    found_new        INTEGER DEFAULT 0,
    progress_json    TEXT,
    error            TEXT,
    llm_calls        INTEGER DEFAULT 0,
    llm_tokens       INTEGER DEFAULT 0,
    rate_limit_hits  INTEGER DEFAULT 0,
    created_at       TEXT NOT NULL DEFAULT (datetime('now')),
    started_at       TEXT,
    finished_at      TEXT
);

-- Checkpoints so an interrupted job can resume where it stopped.
CREATE TABLE IF NOT EXISTS run_state (
    job_id      INTEGER NOT NULL REFERENCES jobs(id) ON DELETE CASCADE,
    stage       TEXT NOT NULL,
    item_key    TEXT NOT NULL,
    status      TEXT NOT NULL CHECK (status IN ('pending','done','failed','skipped')),
    detail      TEXT,
    updated_at  TEXT NOT NULL DEFAULT (datetime('now')),
    PRIMARY KEY (job_id, stage, item_key)
);

-- Which source/query has already been searched for which population of doctors.
CREATE TABLE IF NOT EXISTS search_log (
    id            INTEGER PRIMARY KEY,
    filters_key   TEXT NOT NULL,
    source_name   TEXT NOT NULL,
    query         TEXT,
    status        TEXT NOT NULL CHECK (status IN ('ok','failed','partial')),
    result_count  INTEGER DEFAULT 0,
    searched_at   TEXT NOT NULL DEFAULT (datetime('now'))
);
CREATE INDEX IF NOT EXISTS ix_search_log ON search_log (filters_key, source_name);

CREATE TABLE IF NOT EXISTS page_cache (
    url           TEXT PRIMARY KEY,
    http_status   INTEGER,
    content_hash  TEXT,
    body          TEXT,
    fetched_at    TEXT NOT NULL DEFAULT (datetime('now'))
);

CREATE TABLE IF NOT EXISTS settings (
    key    TEXT PRIMARY KEY,
    value  TEXT NOT NULL      -- JSON
);

-- Raw copy of the Medical Council specialist register (refreshed monthly).
CREATE TABLE IF NOT EXISTS register_entries (
    reg_no         TEXT PRIMARY KEY,          -- e.g. S08-0189
    prefix         TEXT NOT NULL,             -- e.g. S08 (identifies the specialty)
    name_en        TEXT NOT NULL,
    name_zh        TEXT,
    address        TEXT,
    qualification  TEXT,
    year           INTEGER,
    fetched_at     TEXT NOT NULL DEFAULT (datetime('now'))
);
CREATE INDEX IF NOT EXISTS ix_register_prefix ON register_entries (prefix);

-- Which register prefix means which specialty (learned from doctor detail pages).
CREATE TABLE IF NOT EXISTS specialty_codes (
    prefix         TEXT PRIMARY KEY,
    specialty      TEXT,                      -- NULL = checked, not a specialty we support
    sample_reg_no  TEXT,
    verified_at    TEXT NOT NULL DEFAULT (datetime('now'))
);
