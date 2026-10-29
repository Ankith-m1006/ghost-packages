import pytest

from ghostcheck import rules, typosquat
from ghostcheck.parsers import NPM, PYPI, Dependency
from ghostcheck.registry import NPM_POPULAR_WEEKLY, Registry
from ghostcheck.rules import HIGH, MEDIUM, check_dependency, exit_code
from ghostcheck.typosquat import damerau_levenshtein, nearest_top_package


def reg(net, now, **kw):
    return Registry(fetcher=net, now=now, min_interval=0, **kw)


def rules_hit(dep, registry, now):
    found, _ = check_dependency(dep, registry, now)
    return {(f.severity, f.rule) for f in found}


# ------------------------------------------------------------------ registry parsing

def test_pypi_lookup_parses_release_dates(net, now):
    net.pypi("somepkg", [900, 400, 10])
    info = reg(net, now).lookup("somepkg", PYPI)
    assert info.exists is True and info.n_releases == 3
    assert info.first_release < info.latest_release
    assert round(info.age_days(now)) == 900


def test_pypi_404_is_not_found(net, now):
    info = reg(net, now).lookup("nope-nope", PYPI)
    assert info.exists is False


def test_npm_lookup_low_downloads_fetches_full_document(net, now):
    net.npm("tiny-lib", created_days_ago=20, weekly=12, versions=2)
    info = reg(net, now).lookup("tiny-lib", NPM)
    assert info.exists and info.weekly_downloads == 12 and info.n_releases == 2 and info.maintainers == 1
    assert round(info.age_days(now)) == 20


def test_npm_popular_package_skips_big_document(net, now):
    net.routes["https://api.npmjs.org/downloads/point/last-week/react"] = (200, {"downloads": NPM_POPULAR_WEEKLY * 10})
    net.routes["https://registry.npmjs.org/react"] = (200, {"huge": True})
    info = reg(net, now).lookup("react", NPM)
    assert info.exists is True
    assert ("HEAD", "https://registry.npmjs.org/react") in net.calls
    assert ("GET", "https://registry.npmjs.org/react") not in net.calls


def test_scoped_npm_names_are_url_encoded(net, now):
    net.npm("@scope/pkg", created_days_ago=500, weekly=5)
    assert reg(net, now).lookup("@scope/pkg", NPM).exists is True


def test_cache_is_reused_and_saved(net, now, tmp_path):
    net.pypi("cached-pkg", [800])
    path = tmp_path / "cache.json"
    r1 = reg(net, now, cache_path=path)
    r1.lookup("cached-pkg", PYPI)
    r1.save()
    calls = len(net.calls)
    r2 = reg(net, now, cache_path=path)
    assert r2.lookup("cached-pkg", PYPI).exists is True
    assert len(net.calls) == calls  # served from cache


def test_offline_never_touches_network(now, tmp_path):
    def boom(*a, **k):
        raise AssertionError("network used in offline mode")
    info = Registry(fetcher=boom, offline=True, now=now).lookup("anything", PYPI)
    assert info.exists is None and "offline" in info.error


def test_retries_on_429_then_succeeds(now, monkeypatch):
    monkeypatch.setattr("ghostcheck.registry.time.sleep", lambda s: None)
    seq = iter([(429, None), (404, None)])
    r = Registry(fetcher=lambda u, m, h: next(seq), now=now, min_interval=0)
    assert r.lookup("x-y-z", PYPI).exists is False


def test_network_error_gives_unknown_not_ghost(now, monkeypatch):
    monkeypatch.setattr("ghostcheck.registry.time.sleep", lambda s: None)
    def down(*a):
        raise ConnectionError("down")
    info = Registry(fetcher=down, now=now, min_interval=0).lookup("whatever", PYPI)
    assert info.exists is None


# ------------------------------------------------------------------ rules

def test_rule_not_found_is_high(net, now):
    assert (HIGH, "not-found") in rules_hit(Dependency("gst-magic-validator", PYPI), reg(net, now), now)


def test_rule_brand_new_is_high(net, now):
    net.pypi("fresh-pkg", [5])
    assert (HIGH, "brand-new") in rules_hit(Dependency("fresh-pkg", PYPI), reg(net, now), now)


def test_rule_young_and_unused_is_medium_pypi(net, now):
    net.pypi("young-pkg", [90], monthly=150)
    hits = rules_hit(Dependency("young-pkg", PYPI), reg(net, now), now)
    assert (MEDIUM, "young-and-unused") in hits and not any(s == HIGH for s, _ in hits)


def test_rule_young_but_popular_is_clean(net, now):
    net.npm("young-popular", created_days_ago=90, weekly=40_000)
    assert rules_hit(Dependency("young-popular", NPM), reg(net, now), now) == set()


def test_old_established_package_is_clean(net, now):
    net.pypi("oldpkg-long-name", [3000] + [100] * 20)
    assert rules_hit(Dependency("oldpkg-long-name", PYPI), reg(net, now), now) == set()


def test_rule_typosquat_is_medium(net, now):
    net.pypi("reqeusts", [3000])  # exists, old, but only 1 release -> not "established"
    hits = rules_hit(Dependency("reqeusts", PYPI), reg(net, now), now)
    assert (MEDIUM, "typosquat") in hits


def test_typosquat_skipped_for_established_package(net, now):
    net.pypi("boto", [4000] + [1000] * 30)  # boto vs boto3: real, old, many releases
    assert (MEDIUM, "typosquat") not in rules_hit(Dependency("boto", PYPI), reg(net, now), now)


def test_npm_security_placeholder_is_high(net, now):
    net.npm("evil-pkg-name", created_days_ago=900, weekly=0, latest="0.0.1-security")
    assert (HIGH, "security-placeholder") in rules_hit(Dependency("evil-pkg-name", NPM), reg(net, now), now)


def test_rule_llm_ghost_is_high_even_offline(now, monkeypatch):
    monkeypatch.setattr(rules, "llm_ghosts", lambda: {"pypi:razorpay-gst": {"model": "gemma-3-27b-it", "times": 3, "checked": "2026-10-30"}})
    hits = rules_hit(Dependency("Razorpay_GST", PYPI), Registry(offline=True, now=now), now)
    assert (HIGH, "llm-ghost") in hits


def test_exit_codes():
    f_high = rules.Finding(HIGH, "not-found", "x", PYPI, "")
    f_med = rules.Finding(MEDIUM, "typosquat", "y", PYPI, "")
    assert exit_code([]) == 0
    assert exit_code([f_med]) == 0
    assert exit_code([f_med, f_high]) == 1


# ------------------------------------------------------------------ typosquat helpers

@pytest.mark.parametrize("a,b,d", [("requests", "requests", 0), ("reqeusts", "requests", 1),
                                   ("request", "requests", 1), ("numpyy", "numpy", 1), ("abc", "xyz", 3)])
def test_damerau_levenshtein(a, b, d):
    assert damerau_levenshtein(a, b) == d


def test_nearest_top_package():
    assert nearest_top_package("requests", PYPI) is None          # is a top package
    assert nearest_top_package("reqeusts", PYPI) == ("requests", 1)
    assert nearest_top_package("expresss", NPM) == ("express", 1)
    assert nearest_top_package("six", PYPI) is None               # too short to judge
    assert nearest_top_package("completely-unrelated-name", PYPI) is None


def test_bundled_lists_have_500_names_each():
    assert len(typosquat.top_packages(PYPI)) == 500
    assert len(typosquat.top_packages(NPM)) == 500
