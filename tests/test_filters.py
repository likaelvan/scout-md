import pytest
from pydantic import ValidationError

from doctor_leads.filters import SearchFilters

ORTHO = "Orthopaedics & Traumatology"


def test_unknown_specialty_rejected():
    with pytest.raises(ValidationError):
        SearchFilters(specialty="Pizza")


def test_unknown_country_rejected():
    with pytest.raises(ValidationError):
        SearchFilters(specialty=ORTHO, country="XX")


def test_domains_cleaned_and_deduped():
    f = SearchFilters(specialty=ORTHO, excluded_email_domains=["@HKU.hk", "hku.hk", "not a domain", "cuhk.edu.hk"])
    assert f.excluded_email_domains == ["cuhk.edu.hk", "hku.hk"]


def test_filters_key_ignores_count_hospital_picks_and_exclusions():
    a = SearchFilters(specialty=ORTHO, hospital_type="private", target_count=20)
    b = SearchFilters(specialty=ORTHO, hospital_type="private", target_count=50, excluded_email_domains=["hku.hk"],
                      included_hospitals=["Union Hospital"], require_email=False)
    c = SearchFilters(specialty=ORTHO, hospital_type="public")
    d = SearchFilters(specialty="Cardiology", hospital_type="private")
    assert a.filters_key() == b.filters_key()
    assert len({a.filters_key(), c.filters_key(), d.filters_key()}) == 3


def test_summary():
    f = SearchFilters(specialty=ORTHO, excluded_email_domains=["hku.hk"])
    assert f.summary() == ("Find 20 Orthopaedics & Traumatology doctors in Hong Kong, at private hospitals or clinics, "
                           "ignoring emails from @hku.hk, who have an email address.")


def test_summary_any_hospital_no_email_requirement():
    f = SearchFilters(specialty="Urology", hospital_type="any", target_count=1, require_email=False,
                      excluded_email_domains=["hku.hk", "cuhk.edu.hk"])
    assert f.summary() == ("Find 1 Urology doctor in Hong Kong, at any hospital, "
                           "ignoring emails from @cuhk.edu.hk and @hku.hk.")
