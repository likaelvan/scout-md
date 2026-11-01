"""Medical Council of Hong Kong: Specialist Register.

The ground truth for "is this a registered doctor with this specialty?".
  * list.php?type=S&page=N  -> 20 specialists per page (~450 pages)
  * doctor_detail.php?reg_no=S08-0189 -> full record, including the specialty name

The specialty is encoded in the registration-number prefix (S08 = Orthopaedics &
Traumatology). Rather than hard-coding every prefix, we learn each one the first time
by opening a single doctor's detail page and reading the specialty from it.
"""
from __future__ import annotations

import re
import sqlite3
from dataclasses import dataclass
from typing import Callable

from bs4 import BeautifulSoup

from .. import db
from .. import taxonomy as tx
from ..http import Fetcher

BASE = "https://www.mchk.org.hk/english/list_register"
LIST_URL = BASE + "/list.php?page={page}&ipp=20&type=S"
DETAIL_URL = BASE + "/doctor_detail.php?reg_no={reg_no}"
SOURCE_NAME = "mchk_register"

REG_RE = re.compile(r"\bS\d{2}-\d{4}\b")
PAGES_RE = re.compile(r"of\s+(\d{1,4})\b", re.I)
_CJK_PREFIX_RE = re.compile(r"^\s*([一-鿿·]+)\s+(.*)$")

# Verified by hand (detail page of S08-0510 says "骨科 Orthopaedics & Traumatology").
KNOWN_PREFIXES = {"S08": "Orthopaedics & Traumatology"}


@dataclass
class RegisterRow:
    reg_no: str
    name_en: str
    name_zh: str | None
    address: str | None
    qualification: str | None
    year: int | None

    @property
    def prefix(self) -> str:
        return self.reg_no.split("-")[0]


class RegisterFormatChanged(Exception):
    """The page no longer looks like we expect - parsers need updating."""


def _clean(text: str) -> str:
    return re.sub(r"\s+", " ", text or "").strip()


def split_name(cell_text: str) -> tuple[str, str | None]:
    """'區嘉輝 AU, KA FAI' -> ('AU, KA FAI', '區嘉輝'); 'ANTONIO, GREGORY' -> ('ANTONIO, GREGORY', None)."""
    text = _clean(cell_text)
    m = _CJK_PREFIX_RE.match(text)
    return (m.group(2), m.group(1)) if m else (text, None)


def parse_list_page(html: str) -> tuple[list[RegisterRow], int | None]:
    soup = BeautifulSoup(html, "html.parser")
    rows: list[RegisterRow] = []
    for tr in soup.find_all("tr"):
        cells = tr.find_all(["td", "th"])
        if len(cells) < 4:
            continue
        reg = _clean(cells[0].get_text(" "))
        if not REG_RE.fullmatch(reg):
            continue
        name_en, name_zh = split_name(cells[1].get_text(" "))
        address = _clean(cells[2].get_text(" ")) or None
        if address in {"-", "--"}:
            address = None
        qual = _clean(cells[3].get_text(" ")) or None
        year_txt = _clean(cells[4].get_text(" ")) if len(cells) > 4 else ""
        rows.append(RegisterRow(reg, name_en, name_zh, address, qual, int(year_txt) if year_txt.isdigit() else None))

    total = None
    for el in soup.find_all(["a", "span", "div", "li"]):
        for attr in ("title", "aria-label"):
            if el.get(attr) and (m := PAGES_RE.search(el[attr])):
                total = max(total or 0, int(m.group(1)))
    if total is None:
        nums = [int(a.get_text()) for a in soup.find_all("a") if a.get_text().strip().isdigit()]
        total = max(nums) if nums else None
    return rows, total


def parse_detail_specialty(html: str) -> str | None:
    """Find which known specialty the detail page names (longest match wins)."""
    text = _clean(BeautifulSoup(html, "html.parser").get_text(" ")).lower()
    hits = [s for s in tx.SPECIALTIES if s.lower() in text]
    return max(hits, key=len) if hits else None


# ------------------------------------------------------------------ syncing
def register_age_days(conn: sqlite3.Connection) -> float | None:
    """Days since the last COMPLETE register sync (None = never finished one)."""
    synced = db.get_setting(conn, "register_synced_at")
    if not synced:
        return None
    return conn.execute("SELECT julianday('now') - julianday(?)", (synced,)).fetchone()[0]


def sync_register(conn: sqlite3.Connection, fetcher: Fetcher, *, progress: Callable[[str, float], None] = lambda m, f: None,
                  should_stop: Callable[[], bool] = lambda: False, start_page: int | None = None) -> int:
    """Read the whole specialist list into register_entries. Returns rows stored.

    Pages are not cached individually (the table *is* the cache). Safe to resume from
    `start_page` if interrupted.
    """
    page = start_page or int(db.get_setting(conn, "register_sync_next_page") or 1)
    total, stored = None, 0
    while True:
        if should_stop():
            break
        res = fetcher.get(LIST_URL.format(page=page), use_cache=False)
        rows, pages = parse_list_page(res.text)
        total = total or pages
        if not rows:
            if page == 1:
                raise RegisterFormatChanged("No register rows found on page 1 - the page layout may have changed.")
            break
        conn.executemany(
            """INSERT INTO register_entries (reg_no, prefix, name_en, name_zh, address, qualification, year, fetched_at)
               VALUES (?,?,?,?,?,?,?, datetime('now'))
               ON CONFLICT(reg_no) DO UPDATE SET name_en=excluded.name_en, name_zh=excluded.name_zh,
                 address=excluded.address, qualification=excluded.qualification, year=excluded.year, fetched_at=excluded.fetched_at""",
            [(r.reg_no, r.prefix, r.name_en, r.name_zh, r.address, r.qualification, r.year) for r in rows],
        )
        db.set_setting(conn, "register_sync_next_page", page + 1)  # commits; lets an interrupted sync resume
        stored += len(rows)
        progress(f"Reading Medical Council register: page {page}" + (f" of {total}" if total else ""),
                 page / total if total else 0.0)
        if total and page >= total:
            break
        page += 1
    if not should_stop():
        db.set_setting(conn, "register_sync_next_page", 1)
        db.set_setting(conn, "register_synced_at", conn.execute("SELECT datetime('now')").fetchone()[0])
    return stored


def prefix_for_specialty(conn: sqlite3.Connection, fetcher: Fetcher, specialty: str,
                         progress: Callable[[str, float], None] = lambda m, f: None) -> str | None:
    """Return the register prefix for a specialty, learning prefixes from detail pages as needed."""
    row = conn.execute("SELECT prefix FROM specialty_codes WHERE specialty = ?", (specialty,)).fetchone()
    if row:
        return row["prefix"]

    known = {r["prefix"] for r in conn.execute("SELECT prefix FROM specialty_codes")}
    # Try the hard-coded hint first, then every unknown prefix (largest groups first).
    hinted = [p for p, s in KNOWN_PREFIXES.items() if s == specialty]
    others = [r["prefix"] for r in conn.execute(
        "SELECT prefix, COUNT(*) n FROM register_entries GROUP BY prefix ORDER BY n DESC")]
    for prefix in hinted + [p for p in others if p not in hinted]:
        if prefix in known:
            continue
        sample = conn.execute("SELECT reg_no FROM register_entries WHERE prefix = ? LIMIT 1", (prefix,)).fetchone()
        if not sample:
            continue
        progress(f"Learning which register code means {specialty} (checking {prefix})…", 0.0)
        res = fetcher.get(DETAIL_URL.format(reg_no=sample["reg_no"]))
        found = parse_detail_specialty(res.text)
        conn.execute("INSERT OR REPLACE INTO specialty_codes (prefix, specialty, sample_reg_no) VALUES (?,?,?)",
                     (prefix, found, sample["reg_no"]))
        conn.commit()
        known.add(prefix)
        if found == specialty:
            return prefix
    return None
