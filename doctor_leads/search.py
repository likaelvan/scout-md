"""Web search (Serper = Google results). Swappable: anything with .search(query) works."""
from __future__ import annotations

import time
from dataclasses import dataclass

import requests


class SearchError(Exception):
    pass


class SearchQuotaExceeded(SearchError):
    """Out of credits or rate-limited for too long - stop searching for this run."""


class SearchNotConfigured(SearchError):
    pass


@dataclass
class SearchHit:
    title: str
    url: str
    snippet: str


class SerperSearch:
    URL = "https://google.serper.dev/search"

    def __init__(self, api_key: str | None, *, gl: str = "hk", hl: str = "en", max_retries: int = 3,
                 session: requests.Session | None = None, sleep=time.sleep):
        if not api_key:
            raise SearchNotConfigured("SERPER_API_KEY is not set in .env")
        self.api_key = api_key
        self.gl, self.hl = gl, hl
        self.max_retries = max_retries
        self.session = session or requests.Session()
        self._sleep = sleep
        self.queries_made = 0

    def search(self, query: str, num: int = 10) -> list[SearchHit]:
        last = ""
        for attempt in range(self.max_retries + 1):
            try:
                r = self.session.post(self.URL, json={"q": query, "gl": self.gl, "hl": self.hl, "num": num},
                                      headers={"X-API-KEY": self.api_key, "Content-Type": "application/json"}, timeout=20)
            except requests.RequestException as e:
                last = str(e)
            else:
                if r.status_code == 200:
                    self.queries_made += 1
                    data = r.json()
                    return [SearchHit(o.get("title", ""), o.get("link", ""), o.get("snippet", ""))
                            for o in data.get("organic", []) if o.get("link")]
                body = r.text[:200]
                if r.status_code in (401, 403):
                    raise SearchNotConfigured(f"Serper rejected the API key (HTTP {r.status_code})")
                if r.status_code in (400, 402) and "credit" in body.lower():
                    raise SearchQuotaExceeded("Serper credits used up")
                if r.status_code != 429 and r.status_code < 500:
                    raise SearchError(f"Serper error HTTP {r.status_code}: {body}")
                last = f"HTTP {r.status_code}"
            if attempt < self.max_retries:
                self._sleep(2 * (2 ** attempt))
        if last.startswith("HTTP 429"):
            raise SearchQuotaExceeded("Serper rate limit hit repeatedly")
        raise SearchError(f"Serper unavailable: {last}")
