"""Step 1 + 2: pick the Gemma models, then ask every prompt once per model (resumable).

    python -m experiment.generate --list-models
    python -m experiment.generate --model primary
    python -m experiment.generate --model secondary
"""
from __future__ import annotations

import argparse
import json

from ghostcheck.gemma import GemmaError

from . import config
from .common import (Budget, BudgetExceeded, append_jsonl, build_prompt, choose_models, client, load_models,
                     load_prompts, now_iso, raw_path, read_jsonl)


def list_models() -> dict:
    g = client()
    info = choose_models(g.list_models())
    config.MODELS_FILE.write_text(json.dumps(info, indent=2), "utf-8")
    print(f"primary={info['primary']} secondary={info['secondary']}")
    print("gemma models listed:", ", ".join(info["all_gemma_models"]))
    return info


def run_model(model: str, limit: int | None = None) -> int:
    g = client()
    budget = Budget()
    out = raw_path(model)
    done = {r["prompt_id"] for r in read_jsonl(out) if "text" in r}  # errors are retried on the next run
    todo = [p for p in load_prompts() if p["id"] not in done][: limit or None]
    print(f"{model}: {len(done)} done, {len(todo)} to go, budget left {budget.remaining()}")
    n = 0
    for p in todo:
        try:
            res = g.generate(model, build_prompt(p), temperature=config.TEMPERATURE,
                             max_tokens=config.MAX_OUTPUT_TOKENS, on_call=lambda: budget.charge(model, "main"))
        except BudgetExceeded as exc:
            print(f"stopping: {exc}")
            break
        except GemmaError as exc:
            print(f"  {p['id']}: {exc}")
            append_jsonl(out, {"model": model, "prompt_id": p["id"], "language": p["language"], "error": str(exc), "t": now_iso()})
            continue
        append_jsonl(out, {"model": model, "prompt_id": p["id"], "language": p["language"], "text": res["text"],
                           "finish_reason": res["finish_reason"], "usage": res["usage"], "t": now_iso()})
        n += 1
        if n % 10 == 0:
            print(f"  {n} answers, budget left {budget.remaining()}")
    return n


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--list-models", action="store_true")
    ap.add_argument("--model", help="'primary', 'secondary' or an exact model id")
    ap.add_argument("--limit", type=int)
    a = ap.parse_args()
    if a.list_models:
        list_models()
    if a.model:
        model = load_models()[a.model] if a.model in ("primary", "secondary") else a.model
        if model:
            run_model(model, a.limit)


if __name__ == "__main__":
    main()
