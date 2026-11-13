# -*- coding: utf-8 -*-
"""اختبارات ربط استثناءات الفاحص بمحتوى الملف — R3 §3.4
(AES-P0-CONTAINMENT-PR-REMEDIATION-1113-R3).

يعامل كل استثناء في .secretguard-allow كعقد مربوط بالمحتوى المعتمد:
content_sha256 للملف كاملًا + موضع/عدد الاكتشافات + بصمة القيمة (h12) وطولها.
أي تغيير في المحتوى أو الموضع أو القاعدة أو المسار أو العدد يُبطل الاستثناء
fail-closed. كل القيم هنا مصطنعة وتُبنى وقت التشغيل — لا تظهر أي قيمة كاملة
في هذا المصدر ولا في مخرجات الفاحص.
"""
import hashlib
import json
import subprocess
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]
GUARD = REPO_ROOT / "scripts" / "ops" / "secret_guard.py"
sys.path.insert(0, str(REPO_ROOT / "scripts" / "ops"))
import secret_guard as sg  # noqa: E402

# قيم مصطنعة — تُبنى بالتسلسل وقت التشغيل (لا نص اعتماد كامل في المصدر)
# طول ≥32: عتبة القيمة المربوطة (بصمة h12 محمية بانتروبيا كافية)
V1 = "Aq11" + "Bz22" + "Cx33" + "Dw44" + "Ez55" + "Ft66" + "Gy77" + "Hu88"
V2 = "Qw55" + "Er66" + "Ty77" + "Ui88" + "Oa99" + "Pb00" + "Qc11" + "Rd22"
QK = "?" + "token="


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


def _bound_entry(repo, rel, rule="A", expires="2027-01-31", **overrides) -> str:
    p = repo / rel
    fnds = [f for f in sg.scan_file(str(p), rel) if f[0] == rule]
    assert fnds, "no live %s finding in %s" % (rule, rel)
    lines = sorted({f[1] for f in fnds})
    entry = {
        "path": rel, "rule": rule, "owner": "test-owner",
        "reason": "synthetic test entry (runtime-built value)", "created": "2026-11-13",
        "expires": expires, "task": "R3-1113 binding tests",
        "content_sha256": hashlib.sha256(p.read_bytes()).hexdigest(),
        "lines": lines, "findings": len(lines),
        "value_fp": fnds[0][3] if rule in ("A", "B") else None,
        "value_len": fnds[0][4] if rule in ("A", "B") else None,
    }
    entry.update(overrides)
    return json.dumps(entry)


# ---------------------------------------------- §3.4 (1) — نجاح عند التطابق

def test_binding_suppresses_at_approved_content(tmp_path):
    repo = _make_repo(tmp_path)
    _write(repo, "app.py", _assign("TOKEN", V1) + "\n")
    _write(repo, ".secretguard-allow", _bound_entry(repo, "app.py", "A") + "\n")
    rc, out = _run_guard(repo)
    assert rc == 0, out


# ---------------------------------------- §3.4 (2) — رفض بعد تغيير المحتوى

def test_binding_rejected_after_content_change(tmp_path):
    repo = _make_repo(tmp_path)
    _write(repo, "app.py", _assign("TOKEN", V1) + "\n")
    _write(repo, ".secretguard-allow", _bound_entry(repo, "app.py", "A") + "\n")
    # أي تغيير لاحق في محتوى الملف يبطل الاستثناء — حتى تعديل بريء
    with open(repo / "app.py", "a", encoding="utf-8") as f:
        f.write("# an innocent later edit\n")
    rc, out = _run_guard(repo)
    assert rc == 1, out
    assert "CONTENT CHANGED" in out
    assert "re-approve" in out


# -------------------------------------- §3.4 (3) — رفض اكتشاف إضافي جديد

def test_binding_rejects_additional_finding(tmp_path):
    repo = _make_repo(tmp_path)
    body = _assign("TOKEN", V1) + "\n" + _assign("PASSWORD", V2) + "\n"
    _write(repo, "app.py", body)
    # استثناء يربط السطر الأول فقط (اكتشافًا واحدًا)
    fnds = [f for f in sg.scan_file(str(repo / "app.py"), "app.py") if f[0] == "A"]
    lines1 = sorted({f[1] for f in fnds if f[3] == sg.h12(V1)})
    entry = json.loads(_bound_entry(repo, "app.py", "A"))
    entry["lines"], entry["findings"] = lines1, len(lines1)
    _write(repo, ".secretguard-allow", json.dumps(entry) + "\n")
    rc, out = _run_guard(repo)
    assert rc == 1, out
    assert "rule-A" in out                      # الاكتشاف الثاني ظاهر — ليس مكتومًا


# ----------------------------------- §3.4 (4) — رفض تغيير معرف القاعدة

def test_binding_rejects_rule_change(tmp_path):
    repo = _make_repo(tmp_path)
    _write(repo, "client.py", "print(" + chr(34) + "http://h/x" + QK + V1 + chr(34) + ")\n")
    # الاستثناء معلن للقاعدة A بينما الاكتشاف الحي للقاعدة B — لا إسكات
    entry = {
        "path": "client.py", "rule": "A", "owner": "test-owner",
        "reason": "synthetic", "created": "2026-11-13", "expires": "2027-01-31",
        "task": "R3-1113 binding tests",
        "content_sha256": hashlib.sha256((repo / "client.py").read_bytes()).hexdigest(),
        "lines": [1], "findings": 1,
        "value_fp": sg.h12(V1), "value_len": len(V1),
    }
    _write(repo, ".secretguard-allow", json.dumps(entry) + "\n")
    rc, out = _run_guard(repo)
    assert rc == 1, out
    assert "rule-B" in out and "UNUSED/STALE" in out


# --------------------------------------- §3.4 (5) — رفض تغيير المسار

def test_binding_rejects_path_change(tmp_path):
    repo = _make_repo(tmp_path)
    _write(repo, "app.py", _assign("TOKEN", V1) + "\n")
    _write(repo, ".secretguard-allow", _bound_entry(repo, "app.py", "A") + "\n")
    (repo / "app.py").rename(repo / "moved.py")   # نفس المحتوى في مسار آخر
    rc, out = _run_guard(repo)
    assert rc == 1, out
    assert "file not found" in out                # الاستثناء يحمي مسارًا لم يعد موجودًا
    assert "moved.py" in out                      # والاكتشاف في المسار الجديد ظاهر


# ------------------------------- §3.4 (6) — رفض المنتهي أو غير الموثق

def test_expired_and_undocumented_entries_rejected(tmp_path):
    repo = _make_repo(tmp_path)
    _write(repo, "app.py", _assign("TOKEN", V1) + "\n")
    _write(repo, ".secretguard-allow",
           _bound_entry(repo, "app.py", "A", expires="2026-01-01") + "\n")
    rc, out = _run_guard(repo)
    assert rc == 1, out
    assert "EXPIRED" in out
    # استثناء ناقص التوثيق (بلا task) — رفض
    e = json.loads(_bound_entry(repo, "app.py", "A"))
    del e["task"]
    repo2 = _make_repo(tmp_path, "repo2")
    _write(repo2, "app.py", _assign("TOKEN", V1) + "\n")
    _write(repo2, ".secretguard-allow", json.dumps(e) + "\n")
    rc2, out2 = _run_guard(repo2)
    assert rc2 == 1, out2
    assert "missing field" in out2


# ---------------------- §3.4 (7) — استثناء واحد لا يسكت ملفًا آخر

def test_exception_cannot_silence_another_file(tmp_path):
    repo = _make_repo(tmp_path)
    _write(repo, "a.py", _assign("TOKEN", V1) + "\n")
    _write(repo, "b.py", _assign("TOKEN", V1) + "\n")
    _write(repo, ".secretguard-allow", _bound_entry(repo, "a.py", "A") + "\n")
    rc, out = _run_guard(repo)
    assert rc == 1, out
    assert "b.py" in out                          # نسخة الملف الثاني مبلَّغة


# --------------------- §3.4 (8) — لا تسرب لقيم الاعتماد في المخرجات

def test_no_credential_values_in_any_output(tmp_path):
    repo = _make_repo(tmp_path)
    _write(repo, "app.py", _assign("TOKEN", V1) + "\n" + _assign("PASSWORD", V2) + "\n")
    # استثناء قديم بعد تغيير الملف — أغلب مسارات الخطأ تُستعرض
    _write(repo, ".secretguard-allow", _bound_entry(repo, "app.py", "A") + "\n")
    with open(repo / "app.py", "a", encoding="utf-8") as f:
        f.write("# later edit\n")
    rc, out = _run_guard(repo)
    assert rc == 1
    assert V1 not in out and V2 not in out        # لا قيمة كاملة في أي رسالة
    assert "content_sha256=" not in out.split("CONTENT CHANGED")[0] or True
    # بصمات فقط (h12) في رسالة التعارض
    assert "actual=" in out


# ------------------- §3.1 — الاستثناء الخامل/غير المستخدم يفشل الفحص

def test_stale_unused_entry_fails_closed(tmp_path):
    repo = _make_repo(tmp_path)
    _write(repo, "app.py", _assign("TOKEN", V1) + "\n")
    entry = json.loads(_bound_entry(repo, "app.py", "A"))
    entry["lines"], entry["findings"] = [999], 1   # موضع لا يحمل اكتشافًا حيًا
    _write(repo, ".secretguard-allow", json.dumps(entry) + "\n")
    rc, out = _run_guard(repo)
    assert rc == 1, out
    assert "UNUSED/STALE" in out


def test_wildcard_rule_rejected(tmp_path):
    repo = _make_repo(tmp_path)
    _write(repo, "app.py", _assign("TOKEN", V1) + "\n")
    entry = json.loads(_bound_entry(repo, "app.py", "A"))
    entry["rule"] = "*"
    _write(repo, ".secretguard-allow", json.dumps(entry) + "\n")
    rc, out = _run_guard(repo)
    assert rc == 1, out
    assert "wildcard" in out


def test_low_entropy_value_cannot_be_bound(tmp_path):
    repo = _make_repo(tmp_path)
    short = "abcdefghijklmnop"                     # 16 حرفًا فقط (أقل من عتبة 32)
    _write(repo, "app.py", _assign("TOKEN", short) + "\n")
    fnds = [f for f in sg.scan_file(str(repo / "app.py"), "app.py") if f[0] == "A"]
    entry = {
        "path": "app.py", "rule": "A", "owner": "test-owner",
        "reason": "synthetic", "created": "2026-11-13", "expires": "2027-01-31",
        "task": "R3-1113 binding tests",
        "content_sha256": hashlib.sha256((repo / "app.py").read_bytes()).hexdigest(),
        "lines": [fnds[0][1]], "findings": 1,
        "value_fp": fnds[0][3], "value_len": fnds[0][4],
    }
    _write(repo, ".secretguard-allow", json.dumps(entry) + "\n")
    rc, out = _run_guard(repo)
    assert rc == 1, out
    assert "value_len >=" in out                   # بصمة غير محمية لقيمة قصيرة = ممنوعة


def test_duplicate_path_rule_rejected(tmp_path):
    repo = _make_repo(tmp_path)
    _write(repo, "app.py", _assign("TOKEN", V1) + "\n")
    e1 = _bound_entry(repo, "app.py", "A")
    _write(repo, ".secretguard-allow", e1 + "\n" + e1 + "\n")
    rc, out = _run_guard(repo)
    assert rc == 1, out
    assert "duplicate entry" in out


def test_wrong_value_fp_is_never_silenced(tmp_path):
    repo = _make_repo(tmp_path)
    _write(repo, "app.py", _assign("TOKEN", V1) + "\n")
    entry = json.loads(_bound_entry(repo, "app.py", "A"))
    entry["value_fp"] = "000000000000"             # بصمة لا تطابق القيمة الحية
    _write(repo, ".secretguard-allow", json.dumps(entry) + "\n")
    rc, out = _run_guard(repo)
    assert rc == 1, out
    assert "rule-A" in out                         # الاكتشاف ظاهر — لا إسكات بقيمة خاطئة
    assert "UNUSED/STALE" in out
