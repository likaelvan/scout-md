from doctor_leads.sources import mchk
from tests.fakes import FIX


def test_parse_list_page():
    rows, total = mchk.parse_list_page((FIX / "mchk_list_p1.html").read_text(encoding="utf-8"))
    assert total == 2
    assert [r.reg_no for r in rows] == ["S14-9001", "S08-9002", "S08-9003"]
    r = rows[1]
    assert (r.name_en, r.name_zh, r.prefix, r.year) == ("TSANG, CHI HO", "曾志豪", "S08", 1998)
    assert "SAMPLE COMMERCIAL BUILDING" in r.address
    assert rows[0].address is None


def test_split_name_variants():
    assert mchk.split_name("石偉棠 ABDULLAH, VICTOR") == ("ABDULLAH, VICTOR", "石偉棠")
    assert mchk.split_name("ANTONIO, GREGORY") == ("ANTONIO, GREGORY", None)


def test_detail_specialty():
    assert mchk.parse_detail_specialty((FIX / "mchk_detail_S08.html").read_text(encoding="utf-8")) == "Orthopaedics & Traumatology"
    assert mchk.parse_detail_specialty((FIX / "mchk_detail_S14.html").read_text(encoding="utf-8")) == "Cardiology"
    assert mchk.parse_detail_specialty("<html>nothing</html>") is None
