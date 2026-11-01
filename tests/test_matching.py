import pytest

from doctor_leads import classify, emails
from doctor_leads.names import find_name, parse_register_name


def test_parse_register_name():
    n = parse_register_name("MAK, WAI HUNG RAYMOND", "麥偉雄")
    assert (n.surname, n.given, n.western, n.chinese) == ("mak", ["wai", "hung"], ["raymond"], "麥偉雄")
    assert parse_register_name("AH CHONG, AH KIAN").surname == "ah chong"
    assert parse_register_name("AI, HIU FAY DAWN (formerly registered as AI DAWN TERESA HIU-FAY)").western == ["dawn"]


@pytest.mark.parametrize("text,strength", [
    ("Dr. Mak Wai-hung, FRCS", "strong"),
    ("Dr. Wai Hung MAK", "strong"),
    ("Dr Mak Waihung", "strong"),
    ("請聯絡麥偉雄醫生", "strong"),
    ("Dr Raymond Mak", "weak"),
    ("Dr Mak Wai Ming", "none"),
    ("Dr Paul Wai-hung Chan", "none"),
])
def test_find_name(text, strength):
    n = parse_register_name("MAK, WAI HUNG RAYMOND", "麥偉雄")
    assert find_name(n, text).strength == strength


def test_extract_emails():
    text = "Mail us: info@clinic.hk, Dr.Chan(at)ortho[dot]com.hk  logo@2x.png  INFO@CLINIC.HK"
    assert emails.extract_emails(text) == ["info@clinic.hk", "dr.chan@ortho.com.hk"]


def test_email_kind():
    n = parse_register_name("LEE, WING KEI")
    assert emails.kind_of("info@clinic.hk", n) == "clinic_shared"
    assert emails.kind_of("wklee@clinic.hk", n) == "personal"
    assert emails.kind_of("drlee@clinic.hk", n) == "personal"
    assert emails.kind_of("abc123@clinic.hk", n) == "unknown"


def test_check_email_excluded_and_syntax():
    c = emails.check_email("x@med.hku.hk", ["hku.hk"], check_mx=False)
    assert c.excluded and c.syntax_ok
    assert emails.check_email("bad@@x.com", [], check_mx=False).status == "invalid"


@pytest.mark.parametrize("address,htype,hospital,region", [
    ("ROOM 120, 1/F, BLOCK B, ST PAUL'S HOSPITAL, 2 EASTERN HOSPITAL ROAD, CAUSEWAY BAY, HONG KONG", "private", "St. Paul's Hospital", "Hong Kong Island"),
    ("DEPARTMENT OF RADIOLOGY, PAMELA YOUDE NETHERSOLE EASTERN HOSPITAL, 3 LOK MAN ROAD, CHAI WAN, HONG KONG", "public", None, "Hong Kong Island"),
    ("ROOM 801, 8/F, SAMPLE COMMERCIAL BUILDING, 100 NATHAN ROAD, MONGKOK, KOWLOON", "clinic", None, "Kowloon"),
    ("CUHK MEDICAL CENTRE, 9 CHAK CHEUNG STREET, SHA TIN, N.T.", "private", "CUHK Medical Centre", "New Territories"),
    (None, "unknown", None, None),
])
def test_classify_address(address, htype, hospital, region):
    p = classify.classify_address(address)
    assert p.hospital_type == htype and p.region == region
    if hospital:
        assert p.hospital == hospital


def test_hospital_from_url():
    assert classify.hospital_from_url("https://www.hksh.com/en/doctor/123") == "Hong Kong Sanatorium & Hospital"
    assert classify.hospital_from_url("https://example.com") is None
