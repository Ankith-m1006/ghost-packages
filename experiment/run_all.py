"""Run the whole experiment end to end (resumable; re-running skips work already done).

    python -m experiment.run_all
"""
from __future__ import annotations

import os

from . import analyze, generate, repeat, summarize
from .common import load_models


def main() -> None:
    models = generate.list_models()
    generate.run_model(models["primary"])          # 150 calls
    analyze.analyze()
    repeat.run_reruns(models["primary"])           # up to 20 x 3 calls
    if models.get("secondary") and os.environ.get("GP_SECONDARY") == "1":  # optional: slow, off by default
        generate.run_model(models["secondary"])    # up to 150 calls, stops at the cap
    analyze.analyze()
    repeat.score(load_models()["primary"])
    summarize.main()


if __name__ == "__main__":
    main()
