import pandas as pd
import streamlit as st

from doctor_leads.ui_common import empty_state, get_conn, test_mode_banner

st.title("Outreach")
test_mode_banner()
conn = get_conn()

tab_drafts, tab_history = st.tabs(["Drafts awaiting approval", "Sent history"])

with tab_drafts:
    rows = conn.execute(
        """SELECT o.id, d.full_name, o.email, o.subject, o.created_at FROM outreach_log o
           JOIN doctors d ON d.id = o.doctor_id WHERE o.status = 'draft' ORDER BY o.created_at"""
    ).fetchall()
    if rows:
        st.dataframe(pd.DataFrame([dict(r) for r in rows]), hide_index=True, width="stretch")
    else:
        empty_state("No drafts yet.", "Drafts are generated for qualified leads with a verified email (Milestone 5).")

with tab_history:
    rows = conn.execute(
        """SELECT d.full_name, o.email, o.sent_to, o.status, o.test_mode, o.sent_at, o.error FROM outreach_log o
           JOIN doctors d ON d.id = o.doctor_id WHERE o.status IN ('sent','failed','rejected') ORDER BY o.created_at DESC"""
    ).fetchall()
    if rows:
        st.dataframe(pd.DataFrame([dict(r) for r in rows]), hide_index=True, width="stretch")
    else:
        empty_state("Nothing sent yet.")
