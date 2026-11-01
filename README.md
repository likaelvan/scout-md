# Scout MD

Scout MD is a local tool that finds doctor leads, checks them, removes duplicates and helps with outreach. A person approves every email before it's sent.
It has a Streamlit UI and a SQLite database, and uses Groq for the AI steps.

**Status:** Milestones 1 (foundation) and 2 (research) are done. Duplicate matching and Excel export come in Milestone 3.

## Requirements
- Windows, macOS or Linux with Python 3.10+
- A [Serper](https://serper.dev) API key (Google search results), used to find practice details and emails
- A [Groq](https://console.groq.com) API key, used for AI email drafts (later milestone)

## Setup (Windows, PowerShell)

```powershell
cd C:\Users\Globalco\OneDrive\Documents\VannAI\doctor_search
python -m venv .venv
.venv\Scripts\Activate.ps1
pip install -r requirements.txt

python -m scripts.check_llm      # checks your Groq key and lists the models you can use
python -m scripts.probe_sources  # live check of the Medical Council register and Serper
streamlit run app.py             # opens http://localhost:8501
python -m pytest -q              # runs the tests (offline, no API keys needed)
```

Copy `.env.example` to `.env` and fill in your keys (`copy .env.example .env`). `SERPER_API_KEY` is needed to find emails; `GROQ_API_KEY` is used for email drafts later.
The database lives at `C:\Users\<you>\doctor_data\leads.db`, outside OneDrive, because OneDrive syncing can lock or corrupt a live database file.
Set `DATA_DIR` in `.env` to move it.

## Layout

```
app.py                     Streamlit entry point (navigation + sidebar)
ui/                        one file per page: new_search, leads, review, outreach, runs
doctor_leads/
  config.py                .env loading, provider/model, data paths, TEST_MODE
  llm.py                   Groq/OpenAI-compatible JSON client with retries + usage tracking
  taxonomy.py              canonical specialties/locations/hospitals, synonyms, domain exclusion
  filters.py               SearchFilters: what a search asks for (built from the New Search form)
  schema.sql, db.py        SQLite schema, settings, database-first lookup
  sources/mchk.py          Medical Council specialist register (reader + specialty-code learning)
  http.py                  polite fetching: per-site rate limit, retries, robots.txt, page cache
  search.py                Serper (Google) search client
  names.py                 register-name parsing and finding a doctor on a web page
  classify.py              address/URL -> private hospital, clinic or public sector; region
  emails.py                email extraction, syntax/MX/excluded-domain checks, personal vs clinic inbox
  enrich.py                search -> read pages -> evidence tied to source URLs
  verify.py                qualification rules -> QUALIFIED / NEEDS_REVIEW / REJECTED with reasons
  pipeline.py              background search runs with progress, checkpoints and early stop
  ui_common.py             shared Streamlit helpers (config, DB connection, tables)
scripts/check_llm.py       terminal check of the LLM setup
scripts/probe_sources.py   live check of the data sources (saves raw pages to debug/)
tests/                     pytest suite (offline: fake register pages, fake web, fake search)
assets/                    logo and icon
```

## Design rules
- **Searches are built from a form, not free text.** Specialty, location, hospital type and email exclusions are picked from fixed lists, so every search is a valid doctor search.
- **The AI is never trusted on its own.** It's only used for messy pages and email drafts, and its output is always checked before anything is stored.
- **Similar requests share stored data.** `filters_key` identifies the group of doctors being searched for (specialty, location and hospital type), so "20 HK ortho" and "50 HK orthopaedic, no HKU" reuse the same stored leads.
- **TEST_MODE is on by default.** While it's on, no email can reach a doctor.

## How a search runs
1. **Medical Council register.** The full specialist list (about 9,000 entries) is read once a month. The first run takes a few minutes.
2. **Specialty code.** The register number prefix for the specialty is looked up (S08 is Orthopaedics & Traumatology) and remembered.
3. **Candidates.** The register address sorts doctors into private hospital, private clinic, public sector or unknown. Public-sector doctors are skipped when you ask for private practice.
4. **Web check, one doctor at a time.** One Serper search runs, plus a second in Chinese only if needed. Up to 5 pages are read. A page only counts if it clearly names the doctor.
5. **Rules decide the status,** and the reasons are saved. The run stops as soon as the target number of qualified doctors is reached, or when the per-run budget runs out.

## Security and privacy
- **Secrets live only in `.env`**, which git ignores. No keys are hard-coded, and the app only ever shows them masked (for example `gsk_…a1b2`).
- **Real data stays on your computer.** The database (`~/doctor_data/leads.db`), exports and the `debug/` folder of saved pages are all outside the repo or git-ignored.
- **Test data is fictional.** Names, addresses, registration numbers and emails in `tests/` are made up.
- **Polite, safe fetching.** Scout MD respects `robots.txt`, waits between requests to the same site, and only fetches public `http(s)` addresses, never `localhost` or local-network addresses that a search result might point to. It skips non-text files and caps page size.
- **No email is ever guessed.** An email is only kept if it appears on a page that clearly names the doctor. Excluded domains are recorded but never used.
- **Outreach safety.** `TEST_MODE=true` (the default) sends every email to your own test inbox. Before contacting real doctors, check Hong Kong's PDPO rules on direct marketing (consent and opt-out).

## Data sources
- [Medical Council of Hong Kong, Specialist Register](https://www.mchk.org.hk/english/list_register/list.php?type=S): public register; confirms registration and specialty
- Google results via Serper: doctor profile pages on hospital, clinic and directory sites
