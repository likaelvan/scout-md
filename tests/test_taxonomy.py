import pytest

from doctor_leads import taxonomy as tx


@pytest.mark.parametrize("text", [
    "orthopedic doctors", "Orthopaedic surgeon", "ortho", "ORTHOPAEDICS", "orthopeadic", "骨科",
    "Find 20 private-hospital orthopedic doctors in Hong Kong",
])
def test_orthopaedics_synonyms(text):
    assert tx.match_specialty(text) == "Orthopaedics & Traumatology"


def test_unknown_specialty_is_none():
    assert tx.match_specialty("underwater basket weaving") is None


@pytest.mark.parametrize("text,code", [("Hong Kong", "HK"), ("in HK please", "HK"), ("hk", "HK"), ("Singapore", "SG")])
def test_country(text, code):
    assert tx.match_country(text) == code


@pytest.mark.parametrize("email,excluded", [
    ("dr.chan@hku.hk", True),
    ("someone@med.hku.hk", True),          # subdomain
    ("x@HKU.HK", True),                     # case
    ("x@nothku.hk", False),                 # not a subdomain, just similar
    ("x@hku.hk.evil.com", False),
    ("x@clinic.com.hk", False),
])
def test_excluded_domain(email, excluded):
    assert tx.is_excluded_domain(email, ["hku.hk"]) is excluded


def test_clean_domain():
    assert tx.clean_domain(" @HKU.hk ") == "hku.hk"
    assert tx.clean_domain("a@b.com") == "b.com"
    assert tx.clean_domain("not a domain") is None


def test_private_hospital():
    assert tx.match_private_hospital("Hong Kong Sanatorium & Hospital, Happy Valley") == "Hong Kong Sanatorium & Hospital"
    assert tx.match_private_hospital("Queen Mary Hospital") is None
