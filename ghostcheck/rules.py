"""The finding rules. Deterministic: the same registry data always gives the same findings."""
from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone

from .parsers import Dependency, PYPI, normalize_pypi
from .registry import PackageInfo, Registry
from .typosquat import llm_ghosts, nearest_top_package

HIGH, MEDIUM, INFO = "HIGH", "MEDIUM", "INFO"

NEW_DAYS = 30                 # first published less than this many days ago -> HIGH
YOUNG_DAYS = 183              # ~6 months
LOW_WEEKLY_NPM = 1_000        # weekly downloads
LOW_MONTHLY_PYPI = 2_000      # monthly downloads (pypistats)
ESTABLISHED_DAYS = 2 * 365    # typosquat check is skipped for packages older than this ...
ESTABLISHED_RELEASES = 10     # ... that also have at least this many releases


@dataclass(frozen=True)
class Finding:
    severity: str
    rule: str
    package: str
    ecosystem: str
    message: str
    source: str = ""


def _established(info: PackageInfo | None, now: datetime) -> bool:
    if not info or not info.exists:
        return False
    if info.ecosystem != PYPI and (info.weekly_downloads or 0) >= 50_000:
        return True
    age = info.age_days(now)
    return age is not None and age >= ESTABLISHED_DAYS and (info.n_releases or 0) >= ESTABLISHED_RELEASES


def check_dependency(dep: Dependency, registry: Registry | None, now: datetime | None = None) -> tuple[list[Finding], PackageInfo | None]:
    now = now or datetime.now(timezone.utc)
    findings: list[Finding] = []
    f = lambda sev, rule, msg: findings.append(Finding(sev, rule, dep.name, dep.ecosystem, msg, dep.source))

    key = f"{dep.ecosystem}:{normalize_pypi(dep.name) if dep.ecosystem == PYPI else dep.name}"
    ghost = llm_ghosts().get(key)
    if ghost:
        f(HIGH, "llm-ghost",
          f"an LLM invents this name: in our experiment {ghost.get('model', 'Gemma')} suggested it "
          f"({ghost.get('times', 1)}x) and it did not exist on {dep.ecosystem} on {ghost.get('checked', '?')}")

    info = registry.lookup(dep.name, dep.ecosystem) if registry else None
    reg = "PyPI" if dep.ecosystem == PYPI else "npm"
    if info is None or info.exists is None:
        if info is not None:
            f(INFO, "not-checked", f"registry not checked ({info.error or 'unknown'})")
    elif info.exists is False:
        f(HIGH, "not-found", f"does not exist on {reg} ({info.note or '404'}); anyone could register it")
    else:
        if info.note.startswith("npm security holding"):
            f(HIGH, "security-placeholder", "npm replaced this package with a security placeholder (it was malicious)")
        age = info.age_days(now)
        if age is not None and age < NEW_DAYS:
            f(HIGH, "brand-new", f"first published {age:.0f} days ago ({info.first_release[:10]})")
        elif age is not None and age < YOUNG_DAYS:
            if registry is not None:
                info = registry.ensure_downloads(info)
            low = (info.monthly_downloads is not None and info.monthly_downloads < LOW_MONTHLY_PYPI) if dep.ecosystem == PYPI \
                else (info.weekly_downloads is not None and info.weekly_downloads < LOW_WEEKLY_NPM)
            if low:
                dl = f"{info.monthly_downloads}/month" if dep.ecosystem == PYPI else f"{info.weekly_downloads}/week"
                f(MEDIUM, "young-and-unused", f"first published {age:.0f} days ago with only {dl} downloads")

    near = nearest_top_package(dep.name, dep.ecosystem)
    if near and not _established(info, now):
        top, dist = near
        f(MEDIUM, "typosquat", f"{dist} edit{'s' if dist > 1 else ''} away from the popular package '{top}'")
    return findings, info


def exit_code(findings: list[Finding]) -> int:
    return 1 if any(x.severity == HIGH for x in findings) else 0
