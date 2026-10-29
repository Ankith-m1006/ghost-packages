"""Step 5: write experiment/SUMMARY.md and export the ghost list that ghostcheck bundles.

    python -m experiment.summarize
"""
from __future__ import annotations

import json
from collections import Counter, defaultdict

from ghostcheck.parsers import PYPI, normalize_pypi

from . import config
from .classify import GHOST, MISMATCH, RECENT, UNKNOWN, UNRESOLVED
from .common import load_models, raw_path, read_jsonl

NOTES = config.HERE / "spot_check_notes.md"


def key(m: dict) -> str:
    return f"{m['ecosystem']}:{normalize_pypi(m['name']) if m['ecosystem'] == PYPI else m['name']}"


def pct(a: int, b: int) -> str:
    return f"{(100 * a / b):.1f}%" if b else "n/a"


def stats(rows: list[dict]) -> dict:
    mentions = [m for r in rows for m in r["packages"]]
    status_of: dict[str, str] = {}
    for m in mentions:
        status_of.setdefault(key(m), m["status"])
    uniq = set(status_of)
    ghosts = {k for k, s in status_of.items() if s == GHOST}
    return {
        "answers": len(rows),
        "answers_with_ghost": sum(r["has_ghost"] for r in rows),
        "mentions": len(mentions),
        "ghost_mentions": sum(m["status"] == GHOST for m in mentions),
        "unique": len(uniq),
        "unique_ghosts": len(ghosts),
        "ghost_names": sorted(ghosts),
        "recent": sorted(k for k, s in status_of.items() if s == RECENT),
        "mismatch": sum(s == MISMATCH for s in status_of.values()),
        "unresolved": sorted(k for k, s in status_of.items() if s == UNRESOLVED),
        "unknown": sorted(k for k, s in status_of.items() if s == UNKNOWN),
        "answers_without_packages": sum(not r["packages"] for r in rows),
    }


def stat_lines(s: dict) -> list[str]:
    return [
        f"| answers analysed | {s['answers']} |",
        f"| answers with >= 1 ghost package | {s['answers_with_ghost']} ({pct(s['answers_with_ghost'], s['answers'])}) |",
        f"| package mentions (non-stdlib) | {s['mentions']} |",
        f"| unique package names | {s['unique']} |",
        f"| unique ghost names | {s['unique_ghosts']} ({pct(s['unique_ghosts'], s['unique'])} of unique names) |",
        f"| ghost mentions | {s['ghost_mentions']} ({pct(s['ghost_mentions'], s['mentions'])} of mentions) |",
        f"| recently registered (possible squats) | {len(s['recent'])} |",
        f"| import-name mismatches (not ghosts) | {s['mismatch']} |",
        f"| unresolved imports (not counted as ghosts) | {len(s['unresolved'])} |",
        f"| registry check failed | {len(s['unknown'])} |",
        f"| answers with no third-party package | {s['answers_without_packages']} |",
    ]


def repeat_stats(rows: list[dict]) -> dict:
    pairs = [(r["prompt_id"], g, n, len(r["reruns"])) for r in rows for g, n in r["per_ghost_returns"].items()]
    full = [p for p in pairs if p[3] == config.REPEAT_TIMES]
    return {
        "prompts": len(rows),
        "reruns": sum(len(r["reruns"]) for r in rows),
        "pairs": len(pairs),
        "back_once": sum(p[2] >= 1 for p in pairs),
        "back_all": sum(p[2] == config.REPEAT_TIMES for p in full),
        "full_pairs": len(full),
        "prompts_any_back": sum(any(n >= 1 for n in r["per_ghost_returns"].values()) for r in rows),
        "reruns_with_ghost": sum(bool(x["ghosts_in_rerun"]) for r in rows for x in r["reruns"]),
        "total_returns": sum(p[2] for p in pairs),
        "total_slots": sum(p[3] for p in pairs),
    }


def main() -> None:
    models = load_models()
    rows = read_jsonl(config.RESULTS)
    reps = read_jsonl(config.REPEAT_RESULTS)
    cache = json.loads(config.REGISTRY_CACHE.read_text("utf-8")) if config.REGISTRY_CACHE.exists() else {}
    calls = read_jsonl(config.CALLS_LOG)
    stamps = sorted(r["t"] for m in [models.get("primary"), models.get("secondary")] if m
                    for kind in ("main", "repeat") for r in read_jsonl(raw_path(m, kind)) if "t" in r)
    checked = sorted(v.get("checked_at", "") for v in cache.values() if v.get("checked_at"))

    # how often each ghost was suggested (main runs of both models + reruns)
    times: Counter = Counter()
    prompts_for: dict[str, list[str]] = defaultdict(list)
    models_for: dict[str, set] = defaultdict(set)
    first: dict[str, dict] = {}
    for r in rows:
        for m in r["packages"]:
            if m["status"] == GHOST:
                k = key(m)
                times[k] += 1
                models_for[k].add(r["model"])
                if r["prompt_id"] not in prompts_for[k]:
                    prompts_for[k].append(r["prompt_id"])
                first.setdefault(k, {"prompt_id": r["prompt_id"], "task": r["task"], "model": r["model"],
                                     "origin": m["origin"], "imports": m["import_names"]})
    for rr in reps:
        for run in rr["reruns"]:
            for m in run["packages"]:
                if m["status"] == GHOST:
                    times[key(m)] += 1
                    models_for[key(m)].add(rr["model"])
                    first.setdefault(key(m), {"prompt_id": rr["prompt_id"], "task": rr["task"], "model": rr["model"],
                                              "origin": m["origin"], "imports": m["import_names"]})

    L = ["# Ghost Packages: results", ""]
    L.append(f"- Models: primary `{models.get('primary')}`" + (f", secondary `{models.get('secondary')}`" if models.get("secondary") else ""))
    L.append(f"- Gemma models listed by the API on {models.get('listed_at', '?')[:10]}: {', '.join(models.get('all_gemma_models', []))}")
    if stamps:
        L.append(f"- Answers generated: {stamps[0]} to {stamps[-1]} (UTC); temperature {config.TEMPERATURE}, max {config.MAX_OUTPUT_TOKENS} output tokens")
    if checked:
        L.append(f"- Registries checked (PyPI JSON API, npm registry): {checked[0]} to {checked[-1]} (UTC)")
    L.append(f"- Prompts: {len(read_jsonl(config.PROMPTS))} (see prompts.jsonl); API requests used: {len(calls)} of a {config.MAX_CALLS} cap")
    L.append("- GHOST = the name a user would install returned 404. Python import names are never called ghosts on their own (see UNRESOLVED-IMPORT).")
    L.append("")

    for label, sub in [("All models", rows)] + [(f"`{m}`", [r for r in rows if r["model"] == m])
                                                for m in [models.get("primary"), models.get("secondary")] if m]:
        if not sub:
            continue
        s = stats(sub)
        L += [f"## {label}", "", "| metric | value |", "|---|---|"] + stat_lines(s) + [""]
        for lang in ("python", "javascript"):
            ls = stats([r for r in sub if r["language"] == lang])
            if ls["answers"]:
                L.append(f"- {lang}: {ls['answers_with_ghost']}/{ls['answers']} answers with a ghost "
                         f"({pct(ls['answers_with_ghost'], ls['answers'])}), {ls['unique_ghosts']}/{ls['unique']} unique names are ghosts "
                         f"({pct(ls['unique_ghosts'], ls['unique'])})")
        L.append("")

    s_all = stats(rows)
    L += ["## Ghost rate by domain (all models)", "", "| domain | answers | with ghost |", "|---|---|---|"]
    by_dom: dict[str, list] = defaultdict(list)
    for r in rows:
        by_dom[r["domain"]].append(r)
    for d, rs in sorted(by_dom.items(), key=lambda kv: -sum(r["has_ghost"] for r in kv[1]) / len(kv[1])):
        g = sum(r["has_ghost"] for r in rs)
        L.append(f"| {d} | {len(rs)} | {g} ({pct(g, len(rs))}) |")
    L.append("")

    L += ["## Recently registered names (exist, but first published after the model's knowledge cutoff, low usage)", ""]
    if s_all["recent"]:
        L += ["| package | first published | releases | downloads | suggested for |", "|---|---|---|---|---|"]
        for k in s_all["recent"]:
            m = next(m for r in rows for m in r["packages"] if key(m) == k)
            r0 = next(r for r in rows for mm in r["packages"] if key(mm) == k)
            unit = "/month" if m["ecosystem"] == PYPI else "/week"
            L.append(f"| {k} | {(m['first_release'] or '?')[:10]} | {m['n_releases']} | {m['downloads']}{unit} | {r0['prompt_id']}: {r0['task']} |")
    else:
        L.append("None.")
    L.append("")

    if reps:
        rs = repeat_stats(reps)
        L += ["## Repeatability (primary model)", "",
              f"- {rs['prompts']} ghost-producing prompts re-asked {config.REPEAT_TIMES} more times each ({rs['reruns']} reruns).",
              f"- (prompt, ghost) pairs: {rs['pairs']}. The same ghost name came back in at least one rerun: "
              f"{rs['back_once']}/{rs['pairs']} ({pct(rs['back_once'], rs['pairs'])}); in all {config.REPEAT_TIMES} reruns: "
              f"{rs['back_all']}/{rs['full_pairs']} ({pct(rs['back_all'], rs['full_pairs'])}).",
              f"- Across all rerun slots, a ghost reappeared {rs['total_returns']}/{rs['total_slots']} times ({pct(rs['total_returns'], rs['total_slots'])}).",
              f"- Prompts where at least one original ghost came back: {rs['prompts_any_back']}/{rs['prompts']} ({pct(rs['prompts_any_back'], rs['prompts'])}).",
              f"- Reruns that contained any ghost (same or new): {rs['reruns_with_ghost']}/{rs['reruns']} ({pct(rs['reruns_with_ghost'], rs['reruns'])}).",
              ""]

    L += ["## Most convincing ghosts", "",
          "Ranked by how many times the model suggested the name (main runs + reruns, all models), then by number of prompts.", "",
          "| # | ghost | times suggested | models | first prompt |", "|---|---|---|---|---|"]
    ranked = sorted(times, key=lambda k: (-times[k], -len(prompts_for[k]), k))
    for i, k in enumerate(ranked[:10], 1):
        f = first[k]
        L.append(f"| {i} | `{k}` | {times[k]} | {', '.join(sorted(models_for[k]))} | {f['prompt_id']}: {f['task']} |")
    L.append("")
    if s_all["unresolved"]:
        L += ["## Unresolved Python imports (not counted as ghosts)", "", ", ".join(f"`{u}`" for u in s_all["unresolved"]), ""]
    if NOTES.exists():
        L += ["## Manual spot-check notes", "", NOTES.read_text("utf-8").strip(), ""]
    config.SUMMARY.write_text("\n".join(L), "utf-8")

    export = {
        "note": "Package names that did not exist on the registry when Gemma suggested them (Ghost Packages experiment). "
                "A 404 on the date checked; any of these may be registered later, by anyone.",
        "ghosts": [{"name": k.split(":", 1)[1], "ecosystem": k.split(":", 1)[0], "times": times[k],
                    "model": ", ".join(sorted(models_for[k])), "checked": (checked[-1][:10] if checked else ""),
                    "example_task": first[k]["task"]} for k in ranked],
    }
    config.GHOST_EXPORT.write_text(json.dumps(export, indent=1, ensure_ascii=False), "utf-8")
    print(f"wrote {config.SUMMARY} and {len(ranked)} ghosts to {config.GHOST_EXPORT}")


if __name__ == "__main__":
    main()
