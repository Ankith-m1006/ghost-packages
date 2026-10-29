"""Edit-distance check against the bundled top-500 lists."""
from __future__ import annotations

import json
from functools import lru_cache
from importlib import resources

from .parsers import NPM, PYPI, normalize_pypi


def _read_list(filename: str) -> list[str]:
    text = resources.files("ghostcheck.data").joinpath(filename).read_text("utf-8")
    return [ln.strip() for ln in text.splitlines() if ln.strip() and not ln.startswith("#")]


@lru_cache(maxsize=None)
def top_packages(ecosystem: str) -> tuple[str, ...]:
    if ecosystem == PYPI:
        return tuple(normalize_pypi(n) for n in _read_list("top_pypi.txt"))
    return tuple(_read_list("top_npm.txt"))


@lru_cache(maxsize=None)
def llm_ghosts() -> dict[str, dict]:
    """{"pypi:name": {...}, "npm:name": {...}} names that our experiment saw an LLM invent."""
    try:
        text = resources.files("ghostcheck.data").joinpath("llm_ghosts.json").read_text("utf-8")
    except FileNotFoundError:
        return {}
    data = json.loads(text)
    out = {}
    for item in data.get("ghosts", []):
        name = normalize_pypi(item["name"]) if item["ecosystem"] == PYPI else item["name"]
        out[f"{item['ecosystem']}:{name}"] = item
    return out


def damerau_levenshtein(a: str, b: str, limit: int = 3) -> int:
    """Optimal string alignment distance; returns `limit` as soon as it is exceeded."""
    if a == b:
        return 0
    if abs(len(a) - len(b)) >= limit:
        return limit
    prev2: list[int] | None = None
    prev = list(range(len(b) + 1))
    for i in range(1, len(a) + 1):
        cur = [i] + [0] * len(b)
        row_min = cur[0]
        for j in range(1, len(b) + 1):
            cost = 0 if a[i - 1] == b[j - 1] else 1
            cur[j] = min(prev[j] + 1, cur[j - 1] + 1, prev[j - 1] + cost)
            if i > 1 and j > 1 and prev2 is not None and a[i - 1] == b[j - 2] and a[i - 2] == b[j - 1]:
                cur[j] = min(cur[j], prev2[j - 2] + 1)
            row_min = min(row_min, cur[j])
        if row_min >= limit:
            return limit
        prev2, prev = prev, cur
    return min(prev[-1], limit)


def max_distance_for(name: str) -> int:
    """Short names collide by accident, so allow less slack for them."""
    core = name.split("/")[-1]
    if len(core) < 4:
        return 0
    if len(core) < 8:
        return 1
    return 2


def _strip_separators(name: str) -> str:
    return name.replace("-", "").replace("_", "").replace(".", "")


def nearest_top_package(name: str, ecosystem: str) -> tuple[str, int] | None:
    """(top_package, distance) if `name` is 1-2 edits from a top package (and is not one itself)."""
    key = normalize_pypi(name) if ecosystem == PYPI else name.lower()
    tops = top_packages(ecosystem)
    if key in tops:
        return None
    allowed = max_distance_for(key)
    if allowed == 0:
        return None
    best: tuple[str, int] | None = None
    for top in tops:
        if max_distance_for(top) == 0:
            continue
        d = damerau_levenshtein(key, top, limit=allowed + 1)
        # "python-dateutil" vs "pythondateutil": separator-only difference also counts as 1
        if d > 1 and _strip_separators(key) == _strip_separators(top):
            d = 1
        if d <= allowed and (best is None or d < best[1]):
            best = (top, d)
            if d == 1:
                break
    return best
