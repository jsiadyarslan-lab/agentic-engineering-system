#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""secret_guard — AES-P0-MONITOR-CREDENTIAL-CONTAINMENT-1113 (2026-11-13).

Fails (exit 1) when a hardcoded credential can enter the repository.

Rules
  A  assignment of a string literal (>=16 chars) to a name matching
     TOKEN / SECRET / PASSWORD / PASSWD / API_KEY / ACCESS_KEY / CREDENTIAL.
     Env-var indirection, secret-file reads and placeholders are allowed.
  B  a URL/query string embedding ?k= / ?token= / ?api_key= / ?access_key=
     with a 16+ character value.
  C  an nginx-style location that combines `allow all` + `auth_basic off`
     together with proxy_pass (an intentionally public unauthenticated proxy).

Findings are reported with the first 12 hex chars of SHA-256 of the matched
value — never the value itself.

Usage:  python3 scripts/ops/secret_guard.py [root]
Exit:   0 clean · 1 findings · 2 usage error
"""
import hashlib
import os
import re
import sys

TEXT_EXT = {".py", ".js", ".ts", ".html", ".css", ".json", ".yml", ".yaml",
            ".sh", ".conf", ".md", ".txt", ".ini", ".toml", ".env", ".cfg"}
SKIP_DIRS = {".git", "node_modules", "__pycache__", ".venv", "venv", "dist", "build"}

RULE_A = re.compile(
    r"(?m)^(\s*)([A-Za-z0-9_]*"
    r"(?:TOKEN|TOKENS|SECRET|SECRETS|PASSWORD|PASSWD|API_KEY|APIKEY|ACCESS_KEY|CREDENTIAL|CREDENTIALS)"
    r"[A-Za-z0-9_]*)\s*=\s*([\"'])([^\"'\n]{16,})\3")
RULE_B = re.compile(r"[?&](?:k|token|api_key|apikey|access_key)=(?:[A-Za-z0-9_\-]{16,})", re.I)
PLACEHOLDER = re.compile(r"^(?:__TOKEN__|<TOKEN>|«REDACTED»|\[REDACTED\]|REDACTED|"
                         r"\$\{?[A-Za-z_][A-Za-z0-9_]*\}?|CHANGE_?ME|changeme|your[_-]?token[_-]?here|N/?A)$", re.I)


def h12(v: str) -> str:
    return hashlib.sha256(v.encode("utf-8", "ignore")).hexdigest()[:12]


def load_allowlist(root: str):
    """`.secretguard-allow` lines: `<relpath>` (whole file) or `<relpath>:<RULE>`."""
    allow = set()
    ap = os.path.join(root, ".secretguard-allow")
    if os.path.isfile(ap):
        with open(ap, encoding="utf-8", errors="replace") as f:
            for raw in f:
                line = raw.strip()
                if not line or line.startswith("#"):
                    continue
                if ":" in line and line.rsplit(":", 1)[1] in {"A", "B", "C"}:
                    path, rule = line.rsplit(":", 1)
                    allow.add((path, rule))
                else:
                    allow.add((line, "*"))
    return allow


def iter_files(root: str):
    for dirpath, dirnames, filenames in os.walk(root):
        dirnames[:] = [d for d in dirnames if d not in SKIP_DIRS]
        for fn in filenames:
            p = os.path.join(dirpath, fn)
            ext = os.path.splitext(fn)[1].lower()
            if ext in TEXT_EXT or fn.endswith(".nginx") or fn == "Dockerfile":
                yield p


def scan_file(path: str):
    findings = []
    try:
        with open(path, encoding="utf-8", errors="replace") as f:
            text = f.read()
    except OSError:
        return findings
    if "secret_guard" in path:
        return findings  # the scanner itself contains rule definitions
    for m in RULE_A.finditer(text):
        name, value = m.group(2), m.group(4)
        if PLACEHOLDER.search(value):
            continue
        line = text.count("\n", 0, m.start()) + 1
        findings.append(("A", path, line, "name=%s value_len=%d sha256=%s…" % (name, len(value), h12(value))))
    for m in RULE_B.finditer(text):
        value = m.group(0).split("=", 1)[1]
        if PLACEHOLDER.search(value):
            continue
        line = text.count("\n", 0, m.start()) + 1
        findings.append(("B", path, line, "query value_len=%d sha256=%s…" % (len(value), h12(value))))
    if (path.endswith(".md") or "/docs/" in path.replace(os.sep, "/")):
        pass  # historical records / documentation are not actionable config
    elif text.count("allow all") and re.search(r"auth_basic\s+off", text) and re.search(r"proxy_pass", text):
        line = 0
        for i, ln in enumerate(text.splitlines(), 1):
            if "allow all" in ln:
                line = i
                break
        findings.append(("C", path, line, "allow all + auth_basic off + proxy_pass (public unauth proxy)"))
    return findings


def main() -> int:
    if len(sys.argv) > 2:
        print(__doc__)
        return 2
    root = sys.argv[1] if len(sys.argv) > 1 else os.getcwd()
    if not os.path.isdir(root):
        print("not a directory:", root)
        return 2
    all_findings = []
    allow = load_allowlist(root)
    for path in iter_files(root):
        rel = os.path.relpath(path, root).replace(os.sep, "/")
        for rule, _, line, info in scan_file(path):
            if (rel, rule) in allow or (rel, "*") in allow:
                continue
            all_findings.append((rule, path, line, info))
    if not all_findings:
        print("secret_guard: CLEAN (no hardcoded credentials detected) — root=%s" % root)
        return 0
    print("secret_guard: %d finding(s) — hardcoded credential material detected:" % len(all_findings))
    for rule, path, line, info in sorted(all_findings):
        print("  [rule-%s] %s:%d  %s" % (rule, os.path.relpath(path, root), line, info))
    print("Rotate the credential, source it from an env var / secret file, then re-run.")
    return 1


if __name__ == "__main__":
    sys.exit(main())
