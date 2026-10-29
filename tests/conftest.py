"""Shared fixtures: a fake registry so tests never touch the network."""
from __future__ import annotations

import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

NOW = datetime(2026, 10, 29, 12, 0, tzinfo=timezone.utc)


def ts(days_ago: float) -> str:
    return (NOW - timedelta(days=days_ago)).strftime("%Y-%m-%dT%H:%M:%SZ")


def pypi_doc(name: str, release_days_ago: list[float]) -> dict:
    return {
        "info": {"name": name, "summary": "x"},
        "releases": {f"0.{i}": [{"upload_time_iso_8601": ts(d)}] for i, d in enumerate(release_days_ago)},
    }


def npm_doc(name: str, created_days_ago: float, versions: int = 5, latest: str = "1.0.0") -> dict:
    return {
        "name": name,
        "dist-tags": {"latest": latest},
        "versions": {f"1.0.{i}": {} for i in range(versions)},
        "time": {"created": ts(created_days_ago), "modified": ts(1)},
        "maintainers": [{"name": "a"}],
    }


class FakeNet:
    """Maps URL -> (status, body). Unknown PyPI/npm URLs are 404. Records every request."""

    def __init__(self, routes: dict | None = None):
        self.routes = dict(routes or {})
        self.calls: list[tuple[str, str]] = []

    def __call__(self, url: str, method: str = "GET", headers: dict | None = None):
        self.calls.append((method, url))
        if url in self.routes:
            status, body = self.routes[url]
            return status, (body if method == "GET" else None)
        return 404, None

    # helpers
    def pypi(self, name, release_days_ago, monthly=None):
        self.routes[f"https://pypi.org/pypi/{name}/json"] = (200, pypi_doc(name, release_days_ago))
        if monthly is not None:
            self.routes[f"https://pypistats.org/api/packages/{name}/recent"] = (
                200, {"data": {"last_day": 1, "last_week": monthly // 4, "last_month": monthly}})
        return self

    def npm(self, name, created_days_ago, weekly=10, versions=5, latest="1.0.0"):
        enc = name.replace("/", "%2F")
        self.routes[f"https://api.npmjs.org/downloads/point/last-week/{enc}"] = (200, {"downloads": weekly})
        self.routes[f"https://registry.npmjs.org/{enc}"] = (200, npm_doc(name, created_days_ago, versions, latest))
        return self


@pytest.fixture
def net():
    return FakeNet()


@pytest.fixture
def now():
    return NOW
