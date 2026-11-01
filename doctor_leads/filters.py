"""What a search asks for. Built directly from the New Search form - no free text."""
from __future__ import annotations

import hashlib
import json
from typing import Literal

from pydantic import BaseModel, Field, field_validator

from . import taxonomy as tx


class SearchFilters(BaseModel):
    specialty: str
    country: str = "HK"
    region: str | None = None
    hospital_type: Literal["private", "public", "any"] = "private"
    target_count: int = Field(20, ge=1, le=500)
    included_hospitals: list[str] = Field(default_factory=list)   # empty = any hospital
    excluded_hospitals: list[str] = Field(default_factory=list)
    excluded_email_domains: list[str] = Field(default_factory=list)
    require_email: bool = True   # only leads with a usable email count toward the target

    @field_validator("specialty")
    @classmethod
    def _known_specialty(cls, v: str) -> str:
        if v not in tx.SPECIALTIES:
            raise ValueError(f"Unknown specialty: {v}")
        return v

    @field_validator("country")
    @classmethod
    def _known_country(cls, v: str) -> str:
        if v not in tx.COUNTRIES:
            raise ValueError(f"Unknown location: {v}")
        return v

    @field_validator("excluded_email_domains")
    @classmethod
    def _clean_domains(cls, v: list[str]) -> list[str]:
        return sorted({d for d in (tx.clean_domain(x) for x in v) if d})

    def filters_key(self) -> str:
        """Identity of 'which population of doctors is this'.

        Only specialty, location and hospital type count. Target count, hospital
        picks and exclusions are applied at query time, so '20 HK ortho' and
        '50 HK ortho, no HKU' reuse the same stored data and search history.
        """
        basis = {"specialty": self.specialty, "country": self.country, "region": self.region,
                 "hospital_type": self.hospital_type}
        return hashlib.sha1(json.dumps(basis, sort_keys=True).encode()).hexdigest()[:16]

    def summary(self) -> str:
        """Plain-language readback of the search, e.g.
        'Find 20 Urology doctors in Hong Kong, at any hospital, who have an email address.'"""
        place = tx.COUNTRIES[self.country]["name"]
        noun = "doctor" if self.target_count == 1 else "doctors"
        parts = [f"Find {self.target_count} {self.specialty} {noun} in {self.region + ', ' if self.region else ''}{place}"]
        if self.included_hospitals:
            parts.append("at " + _join(self.included_hospitals))
        else:
            parts.append({"private": "at private hospitals or clinics", "public": "at public hospitals",
                          "any": "at any hospital"}[self.hospital_type])
        if self.excluded_hospitals:
            parts.append("but not at " + _join(self.excluded_hospitals))
        if self.excluded_email_domains:
            parts.append("ignoring emails from " + _join(["@" + d for d in self.excluded_email_domains]))
        if self.require_email:
            parts.append("who have an email address")
        return ", ".join(parts) + "."


def _join(items: list[str]) -> str:
    return items[0] if len(items) == 1 else ", ".join(items[:-1]) + " and " + items[-1]
