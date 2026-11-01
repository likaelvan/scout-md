"""Every page renders without errors on an empty database (no LLM key needed)."""
import pytest
from streamlit.testing.v1 import AppTest


@pytest.fixture(autouse=True)
def tmp_data(tmp_path, monkeypatch):
    monkeypatch.setenv("DATA_DIR", str(tmp_path))
    monkeypatch.setenv("GROQ_API_KEY", "")


@pytest.mark.parametrize("page", ["../ui/new_search.py", "../ui/leads.py", "../ui/review.py", "../ui/outreach.py", "../ui/runs.py"])
def test_page_renders(page):
    at = AppTest.from_file(page, default_timeout=30).run()
    assert not at.exception, at.exception


def test_new_search_form():
    at = AppTest.from_file("../ui/new_search.py", default_timeout=30).run()
    assert not at.exception, at.exception
    assert any("Pick a specialty" in i.value for i in at.info)
    at.selectbox[0].select("Orthopaedics & Traumatology").run()
    at.multiselect(key="excl_presets").select("HKU (University of Hong Kong)").run()
    assert not at.exception, at.exception
    summary = at.success[0].value
    assert "Orthopaedics & Traumatology" in summary and "@hku.hk" in summary and "private hospitals" in summary
