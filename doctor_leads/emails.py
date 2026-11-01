"""Finding and checking email addresses. No email is ever guessed."""
from __future__ import annotations

import re
from dataclasses import dataclass
from functools import lru_cache

from . import taxonomy as tx
from .names import DoctorName

EMAIL_RE = re.compile(r"(?<![\w.+-])([a-z0-9][a-z0-9._%+-]{0,63}@[a-z0-9-]+(?:\.[a-z0-9-]+)*\.[a-z]{2,24})(?![\w-])", re.I)
# "name [at] clinic [dot] com" / "name(at)clinic.com"
OBFUSCATED_RE = re.compile(
    r"([a-z0-9._%+-]+)\s*[\[\(\{]\s*at\s*[\]\)\}]\s*([a-z0-9-]+(?:\s*(?:[\[\(\{]\s*dot\s*[\]\)\}]|\.)\s*[a-z0-9-]+)+)", re.I)

GENERIC_LOCALS = {
    "info", "enquiry", "enquiries", "inquiry", "inquiries", "admin", "contact", "contactus", "clinic", "reception",
    "appointment", "appointments", "booking", "bookings", "office", "mail", "hello", "general", "service",
    "services", "cs", "customerservice", "support", "secretary", "frontdesk", "hr", "careers", "jobs", "pr",
    "media", "marketing", "feedback", "webmaster", "noreply", "no-reply", "donotreply", "privacy", "dpo",
}
DISPOSABLE_DOMAINS = {"mailinator.com", "guerrillamail.com", "10minutemail.com", "tempmail.com", "yopmail.com"}
IMAGE_SUFFIXES = (".png", ".jpg", ".jpeg", ".gif", ".webp", ".svg")


@dataclass
class FoundEmail:
    email: str
    distance: int | None     # characters from the nearest mention of the doctor (None = not near)


def extract_emails(text: str) -> list[str]:
    found = [m.group(1) for m in EMAIL_RE.finditer(text)]
    for m in OBFUSCATED_RE.finditer(text):
        domain = re.sub(r"\s*[\[\(\{]\s*dot\s*[\]\)\}]\s*|\s*\.\s*", ".", m.group(2))
        found.append(f"{m.group(1)}@{domain}")
    out, seen = [], set()
    for e in found:
        e = e.strip(".").lower()
        if e.endswith(IMAGE_SUFFIXES) or e in seen:   # "logo@2x.png" is not an email
            continue
        seen.add(e)
        out.append(e)
    return out


def syntax_ok(email: str) -> bool:
    if not EMAIL_RE.fullmatch(email):
        return False
    local, domain = email.rsplit("@", 1)
    return ".." not in email and not local.startswith(".") and not local.endswith(".") and tx.clean_domain(domain) is not None


@lru_cache(maxsize=2048)
def mx_ok(domain: str) -> bool | None:
    """True = domain can receive mail; False = it can't; None = couldn't check (DNS problem)."""
    try:
        import dns.exception
        import dns.resolver
    except ImportError:
        return None
    resolver = dns.resolver.Resolver()
    resolver.lifetime = 6
    try:
        return len(resolver.resolve(domain, "MX")) > 0
    except (dns.resolver.NXDOMAIN, dns.resolver.NoAnswer):
        try:  # no MX: mail may still go to the A record
            return len(resolver.resolve(domain, "A")) > 0
        except dns.exception.DNSException:
            return False
    except dns.exception.DNSException:
        return None


def kind_of(email: str, name: DoctorName) -> str:
    """personal (has the doctor's name), clinic_shared (info@, enquiry@...) or unknown."""
    local = email.split("@")[0].lower()
    letters = re.sub(r"[^a-z]", "", local)
    if local in GENERIC_LOCALS or letters in GENERIC_LOCALS:
        return "clinic_shared"
    initials = "".join(g[0] for g in name.given)
    probes = [name.surname.replace(" ", "")] + ["".join(name.given)] + [w for w in name.western]
    if any(p and len(p) >= 2 and p in letters for p in probes):
        return "personal"
    if initials and (letters.startswith(initials + name.surname) or letters.endswith(name.surname + initials)):
        return "personal"
    return "unknown"


def nearest_distance(text: str, email: str, name_positions: list[int]) -> int | None:
    pos = text.lower().find(email.lower())
    if pos < 0 or not name_positions:
        return None
    return min(abs(pos - p) for p in name_positions)


@dataclass
class EmailCheck:
    email: str
    domain: str
    syntax_ok: bool
    mx_ok: bool | None
    excluded: bool
    disposable: bool

    @property
    def status(self) -> str:
        if not self.syntax_ok or self.disposable or self.mx_ok is False:
            return "invalid"
        if self.mx_ok is None:
            return "risky"
        return "valid"


def check_email(email: str, excluded_domains: list[str], *, check_mx: bool = True) -> EmailCheck:
    domain = email.rsplit("@", 1)[-1].lower()
    ok = syntax_ok(email)
    return EmailCheck(
        email=email, domain=domain, syntax_ok=ok,
        mx_ok=(mx_ok(domain) if (ok and check_mx) else (None if ok else False)),
        excluded=tx.is_excluded_domain(email, excluded_domains),
        disposable=domain in DISPOSABLE_DOMAINS,
    )
