"""Optional plain-English summary written by Gemma. The model only *describes* findings that the
deterministic rules already produced; it never adds, removes or changes a finding."""
from __future__ import annotations

from .gemma import Gemma, GemmaError, load_key
from .rules import Finding

DEFAULT_MODEL = "gemma-3-27b-it"


def build_prompt(findings: list[Finding]) -> str:
    lines = [f"- [{f.severity}] {f.ecosystem} package '{f.package}': {f.message}" for f in findings]
    return (
        "You are explaining the output of a dependency checker to a developer. Write ONE short "
        "paragraph (max 90 words) in plain English: what the risk is and what to do next. Only use "
        "the facts below; do not invent packages, numbers or new problems.\n\nFindings:\n" + "\n".join(lines)
    )


def explain(findings: list[Finding], model: str = DEFAULT_MODEL) -> str:
    if not findings:
        return "No findings, nothing to explain."
    key = load_key()
    if not key:
        return "(--explain skipped: set GEMINI_API_KEY to get a plain-English summary)"
    try:
        out = Gemma(key, min_interval=0).generate(model, build_prompt(findings), temperature=0.2, max_tokens=300)
    except GemmaError as exc:
        return f"(--explain failed: {exc})"
    return out["text"].strip()
