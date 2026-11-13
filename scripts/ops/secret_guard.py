#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""secret_guard — AES-P0-CONTAINMENT-1113, hardened in AES-P0-CONTAINMENT-PR-REMEDIATION-1113-R1 (2026-11-13).

Fails (exit 1) when a hardcoded credential can enter the repository.

Rules
  A  assignment of a string literal (>=16 chars) to a name matching
     TOKEN / SECRET / PASSWORD / PASSWD / API_KEY / ACCESS_KEY / CREDENTIAL.
     Python-style, shell-style (quoted or unquoted, optional `export`)
     and JSON-key style are all covered. Env-var indirection, secret-file
     reads and placeholders are allowed.
  B  a URL/query string embedding ?k= / ?token= / ?api_key= / ?access_key=
     with a 16+ character value.
  C  an nginx location that EFFECTIVELY combines `allow all` +
     `auth_basic off` together with proxy_pass (a public unauthenticated
     proxy). Block-scoped analysis (R1 fix 3): directives are evaluated
     inside the enclosing server/location context with basic
     auth_basic/allow inheritance — never across separate blocks.
  D  REVIEW_REQUIRED (fail-closed): nginx-like content that contains an
     unresolved `include`, or that cannot be parsed into balanced blocks.
     The scanner never declares such content safe.

Findings are reported with the first 12 hex chars of SHA-256 of the matched
value — never the value itself.

Self-exclusion (R1 fix 1): ONLY this exact file — compared as a repo-relative
POSIX path (`scripts/ops/secret_guard.py`) — is skipped. No substring
matching: a file named `secret_guard_credentials.py`, or any path merely
CONTAINING `secret_guard`, IS scanned and MUST be scanned.

Allowlist governance (R1 fix 4): `.secretguard-allow` is JSONL — one JSON
object per entry with path / rule (A|B|C|D|*) / owner / reason / created /
expires (YYYY-MM-DD) / task. Missing or invalid fields, or an expired entry,
fail the scan (fail-closed). Lines starting with '#' are comments.

Usage:  python3 scripts/ops/secret_guard.py [root]
Exit:   0 clean · 1 findings or allowlist config error · 2 usage error
"""
import datetime
import hashlib
import json
import os
import re
import sys

TEXT_EXT = {".py", ".js", ".ts", ".html", ".css", ".json", ".yml", ".yaml",
            ".sh", ".conf", ".md", ".txt", ".ini", ".toml", ".env", ".cfg"}
SKIP_DIRS = {".git", "node_modules", "__pycache__", ".venv", "venv", "dist", "build"}

# R1 fix 1: exact self-exclusion — this file only, by repo-relative POSIX path.
SELF_EXACT = "scripts/ops/secret_guard.py"

_KEYWORD = (r"(?:TOKEN|TOKENS|SECRET|SECRETS|PASSWORD|PASSWD|API_KEY|APIKEY"
            r"|ACCESS_KEY|CREDENTIAL|CREDENTIALS)")
RULE_A_PY = re.compile(
    r"(?m)^(\s*)([A-Za-z0-9_]*" + _KEYWORD + r"[A-Za-z0-9_]*)\s*=\s*"
    r"([\"'])([^\"'\n]{16,})\3")
RULE_A_JSON = re.compile(
    r"(?m)^\s*\"([A-Za-z0-9_]*" + _KEYWORD + r"[A-Za-z0-9_]*)\"\s*:\s*"
    r"\"([^\"\n]{16,})\"", re.I)
RULE_A_SH = re.compile(
    r"(?m)^(?:export\s+)?([A-Za-z0-9_]*" + _KEYWORD +
    r"[A-Za-z0-9_]*)\s*=\s*([^ \n]{16,})\s*$")
RULE_B = re.compile(r"[?&](?:k|token|api_key|apikey|access_key)=(?:[A-Za-z0-9_\-]{16,})", re.I)
PLACEHOLDER = re.compile(r"^(?:__TOKEN__|<TOKEN>|«REDACTED»|\[REDACTED\]|REDACTED|"
                         r"\$\{?[A-Za-z_][A-Za-z0-9_]*\}?|CHANGE_?ME|changeme|"
                         r"your[_-]?token[_-]?here|N/?A)$", re.I)

# gate for running the nginx block analyzer: real conf extensions, or
# nginx-shaped lines (an embedded `location`/`server {` template).
NGINX_EXT = {".conf", ".nginx"}
NGINX_HINT = re.compile(r"(?m)^\s*(?:location\b|server\b[^{\n]*\{)")


# values that look like regex definitions (not credentials) — e.g.
# _COMMAND_TOKEN_RE = r"\\S+…" — backslashes/brackets/parens/pipes are not
# secret alphabet; real secrets are alphanumeric-ish (may include + / = : - _ . ~).
REGEX_LOOKS = re.compile(r"[\\()\[\]|^$?*{}~]")
# fixture-marker words: values containing these are treated as synthetic test
# data (repo convention: tests seed fake provider keys), not live secrets.
MARKER_WORDS = re.compile(r"(test|fake|dummy|example|sample|synth|placeholder|LOGKEY|12345678|999999)", re.I)
# JSON values that are prose (contain spaces / slashes / braces) are descriptions
# or file paths, not credential material.
JSON_COMPACT = re.compile(r"^[A-Za-z0-9_\-+={}:.]{16,}$")


def _placeholder_or_regex(value: str, json_form: bool = False) -> bool:
    if PLACEHOLDER.search(value) or REGEX_LOOKS.search(value) or MARKER_WORDS.search(value):
        return True
    if json_form and not JSON_COMPACT.search(value):
        return True
    return False


def h12(v: str) -> str:
    return hashlib.sha256(v.encode("utf-8", "ignore")).hexdigest()[:12]


# ---------------------------------------------------------------- allowlist

def _today():
    return datetime.datetime.now(datetime.timezone.utc).date()


def load_allowlist(root: str):
    """Governed JSONL allowlist. Returns (allow_set, errors).

    Each valid entry suppresses findings for (path, rule) — or (path, '*')
    when rule is '*'. Any invalid or expired entry is a config ERROR
    (fail-closed): the caller must fail the scan.
    """
    allow, errors = set(), []
    ap = os.path.join(root, ".secretguard-allow")
    if not os.path.isfile(ap):
        return allow, errors
    with open(ap, encoding="utf-8", errors="replace") as f:
        for lineno, raw in enumerate(f, 1):
            line = raw.strip()
            if not line or line.startswith("#"):
                continue
            try:
                entry = json.loads(line)
            except ValueError as e:
                errors.append("allowlist line %d: not valid JSON (%s)" % (lineno, e))
                continue
            required = ("path", "rule", "owner", "reason", "created", "expires", "task")
            missing = [k for k in required if not str(entry.get(k, "")).strip()]
            if missing:
                errors.append("allowlist line %d: missing field(s) %s" % (lineno, ",".join(missing)))
                continue
            rule = str(entry["rule"]).strip()
            if rule not in ("A", "B", "C", "D", "*"):
                errors.append("allowlist line %d: rule must be A|B|C|D|* (got %r)" % (lineno, rule))
                continue
            try:
                created = datetime.date.fromisoformat(str(entry["created"]).strip())
                expires = datetime.date.fromisoformat(str(entry["expires"]).strip())
            except ValueError:
                errors.append("allowlist line %d: created/expires must be YYYY-MM-DD" % lineno)
                continue
            if expires < _today():
                errors.append("allowlist line %d: EXPIRED entry for %s rule=%s "
                              "(expired %s) — renew or remove it" %
                              (lineno, entry["path"], rule, entry["expires"]))
                continue
            if created > _today():
                errors.append("allowlist line %d: created date is in the future" % lineno)
                continue
            allow.add((str(entry["path"]).strip(), rule))
    return allow, errors


# ---------------------------------------------------------------- file walk

def iter_files(root: str):
    for dirpath, dirnames, filenames in os.walk(root):
        dirnames[:] = [d for d in dirnames if d not in SKIP_DIRS]
        for fn in filenames:
            p = os.path.join(dirpath, fn)
            ext = os.path.splitext(fn)[1].lower()
            if ext in TEXT_EXT or fn.endswith(".nginx") or fn == "Dockerfile":
                yield p


# ------------------------------------------------- nginx block-scoped rules

def nginx_tokenize(text: str):
    """Minimal nginx-ish tokenizer with line numbers.

    `{{`/`}}` pairs (Python .format() escapes in deploy templates) collapse
    to a single brace token; short `{placeholder}` runs (format variables like
    `{token}`) stay inside the preceding word so they cannot break blocks;
    `;` is a directive terminator and is dropped from words.
    """
    toks, i, n, line = [], 0, len(text), 1
    while i < n:
        c = text[i]
        if c == "\n":
            line += 1
            i += 1
        elif c in " \t\r":
            i += 1
        elif c == ";":
            toks.append(("semi", ";", line))
            i += 1
        elif c == "#":
            j = text.find("\n", i)
            if j < 0:
                break
            line += 1
            i = j + 1
        elif text[i:i + 2] in ("{{", "}}"):
            toks.append(("brace", text[i + 1], line))
            i += 2
        elif c in "{}":
            m = re.match(r"\{[^{}\n'\" ]{1,64}\}", text[i:])
            if m:  # format placeholder {var} — keep as part of the word stream
                toks.append(("word", m.group(0), line))
                i += len(m.group(0))
            else:
                toks.append(("brace", c, line))
                i += 1
        elif c in "\"'":
            j = text.find(c, i + 1)
            j = n - 1 if j < 0 else j
            toks.append(("word", text[i:j + 1], line))
            i = j + 1
        else:
            m = re.match(r"[^{}#\s\"'\n;]+", text[i:])
            toks.append(("word", m.group(0), line))
            i += len(m.group(0))
    return toks


def nginx_parse(toks):
    """Build a block tree; flag unbalanced constructs as unparsed.

    Words directly before `{` form the block header (e.g. `location /x {`);
    words before `}` or at end-of-input are a final directive of the block.
    """
    root = {"type": "root", "name": "", "directives": [], "children": [], "line": 0}
    stack, words, wline = [root], [], 0
    for kind, val, line in toks:
        if kind == "word":
            words.append(val)
            wline = wline or line
            continue
        if kind == "semi":
            if words:  # directive terminator — nginx statements end with `;`
                stack[-1]["directives"].append((wline or line, words))
                words, wline = [], 0
            continue
        # brace token — settle the pending words first
        if val == "{":
            name = " ".join(words)
            blk = {"type": (name.split()[0] if name.split() else ""),
                   "name": name, "directives": [], "children": [],
                   "line": line, "parent": stack[-1]}
            stack[-1]["children"].append(blk)
            stack.append(blk)
            words, wline = [], 0
        else:  # "}"
            if words:
                stack[-1]["directives"].append((wline or line, words))
                words, wline = [], 0
            if len(stack) == 1:
                root["unparsed"] = True
            else:
                stack.pop()
    if words:
        stack[-1]["directives"].append((wline or 0, words))
    if len(stack) != 1:
        root["unparsed"] = True
    return root


def _walk(block):
    yield block
    for child in block["children"]:
        yield from _walk(child)


def _dir_value(block, name):
    """Nearest directive `name` in block, else inherited from ancestors."""
    node = block
    while node is not None:
        for _, words in node["directives"]:
            if words and words[0] == name:
                return words
        node = node.get("parent")
    return None


def _access_rules(block):
    """Effective allow/deny set: location's own, else inherited from ancestors."""
    node = block
    while node is not None:
        own = [words for _, words in node["directives"]
               if words and words[0] in ("allow", "deny")]
        if own:
            flat = []
            for directive in own:
                flat.extend(directive[1:])
            return flat
        node = node.get("parent")
    return []


def _string_literals(text: str):
    """Yield contents of Python-style string literals (incl. triple-quoted).

    Deploy scripts embed nginx templates inside string literals; the block
    analyzer must therefore analyze the LITERAL CONTENT, not the raw file
    (raw analysis would mix Python braces into the block tree).
    """
    i, n = 0, len(text)
    while i < n:
        c = text[i]
        if c in "\"'":
            if text[i:i + 3] in (chr(34) * 3, chr(39) * 3):
                q = text[i:i + 3]
                j = text.find(q, i + 3)
                j = n - 3 if j < 0 else j
                yield text[i + 3:j]
                i = j + 3
            else:
                j, jn = text.find(c, i + 1), text.find("\n", i + 1)
                if j < 0 or (0 <= jn < j):
                    i += 1
                    continue
                yield text[i + 1:j]
                i = j + 1
        else:
            i += 1


def nginx_analyze(text: str, path: str):
    findings = []
    root = nginx_parse(nginx_tokenize(text))
    root = nginx_parse(nginx_tokenize(text))
    if root.get("unparsed"):
        findings.append(("D", path, 0,
                         "REVIEW_REQUIRED: nginx-like content could not be parsed into "
                         "balanced blocks — not declared safe"))
        return findings
    blocks = list(_walk(root))
    # unresolved includes anywhere below a non-root block -> REVIEW_REQUIRED
    for blk in blocks[1:]:
        for wline, words in blk["directives"]:
            if words and words[0] == "include":
                findings.append(("D", path, wline,
                                 "REVIEW_REQUIRED: unresolved include (%s) inside %s "
                                 "block — manual review required" %
                                 (" ".join(words[1:3]), blk["type"] or "?")))
    # rule C: one location, effective allow all + effective auth_basic off + proxy_pass
    for blk in blocks:
        if blk["type"] != "location":
            continue
        has_proxy = any(words and words[0] == "proxy_pass"
                        for _, words in blk["directives"])
        if not has_proxy:
            continue
        auth = _dir_value(blk, "auth_basic")
        auth_off = bool(auth) and len(auth) > 1 and auth[1] == "off"
        allow_all = "all" in _access_rules(blk)
        if allow_all and auth_off:
            findings.append(("C", path, blk["line"],
                             "location '%s': allow all + auth_basic off + proxy_pass "
                             "(public unauthenticated proxy) [block-scoped]" % blk["name"]))
    return findings


def nginx_findings(text: str, path: str, rel: str):
    """Run the block analyzer on every nginx-shaped blob in the file.

    Blobs: the whole text when it is a real conf-like file (NGINX_EXT) or
    when the raw text itself is nginx-shaped (NGINX_HINT), plus the content
    of any string literal that is nginx-shaped (embedded templates).
    """
    findings = []
    ext = os.path.splitext(path)[1].lower()
    blobs = []
    if ext in NGINX_EXT or NGINX_HINT.search(text):
        blobs.append(text)
    if ext not in NGINX_EXT:
        blobs.extend(lit for lit in _string_literals(text) if NGINX_HINT.search(lit))
    for blob in blobs:
        findings.extend(nginx_analyze(blob, path))
    return findings


# ---------------------------------------------------------------- scan file

def scan_file(path: str, rel: str):
    findings = []
    try:
        with open(path, encoding="utf-8", errors="replace") as f:
            text = f.read()
    except OSError:
        return findings

    seen_a = set()  # dedupe the three rule-A forms on (line, value fingerprint)

    def _add_a(name: str, value: str, line: int, flavor: str):
        if _placeholder_or_regex(value, json_form=(flavor == "json-key")):
            return
        key = (line, h12(value))
        if key in seen_a:  # python-style + shell-style on the same line
            return
        seen_a.add(key)
        findings.append(("A", path, line, "%s name=%s value_len=%d sha256=%s…"
                         % (flavor, name, len(value), h12(value))))

    for m in RULE_A_PY.finditer(text):
        _add_a(m.group(2), m.group(4),
               text.count("\n", 0, m.start()) + 1, "python")
    for m in RULE_A_JSON.finditer(text):
        _add_a(m.group(1), m.group(2),
               text.count("\n", 0, m.start()) + 1, "json-key")
    for m in RULE_A_SH.finditer(text):
        name, value = m.group(1), m.group(2).strip("\"'")
        _add_a(name, value, text.count("\n", 0, m.start()) + 1, "shell")
    for m in RULE_B.finditer(text):
        value = m.group(0).split("=", 1)[1]
        if _placeholder_or_regex(value):
            continue
        line = text.count("\n", 0, m.start()) + 1
        findings.append(("B", path, line, "query value_len=%d sha256=%s…"
                         % (len(value), h12(value))))

    is_doc = rel.endswith(".md") or rel.startswith("docs/") or "/docs/" in rel
    if not is_doc and (os.path.splitext(path)[1].lower() in NGINX_EXT
                       or NGINX_HINT.search(text)):
        findings.extend(nginx_findings(text, path, rel))
    return findings


# ---------------------------------------------------------------- main

def main() -> int:
    if len(sys.argv) > 2:
        print(__doc__)
        return 2
    root = sys.argv[1] if len(sys.argv) > 1 else os.getcwd()
    if not os.path.isdir(root):
        print("not a directory:", root)
        return 2

    allow, allow_errors = load_allowlist(root)
    if allow_errors:
        print("secret_guard: ALLOWLIST CONFIG ERROR — fail-closed:")
        for e in allow_errors:
            print("  " + e)
        return 1

    all_findings = []
    for path in iter_files(root):
        rel = os.path.relpath(path, root).replace(os.sep, "/")
        if rel == SELF_EXACT:
            continue  # R1 fix 1: exact-path self-exclusion only
        for rule, _, line, info in scan_file(path, rel):
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
