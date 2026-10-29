"""Step 3: extract package names from every answer, check them live on PyPI / npm, classify.

    python -m experiment.analyze          -> experiment/results.jsonl
"""
from __future__ import annotations

from datetime import datetime, timezone

from ghostcheck.registry import Registry

from . import config
from .classify import GHOST, classify_answer
from .common import load_models, load_prompts, raw_path, read_jsonl, write_jsonl


def registry() -> Registry:
    # ttl None: the cache is the experiment's snapshot; delete it to re-check everything
    return Registry(cache_path=config.REGISTRY_CACHE, ttl_hours=None, min_interval=0.25)


def latest_answers(model: str, kind: str = "main") -> list[dict]:
    rows = [r for r in read_jsonl(raw_path(model, kind)) if "text" in r]
    if kind == "main":
        by_id = {r["prompt_id"]: r for r in rows}
        return list(by_id.values())
    return rows


def analyze() -> list[dict]:
    reg = registry()
    now = datetime.now(timezone.utc)
    prompts = {p["id"]: p for p in load_prompts()}
    models = load_models()
    out = []
    for model in [models.get("primary"), models.get("secondary")]:
        if not model:
            continue
        for ans in sorted(latest_answers(model), key=lambda r: r["prompt_id"]):
            p = prompts[ans["prompt_id"]]
            c = classify_answer(ans["text"], p["language"], reg, now)
            statuses = [m["status"] for m in c["mentions"]]
            out.append({
                "model": model, "prompt_id": p["id"], "language": p["language"], "domain": p["domain"],
                "task": p["task"], "finish_reason": ans.get("finish_reason"),
                "packages": c["mentions"], "statuses": statuses,
                "has_ghost": GHOST in statuses, "extraction": c["extraction"],
            })
        reg.save()
    write_jsonl(config.RESULTS, out)
    reg.save()
    print(f"analyzed {len(out)} answers; registry requests this run: {reg.requests_made}")
    return out


if __name__ == "__main__":
    analyze()
