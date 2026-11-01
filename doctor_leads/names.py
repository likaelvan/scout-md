"""Doctor-name handling: parse register names, normalise, and find a doctor on a web page.

Register names look like "AU, KIN MING" or "AU, KIN HENG CONSTANTINE" (surname, then
Cantonese given-name syllables, sometimes followed by an English first name).
On the web the same doctor appears as "Dr. Au Kin Ming", "Dr Au Kin-ming",
"Dr. Constantine Au", or "區建恒醫生".
"""
from __future__ import annotations

import re
import unicodedata
from dataclasses import dataclass, field

TITLES = {"dr", "doctor", "prof", "professor", "mr", "mrs", "ms", "miss", "sir", "dame", "jp", "sbs", "bbs", "mh", "obe", "mbe"}
CREDENTIAL_RE = re.compile(
    r"\b(mbbs|mbchb|mb|bs|bch|md|phd|frcs\w*|frcp\w*|fhkam|fhkcos|fhkcs|fhkcp|fracs|facs|mrcs|mrcp|mch|msc|ms|bsc|dch|dip\w*|fcsh\w*|lmchk)\b",
    re.I,
)
_FORMERLY_RE = re.compile(r"\((?:formerly|also known as)[^)]*\)", re.I)
_CJK_RE = re.compile(r"[一-鿿]+")


@dataclass
class DoctorName:
    surname: str                       # "au"
    given: list[str]                   # ["kin", "heng"]  (Cantonese syllables)
    western: list[str] = field(default_factory=list)  # ["constantine"]
    chinese: str | None = None         # "區建恒"

    @property
    def display(self) -> str:
        parts = [w.title() for w in self.western] + [self.surname.title()] + [g.title() for g in self.given]
        return " ".join(parts)

    @property
    def key(self) -> str:
        """Order-insensitive key for dedup: 'au heng kin'."""
        return " ".join(sorted([self.surname, *self.given]))


def _ascii_lower(text: str) -> str:
    text = unicodedata.normalize("NFKD", text)
    return "".join(c for c in text if not unicodedata.combining(c)).lower()


def _syllable_like(token: str) -> bool:
    """Cantonese romanised syllables are short (kin, ming, chung, wai, hung, ...)."""
    return len(token) <= 5 or token in {"cheung", "kwong", "leung", "shing", "chuen", "chung", "hoong"}


def parse_register_name(name_en: str, name_zh: str | None = None) -> DoctorName:
    """'AU, KIN HENG CONSTANTINE' -> surname=au, given=[kin, heng], western=[constantine]."""
    text = _FORMERLY_RE.sub("", name_en)
    if "," in text:
        surname, rest = text.split(",", 1)
    else:
        bits = text.split()
        surname, rest = (bits[0], " ".join(bits[1:])) if bits else ("", "")
    surname_tokens = re.findall(r"[a-z]+", _ascii_lower(surname))
    tokens = re.findall(r"[a-z]+", _ascii_lower(rest))
    given, western = [], []
    for i, t in enumerate(tokens):
        # Syllables come first; the first long, non-syllable token starts the English name(s).
        if not western and (_syllable_like(t) or i == 0) and len(given) < 2:
            given.append(t)
        else:
            western.append(t)
    return DoctorName(" ".join(surname_tokens), given, western, name_zh or None)


def normalize_free_name(text: str) -> str:
    """Normalise a name seen on the web for fuzzy comparison: no titles/credentials, lowercase."""
    t = _ascii_lower(_FORMERLY_RE.sub("", text))
    t = CREDENTIAL_RE.sub(" ", t)
    t = re.sub(r"[^a-z\s]", " ", t.replace("-", " "))
    return " ".join(w for w in t.split() if w not in TITLES)


def _page_words(text: str) -> str:
    """Lowercase letters only, everything else a space - SAME LENGTH as the input,
    so match positions line up with positions in the original text."""
    return "".join(c.lower() if c.isascii() and c.isalpha() else " " for c in text)


@dataclass
class NameMatch:
    strength: str            # "strong" | "weak" | "none"
    positions: list[int]     # character offsets of the matches in the page text
    how: str = ""


def _seq(tokens: list[str]) -> str:
    return r"(?<![a-z])" + r"\s+".join(re.escape(t) for t in tokens) + r"(?![a-z])"


def find_name(name: DoctorName, page_text: str) -> NameMatch:
    """Look for the doctor on a page.

    strong: surname + all given syllables together (any order, hyphenated or joined), or the Chinese name.
    weak:   English first name + surname only ("Dr. Constantine Au") - common, but ambiguous.
    """
    words = _page_words(page_text)
    s = name.surname.split()
    g = name.given
    patterns = []
    if g and s:
        patterns += [_seq(s + g), _seq(g + s), _seq(s + ["".join(g)]), _seq(["".join(g)] + s)]
        if name.western:
            patterns.append(_seq([name.western[0]] + s + g))
    positions = sorted({m.start() for p in patterns for m in re.finditer(p, words)})
    if positions:
        return NameMatch("strong", positions, "full name")
    if name.chinese and len(name.chinese) >= 2:
        raw_pos = [m.start() for m in re.finditer(re.escape(name.chinese), page_text)]
        if raw_pos:
            return NameMatch("strong", raw_pos, "Chinese name")
    if name.western and s:
        pos = [m.start() for m in re.finditer(_seq([name.western[0]] + s), words)]
        if pos:
            return NameMatch("weak", pos, "English first name + surname only")
    return NameMatch("none", [], "")


def chinese_chars(text: str) -> str:
    return "".join(_CJK_RE.findall(text))
