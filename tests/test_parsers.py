import json

import pytest

from ghostcheck.parsers import (NPM, PYPI, extract_from_answer, js_imports, normalize_pypi, parse_npm_command,
                                parse_package_json, parse_pip_command, parse_requirements, python_imports)
from ghostcheck.stdlib import is_node_builtin, is_python_stdlib


def names(deps):
    return [d.name for d in deps]


def test_requirements_txt_handles_specifiers_extras_markers_and_skips_options():
    text = """
# comment
requests[socks]>=2.31  # inline comment
Django==5.0 ; python_version >= "3.10"
-r other.txt
-e .
--index-url https://example.org/simple
numpy
./local/pkg
https://example.org/x-1.0.tar.gz
mypkg @ https://example.org/mypkg-1.0.whl
pandas~=2.2
"""
    deps = parse_requirements(text)
    assert names(deps) == ["requests", "Django", "numpy", "mypkg", "pandas"]
    assert all(d.ecosystem == PYPI for d in deps)
    assert deps[0].source == "requirements.txt:3"


def test_package_json_reads_all_sections_and_skips_local_links():
    pkg = {
        "dependencies": {"express": "^4.19.0", "@aws-sdk/client-s3": "3.500.0", "local": "file:../local"},
        "devDependencies": {"jest": "29", "ws-lib": "workspace:*"},
        "peerDependencies": {"react": ">=18"},
        "optionalDependencies": {"alias": "npm:real-pkg@^1.0.0"},
    }
    deps = parse_package_json(json.dumps(pkg))
    assert names(deps) == ["express", "@aws-sdk/client-s3", "jest", "real-pkg", "react"]
    assert all(d.ecosystem == NPM for d in deps)


def test_package_json_invalid_raises():
    with pytest.raises(ValueError):
        parse_package_json("{not json")


@pytest.mark.parametrize("cmd,expected", [
    ("pip install requests flask", ["requests", "flask"]),
    ("pip3 install -U 'fastapi[all]>=0.110' uvicorn==0.29", ["fastapi", "uvicorn"]),
    ("python -m pip install --upgrade pip", ["pip"]),
    ("pip install -r requirements.txt pdfplumber", ["pdfplumber"]),
    ("$ pip install opencv-python && python app.py", ["opencv-python"]),
    ("pip install --index-url https://x.org/simple private-pkg", ["private-pkg"]),
    ("conda install -c conda-forge rdkit", ["rdkit"]),
    ("pip install git+https://github.com/a/b.git", []),
    ("pip install requests requests", ["requests"]),
])
def test_pip_commands(cmd, expected):
    assert names(parse_pip_command(cmd)) == expected


@pytest.mark.parametrize("cmd,expected", [
    ("npm install express jsonwebtoken", ["express", "jsonwebtoken"]),
    ("npm i -D jest @types/node@20", ["jest", "@types/node"]),
    ("yarn add lodash@^4.17.21", ["lodash"]),
    ("pnpm add @aws-sdk/client-s3 --save", ["@aws-sdk/client-s3"]),
    ("npm install ./local-folder user/repo", []),
    ("npm install --registry https://r.example.org pkg-a", ["pkg-a"]),
])
def test_npm_commands(cmd, expected):
    assert names(parse_npm_command(cmd)) == expected


def test_python_imports_drop_stdlib_relative_and_future():
    code = """
from __future__ import annotations
import os, sys
import json as j
import numpy as np, pandas
from sklearn.model_selection import train_test_split
from . import local
from .utils import helper
import xml.etree.ElementTree as ET
    import requests  # indented import inside a function
"""
    assert python_imports(code) == ["numpy", "pandas", "requests", "sklearn"]


def test_stdlib_lists():
    assert is_python_stdlib("asyncio") and is_python_stdlib("os.path") and is_python_stdlib("distutils")
    assert not is_python_stdlib("requests")
    assert is_node_builtin("fs") and is_node_builtin("fs/promises") and is_node_builtin("node:test")
    assert not is_node_builtin("test") and not is_node_builtin("express")


def test_js_imports_cover_require_import_dynamic_subpath_scoped_and_builtins():
    code = """
const express = require('express');
const fs = require("fs");
const { readFile } = require('node:fs/promises');
import pdf from "pdf-parse/lib/pdf-parse.js";
import { S3Client } from '@aws-sdk/client-s3';
import './styles.css';
import 'dotenv/config';
import helper from './helper.js';
import comp from '@/components/x';
const m = await import('chalk');
export * from 'zod';
"""
    assert js_imports(code) == ["express", "pdf-parse", "@aws-sdk/client-s3", "dotenv", "chalk", "zod"]


def test_answer_extraction_reads_code_blocks_and_install_lines_but_not_prose():
    answer = """Here is how to do it. First import the data and then use pip install with care.

```python
import pdfplumber
import cv2
from gstpro_validator import check
import os
```

Install the packages:

```bash
pip install pdfplumber opencv-python
```

Or run `pip install gstpro-validator` too.
"""
    ex = extract_from_answer(answer, "python")
    assert ex.python_imports == ["pdfplumber", "cv2", "gstpro_validator"]
    assert ex.pip_installs == ["pdfplumber", "opencv-python", "gstpro-validator"]
    assert ex.npm_installs == []


def test_answer_extraction_javascript():
    answer = "```javascript\nconst qr = require('upi-qr-magic');\nconst x = require('path');\n```\n\nnpm install upi-qr-magic qrcode\n"
    ex = extract_from_answer(answer, "javascript")
    assert ex.js_imports == ["upi-qr-magic"]
    assert ex.npm_installs == ["upi-qr-magic", "qrcode"]


def test_normalize_pypi():
    assert normalize_pypi("Python_Dateutil") == "python-dateutil"
    assert normalize_pypi("zope.interface") == "zope-interface"
