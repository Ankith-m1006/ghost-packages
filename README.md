# Ghost Packages

LLMs sometimes tell you to install packages that do not exist ("package hallucination"), and attackers register those names with malware ("slopsquatting").
This repo measures how often Google's open-weight **Gemma** invents package names for everyday coding tasks, checked live against PyPI and npm, and ships **ghostcheck**, a small guard that flags ghost and suspicious dependencies before you install them.

## Headline numbers

> **Not run yet.** The experiment code is complete and tested, but it has not been run in this
> repo, so there are no numbers here yet. `python -m experiment.run_all` writes
> [`experiment/SUMMARY.md`](experiment/SUMMARY.md); copy the headline figures from there into this
> section. Every number must come from that file, exactly as measured.

| metric | value |
|---|---|
| model(s) | _from SUMMARY.md_ |
| answers with at least one ghost package | _from SUMMARY.md_ |
| unique package names that are ghosts | _from SUMMARY.md_ |
| recently registered names (possible squats) | _from SUMMARY.md_ |
| ghosts that came back when the prompt was re-asked | _from SUMMARY.md_ |

## How the experiment works

1. **Prompts.** [`experiment/prompts.jsonl`](experiment/prompts.jsonl) has 150 realistic coding requests (100 Python, 50 JavaScript/Node) across data, scraping, PDFs, Indian payments/GST, ML, DevOps, niche file formats, hardware, finance and bioinformatics. Several are niche but real tasks, because that is where models invent things. Each prompt asks for code plus the exact `pip install` / `npm install` command.
2. **Model.** The script lists the models on the Gemini API and picks the largest `gemma-3*-it` instruct model, plus the next size down for comparison (ids recorded in `experiment/models.json`). Temperature 0.7, at most 1,200 output tokens, 4.5 s between requests, and a hard cap of 400 API requests (retries included), logged in `experiment/calls_log.jsonl`.
3. **Extraction.** Every `import x`, `from x import`, `require('x')`, `import ... from 'x'`, `pip install ...` and `npm install ...` is parsed. Imports are read from code blocks only, so prose never turns into package names. Standard library modules (`sys.stdlib_module_names`) and Node built-ins are dropped, as are relative imports.
4. **Live registry check.** Each unique name is looked up on the PyPI JSON API and the npm registry (at most 5 requests per second, cached in `experiment/registry_cache.json`). It records existence, first and latest release, number of releases, maintainers, and downloads (npm weekly downloads; pypistats monthly downloads only for young packages).
5. **Classification (conservative).**
   - `GHOST`: the name a user would install returns **404**. For Python, that means a name on the `pip install` line. For JavaScript, it is the npm install name or the import specifier, which are the same thing on npm.
   - `RECENTLY-REGISTERED`: the package exists, but it was first published after Gemma 3's knowledge cutoff (August 2024, per the model card) and has very little use (under 5,000 downloads a month on PyPI, under 1,000 a week on npm). The model could not have learned it, so it might be a squat. Every one of these gets checked by hand.
   - `IMPORT-NAME-MISMATCH`: the import name and the install name differ but the install line is correct, for example `import cv2` with `pip install opencv-python`. **Not a ghost.**
   - `UNRESOLVED-IMPORT`: a Python import with no matching install name, where the import name is not on PyPI either. It could be a hallucinated module or a local file, so it is reported separately and **not** counted as a ghost.
6. **Repeatability.** Up to 20 prompts that produced a ghost are asked 3 more times each. A ghost that comes back every time is the dangerous kind, because an attacker can predict it.
7. **Summary.** `experiment/SUMMARY.md` reports the ghost rate (answers with at least one ghost, and unique names that are ghosts), the recently-registered list, repeatability, the Python vs JavaScript split, the rate per domain, and the 10 ghosts suggested most often. The ghost names are exported to `ghostcheck/data/llm_ghosts.json`.

### Reproduce

```bash
pip install -r requirements.txt
# put GEMINI_API_KEY=... in ./.env (git-ignored) or in your environment
python -m experiment.run_all          # resumable; about 30 minutes with the free-tier rate limits
```

Or step by step: `python -m experiment.generate --list-models`, `python -m experiment.generate --model primary`, `python -m experiment.analyze`, `python -m experiment.repeat`, `python -m experiment.generate --model secondary`, `python -m experiment.analyze`, `python -m experiment.summarize`.

The registry cache is the snapshot behind the numbers. Delete `experiment/registry_cache.json` to re-check every name against today's registries.

## ghostcheck

```bash
pip install .                         # from this repo
ghostcheck requirements.txt
ghostcheck package.json
ghostcheck --pip "pip install pdfplumber razorpay-gst-toolkit"
ghostcheck --npm "npm install upi-qr-pay-kit"
ghostcheck --offline requirements.txt # no network
ghostcheck --json requirements.txt    # machine-readable
```

> ghostcheck is **not on PyPI**. On 29 Oct 2026 the name `ghostcheck` returned 404 there, so
> `pip install ghostcheck` would install whatever someone registers under that name later. That is
> exactly the attack this tool is about. Install it from source.

Exit code `0` means no HIGH findings, `1` means at least one HIGH finding, and `2` means a usage or input error.

| rule | severity | what it means |
|---|---|---|
| `not-found` | HIGH | the name does not exist on PyPI / npm (404), so anyone could register it |
| `llm-ghost` | HIGH | the name is in our experiment's list of names Gemma invented |
| `brand-new` | HIGH | first published less than 30 days ago |
| `security-placeholder` | HIGH | npm replaced the package with a `0.0.1-security` placeholder (it was malicious) |
| `young-and-unused` | MEDIUM | first published less than 6 months ago, with under 2,000 downloads a month (PyPI) or under 1,000 a week (npm) |
| `typosquat` | MEDIUM | 1 edit from a top-500 package (names of 4-7 characters) or up to 2 edits (8 or more characters). Skipped for long-established packages |

Every finding comes from plain code, and the same registry data always gives the same result. `--explain` is optional: it asks Gemma (with `GEMINI_API_KEY`) to write one plain-English paragraph about the findings that already exist. The model never adds, removes or changes a finding, and it never affects the exit code. Without `--explain`, no model is called.

The bundled lists in `ghostcheck/data/` are:
- the top 500 PyPI projects, from [hugovk/top-pypi-packages](https://hugovk.dev/top-pypi-packages/) (30-day downloads, snapshot of 2026-10-01)
- the top 500 npm packages, from `npm-high-impact@1.13.0` `lib/top-download.js` (published 2026-06-08)
- the Python standard library and the Node built-in module list
- `llm_ghosts.json`, generated by the experiment

Each file has its source and date in its header.

### Offline mode

`--offline` makes no network requests. It uses the bundled lists and whatever is in the local cache (`~/.cache/ghostcheck/registry_cache.json`, or `--cache PATH`).

- **It can catch** typosquats of top-500 packages, names that Gemma invented in our experiment, and anything already in the cache from an earlier online run (including earlier 404s).
- **It cannot catch** a brand-new hallucinated name, a package published yesterday, or a download count. It cannot prove a 404 offline, so names it does not know are reported as `INFO not-checked`, never as safe.

### GitHub Action

Save this as `.github/workflows/ghostcheck.yml`. It runs on pull requests that change `requirements*.txt` or `package.json`, and fails the check on any HIGH finding.

```yaml
name: ghostcheck
on:
  pull_request:
    paths:
      - "**/requirements*.txt"
      - "**/package.json"

jobs:
  ghostcheck:
    runs-on: ubuntu-latest
    steps:
      - uses: actions/checkout@v4
        with:
          fetch-depth: 0
      - uses: actions/setup-python@v5
        with:
          python-version: "3.12"
      - name: Install ghostcheck (from source, not PyPI)
        run: pip install "git+https://github.com/OWNER/ghost-packages@main"   # replace OWNER, or pin a commit SHA
      - name: Check changed dependency files
        run: |
          files=$(git diff --name-only "origin/${{ github.base_ref }}...HEAD" -- '*requirements*.txt' '*package.json' | grep -v node_modules || true)
          if [ -z "$files" ]; then echo "no dependency files changed"; exit 0; fi
          echo "$files"
          ghostcheck $files
```

## Limits

- **Registries change every day.** A name that 404s today can be registered tomorrow, by anyone. A name that exists today may be removed. The experiment's numbers are a snapshot, dated in SUMMARY.md.
- **This is not malware detection.** ghostcheck tells you a dependency does not exist, is brand new, has almost no users, or looks like a typo of a popular package. It does not inspect code. A package that has existed for years can still be compromised.
- Downloads are a weak signal. Bots inflate npm counts, and PyPI counts come from pypistats.
- The typosquat check only knows the top 500 names of each registry, and it will flag some legitimate packages with similar names. Those are MEDIUM findings, not HIGH ones.
- The experiment covers one model family, 150 prompts, and one temperature. Different prompts, models or settings will give different rates.

## Tests

```bash
pip install -r requirements-dev.txt
python -m pytest
```

The registry is mocked in every test, and no test calls a model.

## Licence

MIT. Copyright (c) 2026 Ankith M. See [LICENSE](LICENSE).

The code was written with an AI coding assistant and reviewed by the author.
