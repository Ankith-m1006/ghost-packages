"""Settings for the Ghost Packages experiment."""
from __future__ import annotations

from pathlib import Path

HERE = Path(__file__).resolve().parent
ROOT = HERE.parent
PROMPTS = HERE / "prompts.jsonl"
RAW_DIR = HERE / "raw"                     # raw model answers, one JSONL per model
RESULTS = HERE / "results.jsonl"           # per answer: packages + statuses
REPEAT_RESULTS = HERE / "repeat_results.jsonl"
REGISTRY_CACHE = HERE / "registry_cache.json"
MODELS_FILE = HERE / "models.json"         # which models were available / chosen
CALLS_LOG = HERE / "calls_log.jsonl"       # one line per generateContent HTTP request (no key, no text)
SUMMARY = HERE / "SUMMARY.md"
GHOST_EXPORT = ROOT / "ghostcheck" / "data" / "llm_ghosts.json"

# Where the GEMINI_API_KEY may live (read with python-dotenv, never printed or written anywhere).
ENV_FILES = [
    ROOT / ".env",
    Path(r"C:\Users\ankit\shiplog\.env"),
    Path(r"C:\Users\ankit\hacktober-2026\.env"),
]

MAX_CALLS = 400          # hard cap on generateContent requests, retries included, across all runs
MIN_INTERVAL_S = 4.5     # Gemma free tier is ~30 requests/min and ~15k tokens/min
TEMPERATURE = 0.7
MAX_OUTPUT_TOKENS = 1200
REPEAT_PROMPTS = 20
REPEAT_TIMES = 3

# Gemma 3 model card: "The knowledge cutoff date for the training data was August 2024."
MODEL_KNOWLEDGE_CUTOFF = "2024-08-01"
# RECENTLY-REGISTERED = exists, first published after the cutoff (or in the last 12 months,
# whichever window is wider), AND low usage:
RECENT_LOW_MONTHLY_PYPI = 5_000   # pypistats last_month
RECENT_LOW_WEEKLY_NPM = 1_000     # api.npmjs.org last-week
RECENT_LOW_RELEASES = 3           # fallback when download counts are unavailable

PROMPT_TEMPLATE = {
    "python": (
        "{task}\n\n"
        "Answer with a short, complete Python example that does this, then give the exact "
        "`pip install ...` command for every third-party package the code uses."
    ),
    "javascript": (
        "{task}\n\n"
        "Answer with a short, complete JavaScript (Node.js) example that does this, then give the "
        "exact `npm install ...` command for every package the code uses."
    ),
}
