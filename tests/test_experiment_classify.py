"""Experiment classification (registry mocked)."""
from experiment import common
from experiment.classify import EXISTS, GHOST, MISMATCH, RECENT, UNRESOLVED, classify_answer
from ghostcheck.registry import Registry


def reg(net, now):
    return Registry(fetcher=net, now=now, min_interval=0)


def statuses(result):
    return {m["name"]: m["status"] for m in result["mentions"]}


def test_cv2_with_opencv_install_is_mismatch_not_ghost(net, now):
    net.pypi("opencv-python", [3000] + [10] * 40)
    ans = "```python\nimport cv2\n```\n```bash\npip install opencv-python\n```"
    assert statuses(classify_answer(ans, "python", reg(net, now), now)) == {"opencv-python": MISMATCH}


def test_ghost_requires_install_name_404(net, now):
    net.pypi("pdfplumber", [2000] + [10] * 30)
    ans = ("```python\nimport pdfplumber\nfrom gst_magic import validate\n```\n"
           "```bash\npip install pdfplumber gst-magic\n```")
    s = statuses(classify_answer(ans, "python", reg(net, now), now))
    assert s == {"pdfplumber": EXISTS, "gst-magic": GHOST}


def test_python_import_without_install_line_is_unresolved_not_ghost(net, now):
    ans = "```python\nfrom tally_xml_reader import load\n```"
    assert statuses(classify_answer(ans, "python", reg(net, now), now)) == {"tally_xml_reader": UNRESOLVED}


def test_python_import_404_explained_by_spare_install_name_is_mismatch(net, now):
    net.pypi("pymupdf-extra", [2000] + [10] * 30)
    ans = "```python\nimport fitzish\n```\npip install pymupdf-extra"
    s = statuses(classify_answer(ans, "python", reg(net, now), now))
    assert s["fitzish"] == MISMATCH and s["pymupdf-extra"] == EXISTS


def test_js_import_specifier_that_404s_is_ghost(net, now):
    net.npm("qrcode", created_days_ago=4000, weekly=40_000, versions=50)
    ans = "```js\nconst upi = require('upi-deeplink-kit');\nconst QR = require('qrcode');\n```\nnpm install qrcode"
    s = statuses(classify_answer(ans, "javascript", reg(net, now), now))
    assert s == {"qrcode": EXISTS, "upi-deeplink-kit": GHOST}


def test_recent_low_usage_package_is_recently_registered(net, now):
    net.pypi("gstr2b-reco", [60], monthly=40)
    ans = "```python\nimport gstr2b_reco\n```\npip install gstr2b-reco"
    assert statuses(classify_answer(ans, "python", reg(net, now), now)) == {"gstr2b-reco": RECENT}


def test_recent_but_popular_is_established(net, now):
    net.pypi("hot-new-lib", [60], monthly=900_000)
    ans = "pip install hot-new-lib"
    assert statuses(classify_answer(ans, "python", reg(net, now), now)) == {"hot-new-lib": EXISTS}


def test_model_selection_prefers_largest_gemma3_instruct():
    models = [{"name": f"models/{n}", "supportedGenerationMethods": ["generateContent"]}
              for n in ["gemma-3-1b-it", "gemma-3-4b-it", "gemma-3-12b-it", "gemma-3-27b-it", "gemma-3n-e4b-it", "gemini-2.5-flash"]]
    info = common.choose_models(models)
    assert info["primary"] == "gemma-3-27b-it" and info["secondary"] == "gemma-3-12b-it"
    assert "gemini-2.5-flash" not in info["all_gemma_models"]


def test_budget_stops_at_cap(tmp_path, monkeypatch):
    monkeypatch.setattr(common.config, "CALLS_LOG", tmp_path / "calls.jsonl")
    b = common.Budget(limit=2)
    b.charge("m", "main")
    b.charge("m", "main")
    try:
        b.charge("m", "main")
    except common.BudgetExceeded:
        pass
    else:
        raise AssertionError("budget not enforced")
    assert common.Budget(limit=2).remaining() == 0  # persisted across runs


def test_choose_models_prefers_newest_gemma_generation():
    from experiment.common import choose_models
    models = [{"name": "models/" + n, "supportedGenerationMethods": ["generateContent"]}
              for n in ["gemma-3-27b-it", "gemma-4-26b-a4b-it", "gemma-4-31b-it", "gemini-2.5-flash"]]
    info = choose_models(models)
    assert info["primary"] == "gemma-4-31b-it" and info["secondary"] == "gemma-4-26b-a4b-it"
