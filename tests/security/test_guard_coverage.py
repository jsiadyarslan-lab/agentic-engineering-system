# -*- coding: utf-8 -*-
"""اختبارات تغطية الفاحص وحدود المحلل — R3 §4.1/§4.2/§4.3
(AES-P0-CONTAINMENT-PR-REMEDIATION-1113-R3).

include على كل المستويات (root/nested/missing/duplicate/cycle)، وعينات
اصطناعية لكل عائلة امتدادات مدعومة، والملفات غير القابلة للتحليل، وسلوك
markers داخل/خارج المناطق التركيبية. كل القيم مصطنعة وتُبنى وقت التشغيل —
لا يحمل هذا الملف أي سطر يشبه اعتمادًا ثابتًا.
"""
import subprocess
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]
GUARD = REPO_ROOT / "scripts" / "ops" / "secret_guard.py"

V1 = "Aq11" + "Bz22" + "Cx33" + "Dw44"
V2 = "Qw55" + "Er66" + "Ty77" + "Ui88"
V3 = "Op0o" + "Lk9l" + "Jm8m" + "In7n"
QK = "?" + "k="
QT = "?" + "token="
PEM_HDR = "-----" + "BEGIN OPENSSH PRIVATE KEY" + "-----"
CRT_HDR = "-----" + "BEGIN CERTIFICATE" + "-----"


def _assign(name: str, value: str) -> str:
    return name + " = " + chr(34) + value + chr(34)


def _make_repo(tmp_path, name="repo") -> Path:
    repo = tmp_path / name
    repo.mkdir(parents=True, exist_ok=True)
    return repo


def _write(repo: Path, rel: str, text: str) -> Path:
    p = repo / rel
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(text, encoding="utf-8")
    return p


def _run_guard(repo: Path):
    r = subprocess.run([sys.executable, str(GUARD), str(repo)],
                       capture_output=True, text=True, timeout=120)
    return r.returncode, r.stdout + r.stderr


# =============================================== §4.1 — include على كل المستويات

def test_root_level_include_review_required(tmp_path):
    """include على مستوى root (خارج أي كتلة) — REVIEW_REQUIRED وليس آمنًا."""
    repo = _make_repo(tmp_path)
    conf = ("include /etc/nginx/mime.types;\n"
            "server {\n    listen 80;\n}\n")
    _write(repo, "site.conf", conf)
    rc, out = _run_guard(repo)
    assert rc == 1, out
    assert "rule-D" in out and "root level" in out


def test_includes_in_server_and_location_each_flagged(tmp_path):
    repo = _make_repo(tmp_path)
    conf = ("server {\n    include conf.d/common.conf;\n"
            "    location /x {\n        include conf.d/x.conf;\n"
            "        proxy_pass http://127.0.0.1:8010;\n    }\n}\n")
    _write(repo, "site.conf", conf)
    rc, out = _run_guard(repo)
    assert rc == 1, out
    assert out.count("rule-D") == 2, out       # كل include يُبلَّغ في موضعه وسياقه


def test_missing_include_target_review_required(tmp_path):
    """include يشير إلى ملف غير موجود — لا يُعلَن آمنًا أبدًا (fail-closed)."""
    repo = _make_repo(tmp_path)
    conf = ("server {\n    include conf.d/definitely-missing.conf;\n"
            "    location /x {\n        proxy_pass http://127.0.0.1:8010;\n    }\n}\n")
    _write(repo, "site.conf", conf)
    rc, out = _run_guard(repo)
    assert rc == 1, out
    assert "rule-D" in out and "REVIEW_REQUIRED" in out


def test_duplicate_includes_each_flagged(tmp_path):
    repo = _make_repo(tmp_path)
    conf = ("server {\n    include conf.d/a.conf;\n    include conf.d/a.conf;\n"
            "    location /x {\n        proxy_pass http://127.0.0.1:8010;\n    }\n}\n")
    _write(repo, "site.conf", conf)
    rc, out = _run_guard(repo)
    assert rc == 1, out
    assert out.count("rule-D") == 2, out       # التكرار لا يُخفى


def test_include_cycle_pair_both_flagged(tmp_path):
    """دورة include (a↔b) — الفاحص لا يتبع includes أصلًا فيعلّمهما كليهما."""
    repo = _make_repo(tmp_path)
    _write(repo, "a.conf", "include b.conf;\nserver {\n    listen 80;\n}\n")
    _write(repo, "b.conf", "include a.conf;\nserver {\n    listen 81;\n}\n")
    rc, out = _run_guard(repo)
    assert rc == 1, out
    assert out.count("rule-D") == 2, out       # الدورة لا تخلق نقطة عمياء


# ===================================== §4.2 — عائلات الامتدادات المدعومة

def test_jsonl_family_detected(tmp_path):
    repo = _make_repo(tmp_path)
    line = "{" + chr(34) + "resume_token" + chr(34) + ": " + chr(34) \
        + "rsm-" + "0f1e2d3c4b5a6978" + chr(34) + "}"
    _write(repo, "events/event_log.jsonl", line + "\n")
    rc, out = _run_guard(repo)
    assert rc == 1, out
    assert "rule-A" in out and "json-key" in out


def test_yaml_family_detected(tmp_path):
    repo = _make_repo(tmp_path)
    body = ("providers:\n"
            "  api" + "_key: " + chr(34) + V1 + chr(34) + "\n"
            "  secret" + "_token: " + V2 + "\n")
    _write(repo, "config.yml", body)
    rc, out = _run_guard(repo)
    assert rc == 1, out
    assert out.count("rule-A") >= 2, out


def test_workflow_yaml_placeholder_safe(tmp_path):
    """workflow بتعبير GitHub Actions — لا إنذار (بنيوي غير قيمة)."""
    repo = _make_repo(tmp_path)
    body = ("jobs:\n  build:\n    steps:\n      - run: |\n"
            "          export TOKEN=${{ secrets.DEPLOY" + "_TOKEN }}\n")
    _write(repo, ".github/workflows/wf.yml", body)
    rc, out = _run_guard(repo)
    assert rc == 0, out


def test_toml_ini_env_families_detected(tmp_path):
    repo = _make_repo(tmp_path)
    _write(repo, "pyproject.toml", "[tool]\n" + _assign("password", V1) + "\n")
    _write(repo, "app.ini", "[auth]\n" + "api" + "_key = " + V2 + "\n")
    _write(repo, ".env", "ACCESS" + "_KEY=" + V3 + "\n")
    rc, out = _run_guard(repo)
    assert rc == 1, out
    assert out.count("rule-A") >= 3, out


def test_rust_const_detected(tmp_path):
    repo = _make_repo(tmp_path)
    _write(repo, "main.rs",
           "const API" + "_KEY: &str = " + chr(34) + V1 + chr(34) + ";\n")
    rc, out = _run_guard(repo)
    assert rc == 1, out
    assert "rule-A" in out


def test_js_ts_const_let_detected(tmp_path):
    repo = _make_repo(tmp_path)
    _write(repo, "app.js", "const API" + "_KEY = " + chr(34) + V1 + chr(34) + ";\n")
    _write(repo, "app.ts",
           "let AUTH" + "_TOKEN: string = " + chr(34) + V2 + chr(34) + ";\n")
    rc, out = _run_guard(repo)
    assert rc == 1, out
    assert out.count("rule-A") >= 2, out


def test_csv_and_log_query_values_detected(tmp_path):
    repo = _make_repo(tmp_path)
    _write(repo, "trace.csv",
           "id,url\n1,http://h/x" + QT + V1 + "\n")
    _write(repo, "run.log", "GET http://h/y" + QK + V2 + " 200\n")
    rc, out = _run_guard(repo)
    assert rc == 1, out
    assert out.count("rule-B") >= 2, out


def test_unknown_extension_text_scanned(tmp_path):
    """امتداد غير معروف لكنه نصي — يُفحص ولا يُصنَّف نظيفًا تلقائيًا."""
    repo = _make_repo(tmp_path)
    _write(repo, "data.xyz", _assign("TOKEN", V1) + "\n")
    rc, out = _run_guard(repo)
    assert rc == 1, out
    assert "rule-A" in out


def test_extensionless_text_file_scanned(tmp_path):
    repo = _make_repo(tmp_path)
    _write(repo, "NOTES", _assign("TOKEN", V1) + "\n")
    rc, out = _run_guard(repo)
    assert rc == 1, out
    assert "rule-A" in out


def test_binary_file_skipped_with_transparent_summary(tmp_path):
    """ملف ثنائي — يُتخطى بالتشخيص ويُعلَن العدد (حد موثق، لا ادعاء فحصه)."""
    repo = _make_repo(tmp_path)
    p = repo / "blob.bin"
    p.write_bytes(b"Aq11Bz22Cx33Dw44\x00\x01\x02binarytail")
    rc, out = _run_guard(repo)
    assert rc == 0, out
    assert "binary-skipped 1" in out


def test_pem_private_key_rule_k(tmp_path):
    """رأس مفتاح خاص PEM — rule-K في أي ملف نصي (بلا استثناء marker)."""
    repo = _make_repo(tmp_path)
    _write(repo, "secret.pem", PEM_HDR + "\n" + "AAAA" * 8 + "\n")
    rc, out = _run_guard(repo)
    assert rc == 1, out
    assert "rule-K" in out


def test_certificate_not_flagged(tmp_path):
    repo = _make_repo(tmp_path)
    _write(repo, "cert.pem", CRT_HDR + "\n" + "AAAA" * 8 + "\n")
    rc, out = _run_guard(repo)
    assert rc == 0, out


# ============================================== §4.3 — markers

def test_marker_word_outside_tests_reported(tmp_path):
    """كلمة marker وحدها خارج tests/ ليست دليلًا كافًا — تُبلَّغ للمراجعة."""
    repo = _make_repo(tmp_path)
    _write(repo, "app.py", _assign("TOKEN", "my" + "test" + "value0987654321") + "\n")
    rc, out = _run_guard(repo)
    assert rc == 1, out
    assert "rule-A" in out and "marker" in out.lower()


def test_marker_word_inside_tests_zone_suppressed(tmp_path):
    repo = _make_repo(tmp_path)
    _write(repo, "tests/data/fake_seed.py",
           _assign("TOKEN", "my" + "test" + "value0987654321") + "\n")
    rc, out = _run_guard(repo)
    assert rc == 0, out


def test_marker_case_variants_outside_flagged(tmp_path):
    repo = _make_repo(tmp_path)
    _write(repo, "app.py",
           _assign("TOKEN", "FaKe" + "Test" + "0987654321ab") + "\n")
    rc, out = _run_guard(repo)
    assert rc == 1, out


def test_partial_marker_in_real_shaped_value_flagged(tmp_path):
    repo = _make_repo(tmp_path)
    _write(repo, "app.py",
           _assign("TOKEN", "abcdefghij" + "sample" + "klmnop098765") + "\n")
    rc, out = _run_guard(repo)
    assert rc == 1, out


def test_marker_cannot_silence_query_value(tmp_path):
    repo = _make_repo(tmp_path)
    url = "http://h/x" + QT + "x" + "fake" + "y123456789012345"
    _write(repo, "client.py", "print(" + chr(34) + url + chr(34) + ")\n")
    rc, out = _run_guard(repo)
    assert rc == 1, out
    assert "rule-B" in out


def test_marker_wrapped_around_secret_shaped_value_flagged(tmp_path):
    """محاولة إخفاء قيمة تشبه الاعتماد داخل marker — تفشل."""
    repo = _make_repo(tmp_path)
    _write(repo, "app.py",
           _assign("TOKEN", "fake" + "Zq9Wm2Tx8Vb4Nr7Kp3Dd6Gg1") + "\n")
    rc, out = _run_guard(repo)
    assert rc == 1, out
    assert "rule-A" in out
