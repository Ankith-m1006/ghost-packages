"""Step 4: repeatability. Re-ask up to 20 ghost-producing prompts 3 more times each (primary model)
and record whether the same ghost name comes back.

    python -m experiment.repeat           -> raw/repeat__<model>.jsonl + repeat_results.jsonl
"""
from __future__ import annotations

from datetime import datetime, timezone

from ghostcheck.gemma import GemmaError
from ghostcheck.parsers import PYPI, normalize_pypi

from . import config
from .analyze import registry
from .classify import GHOST, classify_answer
from .common import (Budget, BudgetExceeded, append_jsonl, build_prompt, client, load_models, load_prompts,
                     now_iso, raw_path, read_jsonl, write_jsonl)


def _key(m: dict) -> str:
    return f"{m['ecosystem']}:{normalize_pypi(m['name']) if m['ecosystem'] == PYPI else m['name']}"


def _all_names(c: dict) -> set[str]:
    """Every name a rerun mentions (installs + imports), normalised, regardless of status."""
    names = {_key(m) for m in c["mentions"]}
    ex = c["extraction"]
    names |= {f"pypi:{normalize_pypi(n)}" for n in ex["pip_installs"] + ex["python_imports"]}
    names |= {f"npm:{n}" for n in ex["npm_installs"] + ex["js_imports"]}
    return names


def selected_prompts(model: str) -> list[dict]:
    results = [r for r in read_jsonl(config.RESULTS) if r["model"] == model and r["has_ghost"]]
    return sorted(results, key=lambda r: r["prompt_id"])[: config.REPEAT_PROMPTS]


def run_reruns(model: str) -> None:
    g = client()
    budget = Budget()
    prompts = {p["id"]: p for p in load_prompts()}
    out = raw_path(model, "repeat")
    have: dict[str, int] = {}
    for r in read_jsonl(out):
        if "text" in r:
            have[r["prompt_id"]] = have.get(r["prompt_id"], 0) + 1
    for r in selected_prompts(model):
        p = prompts[r["prompt_id"]]
        for i in range(have.get(p["id"], 0), config.REPEAT_TIMES):
            try:
                res = g.generate(model, build_prompt(p), temperature=config.TEMPERATURE,
                                 max_tokens=config.MAX_OUTPUT_TOKENS, on_call=lambda: budget.charge(model, "repeat"))
            except BudgetExceeded as exc:
                print(f"stopping: {exc}")
                return
            except GemmaError as exc:
                print(f"  {p['id']} rerun {i + 1}: {exc}")
                continue
            append_jsonl(out, {"model": model, "prompt_id": p["id"], "rerun": i + 1, "language": p["language"],
                               "text": res["text"], "finish_reason": res["finish_reason"], "t": now_iso()})
    print(f"reruns done, budget left {budget.remaining()}")


def score(model: str) -> list[dict]:
    reg = registry()
    now = datetime.now(timezone.utc)
    prompts = {p["id"]: p for p in load_prompts()}
    reruns: dict[str, list[dict]] = {}
    for r in read_jsonl(raw_path(model, "repeat")):
        if "text" in r:
            reruns.setdefault(r["prompt_id"], []).append(r)
    rows = []
    for orig in selected_prompts(model):
        pid = orig["prompt_id"]
        ghosts = sorted({_key(m) for m in orig["packages"] if m["status"] == GHOST})
        runs = []
        for rr in reruns.get(pid, [])[: config.REPEAT_TIMES]:
            c = classify_answer(rr["text"], prompts[pid]["language"], reg, now)
            names = _all_names(c)
            runs.append({
                "rerun": rr["rerun"],
                "original_ghosts_back": [gk for gk in ghosts if gk in names],
                "ghosts_in_rerun": sorted({_key(m) for m in c["mentions"] if m["status"] == GHOST}),
                "packages": c["mentions"],
            })
        rows.append({
            "model": model, "prompt_id": pid, "task": orig["task"], "original_ghosts": ghosts,
            "reruns": runs,
            "per_ghost_returns": {gk: sum(gk in r["original_ghosts_back"] for r in runs) for gk in ghosts},
        })
    reg.save()
    write_jsonl(config.REPEAT_RESULTS, rows)
    return rows


def main() -> None:
    model = load_models()["primary"]
    run_reruns(model)
    rows = score(model)
    print(f"scored {len(rows)} prompts")


if __name__ == "__main__":
    main()
