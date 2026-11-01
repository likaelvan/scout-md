"""Work out where a doctor practises from an address or a web page: hospital, type, region."""
from __future__ import annotations

import re
from dataclasses import dataclass
from urllib.parse import urlparse

from . import taxonomy as tx

# Hospital Authority hospitals and other public bodies (an address here = public sector).
PUBLIC_MARKERS = [
    "queen mary hospital", "prince of wales hospital", "queen elizabeth hospital", "tuen mun hospital",
    "princess margaret hospital", "united christian hospital", "pamela youde nethersole eastern hospital",
    "kwong wah hospital", "caritas medical centre", "tseung kwan o hospital", "north district hospital",
    "alice ho miu ling nethersole hospital", "yan chai hospital", "pok oi hospital", "ruttonjee hospital",
    "tung wah hospital", "tung wah eastern hospital", "grantham hospital", "kowloon hospital",
    "maclehose medical rehabilitation", "duchess of kent children", "hong kong children's hospital",
    "north lantau hospital", "tin shui wai hospital", "kwai chung hospital", "castle peak hospital",
    "haven of hope hospital", "wong tai sin hospital", "our lady of maryknoll hospital", "shatin hospital",
    "tai po hospital", "cheshire home", "siu lam hospital", "hospital authority", "department of health",
    "centre for health protection", "fanling hospital", "kwong wah", "queen mary", "prince of wales",
    "university of hong kong", "chinese university of hong kong", "li ka shing faculty",
]

# Website domains of private hospitals (best effort; used to read hospital from a profile URL).
PRIVATE_HOSPITAL_DOMAINS = {
    "hksh.com": "Hong Kong Sanatorium & Hospital",
    "hksh-hospital.com": "Hong Kong Sanatorium & Hospital",
    "stpaul.org.hk": "St. Paul's Hospital",
    "matilda.org": "Matilda International Hospital",
    "union.org": "Union Hospital",
    "hkah.org.hk": "Hong Kong Adventist Hospital – Stubbs Road",
    "adventistmedical.hk": "Hong Kong Adventist Hospital – Stubbs Road",
    "twah.org.hk": "Hong Kong Adventist Hospital – Tsuen Wan",
    "hkbh.org.hk": "Hong Kong Baptist Hospital",
    "evangel.org.hk": "Evangel Hospital",
    "canossahospital.org.hk": "Canossa Hospital (Caritas)",
    "pbh.org.hk": "Precious Blood Hospital (Caritas)",
    "sth.org.hk": "St. Teresa's Hospital",
    "cuhkmc.hk": "CUHK Medical Centre",
    "gleneagles.hk": "Gleneagles Hospital Hong Kong",
}

CLINIC_MARKERS = re.compile(
    r"\b(room|rm|flat|suite|unit|shop|floor|/f|building|bldg|centre|center|tower|plaza|house|commercial|"
    r"mansion|court|medical centre|clinic|arcade|mall)\b", re.I)

REGION_KEYWORDS = [
    ("New Territories", ["new territories", "n.t.", " nt", "sha tin", "shatin", "tsuen wan", "tuen mun", "yuen long",
                         "tai po", "fanling", "sheung shui", "tseung kwan o", "tai wai", "ma on shan", "kwai chung",
                         "kwai fong", "tsing yi", "tung chung", "tin shui wai", "sai kung", "lantau"]),
    ("Kowloon", ["kowloon", "mongkok", "mong kok", "tsim sha tsui", "yau ma tei", "jordan", "kwun tong",
                 "sham shui po", "hung hom", "to kwa wan", "ho man tin", "kowloon tong", "san po kong",
                 "wong tai sin", "lai chi kok", "cheung sha wan", "diamond hill", "ngau tau kok", "lam tin"]),
    ("Hong Kong Island", ["central", "causeway bay", "wan chai", "wanchai", "admiralty", "happy valley",
                          "sheung wan", "north point", "quarry bay", "chai wan", "aberdeen", "pok fu lam",
                          "pokfulam", "mid-levels", "sai ying pun", "kennedy town", "tai koo", "shau kei wan",
                          "stubbs road", "repulse bay", "hong kong island"]),
]


@dataclass
class Practice:
    hospital_type: str          # private | public | clinic | unknown
    hospital: str | None = None
    region: str | None = None
    evidence: str = ""


def region_of(text: str | None) -> str | None:
    if not text:
        return None
    t = " " + text.lower()
    for region, keys in REGION_KEYWORDS:
        if any(k in t for k in keys):
            return region
    return None


def classify_address(address: str | None) -> Practice:
    if not address:
        return Practice("unknown", evidence="No address on the register")
    a = address.lower()
    hospital = tx.match_private_hospital(address)
    region = region_of(address)
    if hospital:
        return Practice("private", hospital, region, f"Register address is at {hospital}")
    for marker in PUBLIC_MARKERS:
        if marker in a:
            return Practice("public", marker.title(), region, f"Register address is public sector ({marker.title()})")
    if CLINIC_MARKERS.search(address):
        return Practice("clinic", None, region, "Register address looks like a private clinic")
    return Practice("unknown", None, region, "Register address doesn't say public or private")


def hospital_from_url(url: str) -> str | None:
    host = urlparse(url).netloc.lower().removeprefix("www.")
    for domain, hospital in PRIVATE_HOSPITAL_DOMAINS.items():
        if host == domain or host.endswith("." + domain):
            return hospital
    return None


def is_public_text(text: str) -> bool:
    t = text.lower()
    return any(m in t for m in PUBLIC_MARKERS)
