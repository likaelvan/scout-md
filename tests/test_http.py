import pytest

from doctor_leads.http import Fetcher, UnsafeURL, check_url


@pytest.mark.parametrize("url", ["file:///etc/passwd", "http://localhost:8501", "http://127.0.0.1/", "http://192.168.1.1/",
                                 "http://10.0.0.5/x", "ftp://example.com/", "http://printer.local/"])
def test_unsafe_urls_blocked(url):
    with pytest.raises(UnsafeURL):
        check_url(url)


def test_public_url_ok():
    check_url("https://www.mchk.org.hk/english/list_register/list.php?type=S")


class _Resp:
    def __init__(self, status=200, ctype="text/html; charset=utf-8", body=b"<html>ok</html>"):
        self.status_code, self.headers, self._body, self.encoding = status, {"Content-Type": ctype}, body, "utf-8"

    def iter_content(self, n):
        for i in range(0, len(self._body), n):
            yield self._body[i:i + n]

    def close(self):
        pass


class _Session:
    def __init__(self, resp):
        self.resp, self.headers = resp, {}

    def get(self, url, **kw):
        return self.resp


def test_skips_non_text_and_caps_size():
    f = Fetcher(None, min_interval=0, session=_Session(_Resp(ctype="application/pdf")), sleep=lambda s: None)
    assert f.get("https://example.com/a.pdf", check_robots=False).status == 415
    big = _Resp(body=b"a" * 5_000_000)
    f = Fetcher(None, min_interval=0, session=_Session(big), sleep=lambda s: None)
    assert len(f.get("https://example.com/big", check_robots=False).text) == 3_000_000


def test_retries_then_gives_up():
    from doctor_leads.http import SourceUnavailable
    f = Fetcher(None, min_interval=0, max_retries=2, session=_Session(_Resp(status=503)), sleep=lambda s: None)
    with pytest.raises(SourceUnavailable):
        f.get("https://example.com/", check_robots=False)
