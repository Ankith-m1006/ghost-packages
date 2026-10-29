"""Turn dependency files, install commands and code snippets into package names.

Everything here is plain text parsing: no network, no model.
"""
from __future__ import annotations

import json
import re
import shlex
from dataclasses import dataclass, field

from .stdlib import is_node_builtin, is_python_stdlib

PYPI = "pypi"
NPM = "npm"


@dataclass(frozen=True)
class Dependency:
    name: str            # name as it would be installed (distribution / npm package name)
    ecosystem: str       # "pypi" or "npm"
    source: str = ""     # where it came from (file:line, "pip command", ...)


def normalize_pypi(name: str) -> str:
    """PEP 503 normalisation: lowercase, runs of -_. become a single '-'."""
    return re.sub(r"[-_.]+", "-", name).lower()


# ---------------------------------------------------------------- requirement strings

_REQ_NAME = re.compile(r"^\s*([A-Za-z0-9][A-Za-z0-9._-]*)")


def requirement_name(spec: str) -> str | None:
    """'requests[socks]>=2.0 ; python_version>"3"' -> 'requests'. URLs, paths, flags -> None."""
    spec = spec.strip()
    if not spec or spec.startswith(("-", "#", ".", "/", "\\", "~")):
        return None
    if "://" in spec or spec.startswith(("git+", "hg+", "svn+", "bzr+", "file:")):
        # PEP 508 direct reference "name @ https://..." still names a package
        m = re.match(r"^\s*([A-Za-z0-9][A-Za-z0-9._-]*)\s*(\[[^\]]*\])?\s*@", spec)
        return m.group(1) if m else None
    if re.search(r"\.(whl|tar\.gz|zip|tgz)$", spec, re.I):
        return None
    m = _REQ_NAME.match(spec)
    if not m:
        return None
    name = m.group(1).rstrip(".-_")
    return name or None


def parse_requirements(text: str, source: str = "requirements.txt") -> list[Dependency]:
    deps: list[Dependency] = []
    for lineno, raw in enumerate(text.splitlines(), 1):
        line = raw.split(" #", 1)[0].strip()
        if line.startswith("#") or not line:
            continue
        if line.startswith("-"):  # -r other.txt, -e ., --index-url ...
            continue
        name = requirement_name(line)
        if name:
            deps.append(Dependency(name, PYPI, f"{source}:{lineno}"))
    return deps


# ---------------------------------------------------------------- package.json

_DEP_SECTIONS = ("dependencies", "devDependencies", "optionalDependencies", "peerDependencies")


def parse_package_json(text: str, source: str = "package.json") -> list[Dependency]:
    data = json.loads(text)
    deps: list[Dependency] = []
    seen: set[str] = set()
    for section in _DEP_SECTIONS:
        for name, version in (data.get(section) or {}).items():
            v = str(version)
            # local / git / workspace links are not registry packages
            if v.startswith(("file:", "link:", "workspace:", "git+", "git:", "github:", "http:", "https:")):
                continue
            if v.startswith("npm:"):  # alias: "x": "npm:real-name@^1"
                real = v[4:]
                name = real.rsplit("@", 1)[0] if real.count("@") > (1 if real.startswith("@") else 0) else real
            if name not in seen:
                seen.add(name)
                deps.append(Dependency(name, NPM, f"{source}:{section}"))
    return deps


# ---------------------------------------------------------------- install commands

_PIP_CMD = re.compile(
    r"(?:^|[\s;&|`(])(?:sudo\s+)?(?:(?:python[0-9.]*|py)\s+-m\s+)?(?:pip[0-9.]*|uv\s+pip|poetry|pipenv|conda|mamba)\s+(?:install|add)\s+(.+)",
    re.I,
)
_NPM_CMD = re.compile(
    r"(?:^|[\s;&|`(])(?:sudo\s+)?(?:npm\s+(?:install|i|add)|yarn\s+(?:global\s+)?add|pnpm\s+(?:add|install|i)|bun\s+(?:add|install|i))\s+(.+)",
    re.I,
)
# pip flags that take a value
_PIP_VALUE_FLAGS = {"-r", "--requirement", "-c", "--constraint", "-e", "--editable", "-i", "--index-url",
                    "--extra-index-url", "-f", "--find-links", "--target", "-t", "--prefix", "--root",
                    "--platform", "--python-version", "--implementation", "--abi", "--trusted-host",
                    "--cache-dir", "--src", "-c", "--channel"}
_NPM_VALUE_FLAGS = {"--registry", "--prefix", "--tag", "-w", "--workspace", "--filter"}


def _split_args(arg_text: str) -> list[str]:
    arg_text = re.split(r"\s(?:&&|\|\||;|\|)\s|\s#|`", arg_text)[0]
    arg_text = arg_text.replace("\\\n", " ")
    try:
        return shlex.split(arg_text, posix=True)
    except ValueError:
        return arg_text.split()


def parse_pip_command(text: str, source: str = "pip command") -> list[Dependency]:
    """All package names in every `pip install ...` line of `text`."""
    deps: list[Dependency] = []
    for line in text.splitlines():
        line = line.strip().lstrip("$>").strip()
        for m in _PIP_CMD.finditer(line):
            tokens = _split_args(m.group(1))
            skip = False
            for tok in tokens:
                if skip:
                    skip = False
                    continue
                if tok in _PIP_VALUE_FLAGS:
                    skip = True
                    continue
                if tok.startswith("-"):
                    continue
                name = requirement_name(tok)
                if name and not re.fullmatch(r"[0-9.]+", name):
                    deps.append(Dependency(name, PYPI, source))
    return _dedupe(deps, normalize_pypi)


def parse_npm_command(text: str, source: str = "npm command") -> list[Dependency]:
    deps: list[Dependency] = []
    for line in text.splitlines():
        line = line.strip().lstrip("$>").strip()
        for m in _NPM_CMD.finditer(line):
            tokens = _split_args(m.group(1))
            skip = False
            for tok in tokens:
                if skip:
                    skip = False
                    continue
                if tok in _NPM_VALUE_FLAGS:
                    skip = True
                    continue
                if tok.startswith("-"):
                    continue
                name = npm_spec_name(tok)
                if name:
                    deps.append(Dependency(name, NPM, source))
    return _dedupe(deps, str)


_NPM_NAME = re.compile(r"^(@[a-z0-9][a-z0-9._~-]*/)?[a-z0-9][a-z0-9._~-]*$", re.I)


def npm_spec_name(spec: str) -> str | None:
    """'lodash@^4' -> 'lodash', '@types/node@20' -> '@types/node'. Paths/URLs/git -> None."""
    spec = spec.strip().strip(",")
    if not spec or spec.startswith((".", "/", "~", "file:", "git", "http", "link:", "github:")) or "://" in spec:
        return None
    if spec.startswith("@"):
        parts = spec[1:].split("@", 1)
        name = "@" + parts[0]
    else:
        name = spec.split("@", 1)[0]
    if "/" in name and not name.startswith("@"):
        return None  # "user/repo" GitHub shorthand
    return name if _NPM_NAME.match(name) else None


def _dedupe(deps: list[Dependency], key) -> list[Dependency]:
    seen: set[str] = set()
    out = []
    for d in deps:
        k = key(d.name)
        if k not in seen:
            seen.add(k)
            out.append(d)
    return out


# ---------------------------------------------------------------- code snippets

_FENCE = re.compile(r"```[ \t]*([A-Za-z0-9_+.-]*)[^\n]*\n(.*?)```", re.S)
_PY_IMPORT = re.compile(r"^[ \t]*import[ \t]+([A-Za-z_][\w.]*(?:[ \t]+as[ \t]+\w+)?(?:[ \t]*,[ \t]*[A-Za-z_][\w.]*(?:[ \t]+as[ \t]+\w+)?)*)", re.M)
_PY_FROM = re.compile(r"^[ \t]*from[ \t]+([A-Za-z_][\w.]*)[ \t]+import\b", re.M)
_JS_SPEC = re.compile(
    r"""(?:\bfrom\s*|\bimport\s*\(\s*|\brequire\s*\(\s*|^\s*import\s+|\bexport\s+\*\s+from\s*)['"]([^'"\n]+)['"]""",
    re.M,
)


def code_blocks(text: str) -> list[tuple[str, str]]:
    """[(language_tag, body)] for every fenced block; the whole text if there are none."""
    blocks = [(m.group(1).lower(), m.group(2)) for m in _FENCE.finditer(text)]
    return blocks or [("", text)]


def python_imports(code: str) -> list[str]:
    """Top-level, non-stdlib, non-relative module names imported by Python code (in order)."""
    names: list[str] = []
    for m in _PY_IMPORT.finditer(code):
        for part in m.group(1).split(","):
            mod = part.strip().split()[0]
            names.append(mod.split(".")[0])
    for m in _PY_FROM.finditer(code):
        names.append(m.group(1).split(".")[0])
    out = []
    for n in names:
        if n and n != "__future__" and not is_python_stdlib(n) and n not in out:
            out.append(n)
    return out


def js_package_from_specifier(spec: str) -> str | None:
    """'lodash/fp' -> 'lodash', '@aws-sdk/client-s3/dist' -> '@aws-sdk/client-s3'; relative/builtin -> None."""
    spec = spec.strip()
    if not spec or spec.startswith((".", "/", "~", "#", "http:", "https:", "data:", "file:", "@/")):
        return None
    if is_node_builtin(spec):
        return None
    parts = spec.split("/")
    if spec.startswith("@"):
        if len(parts) < 2 or not parts[1]:
            return None
        name = "/".join(parts[:2])
    else:
        name = parts[0]
    return name if _NPM_NAME.match(name) else None


def js_imports(code: str) -> list[str]:
    out: list[str] = []
    for m in _JS_SPEC.finditer(code):
        name = js_package_from_specifier(m.group(1))
        if name and name not in out:
            out.append(name)
    return out


_PY_TAGS = {"python", "py", "python3", "ipython", "jupyter"}
_JS_TAGS = {"javascript", "js", "node", "nodejs", "typescript", "ts", "jsx", "tsx", "mjs", "cjs"}
_SHELL_TAGS = {"bash", "sh", "shell", "console", "zsh", "powershell", "cmd", "text", "terminal", ""}


@dataclass
class Extraction:
    """Packages found in one model answer."""
    python_imports: list[str] = field(default_factory=list)
    pip_installs: list[str] = field(default_factory=list)
    js_imports: list[str] = field(default_factory=list)
    npm_installs: list[str] = field(default_factory=list)


def extract_from_answer(text: str, language: str) -> Extraction:
    """Extract imports and install names from a model's markdown answer.

    `language` is "python" or "javascript" (the language the task asked for). Imports are read
    from code blocks only (so prose such as "import the data" is ignored); install commands are
    read from the whole answer, because models often put them in prose or inline code.
    """
    ex = Extraction()
    blocks = code_blocks(text)
    for tag, body in blocks:
        if language == "python" and (tag in _PY_TAGS or (tag not in _JS_TAGS and tag not in _SHELL_TAGS) or tag == ""):
            for n in python_imports(body):
                if n not in ex.python_imports:
                    ex.python_imports.append(n)
        if language == "javascript" and (tag in _JS_TAGS or tag == "" or tag not in _PY_TAGS | _SHELL_TAGS):
            for n in js_imports(body):
                if n not in ex.js_imports:
                    ex.js_imports.append(n)
    # Install commands: fenced blocks, inline `code` spans, and prose lines that *start* with the
    # command. Free prose ("install it with pip install and the --user flag") is ignored so that
    # English words are never mistaken for package names.
    fenced = [m.group(2) for m in _FENCE.finditer(text)]
    rest = _FENCE.sub("\n", text)
    inline = re.findall(r"`([^`\n]+)`", rest)
    prose_cmds = [ln for ln in rest.splitlines()
                  if re.match(r"^\s*[$>]?\s*(?:sudo\s+)?(?:python[0-9.]*\s+-m\s+)?(?:pip[0-9.]*|npm|yarn|pnpm|bun|uv|poetry|conda)\s", ln)]
    cmd_text = "\n".join(fenced + inline + prose_cmds)
    ex.pip_installs = [d.name for d in parse_pip_command(cmd_text)]
    ex.npm_installs = [d.name for d in parse_npm_command(cmd_text)]
    return ex
