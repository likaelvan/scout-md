"""Shared Streamlit helpers: one config, one DB connection, one LLM client per app."""
from __future__ import annotations

import streamlit as st

from . import db
from .config import Config, load_config
from .llm import LLMClient


@st.cache_resource
def get_config() -> Config:
    return load_config()


@st.cache_resource
def get_conn():
    cfg = get_config()
    conn = db.connect(cfg.db_path)
    db.init_db(conn)
    return conn


@st.cache_resource
def get_llm() -> LLMClient:
    return LLMClient(get_config())


def test_mode_banner() -> None:
    cfg = get_config()
    inbox = db.get_setting(get_conn(), "test_inbox") or cfg.test_inbox
    if cfg.test_mode:
        st.warning(
            f"**TEST MODE is on**: every email goes to {inbox or 'your test inbox (not set yet: Runs & Settings)'}, "
            "never to doctors.",
            icon=":material/science:",
        )
    else:
        st.error("**LIVE MODE**: approved emails will be sent to real doctors.", icon=":material/warning:")


def empty_state(message: str, hint: str | None = None) -> None:
    st.info(message + (f"\n\n{hint}" if hint else ""), icon=":material/inbox:")


def leads_dataframe(conn, doctor_ids: list[int], excluded_domains: list[str] | None = None):
    """One row per doctor with their best email, for display."""
    import pandas as pd

    from . import taxonomy as tx

    if not doctor_ids:
        return pd.DataFrame()
    rows = []
    order = {"QUALIFIED": 0, "NEEDS_REVIEW": 1, "NEW": 2, "REJECTED": 3}
    q = f"SELECT * FROM doctors WHERE id IN ({','.join('?' * len(doctor_ids))})"
    for d in conn.execute(q, doctor_ids).fetchall():
        emails = conn.execute(
            "SELECT email, status, kind FROM emails WHERE doctor_id = ? AND excluded_domain = 0 "
            "ORDER BY status = 'valid' DESC, kind = 'personal' DESC", (d["id"],)).fetchall()
        emails = [e for e in emails if not tx.is_excluded_domain(e["email"], excluded_domains or [])]
        best = emails[0] if emails else None
        rows.append({
            "Doctor": d["full_name"], "Chinese name": d["name_zh"] or "", "Specialty": d["specialty"],
            "Hospital / clinic": d["hospital"] or {"clinic": "Private clinic", "public": "Public sector"}.get(d["hospital_type"], "Unknown"),
            "Region": d["region"] or "", "Email": best["email"] if best else None,
            "Email status": (f"{best['status']} · {best['kind'].replace('_', ' ')}" if best else "none found"),
            "Status": d["status"].replace("_", " ").title(), "Notes": d["status_notes"],
            "Profile": d["profile_url"], "Register no.": d["mchk_reg_no"], "_o": order.get(d["status"], 9),
        })
    return pd.DataFrame(rows).sort_values("_o").drop(columns="_o")
