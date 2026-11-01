"""Polite web fetching: per-site rate limit, retries with backoff, robots.txt, page cache."""
from __future__ import annotations

import hashlib
import ipaddress
import sqlite3
import threading
import time
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from urllib import robotparser
from urllib.parse import urlparse

import requests

USER_AGENT = "Mozilla/5.0 (Windows NT 10.0; Win64; x64) ScoutMD/0.2 (personal research tool)"
RETRY_STATUSES = {429, 500, 502, 503, 504}
MAX_BYTES = 3_000_000            # don't download huge files from search results
TEXT_TYPES = ("text/", "html", "xml", "json")


class SourceUnavailable(Exception):
    """The site couldn't be reached after retries (down, blocked, or timing out)."""


class BlockedByRobots(Exception):
    """robots.txt asks us not to fetch this URL."""


class UnsafeURL(Exception):
    """Not http(s), or points at this computer / the local network."""


def check_url(url: str) -> None:
    """Search results are untrusted: only fetch public http(s) websites."""
    parts = urlparse(url)
    if parts.scheme not in ("http", "https") or not parts.hostname:
        raise UnsafeURL(url)
    host = parts.hostname.lower()
    if host == "localhost" or host.endswith((".local", ".internal", ".localhost")):
        raise UnsafeURL(url)
    try:
        ip = ipaddress.ip_address(host)
    except ValueError:
        return
    if ip.is_private or ip.is_loopback or ip.is_link_local or ip.is_reserved or ip.is_multicast:
        raise UnsafeURL(url)


def _decode(raw: bytes, declared: str | None) -> str:
    enc = declared if declared and declared.lower() != "iso-8859-1" else None
    if not enc:  # Chinese pages often mislabel or omit their charset
        try:
            from charset_normalizer import from_bytes
            best = from_bytes(raw).best()
            enc = best.encoding if best else "utf-8"
        except ImportError:
            enc = "utf-8"
    return raw.decode(enc, errors="replace")


@dataclass
class FetchResult:
    url: str
    status: int
    text: str
    from_cache: bool = False


class Fetcher:
    def __init__(self, conn: sqlite3.Connection | None = None, *, min_interval: float = 1.0,
                 cache_max_age_days: int = 30, max_retries: int = 3, timeout: int = 20,
                 session: requests.Session | None = None, sleep=time.sleep):
        self.conn = conn
        self.min_interval = min_interval
        self.cache_max_age = timedelta(days=cache_max_age_days)
        self.max_retries = max_retries
        self.timeout = timeout
        self.session = session or requests.Session()
        self.session.headers.update({"User-Agent": USER_AGENT, "Accept-Language": "en,zh-HK;q=0.8"})
        self._sleep = sleep
        self._last_hit: dict[str, float] = {}
        self._robots: dict[str, robotparser.RobotFileParser | None] = {}
        self._lock = threading.Lock()
        self.requests_made = 0

    # ---------------------------------------------------------------- helpers
    def _wait_turn(self, host: str) -> None:
        with self._lock:
            wait = self._last_hit.get(host, 0) + self.min_interval - time.monotonic()
            if wait > 0:
                self._sleep(wait)
            self._last_hit[host] = time.monotonic()

    def allowed(self, url: str) -> bool:
        parts = urlparse(url)
        base = f"{parts.scheme}://{parts.netloc}"
        if base not in self._robots:
            rp = robotparser.RobotFileParser()
            try:
                r = self.session.get(base + "/robots.txt", timeout=10)
                rp.parse(r.text.splitlines() if r.status_code == 200 else [])
                self._robots[base] = rp
            except requests.RequestException:
                self._robots[base] = None  # can't read robots.txt: assume allowed
        rp = self._robots[base]
        return True if rp is None else rp.can_fetch(USER_AGENT, url)

    def _cached(self, url: str) -> FetchResult | None:
        if not self.conn:
            return None
        row = self.conn.execute("SELECT http_status, body, fetched_at FROM page_cache WHERE url = ?", (url,)).fetchone()
        if not row:
            return None
        fetched = datetime.fromisoformat(row["fetched_at"]).replace(tzinfo=timezone.utc)
        if datetime.now(timezone.utc) - fetched > self.cache_max_age:
            return None
        return FetchResult(url, row["http_status"], row["body"] or "", from_cache=True)

    def _store(self, res: FetchResult) -> None:
        if not self.conn:
            return
        self.conn.execute(
            """INSERT INTO page_cache (url, http_status, content_hash, body, fetched_at)
               VALUES (?, ?, ?, ?, datetime('now'))
               ON CONFLICT(url) DO UPDATE SET http_status=excluded.http_status, content_hash=excluded.content_hash,
                   body=excluded.body, fetched_at=excluded.fetched_at""",
            (res.url, res.status, hashlib.sha1(res.text.encode()).hexdigest(), res.text),
        )
        self.conn.commit()

    # ---------------------------------------------------------------- main
    def get(self, url: str, *, use_cache: bool = True, check_robots: bool = True) -> FetchResult:
        check_url(url)
        if use_cache and (hit := self._cached(url)):
            return hit
        if check_robots and not self.allowed(url):
            raise BlockedByRobots(url)

        host = urlparse(url).netloc
        last_err = ""
        for attempt in range(self.max_retries + 1):
            self._wait_turn(host)
            try:
                r = self.session.get(url, timeout=self.timeout, stream=True)
                self.requests_made += 1
            except requests.RequestException as e:
                last_err = f"{type(e).__name__}: {e}"
            else:
                try:
                    if r.status_code in RETRY_STATUSES:
                        last_err = f"HTTP {r.status_code}"
                        retry_after = r.headers.get("Retry-After", "")
                        if retry_after.isdigit():
                            self._sleep(min(int(retry_after), 60))
                    else:
                        ctype = r.headers.get("Content-Type", "").lower()
                        if ctype and not any(t in ctype for t in TEXT_TYPES):
                            return FetchResult(url, 415, "")   # PDF, image, video...: skip
                        raw = b""
                        for chunk in r.iter_content(65536):
                            raw += chunk
                            if len(raw) > MAX_BYTES:
                                break
                        res = FetchResult(url, r.status_code, _decode(raw[:MAX_BYTES], r.encoding))
                        if r.status_code == 200 and use_cache:
                            self._store(res)
                        return res
                except requests.RequestException as e:
                    last_err = f"{type(e).__name__}: {e}"
                finally:
                    r.close()
            if attempt < self.max_retries:
                self._sleep(2 * (2 ** attempt))
        raise SourceUnavailable(f"{url} unavailable after {self.max_retries + 1} tries ({last_err})")
