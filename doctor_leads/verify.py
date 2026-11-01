"""Qualification rules: decide QUALIFIED / NEEDS_REVIEW / REJECTED, with plain-language reasons.

Principle: anything we can't confirm goes to a human (NEEDS_REVIEW), never straight in.
"""
from __future__ import annotations

from dataclasses import dataclass, field

from . import emails as em
from .classify import Practice
from .enrich import EnrichResult
from .filters import SearchFilters


@dataclass
class EmailDecision:
    email: str
    source_url: str
    kind: str
    near_name: bool
    check: em.EmailCheck
    usable: bool
    note: str = ""


@dataclass
class Decision:
    status: str
    hospital: str | None
    hospital_type: str
    region: str | None
    best_email: EmailDecision | None
    emails: list[EmailDecision] = field(default_factory=list)
    notes: list[str] = field(default_factory=list)
    reject: list[str] = field(default_factory=list)
    review: list[str] = field(default_factory=list)
    conflicts: list[tuple[str, str, str, str, str]] = field(default_factory=list)  # field, a, src_a, b, src_b

    @property
    def summary(self) -> str:
        return " · ".join(self.reject + self.review + self.notes)


def decide(reg_no: str, specialty: str, practice: Practice, web: EnrichResult | None, filters: SearchFilters,
           *, shared_emails: set[str] = frozenset(), check_mx: bool = True) -> Decision:
    notes = [f"Registered specialist in {specialty} ({reg_no})"]
    reject: list[str] = []
    review: list[str] = []
    conflicts = []

    # ---------------------------------------------------------------- where they work
    hospital, htype, region = practice.hospital, practice.hospital_type, practice.region
    web_private = (web.private_hospitals if web else {}) or {}
    if htype == "private":
        notes.append(practice.evidence)
    elif web_private:
        h, url = next(iter(web_private.items()))
        if htype == "public":
            conflicts.append(("hospital", practice.hospital or "public sector", "register", h, url))
            notes.append(f"Register address is public sector, but a web profile shows private practice at {h}")
        else:
            notes.append(f"Practises at {h} (web profile)")
        hospital, htype = h, "private"
    elif htype == "clinic":
        notes.append(practice.evidence)
    elif htype == "public":
        notes.append(practice.evidence)
    else:
        review.append("Couldn't confirm where they practise")

    if filters.hospital_type == "private" and htype == "public":
        reject.append("Works in the public sector, not a private hospital or clinic")
    if filters.hospital_type == "public" and htype in ("private", "clinic"):
        reject.append("Works in private practice, not a public hospital")
    if filters.included_hospitals:
        if hospital is None:
            review.append("Couldn't confirm which hospital they work at")
        elif hospital not in filters.included_hospitals:
            reject.append(f"Not at the selected hospitals (works at {hospital})")
    if hospital and hospital in filters.excluded_hospitals:
        reject.append(f"Works at an excluded hospital ({hospital})")
    if filters.region:
        if region is None:
            review.append(f"Couldn't confirm they're in {filters.region}")
        elif region != filters.region:
            reject.append(f"Practises in {region}, not {filters.region}")

    # ---------------------------------------------------------------- web identity
    if web is not None:
        if not web.strong_pages and web.weak_pages:
            review.append("Only a partial name match found online - check it's the same person")
        if web.errors and not web.strong_pages:
            notes.append("Some web pages couldn't be read: " + ", ".join(web.errors[:3]))

    # ---------------------------------------------------------------- emails
    decisions: list[EmailDecision] = []
    seen = set()
    for ev in (web.emails if web else []):
        if ev.email in seen:
            continue
        seen.add(ev.email)
        chk = em.check_email(ev.email, filters.excluded_email_domains, check_mx=check_mx)
        kind = "clinic_shared" if ev.email in shared_emails else ev.kind
        if chk.excluded:
            decisions.append(EmailDecision(ev.email, ev.source_url, kind, ev.near_name, chk, False,
                                           f"Ignored: @{chk.domain} is an excluded domain"))
            continue
        if chk.status == "invalid":
            decisions.append(EmailDecision(ev.email, ev.source_url, kind, ev.near_name, chk, False, "Invalid email"))
            continue
        usable = ev.near_name and chk.status == "valid"
        note = "" if usable else ("Not clearly linked to the doctor on the page" if not ev.near_name
                                  else "Couldn't confirm the email domain accepts mail")
        decisions.append(EmailDecision(ev.email, ev.source_url, kind, ev.near_name, chk, usable, note))

    rank = {"personal": 0, "unknown": 1, "clinic_shared": 2}
    usable = sorted([d for d in decisions if d.usable], key=lambda d: rank.get(d.kind, 3))
    maybe = [d for d in decisions if not d.usable and not d.check.excluded and d.check.status != "invalid"]
    best = usable[0] if usable else None
    excluded_notes = sorted({d.note for d in decisions if d.check.excluded})
    notes += excluded_notes
    if best:
        label = {"personal": "personal email", "clinic_shared": "clinic inbox (shared)", "unknown": "email"}[best.kind]
        notes.append(f"{label.capitalize()} found next to their name on {best.source_url}")
        if best.email in shared_emails:
            notes.append("This email is also listed for other doctors")
    elif maybe:
        review.append(f"Email {maybe[0].email} found but needs checking: {maybe[0].note.lower()}")
    elif filters.require_email:
        review.append("No email found")
    else:
        notes.append("No email found")

    status = "REJECTED" if reject else "NEEDS_REVIEW" if review else "QUALIFIED"
    return Decision(status, hospital, htype, region, best, decisions, notes, reject, review, conflicts)
