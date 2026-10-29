"""Turn one model answer into package mentions with a status each.

Statuses (conservative on purpose):
  GHOST                 the name a user would install does not exist on the registry (404).
                        Python: a name from the pip install line. JavaScript: a name from the npm
                        install line or an import/require specifier (npm import name == package name).
  RECENTLY-REGISTERED   exists, but was first published after the model's knowledge cutoff and has
                        very little usage: the model could not have learned it, so it may be a squat.
  EXISTS-ESTABLISHED    exists and is not recent+unused.
  IMPORT-NAME-MISMATCH  Python import name differs from the distribution name, and the install line
                        (or a well-known mapping) supplies the right distribution, e.g. cv2 ->
                        opencv-python. Not a ghost.
  UNRESOLVED-IMPORT     Python import with no matching install name, and the import name itself is
                        not on PyPI. Could be a hallucinated module or a local file; NOT counted as a ghost.
  UNKNOWN               registry could not be checked.
"""
from __future__ import annotations

from dataclasses import asdict, dataclass
from datetime import datetime, timedelta, timezone

from ghostcheck.parsers import NPM, PYPI, extract_from_answer, normalize_pypi
from ghostcheck.registry import PackageInfo, Registry, parse_ts

from . import config
from .import_map import IMPORT_TO_DIST

GHOST = "GHOST"
RECENT = "RECENTLY-REGISTERED"
EXISTS = "EXISTS-ESTABLISHED"
MISMATCH = "IMPORT-NAME-MISMATCH"
UNRESOLVED = "UNRESOLVED-IMPORT"
UNKNOWN = "UNKNOWN"


@dataclass
class Mention:
    ecosystem: str
    name: str                 # the name that was checked on the registry
    install_name: str | None  # from the install command, if any
    import_names: list[str]   # import names that map to it
    origin: str               # "install", "import" or "both"
    status: str
    first_release: str | None = None
    n_releases: int | None = None
    downloads: int | None = None
    note: str = ""


def recent_window_start(now: datetime) -> datetime:
    cutoff = parse_ts(config.MODEL_KNOWLEDGE_CUTOFF + "T00:00:00Z")
    return min(cutoff, now - timedelta(days=365))


def status_for(info: PackageInfo, registry: Registry, now: datetime) -> tuple[str, PackageInfo]:
    if info.exists is None:
        return UNKNOWN, info
    if info.exists is False:
        return GHOST, info
    if not info.first_release:
        return EXISTS, info  # popular npm package (created date not fetched) or no files
    if parse_ts(info.first_release) < recent_window_start(now):
        return EXISTS, info
    if info.ecosystem == PYPI:
        info = registry.ensure_downloads(info)
        low = (info.monthly_downloads < config.RECENT_LOW_MONTHLY_PYPI) if info.monthly_downloads is not None \
            else (info.n_releases or 0) <= config.RECENT_LOW_RELEASES
    else:
        low = (info.weekly_downloads or 0) < config.RECENT_LOW_WEEKLY_NPM
    return (RECENT if low else EXISTS), info


def _mention(eco, name, install, imports, origin, status, info: PackageInfo | None, note=""):
    dl = None
    if info is not None:
        dl = info.monthly_downloads if eco == PYPI else info.weekly_downloads
    return Mention(eco, name, install, imports, origin, status,
                   info.first_release if info else None, info.n_releases if info else None, dl,
                   note or (info.note if info else ""))


def _candidates(imp: str) -> set[str]:
    n = normalize_pypi(imp)
    c = {n, f"python-{n}", f"py{n}", f"{n}-python", f"{n}-py", f"py-{n}"}
    if imp in IMPORT_TO_DIST:
        c.add(normalize_pypi(IMPORT_TO_DIST[imp]))
    return c


def classify_python(installs: list[str], imports: list[str], registry: Registry, now: datetime) -> list[Mention]:
    out: list[Mention] = []
    inst_norm = {normalize_pypi(n): n for n in installs}
    matched: dict[str, list[str]] = {k: [] for k in inst_norm}
    unmatched_imports = []
    for imp in imports:
        hit = next((k for k in inst_norm if k in _candidates(imp)), None)
        if hit:
            matched[hit].append(imp)
        else:
            unmatched_imports.append(imp)

    spare_installs = []  # install names no import explained (may provide an import under another name)
    for key, raw in inst_norm.items():
        info = registry.lookup(raw, PYPI)
        status, info = status_for(info, registry, now)
        imps = matched[key]
        if status == EXISTS and any(normalize_pypi(i) != key for i in imps):
            status = MISMATCH
        if not imps and status in (EXISTS, RECENT):
            spare_installs.append(key)
        out.append(_mention(PYPI, raw, raw, imps, "both" if imps else "install", status, info))

    for imp in unmatched_imports:
        if imp in IMPORT_TO_DIST:
            dist_info = registry.lookup(IMPORT_TO_DIST[imp], PYPI)
            out.append(_mention(PYPI, IMPORT_TO_DIST[imp], None, [imp], "import", MISMATCH, dist_info,
                                f"well-known import name; distribution is {IMPORT_TO_DIST[imp]}"))
            continue
        info = registry.lookup(imp, PYPI)
        if info.exists is False:
            if spare_installs:
                out.append(_mention(PYPI, imp, None, [imp], "import", MISMATCH, info,
                                    f"not on PyPI; probably provided by {', '.join(spare_installs)} from the install line"))
            else:
                out.append(_mention(PYPI, imp, None, [imp], "import", UNRESOLVED, info,
                                    "import name not on PyPI and no install name provides it"))
            continue
        status, info = status_for(info, registry, now)
        out.append(_mention(PYPI, imp, None, [imp], "import", status, info))
    return out


def classify_js(installs: list[str], imports: list[str], registry: Registry, now: datetime) -> list[Mention]:
    out: list[Mention] = []
    names = list(dict.fromkeys(installs + imports))
    for name in names:
        origin = "both" if (name in installs and name in imports) else ("install" if name in installs else "import")
        info = registry.lookup(name, NPM)
        status, info = status_for(info, registry, now)
        out.append(_mention(NPM, name, name if name in installs else None, [name] if name in imports else [], origin, status, info))
    return out


def classify_answer(text: str, language: str, registry: Registry, now: datetime | None = None) -> dict:
    now = now or datetime.now(timezone.utc)
    ex = extract_from_answer(text, language)
    if language == "python":
        mentions = classify_python(ex.pip_installs, ex.python_imports, registry, now)
        # an npm line inside a Python answer (rare) is still a recommendation to install
        mentions += classify_js(ex.npm_installs, [], registry, now)
    else:
        mentions = classify_js(ex.npm_installs, ex.js_imports, registry, now)
        mentions += classify_python(ex.pip_installs, [], registry, now)
    return {"extraction": asdict(ex), "mentions": [asdict(m) for m in mentions]}
