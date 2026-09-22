"""إثبات التنفيذ الحقيقي (الأمر 011 §29) — عبر resolve_executor نفسه
الذي يستخدمه المسبار والمنفذ: مساحة عمل + كتابة + تنفيذ + pytest +
أداة + التقاط، مع هوية البيئة في كل نتيجة.
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

sys.path.insert(0, "src")

from api import routes  # noqa: E402  — جلسة الإنتاج نفسها
from execution import service as execution_service  # noqa: E402

sessions = routes._sessions

# 1) المصدر الموحد: نفس (بيئة، خلفية) للمسبار والمنفذ
environment, backend = execution_service.resolve_executor(sessions)
print(f"[env] {environment['name']} ({environment['backend']}, "
      f"isolation={environment.get('isolation')}, "
      f"status={environment['status']})")

proof_dir = Path("runtime/order011-proof")
proof_dir.mkdir(parents=True, exist_ok=True)
workspace = proof_dir / "ws"
artifacts = proof_dir / "art"
workspace.mkdir(exist_ok=True)
artifacts.mkdir(exist_ok=True)

# 2) سلسلة §29: كتابة ملف + اختبار pytest + أداة + التقاط
# عقد الركيزة (E1): /work مصدر قراءة فقط، و/artifacts هو مخرج
# الحيازة القابل للكتابة — الكود يكتب ملفاته ويختبرها هناك
code = r'''
import pathlib, sys, json

art = pathlib.Path("/artifacts")
(art / "calc.py").write_text(
    "def add(a, b):\n    return a + b\n", encoding="utf-8")
(art / "test_calc.py").write_text(
    "from calc import add\n\ndef test_add():\n"
    "    assert add(2, 3) == 5\n"
    "    assert add(-1, 1) == 0\n", encoding="utf-8")
print("workspace files written: calc.py, test_calc.py")

# pytest داخل العملية — الركيزة أحادية العملية (seccomp يمنع fork)
sys.path.insert(0, str(art))
import pytest

pytest_exit = pytest.main(["-q", str(art / "test_calc.py")])
print("pytest exit:", pytest_exit)
print("pytest passed:", pytest_exit == 0)

(art / "proof.json").write_text(json.dumps({
    "pytest_exit": int(pytest_exit),
    "environment": "isolated-substrate",
    "passed": pytest_exit == 0,
}, ensure_ascii=False), encoding="utf-8")
print("artifact written: proof.json")
'''

outcome = backend.run_code(
    code, workspace=workspace, artifacts=artifacts, timeout_s=120.0,
)
print(f"[run] termination={outcome.termination} exit={outcome.exit_code} "
      f"duration={outcome.duration_ms}ms env_id={outcome.environment_id}")
print("[stdout]", outcome.stdout.strip()[:300])
if outcome.stderr:
    print("[stderr]", outcome.stderr.strip()[:200])
print("[artifacts]", list(outcome.artifacts.keys()))

# 3) git على مساحة العمل الحقيقية (خارج الركيزة — المستوى المسؤول)
import subprocess

git = subprocess.run(
    ["git", "init", "-q"], cwd=artifacts, capture_output=True, text=True)
subprocess.run(["git", "add", "-A"], cwd=artifacts, capture_output=True)
diff = subprocess.run(
    ["git", "diff", "--cached", "--stat"], cwd=artifacts,
    capture_output=True, text=True,
)
print("[git]", "initialized" if git.returncode == 0 else git.stderr[:100])
print("[git-diff]", diff.stdout.strip()[:200])

# 4) الحكم
checks = {
    "same_source_env": environment["status"] == "READY",
    "exec_completed": outcome.termination == "COMPLETED"
    and outcome.exit_code == 0,
    "pytest_passed": "pytest exit: 0" in outcome.stdout,
    "artifact_captured": "proof.json" in outcome.artifacts,
    "git_diff_shows_files": "calc.py" in diff.stdout
    or "test_calc.py" in diff.stdout,
}
print("[verdict]", json.dumps(checks, ensure_ascii=False))
ok = all(checks.values())
print("§29 REAL EXECUTION:", "PROVEN" if ok else "INCOMPLETE")
raise SystemExit(0 if ok else 1)
