"""Canonical vocabularies so differently-worded requests map to the same filters.

"ortho surgeons in HK" and "orthopaedic doctors, Hong Kong" both become
specialty="Orthopaedics & Traumatology", country="HK".
"""
from __future__ import annotations

import re

from rapidfuzz import fuzz, process

# Canonical names follow the Medical Council of Hong Kong Specialist Register.
SPECIALTIES: dict[str, list[str]] = {
    "Orthopaedics & Traumatology": [
        "orthopaedics", "orthopedics", "orthopaedic", "orthopedic", "ortho",
        "orthopaedic surgery", "orthopedic surgery", "orthopaedic surgeon", "orthopedic surgeon",
        "trauma and orthopaedics", "bone doctor", "骨科",
    ],
    "Cardiology": ["cardiology", "cardiologist", "heart doctor", "心臟科"],
    "General Surgery": ["general surgery", "general surgeon"],
    "Neurosurgery": ["neurosurgery", "neurosurgeon", "brain surgeon"],
    "Plastic Surgery": ["plastic surgery", "plastic surgeon", "cosmetic surgeon"],
    "Urology": ["urology", "urologist"],
    "Obstetrics & Gynaecology": ["obstetrics", "gynaecology", "gynecology", "obgyn", "ob/gyn", "ob-gyn", "gynaecologist", "gynecologist", "obstetrician"],
    "Paediatrics": ["paediatrics", "pediatrics", "paediatrician", "pediatrician", "children's doctor"],
    "Ophthalmology": ["ophthalmology", "ophthalmologist", "eye doctor", "eye surgeon"],
    "Otorhinolaryngology": ["otorhinolaryngology", "ent", "ear nose and throat", "ent surgeon"],
    "Dermatology & Venereology": ["dermatology", "dermatologist", "skin doctor"],
    "Psychiatry": ["psychiatry", "psychiatrist"],
    "Gastroenterology & Hepatology": ["gastroenterology", "gastroenterologist", "hepatology", "gi doctor"],
    "Clinical Oncology": ["oncology", "oncologist", "clinical oncology", "cancer doctor"],
    "Anaesthesiology": ["anaesthesiology", "anesthesiology", "anaesthetist", "anesthesiologist"],
    "Family Medicine": ["family medicine", "family doctor", "general practitioner", "gp"],
    "Rheumatology": ["rheumatology", "rheumatologist"],
    "Respiratory Medicine": ["respiratory medicine", "pulmonology", "pulmonologist", "chest physician"],
    "Endocrinology, Diabetes & Metabolism": ["endocrinology", "endocrinologist", "diabetes specialist"],
    "Nephrology": ["nephrology", "nephrologist", "kidney doctor"],
    "Neurology": ["neurology", "neurologist"],
    "Radiology": ["radiology", "radiologist"],
}

COUNTRIES: dict[str, dict] = {
    "HK": {
        "name": "Hong Kong",
        "aliases": ["hong kong", "hk", "hksar", "香港"],
        "regions": ["Hong Kong Island", "Kowloon", "New Territories"],
    },
    "SG": {"name": "Singapore", "aliases": ["singapore", "sg"], "regions": []},
    "MO": {"name": "Macau", "aliases": ["macau", "macao"], "regions": []},
}
# Countries that have source adapters (others parse fine but can't be searched yet).
SUPPORTED_COUNTRIES = {"HK"}

HOSPITAL_TYPES = ["private", "public", "any"]

# Hong Kong private hospitals (to be re-verified against official sources in M2).
HK_PRIVATE_HOSPITALS: dict[str, list[str]] = {
    "Canossa Hospital (Caritas)": ["canossa"],
    "CUHK Medical Centre": ["cuhk medical centre", "cuhkmc"],
    "Evangel Hospital": ["evangel"],
    "Gleneagles Hospital Hong Kong": ["gleneagles"],
    "Hong Kong Adventist Hospital – Stubbs Road": ["adventist stubbs road", "hkah stubbs road", "hong kong adventist hospital"],
    "Hong Kong Adventist Hospital – Tsuen Wan": ["tsuen wan adventist", "hkah tsuen wan"],
    "Hong Kong Baptist Hospital": ["baptist hospital", "hkbh"],
    "Hong Kong Sanatorium & Hospital": ["sanatorium", "hksh", "hong kong sanatorium"],
    "Matilda International Hospital": ["matilda"],
    "Precious Blood Hospital (Caritas)": ["precious blood"],
    "St. Paul's Hospital": ["st paul's", "st pauls", "st. paul's"],
    "St. Teresa's Hospital": ["st teresa's", "st teresas", "st. teresa's"],
    "Union Hospital": ["union hospital"],
}

# Email-domain exclusion presets shown in the New Search form. Matching includes
# subdomains (e.g. "hku.hk" also excludes "med.hku.hk").
EMAIL_EXCLUSION_PRESETS: dict[str, list[str]] = {
    "HKU (University of Hong Kong)": ["hku.hk", "hku-szh.org"],
    "CUHK": ["cuhk.edu.hk"],
    "HKUST": ["ust.hk"],
    "PolyU": ["polyu.edu.hk"],
    "Hospital Authority (public hospitals)": ["ha.org.hk"],
}

_DOMAIN_RE = re.compile(r"^(?=.{3,253}$)([a-z0-9](?:[a-z0-9-]{0,61}[a-z0-9])?\.)+[a-z]{2,}$")


def _norm(text: str) -> str:
    return re.sub(r"\s+", " ", re.sub(r"[^\w\s&/'\-一-鿿]", " ", text.lower())).strip()


def _synonym_index() -> list[tuple[str, str]]:
    pairs = []
    for canon, syns in SPECIALTIES.items():
        pairs.append((canon.lower(), canon))
        pairs += [(s.lower(), canon) for s in syns]
    # Longest first so "orthopaedic surgery" wins over "ortho".
    return sorted(pairs, key=lambda p: -len(p[0]))


_SPECIALTY_INDEX = _synonym_index()


def match_specialty(text: str | None, *, fuzzy_cutoff: int = 88) -> str | None:
    """Map free text to a canonical specialty, or None if not confident."""
    if not text:
        return None
    t = _norm(text)
    for syn, canon in _SPECIALTY_INDEX:
        if t == syn:
            return canon
    for syn, canon in _SPECIALTY_INDEX:
        # Whole-word containment ("orthopedic doctors in hk" contains "orthopedic").
        if re.search(rf"(?<![\w]){re.escape(syn)}(?![\w])", t):
            return canon
    # Fuzzy only on the whole phrase, to catch typos like "orthopeadic".
    best = process.extractOne(t, [s for s, _ in _SPECIALTY_INDEX], scorer=fuzz.ratio, score_cutoff=fuzzy_cutoff)
    if best:
        return dict(_SPECIALTY_INDEX)[best[0]]
    return None


def match_country(text: str | None) -> str | None:
    if not text:
        return None
    t = _norm(text)
    if t.upper() in COUNTRIES:
        return t.upper()
    for code, info in COUNTRIES.items():
        for alias in sorted(info["aliases"], key=len, reverse=True):
            if re.search(rf"(?<![\w]){re.escape(alias)}(?![\w])", t):
                return code
    return None


def match_region(text: str | None, country: str) -> str | None:
    if not text:
        return None
    t = _norm(text)
    for region in COUNTRIES.get(country, {}).get("regions", []):
        if region.lower() in t:
            return region
    return None


def clean_domain(value: str) -> str | None:
    """'@HKU.hk ' -> 'hku.hk'. Returns None if it isn't a plausible domain."""
    d = value.strip().lower().lstrip("@").rstrip(".")
    if "@" in d:
        d = d.split("@", 1)[1]
    return d if _DOMAIN_RE.match(d) else None


def is_excluded_domain(email_or_domain: str, excluded: list[str]) -> bool:
    """True if the email's domain equals or is a subdomain of an excluded domain."""
    d = email_or_domain.strip().lower()
    if "@" in d:
        d = d.rsplit("@", 1)[1]
    d = d.rstrip(".")
    return any(d == x or d.endswith("." + x) for x in excluded)


def match_private_hospital(text: str | None) -> str | None:
    if not text:
        return None
    t = _norm(text)
    for canon, aliases in HK_PRIVATE_HOSPITALS.items():
        if canon.lower() in t or any(a in t for a in aliases):
            return canon
    return None
