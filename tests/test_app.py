from streamlit.testing.v1 import AppTest


def test_app_shell(tmp_path, monkeypatch):
    monkeypatch.setenv("DATA_DIR", str(tmp_path))
    at = AppTest.from_file("../app.py", default_timeout=30).run()
    assert not at.exception, at.exception
    assert any("You approve every email" in c.value for c in at.sidebar.caption)
