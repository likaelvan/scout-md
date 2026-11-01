"""Enrich one register doctor from the web: practice location, profile URL and emails.

Every piece of evidence is tied to the page it came from, and only pages that clearly
mention THIS doctor (strong name match) are allowed to contribute emails or hospitals.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from urllib.parse import urlparse

from bs4 import BeautifulSoup

from . import classify
from . import emails as em
from . import taxonomy as tx
from .http import BlockedByRobots, Fetcher, SourceUnavailable, UnsafeURL
from .names import DoctorName, find_name
from .search import SearchHit

SKIP_DOMAINS = ("facebook.com", "instagram.com", "linkedin.com", "youtube.com", "twitter.com", "x.com",
                "tiktok.com", "wikipedia.org", "mchk.org.hk", "pinterest.com")
NEAR_CHARS = 400          # an email/hospital this close to the doctor's name is "about them"
MAX_PAGES = 5


@dataclass
class EmailEvidence:
    email: str
    source_url: str
    near_name: bool
    kind: str


@dataclass
class EnrichResult:
    queries: list[str] = field(default_factory=list)
    pages_checked: int = 0
    strong_pages: list[str] = field(default_factory=list)
    weak_pages: list[str] = field(default_factory=list)
    emails: list[EmailEvidence] = field(default_factory=list)
    private_hospitals: dict[str, str] = field(default_factory=dict)   # hospital -> url
    public_pages: list[str] = field(default_factory=list)
    profile_url: str | None = None
    errors: list[str] = field(default_factory=list)


def search_term(specialty: str) -> str:
    syns = tx.SPECIALTIES.get(specialty, [])
    return syns[0] if syns else specialty


def build_queries(name: DoctorName, specialty: str) -> list[str]:
    full = " ".join([name.surname, *name.given]).title()
    qs = [f'"{full}" {search_term(specialty)} Hong Kong']
    if name.chinese:
        qs.append(f'"{name.chinese}" 醫生')
    return qs


def page_text(html: str) -> str:
    soup = BeautifulSoup(html, "html.parser")
    for tag in soup(["script", "style", "noscript"]):
        tag.decompose()
    mailtos = " ".join(a["href"][7:].split("?")[0] for a in soup.find_all("a", href=True)
                       if a["href"].lower().startswith("mailto:"))
    return " ".join(soup.get_text(" ").split()) + " " + mailtos


def analyse_page(url: str, text: str, name: DoctorName, result: EnrichResult) -> None:
    match = find_name(name, text)
    if match.strength == "none":
        return
    if match.strength == "weak":
        result.weak_pages.append(url)
        return
    result.strong_pages.append(url)

    for e in em.extract_emails(text):
        dist = em.nearest_distance(text, e, match.positions)
        near = dist is not None and dist <= NEAR_CHARS
        result.emails.append(EmailEvidence(e, url, near, em.kind_of(e, name)))

    hosp = classify.hospital_from_url(url)
    if hosp:
        result.private_hospitals.setdefault(hosp, url)
    for p in match.positions:
        window = text[max(0, p - NEAR_CHARS): p + NEAR_CHARS]
        h = tx.match_private_hospital(window)
        if h:
            result.private_hospitals.setdefault(h, url)
        if classify.is_public_text(window):
            result.public_pages.append(url)


def enrich(name: DoctorName, specialty: str, searcher, fetcher: Fetcher, *, max_pages: int = MAX_PAGES) -> EnrichResult:
    """Search, read the top pages, and collect evidence. Search errors propagate (quota!)."""
    result = EnrichResult()
    seen: set[str] = set()
    for q in build_queries(name, specialty):
        result.queries.append(q)
        hits: list[SearchHit] = searcher.search(q)
        for hit in hits:
            host = urlparse(hit.url).netloc.lower()
            if hit.url in seen or any(host.endswith(d) for d in SKIP_DOMAINS) or hit.url.lower().endswith(".pdf"):
                continue
            if result.pages_checked >= max_pages:
                break
            seen.add(hit.url)
            try:
                res = fetcher.get(hit.url)
            except (SourceUnavailable, BlockedByRobots, UnsafeURL) as e:
                result.errors.append(f"{host}: {type(e).__name__}")
                continue
            result.pages_checked += 1
            if res.status != 200:
                result.errors.append(f"{host}: HTTP {res.status}")
                continue
            analyse_page(hit.url, page_text(res.text), name, result)
        if result.strong_pages:   # good enough - skip the Chinese-name query to save credits
            break

    # Best profile page: private-hospital site > page with a near-name email > any strong page.
    hosp_pages = [u for u in result.strong_pages if classify.hospital_from_url(u)]
    email_pages = [e.source_url for e in result.emails if e.near_name]
    result.profile_url = (hosp_pages or email_pages or result.strong_pages or [None])[0]
    return result
