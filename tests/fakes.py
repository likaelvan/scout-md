"""Offline stand-ins for the web and for Serper."""
from pathlib import Path

from doctor_leads.http import FetchResult, SourceUnavailable
from doctor_leads.search import SearchHit
from doctor_leads.sources import mchk

FIX = Path(__file__).parent / "fixtures"

WEB = {
    "https://www.stpaul.org.hk/en/doctors/lee-wing-kei":
        "<html><body><h1>Dr. Lee Wing Kei</h1><p>Specialist in Orthopaedics &amp; Traumatology, St. Paul's Hospital.</p>"
        "<p>Email: <a href='mailto:wklee@lee-ortho-clinic.example'>wklee@lee-ortho-clinic.example</a></p></body></html>",
    "https://tsang-ortho.example/":
        "<html><body><h2>Dr TSANG Chi-ho</h2><p>Orthopaedic surgeon, Sample Commercial Building, Mongkok.</p>"
        "<p>Enquiries: info@tsang-ortho.example</p></body></html>",
    "https://www.finddoc.com/en/doctors/wong-siu-fung":
        "<html><body><h1>Dr. Wong Siu Fung</h1><p>Orthopaedics. Practises at Hong Kong Sanatorium &amp; Hospital.</p></body></html>",
    "https://www.hku.hk/staff/wong":
        "<html><body><p>Dr Wong Siu Fung, Clinical Associate Professor. staff.wong@hku.hk</p></body></html>",
    "https://news.example/interview":
        "<html><body><p>Interview with Dr Joyce Fung about sports injuries. Contact press@news.example</p></body></html>",
}
SEARCH = {
    "lee wing kei": ["https://www.stpaul.org.hk/en/doctors/lee-wing-kei", "https://www.facebook.com/x"],
    "tsang chi ho": ["https://tsang-ortho.example/"],
    "wong siu fung": ["https://www.finddoc.com/en/doctors/wong-siu-fung", "https://www.hku.hk/staff/wong"],
    "fung mei ling": ["https://news.example/interview", "https://down.example.hk/page"],
    "ho ka yan": [],
}


class FakeFetcher:
    def __init__(self):
        self.calls = []

    def get(self, url, use_cache=True, check_robots=True):
        self.calls.append(url)
        if "list.php" in url:
            page = 2 if "page=2" in url else (99 if "page=3" in url else 1)
            if page == 99:
                return FetchResult(url, 200, "<html></html>")
            return FetchResult(url, 200, (FIX / f"mchk_list_p{page}.html").read_text(encoding="utf-8"))
        if "doctor_detail.php" in url:
            prefix = url.split("reg_no=")[1][:3]
            f = FIX / f"mchk_detail_{prefix}.html"
            return FetchResult(url, 200, f.read_text(encoding="utf-8") if f.exists() else "<html>Unknown</html>")
        if url in WEB:
            return FetchResult(url, 200, WEB[url])
        raise SourceUnavailable(url)


class FakeSearch:
    def __init__(self):
        self.queries = []

    def search(self, query, num=10):
        self.queries.append(query)
        q = query.lower()
        for key, urls in SEARCH.items():
            if key in q:
                return [SearchHit("t", u, "") for u in urls]
        return []
