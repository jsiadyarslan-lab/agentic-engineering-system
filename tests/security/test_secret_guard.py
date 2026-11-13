# -*- coding: utf-8 -*-
"""اختبارات فاحص الأسرار — AES-P0-CONTAINMENT-PR-REMEDIATION-1113-R1 (fix 2).

كل القيم الاعتمادية في هذه الاختبارات مصطنعة بالكامل (SYNTH…) ولا تمثل
أي اعتماد حقيقي أو تاريخي. تُبنى أسطر الملفات بالتسلسل في وقت التشغيل
حتى لا يحمل ملف الاختبار نفسه أي سطر يشبه اعتمادًا ثابتًا.
"""
import subprocess
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]
GUARD = REPO_ROOT / "scripts" / "ops" / "secret_guard.py"

# قيم مصطنعة — أجزاء تُجمع في وقت التشغيل (لا يظهر النص الكامل في المصدر)
V1 = "Aq11" + "Bz22" + "Cx33" + "Dw44"
V2 = "Qw55" + "Er66" + "Ty77" + "Ui88"
V3 = "Op0o" + "Lk9l" + "Jm8m" + "In7n"
QK = "?" + "k="            # بُني بالتسلسل: لا يظهر نص الاستعلام كاملًا في المصدر
QK2 = "?" + "token="


def _assign(name: str, value: str) -> str:
    return name + " = " + chr(34) + value + chr(34)


def _run_guard(repo: Path):
    r = subprocess.run([sys.executable, str(GUARD), str(repo)],
                       capture_output=True, text=True, timeout=120)
    return r.returncode, r.stdout + r.stderr


def _make_repo(tmp_path, name="repo") -> Path:
    repo = tmp_path / name
    repo.mkdir(parents=True, exist_ok=True)
    return repo


def _write(repo: Path, rel: str, text: str) -> Path:
    p = repo / rel
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(text, encoding="utf-8")
    return p


# ------------------------------------------------------------------ rule A

def test_detects_python_token_literal(tmp_path):
    repo = _make_repo(tmp_path)
    _write(repo, "app.py", "import os\n\n" + _assign("TOKEN", V1) + "\n")
    rc, out = _run_guard(repo)
    assert rc == 1, out
    assert "rule-A" in out
    assert V1 not in out          # القيمة نفسها لا تُطبع أبدًا — بصمة فقط


def test_detects_api_key_password_credential_names(tmp_path):
    repo = _make_repo(tmp_path)
    _write(repo, "a.py", _assign("API_KEY", V1) + "\n")
    _write(repo, "b.py", _assign("PASSWORD", V2) + "\n")
    _write(repo, "c.py", _assign("DB_CREDENTIAL", V3) + "\n")
    rc, out = _run_guard(repo)
    assert rc == 1
    assert out.count("rule-A") >= 3


def test_detects_json_and_shell_forms(tmp_path):
    repo = _make_repo(tmp_path)
    _write(repo, "conf.json", "{\n  " + chr(34) + "api_key" + chr(34) + ": "
           + chr(34) + V1 + chr(34) + "\n}\n")
    _write(repo, "env.sh", "export " + "TOKEN" + "=" + V2 + "\n")
    rc, out = _run_guard(repo)
    assert rc == 1
    assert out.count("rule-A") >= 2


def test_placeholders_not_flagged(tmp_path):
    repo = _make_repo(tmp_path)
    _write(repo, "ok.py", "\n".join([
        _assign("TOKEN", "${" + "TOKEN}"),
        _assign("PASSWORD", "changeme"),
        _assign("API_KEY", "__" + "TOKEN__"),
        _assign("SECRET", "REDACTED"),
    ]) + "\n")
    rc, out = _run_guard(repo)
    assert rc == 0, out


def test_regex_definition_not_flagged(tmp_path):
    repo = _make_repo(tmp_path)
    body = "COMMAND" + "_TOKEN_RE = " + "r" + chr(34) + chr(92) + "d+" + chr(34) + "\n"
    _write(repo, "parse.py", body)
    rc, out = _run_guard(repo)
    assert rc == 0, out


# ------------------------------------------------------------------ rule B

def test_detects_query_string_k_token_api_key(tmp_path):
    repo = _make_repo(tmp_path)
    url1 = "http://h/x" + QK + V1
    url2 = "http://h/y" + QK2 + V2
    _write(repo, "client.py", "print(" + chr(34) + url1 + chr(34) + ")\nprint("
           + chr(34) + url2 + chr(34) + ")\n")
    rc, out = _run_guard(repo)
    assert rc == 1
    assert "rule-B" in out
    assert V1 not in out and V2 not in out


# ------------------------------------------- fix 1 — exact self-exclusion

def test_exclusion_is_exact_path_not_substring(tmp_path):
    """المستودع الذي اسمه نفسه يحت secret_guard + ملف اسمه secret_guard_credentials.py."""
    repo = _make_repo(tmp_path, "my-" + "secret_guard" + "-repo-1113")
    _write(repo, "secret_guard" + "_credentials.py", _assign("TOKEN", V1) + "\n")
    rc, out = _run_guard(repo)
    assert rc == 1, out
    assert "rule-A" in out


def test_guard_file_is_skipped_only_at_exact_relpath(tmp_path):
    src = GUARD.read_text(encoding="utf-8")
    repo = _make_repo(tmp_path)
    # نسخة في المسار الدقيق — تُستثنى
    _write(repo, "scripts/ops/secret_guard.py", src)
    rc, out = _run_guard(repo)
    assert rc == 0, out
    # نسخة في مسار آخر + اعتماد مصطنع — يجب أن تُكتشف
    _write(repo, "tools/secret_guard.py", src + "\n\n" + _assign("TOKEN", V1) + "\n")
    rc, out = _run_guard(repo)
    assert rc == 1, out
    assert "tools/secret_guard.py" in out


def test_copy_of_guard_with_credential_at_other_path(tmp_path):
    """حتى نسخة الفاحص نفسها في مسار آخر تُفحص — لا استثناء واسع."""
    repo = _make_repo(tmp_path)
    src = GUARD.read_text(encoding="utf-8") + "\n\n" + _assign("TOKEN", V1) + "\n"
    _write(repo, "scripts/ops/secret_guard.py", "x = 1\n")
    _write(repo, "other/secret_guard_v9.py", src)
    rc, out = _run_guard(repo)
    assert rc == 1, out


# ------------------------------------------------- fix 4 — allowlist rules

def _allow_entry(path, rule="*", expires="2027-01-31", **kw):
    import json
    entry = {"path": path, "rule": rule, "owner": "test-owner",
             "reason": "synthetic test entry", "created": "2026-11-13",
             "expires": expires, "task": "R1-1113 tests"}
    entry.update(kw)
    return json.dumps(entry)


def test_allowlist_valid_entry_suppresses(tmp_path):
    repo = _make_repo(tmp_path)
    _write(repo, "legacy.py", _assign("TOKEN", V1) + "\n")
    _write(repo, ".secretguard-allow", _allow_entry("legacy.py", "A") + "\n")
    rc, out = _run_guard(repo)
    assert rc == 0, out


def test_allowlist_missing_fields_rejected(tmp_path):
    repo = _make_repo(tmp_path)
    _write(repo, "legacy.py", _assign("TOKEN", V1) + "\n")
    import json
    bad = json.dumps({"path": "legacy.py", "rule": "A"})  # بلا مالك ولا مدة
    _write(repo, ".secretguard-allow", bad + "\n")
    rc, out = _run_guard(repo)
    assert rc == 1
    assert "ALLOWLIST CONFIG ERROR" in out
    assert "missing field" in out


def test_allowlist_expired_entry_fails_closed(tmp_path):
    repo = _make_repo(tmp_path)
    _write(repo, "legacy.py", _assign("TOKEN", V1) + "\n")
    _write(repo, ".secretguard-allow", _allow_entry("legacy.py", "A",
                                                     expires="2026-01-01") + "\n")
    rc, out = _run_guard(repo)
    assert rc == 1
    assert "EXPIRED" in out


def test_allowlist_invalid_json_line_rejected(tmp_path):
    repo = _make_repo(tmp_path)
    _write(repo, "legacy.py", _assign("TOKEN", V1) + "\n")
    _write(repo, ".secretguard-allow", "not json at all\n")
    rc, out = _run_guard(repo)
    assert rc == 1
    assert "not valid JSON" in out


def test_allowlist_bad_rule_value_rejected(tmp_path):
    repo = _make_repo(tmp_path)
    _write(repo, ".secretguard-allow", _allow_entry("legacy.py", "Z") + "\n")
    rc, out = _run_guard(repo)
    assert rc == 1
    assert "rule must be" in out


# ------------------------------------------- fix 3 — nginx block scoping

def _loc(prefix, body_lines):
    return "    " + "location " + prefix + " {\n" + body_lines + "    }\n"


def test_nginx_public_unauth_proxy_detected(tmp_path):
    repo = _make_repo(tmp_path)
    conf = ("server {\n"
            "    auth_basic " + chr(34) + "realm" + chr(34) + ";\n"
            + _loc("/x",
                   "        allow all;\n        auth_basic off;\n"
                   "        proxy_pass http://127.0.0.1:8010/health;\n")
            + "}\n")
    _write(repo, "site.conf", conf)
    rc, out = _run_guard(repo)
    assert rc == 1
    assert "rule-C" in out


def test_nginx_separate_blocks_not_flagged(tmp_path):
    """allow all في كتلة، auth_basic off في كتلة أخرى، proxy_pass في ثالثة — لا إنذار."""
    repo = _make_repo(tmp_path)
    conf = ("server {\n"
            "    auth_basic " + chr(34) + "realm" + chr(34) + ";\n"
            + _loc("/pub", "        allow all;\n")
            + _loc("/noauth", "        auth_basic off;\n        allow 10.0.0.1;\n")
            + _loc("/api", "        proxy_pass http://127.0.0.1:8010;\n")
            + "}\n")
    _write(repo, "site.conf", conf)
    rc, out = _run_guard(repo)
    assert rc == 0, out


def test_nginx_include_unresolved_review_required(tmp_path):
    repo = _make_repo(tmp_path)
    conf = ("server {\n    include /etc/nginx/extra-site.conf;\n"
            + _loc("/api", "        proxy_pass http://127.0.0.1:8010;\n")
            + "}\n")
    _write(repo, "site.conf", conf)
    rc, out = _run_guard(repo)
    assert rc == 1
    assert "rule-D" in out and "REVIEW_REQUIRED" in out


def test_nginx_unparsable_content_review_required(tmp_path):
    repo = _make_repo(tmp_path)
    _write(repo, "broken.conf", "server {\n  listen 80;\n")  # قوس غير مغلق
    rc, out = _run_guard(repo)
    assert rc == 1
    assert "rule-D" in out


def test_nginx_embedded_template_in_python_detected(tmp_path):
    """قالب nginx داخل سلسلة Python (نمط w1t03) — يُكتشف ضمن حدود الكتلة."""
    repo = _make_repo(tmp_path)
    tmpl = ("LOCATION = " + chr(34) * 3 + "\n"
            "    location = /healthz-{token} " + "{{" + "\n"
            "        allow all;\n        auth_basic off;\n"
            "        proxy_pass http://127.0.0.1:8010/health;\n"
            "    " + "}}" + "\n" + chr(34) * 3 + "\n")
    _write(repo, "deploy_helper.py", tmpl)
    rc, out = _run_guard(repo)
    assert rc == 1
    assert "rule-C" in out


def test_docs_markdown_nginx_text_not_flagged(tmp_path):
    repo = _make_repo(tmp_path)
    _write(repo, "docs/notes.md",
           "    location /x { allow all; auth_basic off; proxy_pass http://h; }\n")
    rc, out = _run_guard(repo)
    assert rc == 0, out


def test_clean_repo_passes(tmp_path):
    repo = _make_repo(tmp_path)
    _write(repo, "main.py", "import os\n\nprint(os.environ.get(\"W2T25_MONITOR_TOKEN\"))\n")
    rc, out = _run_guard(repo)
    assert rc == 0, out
