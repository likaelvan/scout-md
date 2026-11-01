import json

import pandas as pd
import streamlit as st

from doctor_leads import db
from doctor_leads.llm import LLMError
from doctor_leads.ui_common import empty_state, get_config, get_conn, get_llm

st.title("Runs & Settings")
cfg = get_config()
conn = get_conn()

# ---------------------------------------------------------------- runs
st.subheader("Search runs")
from doctor_leads import pipeline
pipeline.mark_orphans(conn)
rows = conn.execute(
    """SELECT id, request_text, status, target_count, found_existing, found_new, llm_calls, llm_tokens,
              rate_limit_hits, error, created_at, finished_at FROM jobs ORDER BY id DESC LIMIT 100"""
).fetchall()
if rows:
    st.dataframe(pd.DataFrame([dict(r) for r in rows]), hide_index=True, width="stretch")
else:
    empty_state("No runs yet.")

# ---------------------------------------------------------------- LLM
st.subheader("LLM connection")
c1, c2, c3 = st.columns(3)
c1.metric("Provider", cfg.llm_provider)
c2.metric("Model", cfg.llm_model)
c3.metric("API key", cfg.llm_key_masked)
if st.button("Test connection", icon=":material/bolt:"):
    llm = get_llm()
    try:
        models = llm.list_models()
        if cfg.llm_model in models:
            st.success(f"Key works and model `{cfg.llm_model}` is available.")
        else:
            st.error(f"Key works, but model `{cfg.llm_model}` isn't available. Set LLM_MODEL in .env to one of these:")
            st.code("\n".join(models))
        reply = llm.complete_json('Reply with JSON {"ok": true}.', "ping")
        st.caption(f"Test call reply: `{json.dumps(reply)}`")
    except LLMError as e:
        st.error(str(e))

st.subheader("Web search")
if cfg.serper_api_key:
    st.success(f"Serper key set ({cfg.serper_api_key[:4]}…{cfg.serper_api_key[-4:]}).", icon=":material/travel_explore:")
else:
    st.warning("No `SERPER_API_KEY` in `.env`: searches can list registered specialists but can't find emails.",
               icon=":material/key_off:")

# ---------------------------------------------------------------- settings
st.subheader("Settings")
s = db.all_settings(conn)
with st.form("settings"):
    inbox = st.text_input("Test inbox (all emails go here while TEST MODE is on)", value=s.get("test_inbox") or cfg.test_inbox or "")
    domains = st.text_input("Always-excluded email domains (comma-separated)", value=", ".join(s["default_excluded_email_domains"]))
    c1, c2 = st.columns(2)
    cache_days = c1.number_input("Re-fetch cached pages after (days)", 1, 365, int(s["cache_max_age_days"]))
    stale_days = c2.number_input("Re-verify leads after (days)", 1, 365, int(s["lead_stale_after_days"]))
    budget = st.number_input("Most doctors to check per search run (limits Serper credits used)", 5, 1000,
                             int(s["max_candidates_per_run"]))
    c3, c4 = st.columns(2)
    auto_merge = c3.slider("Duplicate auto-merge score", 80, 100, int(s["dedup_auto_merge_score"]))
    review = c4.slider("Duplicate review score", 60, 99, int(s["dedup_review_score"]))
    if st.form_submit_button("Save settings"):
        if review >= auto_merge:
            st.error("The review score must be lower than the auto-merge score.")
        else:
            db.set_setting(conn, "test_inbox", inbox.strip() or None)
            db.set_setting(conn, "default_excluded_email_domains", [d.strip().lower() for d in domains.split(",") if d.strip()])
            db.set_setting(conn, "cache_max_age_days", int(cache_days))
            db.set_setting(conn, "lead_stale_after_days", int(stale_days))
            db.set_setting(conn, "dedup_auto_merge_score", int(auto_merge))
            db.set_setting(conn, "dedup_review_score", int(review))
            db.set_setting(conn, "max_candidates_per_run", int(budget))
            st.success("Saved.")

with st.expander("Database"):
    st.caption(f"`{cfg.db_path}`")
    st.json(db.table_counts(conn))
