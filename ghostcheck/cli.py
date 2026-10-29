"""ghostcheck command line.

    ghostcheck requirements.txt
    ghostcheck package.json
    ghostcheck --pip "pip install a b"
    ghostcheck --npm "npm install a b"

Exit codes: 0 = no HIGH findings, 1 = at least one HIGH finding, 2 = usage / input error.
"""
from __future__ import annotations

import argparse
import json
import os
import sys
from dataclasses import asdict
from pathlib import Path

from . import __version__
from .parsers import Dependency, parse_npm_command, parse_package_json, parse_pip_command, parse_requirements
from .registry import Registry
from .rules import HIGH, INFO, MEDIUM, Finding, check_dependency, exit_code


def default_cache_path() -> Path:
    base = os.environ.get("GHOSTCHECK_CACHE") or os.environ.get("XDG_CACHE_HOME") or (Path.home() / ".cache")
    p = Path(base)
    return p if p.suffix == ".json" else p / "ghostcheck" / "registry_cache.json"


def load_dependencies(args) -> list[Dependency]:
    deps: list[Dependency] = []
    if args.pip:
        deps += parse_pip_command(args.pip)
    if args.npm:
        deps += parse_npm_command(args.npm)
    for f in args.files:
        path = Path(f)
        text = path.read_text("utf-8")
        if path.name.endswith(".json"):
            deps += parse_package_json(text, source=path.name)
        else:
            deps += parse_requirements(text, source=path.name)
    return deps


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(prog="ghostcheck", description="Flag ghost / suspicious dependencies before you install them.")
    ap.add_argument("files", nargs="*", help="requirements*.txt or package.json files")
    ap.add_argument("--pip", metavar="CMD", help='a pip command, e.g. "pip install foo bar"')
    ap.add_argument("--npm", metavar="CMD", help='an npm command, e.g. "npm install foo"')
    ap.add_argument("--offline", action="store_true", help="no network: bundled lists + cache only")
    ap.add_argument("--cache", metavar="PATH", help="registry cache file (default ~/.cache/ghostcheck/registry_cache.json)")
    ap.add_argument("--json", action="store_true", help="machine-readable output")
    ap.add_argument("--explain", action="store_true", help="add a plain-English paragraph written by Gemma (needs GEMINI_API_KEY)")
    ap.add_argument("--version", action="version", version=f"ghostcheck {__version__}")
    args = ap.parse_args(argv)

    if not (args.files or args.pip or args.npm):
        ap.print_usage(sys.stderr)
        print("ghostcheck: give a file, --pip or --npm", file=sys.stderr)
        return 2
    try:
        deps = load_dependencies(args)
    except (OSError, ValueError) as exc:
        print(f"ghostcheck: {exc}", file=sys.stderr)
        return 2

    registry = Registry(cache_path=args.cache or default_cache_path(), offline=args.offline)
    findings: list[Finding] = []
    for dep in deps:
        found, _ = check_dependency(dep, registry)
        findings += found
    try:
        registry.save()
    except OSError:
        pass

    code = exit_code(findings)
    if args.json:
        print(json.dumps({"checked": len(deps), "offline": args.offline, "exit_code": code,
                          "findings": [asdict(f) for f in findings]}, indent=2))
    else:
        mode = " (offline)" if args.offline else ""
        print(f"ghostcheck {__version__}: checked {len(deps)} dependencies{mode}")
        order = {HIGH: 0, MEDIUM: 1, INFO: 2}
        for f in sorted(findings, key=lambda x: (order[x.severity], x.package)):
            where = f"  [{f.source}]" if f.source else ""
            print(f"  {f.severity:<6} {f.ecosystem}:{f.package}  {f.rule}: {f.message}{where}")
        highs = sum(f.severity == HIGH for f in findings)
        meds = sum(f.severity == MEDIUM for f in findings)
        print(f"{highs} high, {meds} medium" + ("  -> do not install until reviewed" if highs else ""))
    if args.explain and findings:
        from .explain import explain
        print("\n" + explain([f for f in findings if f.severity != INFO]))
    return code


if __name__ == "__main__":
    sys.exit(main())
