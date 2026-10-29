"""Names that are never third-party packages: the Python standard library and Node built-ins."""
from __future__ import annotations

import sys
from functools import lru_cache
from importlib import resources

# Node.js built-in modules, from `require('module').builtinModules` on Node v24.13.1
# (subpaths such as "fs/promises" are covered by the top-level name).
NODE_BUILTINS = frozenset(
    """
    _http_agent _http_client _http_common _http_incoming _http_outgoing _http_server
    _stream_duplex _stream_passthrough _stream_readable _stream_transform _stream_wrap
    _stream_writable _tls_common _tls_wrap assert async_hooks buffer child_process cluster
    console constants crypto dgram diagnostics_channel dns domain events fs http http2 https
    inspector module net os path perf_hooks process punycode querystring readline repl
    stream string_decoder sys timers tls trace_events tty url util v8 vm wasi worker_threads
    zlib sea sqlite test
    """.split()
)

# Modules that only exist with the "node:" prefix (node:test, node:sqlite, node:sea).
NODE_PREFIX_ONLY = frozenset({"test", "sqlite", "sea"})


@lru_cache(maxsize=1)
def python_stdlib() -> frozenset[str]:
    """Standard-library top-level module names (running interpreter + bundled list)."""
    names = set(getattr(sys, "stdlib_module_names", ()))
    text = resources.files("ghostcheck.data").joinpath("python_stdlib.txt").read_text("utf-8")
    names.update(line.strip() for line in text.splitlines() if line.strip() and not line.startswith("#"))
    return frozenset(names)


def is_python_stdlib(module: str) -> bool:
    return module.split(".")[0] in python_stdlib()


def is_node_builtin(specifier: str) -> bool:
    if specifier.startswith("node:"):
        return True
    top = specifier.split("/")[0]
    return top in NODE_BUILTINS and top not in NODE_PREFIX_ONLY
