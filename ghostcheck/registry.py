"""Live lookups against PyPI and the npm registry, with a JSON cache and polite rate limiting."""
from __future__ import annotations

import json
import os
import threading
import time
from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Callable
from urllib.parse import quote

from .parsers import NPM, PYPI, normalize_pypi

USER_AGENT = "ghostcheck/0.1 (+https://github.com/; dependency existence check)"
# npm packages above this weekly download count are treated as established without fetching
# their full registry document (which can be 30 MB for packages like `next`).
NPM_POPULAR_WEEKLY = 50_000


@dataclass
class PackageInfo:
    name: str
    ecosystem: str
    exists: bool | None              # None = could not check (offline / network error)
    first_release: str | None = None  # ISO-8601 UTC
    latest_release: str | None = None
    n_releases: int | None = None
    maintainers: int | None = None
    weekly_downloads: int | None = None   # npm: last week; PyPI: pypistats last_week
    monthly_downloads: int | None = None  # PyPI: pypistats last_month
    note: str = ""
    error: str = ""
    checked_at: str = ""
    extra: dict = field(default_factory=dict)

    def age_days(self, now: datetime | None = None) -> float | None:
        if not self.first_release:
            return None
        now = now or datetime.now(timezone.utc)
        return (now - parse_ts(self.first_release)).total_seconds() / 86400


def parse_ts(s: str) -> datetime:
    s = s.replace("Z", "+00:00")
    dt = datetime.fromisoformat(s)
    return dt if dt.tzinfo else dt.replace(tzinfo=timezone.utc)


def _iso(dt: datetime) -> str:
    return dt.astimezone(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def cache_key(name: str, ecosystem: str) -> str:
    return f"{ecosystem}:{normalize_pypi(name) if ecosystem == PYPI else name}"


# fetch(url, method, headers) -> (status_code, parsed_json_or_None)
Fetcher = Callable[[str, str, dict], tuple[int, object]]


def _requests_fetcher() -> Fetcher:
    import requests

    session = requests.Session()
    session.headers["User-Agent"] = USER_AGENT

    def fetch(url: str, method: str = "GET", headers: dict | None = None):
        resp = session.request(method, url, headers=headers or {}, timeout=30)
        body = None
        if method == "GET" and resp.content:
            try:
                body = resp.json()
            except ValueError:
                body = None
        return resp.status_code, body

    return fetch


class Registry:
    def __init__(
        self,
        cache_path: str | os.PathLike | None = None,
        offline: bool = False,
        ttl_hours: float | None = 24,
        min_interval: float = 0.2,   # <= 5 requests per second
        fetcher: Fetcher | None = None,
        now: datetime | None = None,
    ):
        self.cache_path = Path(cache_path) if cache_path else None
        self.offline = offline
        self.ttl_hours = ttl_hours
        self.min_interval = min_interval
        self._fetcher = fetcher
        self.now = now or datetime.now(timezone.utc)
        self._last = 0.0
        self._lock = threading.Lock()
        self.requests_made = 0
        self.cache: dict[str, dict] = {}
        if self.cache_path and self.cache_path.exists():
            try:
                self.cache = json.loads(self.cache_path.read_text("utf-8"))
            except (ValueError, OSError):
                self.cache = {}

    # ------------------------------------------------------------ plumbing
    def _fetch(self, url: str, method: str = "GET", headers: dict | None = None, retries: int = 4):
        if self._fetcher is None:
            self._fetcher = _requests_fetcher()
        delay = 2.0
        for attempt in range(retries + 1):
            with self._lock:
                wait = self.min_interval - (time.monotonic() - self._last)
                if wait > 0:
                    time.sleep(wait)
                self._last = time.monotonic()
            self.requests_made += 1
            try:
                status, body = self._fetcher(url, method, headers or {})
            except Exception as exc:  # network error
                if attempt == retries:
                    raise
                time.sleep(delay)
                delay *= 2
                continue
            if status == 429 or status >= 500:
                if attempt == retries:
                    return status, body
                time.sleep(delay)
                delay *= 2
                continue
            return status, body
        return 0, None

    def save(self) -> None:
        if not self.cache_path:
            return
        self.cache_path.parent.mkdir(parents=True, exist_ok=True)
        tmp = self.cache_path.with_suffix(".tmp")
        tmp.write_text(json.dumps(self.cache, indent=1, sort_keys=True), "utf-8")
        tmp.replace(self.cache_path)

    def _fresh(self, entry: dict) -> bool:
        if self.ttl_hours is None or self.offline:
            return True
        try:
            age = (self.now - parse_ts(entry["checked_at"])).total_seconds() / 3600
        except (KeyError, ValueError):
            return False
        return age < self.ttl_hours

    # ------------------------------------------------------------ public
    def lookup(self, name: str, ecosystem: str) -> PackageInfo:
        key = cache_key(name, ecosystem)
        entry = self.cache.get(key)
        if entry and self._fresh(entry) and entry.get("exists") is not None:
            return PackageInfo(**entry)
        if self.offline:
            if entry:
                return PackageInfo(**entry)
            return PackageInfo(name, ecosystem, None, error="offline: not in cache")
        try:
            info = self._lookup_pypi(name) if ecosystem == PYPI else self._lookup_npm(name)
        except Exception as exc:
            return PackageInfo(name, ecosystem, None, error=f"lookup failed: {type(exc).__name__}")
        info.checked_at = _iso(self.now)
        if info.exists is not None:
            self.cache[key] = asdict(info)
        return info

    def ensure_downloads(self, info: PackageInfo) -> PackageInfo:
        """Fill PyPI download counts (pypistats) on demand; npm counts are always fetched."""
        if self.offline or not info.exists or info.ecosystem != PYPI or info.monthly_downloads is not None:
            return info
        try:
            status, body = self._fetch(f"https://pypistats.org/api/packages/{quote(normalize_pypi(info.name))}/recent")
        except Exception:
            return info
        if status == 200 and isinstance(body, dict):
            data = body.get("data") or {}
            info.weekly_downloads = data.get("last_week")
            info.monthly_downloads = data.get("last_month")
        elif status == 404:
            info.weekly_downloads = info.monthly_downloads = 0
        else:
            return info
        self.cache[cache_key(info.name, info.ecosystem)] = asdict(info)
        return info

    # ------------------------------------------------------------ PyPI
    def _lookup_pypi(self, name: str) -> PackageInfo:
        status, body = self._fetch(f"https://pypi.org/pypi/{quote(name)}/json")
        if status == 404:
            return PackageInfo(name, PYPI, False, note="PyPI 404")
        if status != 200 or not isinstance(body, dict):
            return PackageInfo(name, PYPI, None, error=f"PyPI HTTP {status}")
        releases = body.get("releases") or {}
        times = []
        n_with_files = 0
        for files in releases.values():
            stamps = [f.get("upload_time_iso_8601") or f.get("upload_time") for f in files or []]
            stamps = [s for s in stamps if s]
            if stamps:
                n_with_files += 1
                times.extend(parse_ts(s) for s in stamps)
        info_block = body.get("info") or {}
        info = PackageInfo(
            name=info_block.get("name") or name,
            ecosystem=PYPI,
            exists=True,
            first_release=_iso(min(times)) if times else None,
            latest_release=_iso(max(times)) if times else None,
            n_releases=n_with_files,
        )
        if not times:
            info.note = "project exists but has no uploaded files"
        info.extra = {
            "summary": (info_block.get("summary") or "")[:200],
            "home_page": info_block.get("home_page") or (info_block.get("project_urls") or {}).get("Homepage") or "",
            "requested_as": name,
        }
        return info

    # ------------------------------------------------------------ npm
    def _lookup_npm(self, name: str) -> PackageInfo:
        enc = quote(name, safe="@")
        enc = enc.replace("/", "%2F")
        st_dl, dl = self._fetch(f"https://api.npmjs.org/downloads/point/last-week/{enc}")
        weekly = dl.get("downloads") if st_dl == 200 and isinstance(dl, dict) else None

        if weekly is not None and weekly >= NPM_POPULAR_WEEKLY:
            status, _ = self._fetch(f"https://registry.npmjs.org/{enc}", method="HEAD")
            if status == 200:
                return PackageInfo(name, NPM, True, weekly_downloads=weekly,
                                   note=f"popular (>= {NPM_POPULAR_WEEKLY}/week); full document not fetched")

        status, body = self._fetch(f"https://registry.npmjs.org/{enc}")
        if status == 404:
            return PackageInfo(name, NPM, False, note="npm 404")
        if status != 200 or not isinstance(body, dict):
            return PackageInfo(name, NPM, None, error=f"npm HTTP {status}")
        t = body.get("time") or {}
        versions = body.get("versions") or {}
        info = PackageInfo(
            name=name,
            ecosystem=NPM,
            exists=True,
            first_release=_iso(parse_ts(t["created"])) if t.get("created") else None,
            latest_release=_iso(parse_ts(t["modified"])) if t.get("modified") else None,
            n_releases=len(versions),
            maintainers=len(body.get("maintainers") or []),
            weekly_downloads=weekly if weekly is not None else 0,
        )
        if "unpublished" in t and not versions:
            info.exists = False
            info.note = "npm: unpublished (name was used, now has no versions)"
        latest = (body.get("dist-tags") or {}).get("latest", "")
        if "security" in latest:
            info.note = "npm security holding package (name taken over by npm, usually after malware removal)"
        info.extra = {"description": (body.get("description") or "")[:200], "latest": latest}
        return info
