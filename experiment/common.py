"""Shared helpers: JSONL I/O, the call budget, model selection."""
from __future__ import annotations

import json
import re
import sys
from datetime import datetime, timezone
from pathlib import Path

from ghostcheck.gemma import Gemma, load_key

from . import config


def read_jsonl(path: Path) -> list[dict]:
    if not path.exists():
        return []
    return [json.loads(line) for line in path.read_text("utf-8").splitlines() if line.strip()]


def append_jsonl(path: Path, row: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("a", encoding="utf-8", newline="\n") as f:
        f.write(json.dumps(row, ensure_ascii=False) + "\n")


def write_jsonl(path: Path, rows: list[dict]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8", newline="\n") as f:
        for r in rows:
            f.write(json.dumps(r, ensure_ascii=False) + "\n")


def now_iso() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def load_prompts() -> list[dict]:
    return read_jsonl(config.PROMPTS)


def raw_path(model: str, kind: str = "main") -> Path:
    return config.RAW_DIR / f"{kind}__{model}.jsonl"


class BudgetExceeded(RuntimeError):
    pass


class Budget:
    """Counts every generateContent HTTP request (retries included) in calls_log.jsonl."""

    def __init__(self, limit: int = config.MAX_CALLS):
        self.limit = limit
        self.used = len(read_jsonl(config.CALLS_LOG))

    def remaining(self) -> int:
        return self.limit - self.used

    def charge(self, model: str, purpose: str) -> None:
        if self.used >= self.limit:
            raise BudgetExceeded(f"call budget of {self.limit} reached")
        self.used += 1
        append_jsonl(config.CALLS_LOG, {"t": now_iso(), "model": model, "purpose": purpose})


def client() -> Gemma:
    key = load_key(config.ENV_FILES)
    if not key:
        sys.exit("GEMINI_API_KEY not found (env var, ./.env, or the .env files listed in experiment/config.py)")
    return Gemma(key, min_interval=config.MIN_INTERVAL_S)


def _size_b(name: str) -> float:
    m = re.search(r"-(\d+(?:\.\d+)?)b-", name + "-")
    if m:
        return float(m.group(1))
    m = re.search(r"-e(\d+)b-", name + "-")  # gemma-3n-e4b-it: effective size
    return float(m.group(1)) if m else 0.0


def choose_models(models: list[dict]) -> dict:
    """Best Gemma instruct model (newest generation, then largest), plus the next one down for comparison."""
    gemma = []
    for m in models:
        name = m.get("name", "").removeprefix("models/")
        if re.match(r"gemma-\d", name) and name.endswith("-it") and "generateContent" in m.get("supportedGenerationMethods", []):
            gemma.append(name)
    gen = lambda g: int(re.match(r"gemma-(\d+)", g).group(1))
    plain = sorted([g for g in gemma if not re.match(r"gemma-\d+n", g)], key=lambda g: (gen(g), _size_b(g)), reverse=True)
    chosen = plain[:2] if plain else sorted(gemma, key=lambda g: (gen(g), _size_b(g)), reverse=True)[:2]
    return {
        "listed_at": now_iso(),
        "all_gemma_models": sorted(m.get("name", "").removeprefix("models/") for m in models if "gemma" in m.get("name", "")),
        "primary": chosen[0] if chosen else None,
        "secondary": chosen[1] if len(chosen) > 1 else None,
    }


def load_models() -> dict:
    return json.loads(config.MODELS_FILE.read_text("utf-8"))


def build_prompt(p: dict) -> str:
    return config.PROMPT_TEMPLATE[p["language"]].format(task=p["task"])
