"""Scout MD: Streamlit entry point.  Run with:  streamlit run app.py"""
from pathlib import Path

import streamlit as st

from doctor_leads import APP_NAME, APP_TAGLINE
from doctor_leads.ui_common import get_config, get_conn

ASSETS = Path(__file__).parent / "assets"

st.set_page_config(page_title=APP_NAME, page_icon=str(ASSETS / "icon.svg"), layout="wide")
st.logo(str(ASSETS / "logo.svg"), icon_image=str(ASSETS / "icon.svg"), size="large")

pages = [
    st.Page("ui/new_search.py", title="New Search", icon=":material/search:", default=True),
    st.Page("ui/leads.py", title="Leads", icon=":material/table:"),
    st.Page("ui/review.py", title="Review", icon=":material/rule:"),
    st.Page("ui/outreach.py", title="Outreach", icon=":material/mail:"),
    st.Page("ui/runs.py", title="Runs & Settings", icon=":material/settings:"),
]
nav = st.navigation(pages)

cfg = get_config()
conn = get_conn()
with st.sidebar:
    st.caption(APP_TAGLINE)
    st.divider()
    if cfg.test_mode:
        st.caption(":orange[TEST MODE on]")
    else:
        st.caption(":red[LIVE MODE]")

nav.run()
