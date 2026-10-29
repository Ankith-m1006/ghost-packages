"""End-to-end run of analyze -> repeat -> summarize on canned answers (no network, no model)."""
import json

import ghostcheck.registry as registry_mod
from experiment import analyze, common, config, repeat, summarize


def test_pipeline_end_to_end(tmp_path, monkeypatch, net):
    for name in ["RAW_DIR", "RESULTS", "REPEAT_RESULTS", "REGISTRY_CACHE", "MODELS_FILE", "CALLS_LOG", "SUMMARY"]:
        target = tmp_path / ("raw" if name == "RAW_DIR" else name.lower())
        monkeypatch.setattr(config, name, target)
    monkeypatch.setattr(config, "GHOST_EXPORT", tmp_path / "llm_ghosts.json")
    monkeypatch.setattr(config, "MIN_INTERVAL_S", 0)
    monkeypatch.setattr(summarize, "NOTES", tmp_path / "notes.md")

    net.pypi("pdfplumber", [3000] + [10] * 30)
    net.npm("qrcode", created_days_ago=4000, weekly=90_000, versions=40)
    monkeypatch.setattr(registry_mod, "_requests_fetcher", lambda: net)

    model = "gemma-3-27b-it"
    config.MODELS_FILE.write_text(json.dumps({"primary": model, "secondary": None, "all_gemma_models": [model], "listed_at": "2026-10-29T00:00:00Z"}))
    py_ans = "```python\nimport pdfplumber\nfrom gst_pdf_magic import parse\n```\n```bash\npip install pdfplumber gst-pdf-magic\n```"
    js_ans = "```js\nconst QR = require('qrcode');\n```\nnpm install qrcode"
    common.append_jsonl(common.raw_path(model), {"model": model, "prompt_id": "py001", "language": "python", "text": py_ans, "t": "2026-10-29T01:00:00Z"})
    common.append_jsonl(common.raw_path(model), {"model": model, "prompt_id": "js001", "language": "javascript", "text": js_ans, "t": "2026-10-29T01:01:00Z"})

    rows = analyze.analyze()
    assert [r["has_ghost"] for r in rows] == [False, True] or [r["has_ghost"] for r in rows] == [True, False]

    # reruns: the ghost comes back twice out of three
    answers = iter([py_ans, "```python\nimport pdfplumber\n```\npip install pdfplumber", py_ans])

    class FakeGemma:
        def generate(self, model, prompt, on_call=None, **kw):
            on_call()
            return {"text": next(answers), "finish_reason": "STOP", "usage": {}}
    monkeypatch.setattr(repeat, "client", lambda: FakeGemma())
    repeat.run_reruns(model)
    reps = repeat.score(model)
    assert reps[0]["per_ghost_returns"] == {"pypi:gst-pdf-magic": 2}
    assert common.Budget().used == 3

    summarize.main()
    text = config.SUMMARY.read_text("utf-8")
    assert "| answers with >= 1 ghost package | 1 (50.0%) |" in text
    assert "| unique ghost names | 1 (33.3% of unique names) |" in text
    assert "2/3 times (66.7%)" in text
    assert "`pypi:gst-pdf-magic` | 3 |" in text
    ghosts = json.loads(config.GHOST_EXPORT.read_text("utf-8"))["ghosts"]
    assert ghosts[0]["name"] == "gst-pdf-magic" and ghosts[0]["times"] == 3
