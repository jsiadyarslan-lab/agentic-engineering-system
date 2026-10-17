"""اختبار الخلفيات الحقيقية (الأمر 010 §16-§21).

- LocalLinuxBackend: وصف صادق + تنفيذ فعلي على Linux/x86_64 (بيئة CI)
  أو رفض صادق بلا عزل على غيرها — لا حالة ثالثة.
- RemoteWorkerBackend: بروتوكول حقيقي ضد عامل حقيقي — يُطلق العامل
  الفعلي (scripts/execution_worker.py) كعملية على منفذ اختباري، ثم
  فحوص إقلاع/كتابة/تنفيذ/التقاط عبر HTTP فعلي.
"""

from __future__ import annotations

import socket
import subprocess
import sys
import time
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO / "src"))

from execution.backends import (  # noqa: E402
    LocalLinuxBackend,
    RemoteWorkerBackend,
)


def _free_port() -> int:
    with socket.socket() as sock:
        sock.bind(("127.0.0.1", 0))
        return sock.getsockname()[1]


def test_local_backend_describes_platform_truthfully():
    backend = LocalLinuxBackend()
    profile = backend.describe()
    assert profile["backend"] == "LOCAL"
    assert profile["os"] and profile["architecture"]
    assert isinstance(profile["sandboxed"], bool)
    assert "network_policy" in profile and "resource_limits" in profile
    # §17: كل حقول عقد البيئة حاضرة
    for key in ("environment_id", "os", "architecture", "runtime",
                "workspace_root", "network_policy", "resource_limits",
                "capabilities"):
        assert key in profile, f"حقل عقد مفقود: {key}"


def test_local_backend_verify_real_or_honest_refusal():
    """التحقق: جاهز فعليًا أو رفض صادق — لا READY بلا فحوص (§28)."""
    backend = LocalLinuxBackend()
    result = backend.verify()
    assert result.status in ("READY", "NOT_READY", "UNAVAILABLE")
    if result.status == "READY":
        names = {check["name"] for check in result.checks}
        assert {"boot", "execute", "capture"} <= names
        assert all(check["ok"] for check in result.checks)
        assert result.profile.get("sandboxed") is True
    if result.status == "UNAVAILABLE":
        assert result.reason  # سبب معلن لا صمت


def test_local_backend_run_code_real_execution(tmp_path):
    """تنفيذ فعلي داخل الركيزة على Linux — أو رفض صادق مع سبب كامل."""
    backend = LocalLinuxBackend()
    available, _reason = backend.available()
    outcome = backend.run_code(
        "print('order010-inside')", workspace=tmp_path / "ws",
        artifacts=tmp_path / "art",
    )
    if available:
        assert outcome.ok
        assert "order010-inside" in outcome.stdout
        assert outcome.environment_id == backend.environment_id
    else:
        assert outcome.termination == "FAILED_TO_START"
        assert outcome.detail  # السبب الكامل لا رسالة خام


def test_local_backend_unsupported_platform_honest_reason(tmp_path, monkeypatch):
    """محاكاة منصة غير مدعومة: FAILED_TO_START بالسبب المعلن (§20)."""
    import substrate.local_substrate as ls

    monkeypatch.setattr(ls, "_SUPPORTED_ARCH", False)
    backend = LocalLinuxBackend()
    outcome = backend.run_code(
        "print('x')", workspace=tmp_path / "ws", artifacts=tmp_path / "art",
    )
    assert outcome.termination == "FAILED_TO_START"
    assert "الركيزة المعزولة" in outcome.detail or "Linux/x86_64" in outcome.detail
    assert "REMOTE_WORKER" in outcome.detail  # المسار الحقيقي معلن


class RealWorker:
    """عامل حقيقي كعملية — نفس ما يشغّله المالك على جهازه."""

    def __init__(self, token: str = "test-token-010"):
        self.port = _free_port()
        self.token = token
        self.process: subprocess.Popen | None = None

    def __enter__(self):
        self.process = subprocess.Popen(
            [sys.executable, str(REPO / "scripts" / "execution_worker.py"),
             "--port", str(self.port), "--host", "127.0.0.1",
             "--token", self.token],
            cwd=str(REPO), stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
        )
        deadline = time.time() + 20
        while time.time() < deadline:
            try:
                with socket.create_connection(("127.0.0.1", self.port), 0.4):
                    return self
            except OSError:
                if self.process.poll() is not None:
                    raise RuntimeError("العامل مات قبل الاستماع")
                time.sleep(0.15)
        raise RuntimeError("العامل لم يستمع خلال 20 ثانية")

    def __exit__(self, *args):
        if self.process and self.process.poll() is None:
            self.process.kill()
            self.process.wait(timeout=10)

    @property
    def url(self) -> str:
        return f"http://127.0.0.1:{self.port}"


@pytest.mark.timeout(90)
def test_remote_worker_protocol_real_over_http():
    """البروتوكول كاملًا ضد عامل حقيقي: توكن + قدرات + فحص + تنفيذ (§21)."""
    with RealWorker() as worker:
        good = RemoteWorkerBackend(worker.url, token=worker.token)
        # التوكن مطلوب: بقيمة خاطئة = خطأ معلن
        bad = RemoteWorkerBackend(worker.url, token="wrong")
        with pytest.raises(ConnectionError):
            bad.health()
        # الصحة والقدرات — وصف صادق من العامل نفسه
        health = good.health()
        assert health["ok"] is True
        caps = good.describe()
        assert caps["os"] and caps["architecture"] and caps["runtime"]
        assert isinstance(caps["sandboxed"], bool)
        assert caps["available"] is True
        # التحقق: سلم الجاهزية الكامل (011 §10) — درجات مسماة
        verify = good.verify()
        assert verify.status == "READY", verify.reason
        names = {c["name"] for c in verify.checks}
        assert names >= {
            "connectivity", "authentication", "heartbeat",
            "environment_probe", "workspace_probe", "execute_probe",
            "artifact_probe",
        }
        assert all(c["ok"] for c in verify.checks)
        # التنفيذ الفعلي عبر العامل + التقاط artifact
        # (013.17-R1 §8) وضعا العامل: الركيزة (‎/artifacts مطلق —
        # اصطلاحها المعلن) والمعلن (نسبي artifacts/) — الكود يكتب في
        # كليهما فينجح عقد الالتقاط أيا كان وضع المضيف، واصطلاح كل وضع
        # مغطى باختباراته المخصصة على مضيف ركيزة
        code = (
            "import pathlib\n"
            "for target in ('/artifacts/order010.txt',\n"
            "               'artifacts/order010.txt'):\n"
            "    try:\n"
            "        p = pathlib.Path(target)\n"
            "        p.parent.mkdir(parents=True, exist_ok=True)\n"
            "        p.write_text('remote-ok', encoding='utf-8')\n"
            "    except OSError:\n"
            "        pass\n"
            "print('remote-exec-ok')\n"
        )
        import tempfile

        with tempfile.TemporaryDirectory() as tmp:
            outcome = good.run_code(
                code, workspace=Path(tmp) / "ws",
                artifacts=Path(tmp) / "art", timeout_s=60,
            )
        assert outcome.ok, outcome.detail
        assert "remote-exec-ok" in outcome.stdout
        assert outcome.artifacts.get("order010.txt") == "remote-ok"
        assert outcome.backend == "REMOTE_WORKER"


@pytest.mark.timeout(60)
def test_remote_worker_unreachable_is_not_ready():
    """عامل غائب = NOT_READY بسبب معروف — لا جاهزية وهمية (§20)."""
    port = _free_port()  # لا أحد يستمع عليه
    backend = RemoteWorkerBackend(f"http://127.0.0.1:{port}")
    profile = backend.describe()
    assert profile["available"] is False
    assert profile["unavailable_reason"]
    verify = backend.verify()
    assert verify.status == "NOT_READY"
    assert verify.reason
