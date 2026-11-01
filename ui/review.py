import pandas as pd
import streamlit as st

from doctor_leads.ui_common import empty_state, get_conn

st.title("Review")
st.caption("Leads the system couldn't confirm on its own, and possible duplicates. Nothing here is used until you decide.")
conn = get_conn()

tab_leads, tab_dupes = st.tabs(["Uncertain leads", "Possible duplicates"])

with tab_leads:
    rows = conn.execute(
        """SELECT r.id, d.full_name, d.hospital, r.kind, r.reason, r.created_at
           FROM review_queue r JOIN doctors d ON d.id = r.doctor_id
           WHERE r.status = 'open' AND r.kind != 'duplicate' ORDER BY r.created_at"""
    ).fetchall()
    if rows:
        st.dataframe(pd.DataFrame([dict(r) for r in rows]), hide_index=True, width="stretch")
    else:
        empty_state("Nothing to review.")

with tab_dupes:
    rows = conn.execute(
        """SELECT r.id, a.full_name AS doctor_a, b.full_name AS doctor_b, r.score, r.reason
           FROM review_queue r JOIN doctors a ON a.id = r.doctor_id JOIN doctors b ON b.id = r.other_id
           WHERE r.status = 'open' AND r.kind = 'duplicate' ORDER BY r.score DESC"""
    ).fetchall()
    if rows:
        st.dataframe(pd.DataFrame([dict(r) for r in rows]), hide_index=True, width="stretch")
    else:
        empty_state("No possible duplicates.")

st.caption("Approve / fix / reject and merge actions arrive in Milestone 4.")
