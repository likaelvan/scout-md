import pandas as pd
import streamlit as st

from doctor_leads.ui_common import empty_state, get_conn

st.title("Leads")
conn = get_conn()

rows = conn.execute(
    """SELECT d.id, d.full_name, d.specialty, d.hospital, d.hospital_type, d.region, d.status, d.status_notes,
              (SELECT e.email FROM emails e WHERE e.doctor_id = d.id ORDER BY e.status = 'valid' DESC LIMIT 1) AS email,
              (SELECT e.status FROM emails e WHERE e.doctor_id = d.id ORDER BY e.status = 'valid' DESC LIMIT 1) AS email_status,
              d.profile_url, d.last_verified_at
       FROM doctors d WHERE d.status != 'MERGED' ORDER BY d.updated_at DESC"""
).fetchall()

if not rows:
    empty_state("No leads yet.", "Run a search from **New Search** to start building your list.")
    st.stop()

df = pd.DataFrame([dict(r) for r in rows])
c1, c2, c3 = st.columns(3)
status = c1.multiselect("Status", ["QUALIFIED", "NEEDS_REVIEW", "REJECTED", "NEW"], default=["QUALIFIED", "NEEDS_REVIEW"])
specialty = c2.multiselect("Specialty", sorted(df["specialty"].dropna().unique()))
q = c3.text_input("Search name or hospital")

view = df[df["status"].isin(status)] if status else df
if specialty:
    view = view[view["specialty"].isin(specialty)]
if q:
    m = view["full_name"].str.contains(q, case=False, na=False) | view["hospital"].str.contains(q, case=False, na=False)
    view = view[m]

st.caption(f"{len(view)} of {len(df)} leads")
st.dataframe(view, hide_index=True, width="stretch",
             column_config={"profile_url": st.column_config.LinkColumn("Profile"), "id": None})
st.button("Export to Excel", icon=":material/download:", disabled=True, help="Arrives in Milestone 3.")
