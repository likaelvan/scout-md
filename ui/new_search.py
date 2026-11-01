import pandas as pd
import streamlit as st
from pydantic import ValidationError

from doctor_leads import db
from doctor_leads import taxonomy as tx
from doctor_leads.filters import SearchFilters
from doctor_leads import pipeline
from doctor_leads.ui_common import get_config, get_conn, leads_dataframe

st.title("New Search")
st.caption("Choose which doctors you need. Matches already in your database show up right away.")
conn = get_conn()

# ------------------------------------------------------------- who
st.subheader("Doctors")
c1, c2, c3 = st.columns(3)
specialty = c1.selectbox("Specialty", list(tx.SPECIALTIES), index=None, placeholder="Pick a specialty")
supported = sorted(tx.SUPPORTED_COUNTRIES)
country = c2.selectbox("Location", supported, format_func=lambda c: tx.COUNTRIES[c]["name"],
                       help="More locations become available as data sources are added for them.")
regions = tx.COUNTRIES[country]["regions"]
region = c3.selectbox("Region", ["Anywhere"] + regions)

c4, c5 = st.columns([2, 1])
hospital_type = c4.segmented_control(
    "Works at", ["private", "public", "any"], default="private",
    format_func={"private": "Private hospitals & clinics", "public": "Public hospitals", "any": "Any"}.get,
) or "private"
target = c5.number_input("How many doctors", min_value=1, max_value=500, value=20, step=5)

included, excluded_h = [], []
if country == "HK" and hospital_type == "private":
    with st.expander("Specific hospitals (optional)"):
        hospitals = list(tx.HK_PRIVATE_HOSPITALS)
        included = st.multiselect("Only these hospitals", hospitals, placeholder="Any private hospital")
        excluded_h = st.multiselect("Exclude these hospitals", [h for h in hospitals if h not in included],
                                    placeholder="None")

# ------------------------------------------------------------- email rules
st.subheader("Email rules")
presets = st.multiselect(
    "Exclude email domains from", list(tx.EMAIL_EXCLUSION_PRESETS), placeholder="No institutions excluded", key="excl_presets",
    help="Subdomains are excluded too (hku.hk also excludes med.hku.hk).",
)
defaults = db.get_setting(conn, "default_excluded_email_domains") or []
custom = st.text_input("Other domains to exclude (comma-separated)", value=", ".join(defaults),
                       placeholder="e.g. example.com, clinic.org.hk")
require_email = st.toggle("Only count doctors with an email address", value=True,
                          help="Off: doctors without an email are still listed, but don't count toward the number above.")

if not specialty:
    st.info("Pick a specialty to see matching doctors.", icon=":material/arrow_upward:")
    st.stop()

domains = [d for p in presets for d in tx.EMAIL_EXCLUSION_PRESETS[p]] + [d for d in custom.split(",") if d.strip()]
bad = [d.strip() for d in custom.split(",") if d.strip() and not tx.clean_domain(d)]
if bad:
    st.warning("Ignored, not valid domains: " + ", ".join(bad))

try:
    f = SearchFilters(
        specialty=specialty, country=country, region=None if region == "Anywhere" else region,
        hospital_type=hospital_type, target_count=int(target), included_hospitals=included,
        excluded_hospitals=excluded_h, excluded_email_domains=domains, require_email=require_email,
    )
except ValidationError as e:
    st.error(f"Check the filters: {e.errors()[0]['msg']}")
    st.stop()

st.divider()
st.subheader("Search summary")
st.caption("What Scout MD will look for, based on the filters above. Change the filters to adjust it.")
st.success(f.summary(), icon=":material/check_circle:")

# ------------------------------------------------------------- run
cfg = get_config()
pipeline.mark_orphans(conn)
qualified = pipeline.qualified_with_email(conn, f)
needed = max(f.target_count - len(qualified), 0)

st.subheader("Run the search")
if not cfg.serper_api_key:
    st.warning("Web search is off, so no emails can be found. Add `SERPER_API_KEY` to your `.env` file and restart "
               "the app. Without it, Scout MD still lists registered specialists and where they practise.",
               icon=":material/key_off:")

running = conn.execute("SELECT id FROM jobs WHERE filters_key = ? AND status IN ('queued','running') ORDER BY id DESC LIMIT 1",
                       (f.filters_key(),)).fetchone()
if needed == 0:
    st.success(f"You already have {len(qualified)} qualified doctors for this search. No new search needed.",
               icon=":material/task_alt:")
elif st.button(f"Find {needed} more doctor{'s' if needed != 1 else ''}", type="primary",
               icon=":material/travel_explore:", disabled=running is not None,
               help="Already running - see progress below." if running else None):
    job_id = pipeline.create_job(conn, f)
    pipeline.start_job(cfg, job_id)
    st.session_state.job_id = job_id
    st.rerun()

job_id = running["id"] if running else st.session_state.get("job_id")
job = pipeline.get_job(conn, job_id) if job_id else None
if job and job["filters_key"] != f.filters_key():
    job = None


def _progress_panel(job_id: int) -> None:
    job = pipeline.get_job(get_conn(), job_id)
    prog = job["progress"]
    live = job["status"] in ("queued", "running")
    with st.container(border=True):
        if live:
            st.progress(prog.get("fraction", 0.0), text=prog.get("message", "Starting…"))
            c1, c2, c3 = st.columns([1, 1, 1])
            c1.metric("Qualified", f"{prog.get('qualified', 0)} / {job['target_count']}")
            c2.metric("Doctors checked", prog.get("checked", 0))
            if c3.button("Stop", icon=":material/stop_circle:"):
                pipeline.cancel_job(get_conn(), job_id)
        else:
            msg = job["error"] or prog.get("message", "")
            {"done": st.success, "partial": st.warning, "failed": st.error, "cancelled": st.info}.get(
                job["status"], st.info)(f"**Search {job['status']}.** {msg}" if msg else f"**Search {job['status']}.**")
            if st.session_state.get("_refreshed_for") != job_id:   # refresh the results table once
                st.session_state["_refreshed_for"] = job_id
                st.rerun(scope="app")
        if prog.get("log"):
            with st.expander("Activity", expanded=live):
                st.markdown("\n".join(f"- {line}" for line in prog["log"][:15]))
        if prog.get("traceback"):
            with st.expander("Error details"):
                st.code(prog["traceback"])


if job:
    live = job["status"] in ("queued", "running")
    st.fragment(run_every=2 if live else None)(_progress_panel)(job["id"])

# ------------------------------------------------------------- results
st.subheader("Matching doctors in your database")
existing = db.find_matching_doctors(conn, f)
if existing:
    st.caption(f"{len(qualified)} qualified · {len(existing)} total (qualified first). Rejected doctors are on the Leads page.")
    st.dataframe(leads_dataframe(conn, [r["id"] for r in existing], f.excluded_email_domains), hide_index=True,
                 width="stretch", column_config={"Profile": st.column_config.LinkColumn("Profile", display_text="open")})
else:
    st.caption("None yet. Run the search to start building the list.")
