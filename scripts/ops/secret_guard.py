#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""secret_guard — AES-P0-CONTAINMENT-1113.

Hardened in R1 (2026-11-13) and R3 (2026-11-13,
AES-P0-CONTAINMENT-PR-REMEDIATION-1113-R3).

Fails (exit 1) when hardcoded credential material can enter the repository.

Rules
  A  assignment of a credential-shaped literal (>=16 chars) to a name matching
     TOKEN / SECRET / PASSWORD / PASSWD / API_KEY / ACCESS_KEY / CREDENTIAL.
     Python-style, shell/env-style, JSON-key style, YAML-key style, plus
     const/let/var/final/pub declarations (JS/TS/Rust/Go/Java shape) and
     colon type annotations (Rust `&str`, TS `string`, Python hints) are all
     covered. Env-var indirection, secret-file reads and structural
     placeholders stay allowed.
  B  a URL/query string embedding ?k= / ?token= / ?api_key= / ?access_key=
     with a 16+ character value.
  C  an nginx location that EFFECTIVELY combines `allow all` +
     `auth_basic off` together with proxy_pass (a public unauthenticated
     proxy). Block-scoped analysis (R1 fix 3): directives are evaluated
     inside the enclosing server/location context with basic
     auth_basic/allow inheritance — never across separate blocks.
  D  REVIEW_REQUIRED (fail-closed): nginx-like content that contains an
     unresolved `include` at ANY level — root, http, server or location —
     or that cannot be parsed into balanced blocks. The scanner never
     declares such content safe. (R3: root-level includes are now flagged;
     includes are never resolved or followed, so duplicate includes each
     report and include cycles cannot create blind spots.)
  K  (R3) PEM private-key material: a `-----BEGIN … PRIVATE KEY-----`
     header anywhere in a scanned text file. Key files never belong in a
     repository; structural header detection, no marker exemption.

Findings are reported with the first 12 hex chars of SHA-256 of the matched
value — never the value itself.

Self-exclusion (R1 fix 1): ONLY this exact file — compared as a repo-relative
POSIX path (`scripts/ops/secret_guard.py`) — is skipped. No substring
matching: a file named `secret_guard_credentials.py`, or any path merely
CONTAINING `secret_guard`, IS scanned and MUST be scanned.

Allowlist governance — R3 CONTENT BINDING (§3)
    `.secretguard-allow` is JSONL — one JSON object per entry. An entry no
    longer suppresses by (path, rule) alone: it is bound to the exact
    reviewed content of the target file. Required fields:

      path           repo-relative POSIX path (no `..`, not absolute)
      rule           A | B | C | D | K  — a SPECIFIC rule; `*` is rejected
      owner          who owns the exception
      reason         why it exists (specific — nature proven, not boilerplate)
      created        YYYY-MM-DD (not in the future)
      expires        YYYY-MM-DD (an expired entry FAILS the scan)
      task           the follow-up task that must resolve it
      content_sha256 SHA-256 of the WHOLE target file at approval time
      lines          list of finding line numbers the entry covers
      findings       int == len(lines) — expected finding count
      value_fp       rule A/B: first 12 hex of SHA-256(value);
                     rule C/D/K: null
      value_len      rule A/B: length of the value; MUST be >= 32 — a
                     shorter (low-entropy) value cannot be fingerprinted
                     safely and is NOT exceptable: fix it at source instead;
                     rule C/D/K: null

    Fail-closed enforcement (all of these FAIL the scan):
      * missing/invalid/unknown fields, bad JSON, future `created`
      * expired entry
      * wildcard rule `*`
      * entry references a file that does not exist
      * file content hash differs from `content_sha256` (any change to the
        file invalidates the exception — re-approve with new evidence)
      * duplicate (path, rule) entries
      * an entry that matches NO live finding (stale/unused exception —
        remove it; dormant exceptions are not kept "for the future")
      * a live finding on the bound (path, rule) whose line/value_fp/len
        does not match the binding (reported — never silenced)

    Re-approving an entry needs NO secret handling: the guard's own failure
    output prints the line, value length and value fingerprint (h12) of
    each finding, and the content digest comes from `sha256sum` of the
    changed file.

Coverage (R3): every file that TEXTUALLY looks like text is scanned —
known TEXT_EXT families, plus any unknown-extension or extensionless file
that passes the binary sniff (NUL byte / printable ratio). Binary files
(images/fonts/archives/databases) are skipped by sniff and reported in the
summary line; secrets encoded inside binaries are out of detection scope
(see Limitations). MARKER_WORDS ("test", "fake", "dummy", …) suppress a
value ONLY inside synthetic zones (tests/…, */fixtures/…, test_* files).
Outside a synthetic zone a marker word alone is NOT sufficient proof that
a value is fake: the value is reported for manual review.

Limitations (R3 — what this scanner does NOT prove)
  * Heuristic first line of defense, not a security proof: name/URL/header
    shape-based detection. It does not semantically verify nginx behavior,
    and rule C/D findings do not certify any deployed configuration.
  * Includes are never resolved or expanded (always REVIEW_REQUIRED);
    nginx semantics of included files are out of scope.
  * Encoded secrets (base64/hex-wrapped) inside prose or binaries, and
    content of binary formats, are not detected.
  * A marker word inside a synthetic zone silences a value by repo
    convention — committing a REAL secret into tests/ would be silenced;
    prevented by review + branch protection, not by the scanner.
  When analysis cannot prove safety the guard fails closed (rule D /
  REVIEW_REQUIRED) instead of declaring content clean.

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
            ".sh", ".conf", ".md", ".txt", ".ini", ".toml", ".env", ".cfg",
            ".jsonl", ".csv", ".log", ".out", ".err", ".rs", ".ps1", ".cmd",
            ".proto", ".lock"}
SKIP_DIRS = {".git", "node_modules", "__pycache__", ".venv", "venv", "dist",
             "build", ".pytest_cache", ".mypy_cache", ".ruff_cache"}
SPECIAL_NAMES = {"Dockerfile"}

# R1 fix 1: exact self-exclusion — this file only, by repo-relative POSIX path.
SELF_EXACT = "scripts/ops/secret_guard.py"

_KEYWORD = (r"(?:TOKEN|TOKENS|SECRET|SECRETS|PASSWORD|PASSWD|API_KEY|APIKEY"
            r"|ACCESS_KEY|CREDENTIAL|CREDENTIALS)")
# R3: optional declaration prefix (JS/TS/Rust/Go/Java shape) + optional
# colon type annotation (Rust `&str`, TS `string`, Python hints).
_DECL_PREFIX = r"(?:(?:pub\s+)?(?:const|let|static|var|final)\s+)?"
# type annotation charset: identifier-ish type syntax only (&str, String,
# Record<string, x>, str…) — prose labels with slashes/percent/hash between a
# keyword name and `=` (e.g. design-token color lists) must NOT match.
_TYPE_ANN = r"(?::\s*[^\"'\n=;/#%!?|*+]{1,48})?"
RULE_A_PY = re.compile(
    r"(?m)^(\s*)" + _DECL_PREFIX + r"([A-Za-z0-9_]*" + _KEYWORD + r"[A-Za-z0-9_]*)"
    r"\s*" + _TYPE_ANN + r"=\s*([\"'])([^\"'\n]{16,})\3", re.I)
RULE_A_JSON = re.compile(
    r"(?m)(?:^|[\[{,]\s*)\"([A-Za-z0-9_]*" + _KEYWORD + r"[A-Za-z0-9_]*)\"\s*:\s*"
    r"\"([^\"\n]{16,})\"", re.I)
RULE_A_SH = re.compile(
    r"(?m)^(?:export\s+)?([A-Za-z0-9_]*" + _KEYWORD +
    r"[A-Za-z0-9_]*)\s*=\s*([^ \n]{16,})\s*$", re.I)
# R3: YAML key form — `token: "value"` / `- token: value` / bare token value.
RULE_A_YML = re.compile(
    r"(?m)^\s*(?:-\s+)?([A-Za-z0-9_]*" + _KEYWORD + r"[A-Za-z0-9_]*)\s*:\s*"
    r"(?:[\"']([^\"'\n]{16,})[\"']|([A-Za-z0-9_\-+/=]{16,}))(?:\s*#.*)?$", re.I)
RULE_B = re.compile(r"[?&](?:k|token|api_key|apikey|access_key)=(?:[A-Za-z0-9_\-]{16,})", re.I)
PLACEHOLDER = re.compile(r"^(?:__TOKEN__|<TOKEN>|«REDACTED»|\[REDACTED\]|REDACTED|"
                         r"\$\{?[A-Za-z_][A-Za-z0-9_]*\}?|CHANGE_?ME|changeme|"
                         r"your[_-]?token[_-]?here|N/?A)$", re.I)
# R3: PEM private-key structural header — rule K, applies to every text file.
PEM_HEADER = re.compile(r"-----BEGIN (?:[A-Z0-9]{1,24} )?PRIVATE KEY(?: BLOCK)?-----")

# gate for running the nginx block analyzer: real conf extensions, or
# nginx-shaped lines (an embedded `location`/`server {` template).
NGINX_EXT = {".conf", ".nginx"}
NGINX_HINT = re.compile(r"(?m)^\s*(?:location\b|server\b[^{\n]*\{)")


# values that look like regex definitions (not credentials) — e.g.
# _COMMAND_TOKEN_RE = r"\\S+…" — backslashes/brackets/parens/pipes are not
# secret alphabet; real secrets are alphanumeric-ish (may include + / = : - _ . ~).
REGEX_LOOKS = re.compile(r"[\\()\[\]|^$?*{}~]")
# fixture-marker words: values containing these are treated as synthetic
# test data ONLY inside synthetic zones (tests/…, */fixtures/…, test_* files).
# Outside a synthetic zone a marker word alone is NOT sufficient proof
# (R3 §4.3): the value is reported for manual review.
MARKER_WORDS = re.compile(r"(test|fake|dummy|example|sample|synth|placeholder|LOGKEY|12345678|999999)", re.I)
# JSON values that are prose (contain spaces / slashes / braces) are descriptions
# or file paths, not credential material.
JSON_COMPACT = re.compile(r"^[A-Za-z0-9_\-+={}:.]{16,}$")

# minimum value length for a fingerprint-bound allowlist entry (rule A/B):
# below this the h12 fingerprint of a low-entropy value would be
# brute-forceable — such values are NOT exceptable, they must be fixed.
MIN_BOUND_VALUE_LEN = 32


def _synthetic_zone(rel: str) -> bool:
    rel = rel.replace(os.sep, "/")
    base = rel.rsplit("/", 1)[-1]
    return (rel.startswith("tests/") or rel.startswith("test_")
            or "/tests/" in ("/" + rel) or "/fixtures/" in rel
            or base.startswith("test_"))


def _placeholder_or_regex(value: str, json_form: bool = False) -> bool:
    if PLACEHOLDER.search(value) or REGEX_LOOKS.search(value):
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
    """Governed JSONL allowlist with R3 content binding.

    Returns (entries, errors). Each entry is a validated dict; ANY invalid,
    expired, wildcard or mis-bound entry is a config ERROR (fail-closed):
    the caller must fail the scan. Content-binding checks against the
    actual files happen in main() after the entries load.
    """
    entries, errors = [], []
    seen_keys = set()
    ap = os.path.join(root, ".secretguard-allow")
    if not os.path.isfile(ap):
        return entries, errors
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
            required = ("path", "rule", "owner", "reason", "created", "expires",
                        "task", "content_sha256", "lines", "findings",
                        "value_fp", "value_len")
            missing = [k for k in required if k not in entry]
            if missing:
                errors.append("allowlist line %d: missing field(s) %s (R3 content "
                              "binding schema)" % (lineno, ",".join(missing)))
                continue
            rel = str(entry["path"]).strip()
            if (not rel or rel.startswith("/") or ".." in rel.split("/")
                    or os.path.isabs(rel) or "\\" in rel):
                errors.append("allowlist line %d: path must be a repo-relative "
                              "POSIX path (got %r)" % (lineno, entry["path"]))
                continue
            rule = str(entry["rule"]).strip()
            if rule == "*":
                errors.append("allowlist line %d: wildcard rule '*' is not allowed "
                              "— bind the exception to a specific rule (R3 content "
                              "binding)" % lineno)
                continue
            if rule not in ("A", "B", "C", "D", "K"):
                errors.append("allowlist line %d: rule must be A|B|C|D|K (got %r)" % (lineno, rule))
                continue
            csha = str(entry["content_sha256"]).strip().lower()
            if not re.fullmatch(r"[0-9a-f]{64}", csha):
                errors.append("allowlist line %d: content_sha256 must be a lowercase "
                              "SHA-256 hex digest of the whole file" % lineno)
                continue
            lines = entry["lines"]
            if (not isinstance(lines, list) or not lines
                    or not all(isinstance(x, int) and not isinstance(x, bool) and x >= 1 for x in lines)):
                errors.append("allowlist line %d: lines must be a non-empty list of "
                              "finding line numbers" % lineno)
                continue
            if sorted(set(lines)) != list(lines):
                errors.append("allowlist line %d: lines must be sorted and unique" % lineno)
                continue
            findings = entry["findings"]
            if not isinstance(findings, int) or isinstance(findings, bool) or findings < 1:
                errors.append("allowlist line %d: findings must be a positive integer" % lineno)
                continue
            if findings != len(lines):
                errors.append("allowlist line %d: findings (%d) must equal len(lines) "
                              "(%d)" % (lineno, findings, len(lines)))
                continue
            value_fp, value_len = entry["value_fp"], entry["value_len"]
            if rule in ("A", "B"):
                if not isinstance(value_fp, str) or not re.fullmatch(r"[0-9a-f]{12}", value_fp):
                    errors.append("allowlist line %d: rule %s requires value_fp = first "
                                  "12 hex of SHA-256(value)" % (lineno, rule))
                    continue
                if not isinstance(value_len, int) or isinstance(value_len, bool) \
                        or value_len < MIN_BOUND_VALUE_LEN:
                    errors.append("allowlist line %d: rule %s requires value_len >= %d "
                                  "(a low-entropy value cannot be fingerprint-bound — "
                                  "fix it at source instead)" % (lineno, rule, MIN_BOUND_VALUE_LEN))
                    continue
            else:
                if value_fp is not None or value_len is not None:
                    errors.append("allowlist line %d: rule %s carries no value — "
                                  "value_fp and value_len must be null" % (lineno, rule))
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
                              (lineno, rel, rule, entry["expires"]))
                continue
            if created > _today():
                errors.append("allowlist line %d: created date is in the future" % lineno)
                continue
            key = (rel, rule)
            if key in seen_keys:
                errors.append("allowlist line %d: duplicate entry for %s rule=%s" % (lineno, rel, rule))
                continue
            seen_keys.add(key)
            entry["_lines"] = list(lines)
            entry["_path"] = rel
            entry["_rule"] = rule
            entry["_value_fp"] = value_fp if rule in ("A", "B") else None
            entry["_value_len"] = value_len if rule in ("A", "B") else None
            entries.append(entry)
    return entries, errors


# ---------------------------------------------------------------- file walk

def _looks_text(path: str) -> bool:
    """Binary sniff for unknown-extension / extensionless files (R3).

    A file counts as text when it has no NUL byte and its first 64KB are
    >=85% printable. Binary files are skipped (and counted for the summary)
    — secrets inside binary formats are out of detection scope (docstring
    Limitations).
    """
    try:
        with open(path, "rb") as f:
            head = f.read(65536)
    except OSError:
        return False
    if not head:
        return True
    if b"\x00" in head:
        return False
    printable = sum(1 for b in head if 32 <= b < 127 or b in (9, 10, 13))
    return printable / len(head) >= 0.85


def iter_files(root: str):
    """Yield (path, kind) for every file under root (R3 coverage).

    kind: "known"   — TEXT_EXT family / Dockerfile / *.nginx: scanned.
          "sniffed" — unknown or no extension, but text-like by sniff: scanned.
          "binary"  — failed the sniff: skipped, counted in the summary.
    An unknown-extension or extensionless TEXT file is never silently
    classified as clean.
    """
    for dirpath, dirnames, filenames in os.walk(root):
        dirnames[:] = [d for d in dirnames if d not in SKIP_DIRS]
        for fn in filenames:
            p = os.path.join(dirpath, fn)
            ext = os.path.splitext(fn)[1].lower()
            if ext in TEXT_EXT or fn in SPECIAL_NAMES or fn.endswith(".nginx"):
                yield p, "known"
            elif _looks_text(p):
                yield p, "sniffed"
            else:
                yield p, "binary"


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
    if root.get("unparsed"):
        findings.append(("D", 0,
                         "REVIEW_REQUIRED: nginx-like content could not be parsed into "
                         "balanced blocks — not declared safe", None, None))
        return findings
    blocks = list(_walk(root))
    # R3 §4.1: unresolved includes at ANY level — root included — are
    # REVIEW_REQUIRED. Includes are never resolved/followed, so nested,
    # duplicate and cyclic includes cannot slip through: every include
    # directive reports, in every file, at its own position and context.
    for blk in blocks:
        ctx = "root level (no enclosing block)" if blk["type"] == "root" \
            else "%s block" % (blk["name"] or blk["type"] or "?")
        for wline, words in blk["directives"]:
            if words and words[0] == "include":
                findings.append(("D", wline,
                                 "REVIEW_REQUIRED: unresolved include (%s) at %s — "
                                 "manual review required" %
                                 (" ".join(words[1:3]), ctx), None, None))
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
            findings.append(("C", blk["line"],
                             "location '%s': allow all + auth_basic off + proxy_pass "
                             "(public unauthenticated proxy) [block-scoped]" % blk["name"],
                             None, None))
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
    """Return findings as (rule, line, info, value_fp, value_len).

    value_fp is the h12 fingerprint of the offending value for rules A/B
    (needed for allowlist content binding) and None for value-less rules
    C/D/K. Values themselves NEVER appear in info strings.
    """
    findings = []
    try:
        with open(path, encoding="utf-8", errors="replace") as f:
            text = f.read()
    except OSError:
        return findings

    synthetic = _synthetic_zone(rel)
    seen_a = set()  # dedupe the rule-A flavors on (line, value fingerprint)

    def _add_a(name: str, value: str, line: int, flavor: str):
        if _placeholder_or_regex(value, json_form=(flavor in ("json-key", "yaml-quoted"))):
            return
        if MARKER_WORDS.search(value) and synthetic:
            return  # repo convention (R3 §4.2/§4.3): synthetic test data lives in tests/
        key = (line, h12(value))
        if key in seen_a:  # python-style + shell-style on the same line
            return
        seen_a.add(key)
        info = "%s name=%s value_len=%d sha256=%s…" % (flavor, name, len(value), h12(value))
        if not synthetic and MARKER_WORDS.search(value):
            # R3 §4.3: a marker word alone is not proof of a fake value
            # outside a synthetic zone — report, never silence.
            info += " [synthetic marker word present — marker alone is not "
            info += "sufficient proof; manual review required]"
        findings.append(("A", line, info, h12(value), len(value)))

    for m in RULE_A_PY.finditer(text):
        _add_a(m.group(2), m.group(4),
               text.count("\n", 0, m.start()) + 1, "python")
    for m in RULE_A_JSON.finditer(text):
        _add_a(m.group(1), m.group(2),
               text.count("\n", 0, m.start()) + 1, "json-key")
    for m in RULE_A_SH.finditer(text):
        name, value = m.group(1), m.group(2).strip("\"'")
        _add_a(name, value, text.count("\n", 0, m.start()) + 1, "shell")
    for m in RULE_A_YML.finditer(text):
        value = m.group(2) if m.group(2) is not None else m.group(3)
        _add_a(m.group(1), value, text.count("\n", 0, m.start()) + 1,
               "yaml-quoted" if m.group(2) is not None else "yaml-bare")
    for m in RULE_B.finditer(text):
        value = m.group(0).split("=", 1)[1]
        if _placeholder_or_regex(value):
            continue
        if MARKER_WORDS.search(value) and synthetic:
            continue  # synthetic-zone convention (R3 §4.2/§4.3)
        line = text.count("\n", 0, m.start()) + 1
        info = "query value_len=%d sha256=%s…" % (len(value), h12(value))
        if not synthetic and MARKER_WORDS.search(value):
            info += " [synthetic marker word present — marker alone is not "
            info += "sufficient proof; manual review required]"
        findings.append(("B", line, info, h12(value), len(value)))
    for m in PEM_HEADER.finditer(text):
        line = text.count("\n", 0, m.start()) + 1
        findings.append(("K", line,
                         "PEM private key material (%s) — key files never belong "
                         "in a repository" % m.group(0).replace("-----", "").strip(),
                         None, None))

    is_doc = rel.endswith(".md") or rel.startswith("docs/") or "/docs/" in rel
    if not is_doc and (os.path.splitext(path)[1].lower() in NGINX_EXT
                       or NGINX_HINT.search(text)):
        findings.extend(nginx_findings(text, path, rel))
    return findings


# ---------------------------------------------------------------- main

def _sha256_file(fp: str) -> str:
    h = hashlib.sha256()
    with open(fp, "rb") as f:
        for chunk in iter(lambda: f.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


def main() -> int:
    if len(sys.argv) > 2:
        print(__doc__)
        return 2
    root = sys.argv[1] if len(sys.argv) > 1 else os.getcwd()
    if not os.path.isdir(root):
        print("not a directory:", root)
        return 2

    entries, allow_errors = load_allowlist(root)
    if allow_errors:
        print("secret_guard: ALLOWLIST CONFIG ERROR — fail-closed:")
        for e in allow_errors:
            print("  " + e)
        return 1

    by_key = {}
    for idx, e in enumerate(entries):
        by_key.setdefault((e["_path"], e["_rule"]), []).append(idx)

    # R3 content binding: the file must exist and match the approved digest.
    errored_entries = set()
    for idx, e in enumerate(entries):
        fp = os.path.join(root, e["_path"])
        if not os.path.isfile(fp):
            allow_errors.append("allowlist entry %s rule=%s: file not found — "
                                "remove the exception (it protects nothing)" % (e["_path"], e["_rule"]))
            errored_entries.add(idx)
            continue
        actual = _sha256_file(fp)
        if actual != e["content_sha256"]:
            allow_errors.append("allowlist entry %s rule=%s: CONTENT CHANGED — approved "
                                "content_sha256=%s…, actual=%s… — exception invalid, "
                                "re-approve it against the new content "
                                "(fail-closed per R3 §3.3)" %
                                (e["_path"], e["_rule"], e["content_sha256"][:12], actual[:12]))
            errored_entries.add(idx)

    all_findings = []
    matched = [0] * len(entries)
    scanned = binary_skipped = 0
    for path, kind in iter_files(root):
        rel = os.path.relpath(path, root).replace(os.sep, "/")
        if rel == SELF_EXACT:
            continue  # R1 fix 1: exact-path self-exclusion only
        if kind == "binary":
            binary_skipped += 1
            continue
        scanned += 1
        for rule, line, info, vfp, vlen in scan_file(path, rel):
            suppressed = False
            for idx in by_key.get((rel, rule), []):
                e = entries[idx]
                if idx in errored_entries:
                    continue
                if line not in e["_lines"]:
                    continue
                if e["_value_fp"] is not None and (vfp != e["_value_fp"] or vlen != e["_value_len"]):
                    continue
                matched[idx] += 1
                suppressed = True
                break
            if not suppressed:
                all_findings.append((rule, path, line, info))

    # R3 §3.1: a binding that matches no live finding is a stale/unused
    # exception — fail-closed, remove it (dormant exceptions are not kept).
    for idx, e in enumerate(entries):
        if idx not in errored_entries and matched[idx] == 0:
            allow_errors.append("allowlist entry %s rule=%s: UNUSED/STALE — no live "
                                "finding matches this binding; remove the exception "
                                "(dormant exceptions are not kept)" % (e["_path"], e["_rule"]))

    summary = " [scanned %d text file(s), binary-skipped %d file(s)]" % (scanned, binary_skipped)

    if allow_errors:
        # fail-closed: config errors are shown TOGETHER with any unsuppressed
        # findings so the reviewer sees both signals at once.
        print("secret_guard: ALLOWLIST CONFIG ERROR — fail-closed:")
        for e in allow_errors:
            print("  " + e)
        if all_findings:
            print("secret_guard: %d finding(s) — hardcoded credential material "
                  "detected:%s" % (len(all_findings), summary))
            for rule, path, line, info in sorted(all_findings):
                print("  [rule-%s] %s:%d  %s" % (rule, os.path.relpath(path, root), line, info))
        return 1

    if not all_findings:
        print("secret_guard: CLEAN (no hardcoded credentials detected) — root=%s%s"
              % (root, summary))
        return 0
    print("secret_guard: %d finding(s) — hardcoded credential material detected:%s"
          % (len(all_findings), summary))
    for rule, path, line, info in sorted(all_findings):
        print("  [rule-%s] %s:%d  %s" % (rule, os.path.relpath(path, root), line, info))
    print("Rotate the credential, source it from an env var / secret file, then re-run.")
    return 1


if __name__ == "__main__":
    sys.exit(main())
