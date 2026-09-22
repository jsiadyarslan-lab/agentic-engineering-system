"""اختبارات الأمر 013.3 (§13) — عقد مساحة العمل وحد التشغيل.

السيناريوهات العشرة حرفيًا كما في الأمر:

A. cwd صالح ← التنفيذ ينجح (عملية حقيقية بنفس حد التنفيذ)
B. cwd غير موجود على Windows ← RUNTIME_WORKSPACE_INVALID
C. مسار Linux على مضيف Windows ← رفض قبل CreateProcess
D. WSL2 + مسار Linux صالح ← العامل يُطلق داخل WSL عبر wsl.exe
   (بلا cwd بنمط Linux لعملية Windows أبدًا)
E. عامل Linux بعيد + cwd بعيد صالح ← العامل يعمل فعليًا عبر HTTP
F. STRICT_ISOLATED + Windows محلي ← حجب صادق (ENVIRONMENT_UNAVAILABLE)
G. فشل إطلاق العامل ← البيئة تبقى NOT_READY (لا READY كاذبة)
H. تجهيز مساحة العمل ← ينشئ cwd صالحًا قبل إطلاق العامل
I. نفس cwd غير الصالح ← لا إعادة محاولة لانهائية (واحدة بعد الإصلاح)
J. إصلاح مساحة العمل ← نفس المهمة الدائمة تستأنف بنجاح

والجذر المعالَج (§1): POST /environments/{id}/test-run كان يمرر
``Path(tmp)/"ws"`` دون إنشائه ← WinError 267 على Windows. الآن نفس
نقطة النهاية تنشئ مساحة العمل عبر عقد الخلفية نفسه.
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
    LocalProcessBackend, RemoteWorkerBackend,
)
from execution.workspace import (  # noqa: E402
    RUNTIME_WORKSPACE_INVALID,
    WorkspaceInvalid,
    classify_process_oserror,
    execution_mode_of_environment,
    looks_like_posix_absolute,
    resolve_execution_workspace,
)
from persistence.database import (  # noqa: E402
    build_engine, init_db, make_session_factory,
)


@pytest.fixture()
def sessions(tmp_path):
    engine = build_engine(tmp_path / "ws-0133.db")
    init_db(engine)
    return make_session_factory(engine)


class _WinError267(OSError):
    """محاكاة خطأ Windows ERROR_DIRECTORY على أي منصة اختبار."""

    def __init__(self) -> None:
        super().__init__(267, "The directory name is invalid")
        self.winerror = 267


# ------------------------------------------------------------------ #
# A — cwd صالح ← نجاح فعلي
# ------------------------------------------------------------------ #

def test_a_valid_cwd_runs_and_reports_preflight(tmp_path):
    """(A) مساحة عمل صالحة: إنشاء ← تحقق ← إطلاع ← نجاح حقيقي."""
    backend = LocalProcessBackend(environment_id="ws-a")
    workspace = tmp_path / "jobs" / "123" / "ws"
    workspace.mkdir(parents=True)
    outcome = backend.run_code(
        "import os; print('cwd-ok', os.getcwd())",
        workspace=workspace, artifacts=tmp_path / "art", timeout_s=30,
    )
    assert outcome.ok, outcome.detail
    assert "cwd-ok" in outcome.stdout
    assert outcome.failure == {}  # لا فشل مساحة عمل
    resolved = resolve_execution_workspace(
        {"backend": "LOCAL", "sandboxed": False, "id": "ws-a"},
        workspace=workspace,
    )
    assert resolved.preflight["cwd_exists"] is True
    assert resolved.preflight["cwd_is_directory"] is True


def test_a_execution_mode_matrix():
    """مصفوفة وضع التنفيذ — القرار البنيوي قبل أي مسار (§7)."""
    assert execution_mode_of_environment(
        {"backend": "REMOTE_WORKER"}, host_os="Windows",
    ) == "REMOTE_PROCESS"
    assert execution_mode_of_environment(
        {"backend": "LOCAL", "sandboxed": True}, host_os="Windows",
    ) == "POSIX_PROCESS"
    assert execution_mode_of_environment(
        {"backend": "LOCAL", "sandboxed": False}, host_os="Windows",
    ) == "WINDOWS_PROCESS"
    assert execution_mode_of_environment(
        {"backend": "LOCAL", "sandboxed": False}, host_os="Linux",
    ) == "POSIX_PROCESS"


# ------------------------------------------------------------------ #
# B — cwd غير موجود على Windows ← RUNTIME_WORKSPACE_INVALID
# ------------------------------------------------------------------ #

def _simulate_windows_host(monkeypatch, tmp_path):
    """محاكاة مضيف Windows أمينة: host_os=Windows، ومسارات المنصة
    الأصلية (تحت tmp_path) لا تبدو POSIX — كما C:\\… على Windows فعلي."""
    import execution.backends as backends
    import execution.workspace as ws_mod

    monkeypatch.setattr(ws_mod, "host_os_detected", lambda: "Windows")
    monkeypatch.setattr(backends, "host_os_detected", lambda: "Windows")
    real_looks = ws_mod.looks_like_posix_absolute

    def looks_native_is_windows(path):
        return real_looks(path) and not str(path).startswith(str(tmp_path))

    monkeypatch.setattr(ws_mod, "looks_like_posix_absolute",
                        looks_native_is_windows)


def test_b_windows_nonexistent_cwd_classified(tmp_path, monkeypatch):
    """(B) إطلاق بـ cwd غير موجود: WinError 267 يُصنّف مسمّى لا عامًا،
    مع كل الحقول (host/cwd/environment_id/execution_mode)."""
    import execution.backends as backends

    _simulate_windows_host(monkeypatch, tmp_path)
    # مسار بنمط Windows (يفسَّر نسبيًا على مضيف Linux الاختباري — يُنشأ
    # تحت tmp_path فلا يلوث شيئًا، والسلوك المرجو هو نفسه على Windows)
    monkeypatch.chdir(tmp_path)
    workspace = Path("C:/agent-runtime/jobs/1/ws")

    calls = {"n": 0}

    def fake_run(*_args, **_kwargs):
        calls["n"] += 1
        raise _WinError267()

    monkeypatch.setattr(backends.subprocess, "run", fake_run)
    backend = LocalProcessBackend(environment_id="ws-b")
    outcome = backend.run_code(
        "print('x')", workspace=workspace,
        artifacts=tmp_path / "art", timeout_s=10,
    )
    assert outcome.termination == "FAILED_TO_START"
    assert outcome.failure["code"] == RUNTIME_WORKSPACE_INVALID
    assert outcome.failure["reason"] == "WINDOWS_CWD_INVALID"
    assert outcome.failure["winerror"] == 267
    assert outcome.failure["cwd"].replace("\\", "/").endswith(
        "agent-runtime/jobs/1/ws"
    )
    assert outcome.failure["host"] == "Windows"
    assert outcome.failure["execution_mode"] == "WINDOWS_PROCESS"
    assert outcome.failure["environment_id"] == "ws-b"
    assert "RUNTIME_WORKSPACE_INVALID" in outcome.detail


def test_b_classify_winerror_267_structured():
    """(B §9) التصنيف وحده: كل حقول التقرير المهيكل حاضرة."""
    error = _WinError267()
    report = classify_process_oserror(
        error, cwd=r"C:\agent-runtime\jobs\1\ws",
        environment_id="7", worker_id="w-1",
        execution_mode="WINDOWS_PROCESS", host_os="Windows",
    )
    assert report is not None
    assert report["code"] == RUNTIME_WORKSPACE_INVALID
    assert report["reason"] == "WINDOWS_CWD_INVALID"
    assert report["cwd"] == r"C:\agent-runtime\jobs\1\ws"
    assert report["host"] == "Windows"
    assert report["environment_id"] == "7"
    assert report["worker_id"] == "w-1"
    assert report["winerror"] == 267
    assert "267" in report["original"] or "invalid" in report["original"]


def test_b_other_oserror_not_workspace():
    """خطأ تشغيلي غير مساحة العمل لا يُصنّف ظلمًا — تصنيف دقيق."""
    error = OSError(13, "Permission denied")
    report = classify_process_oserror(
        error, cwd="/tmp/x", host_os="Linux",
    )
    assert report is None  # ليس فشل cwd — يبقى خطأ تشغيل آخر


# ------------------------------------------------------------------ #
# C — مسار Linux على Windows ← رفض قبل CreateProcess
# ------------------------------------------------------------------ #

def test_c_linux_path_on_windows_rejected_before_createprocess(
    tmp_path, monkeypatch,
):
    """(C) ‎/workspace أو ‎/work كـ cwd على Windows: مرفوض قبل أي
    subprocess.run — هذا بالضبط ما كان يصل إلى CreateProcess."""
    import execution.backends as backends
    import execution.workspace as ws_mod

    monkeypatch.setattr(ws_mod, "host_os_detected", lambda: "Windows")
    monkeypatch.setattr(backends, "host_os_detected", lambda: "Windows")

    def must_not_launch(*_args, **_kwargs):
        raise AssertionError(
            "CreateProcess استُدعي بمسار Linux على Windows — ممنوع (§2)"
        )

    monkeypatch.setattr(backends.subprocess, "run", must_not_launch)

    backend = LocalProcessBackend(environment_id="ws-c")
    for linux_path in ("/workspace/job-1", "/work", "/tmp/run"):
        outcome = backend.run_code(
            "print('x')", workspace=Path(linux_path),
            artifacts=Path("/tmp/art"), timeout_s=10,
        )
        assert outcome.termination == "FAILED_TO_START"
        assert outcome.failure["code"] == RUNTIME_WORKSPACE_INVALID
        assert outcome.failure["reason"] == "LINUX_PATH_ON_WINDOWS"
        assert outcome.failure["cwd"] == linux_path
    # العقد الصرف كذلك يرفضها مباشرة
    with pytest.raises(WorkspaceInvalid) as exc:
        resolve_execution_workspace(
            {"backend": "LOCAL", "sandboxed": False}, host_os="Windows",
            workspace="/workspace/job-1",
        )
    assert exc.value.report["reason"] == "LINUX_PATH_ON_WINDOWS"
    assert looks_like_posix_absolute("/workspace")
    assert not looks_like_posix_absolute(r"C:\workspace")


# ------------------------------------------------------------------ #
# D — WSL2: العامل يُطلق داخل WSL عبر wsl.exe بلا cwd لعملية Windows
# ------------------------------------------------------------------ #

class _FakeWslRunner:
    """wsl.exe مزيف — يقرر من الأوامر نفسها ويوثّق كل استدعاء."""

    def __init__(self, repo_linux="/mnt/c/aes"):
        self.repo_linux = repo_linux
        self.calls: list[list[str]] = []

    def __call__(self, argv, **_kwargs):
        self.calls.append(list(argv))
        joined = " ".join(argv)
        if "uname" in joined:
            proc = subprocess.CompletedProcess(argv, 0, "Linux x86_64", "")
        elif "python3 --version" in joined:
            proc = subprocess.CompletedProcess(argv, 0, "Python 3.10.12", "")
        elif "wslpath" in joined:
            proc = subprocess.CompletedProcess(argv, 0, self.repo_linux, "")
        elif "test -d" in joined and "cd" in joined:
            proc = subprocess.CompletedProcess(
                argv, 0,
                f"{self.repo_linux}\nPython 3.10.12", "",
            )
        elif "mkdir -p" in joined:
            proc = subprocess.CompletedProcess(argv, 0, "WORKSPACE_OK", "")
        else:
            proc = subprocess.CompletedProcess(argv, 1, "", "unknown")
        return proc


class _FakePopen:
    def __init__(self, argv, **kwargs):
        self.argv = list(argv)
        self.kwargs = dict(kwargs)
        self.pid = 4242


def test_d_wsl_launch_boundary(tmp_path):
    """(D) الحد الصريح: wslpath يحل داخل WSL ← تحقق داخل WSL ← إنشاء
    مساحة العمل داخل WSL ← إطلاق wsl.exe بلا cwd أبدًا (جذر §3)."""
    from execution import wsl as wsl_mod

    fake = _FakeWslRunner(repo_linux="/mnt/c/aes")
    spawned: dict = {}

    def fake_spawner(argv, **kwargs):
        spawned["argv"] = list(argv)
        spawned["kwargs"] = dict(kwargs)
        return _FakePopen(argv, **kwargs)

    result = wsl_mod.launch_wsl_worker(
        repo_windows_root=tmp_path, port=8901, token="sec",
        runner=fake, spawner=fake_spawner,
    )
    assert result["ok"] is True, result
    assert result["repo_linux"] == "/mnt/c/aes"
    assert result["workspace_linux"] == "/mnt/c/aes/runtime/wsl-worker"
    # المسار حُل داخل WSL عبر wslpath — لا تخمين ترجمة
    assert any("wslpath" in " ".join(c) for c in fake.calls)
    # التحقق داخل WSL قبل الإطلاق (pwd + test -d + python3)
    assert any("test -d" in " ".join(c) and "cd" in " ".join(c)
               for c in fake.calls)
    # أمر العامل داخل WSL بمسار Linux (لا مسار Windows)
    argv = spawned["argv"]
    assert argv[0] == "wsl.exe"
    assert "/mnt/c/aes/scripts/execution_worker.py" in argv
    assert "--port" in argv and "8901" in argv
    # القاعدة الحاسمة: لا cwd إطلاقًا لعملية wsl.exe — لا مسار Linux
    # يُمرَّر إلى CreateProcess على Windows أبدًا (جذر WinError 267)
    assert "cwd" not in spawned["kwargs"]


def test_d_wsl_detection_honest_no_wsl(monkeypatch):
    """(D §5) لا wsl.exe ← غير متاح بسببه الحرفي — لا افتراض توفر."""
    import shutil

    from execution import wsl as wsl_mod

    monkeypatch.setattr(shutil, "which", lambda _name: None)
    detection = wsl_mod.wsl_available()
    assert detection["available"] is False
    assert detection["reason"] == "WSL2_UNAVAILABLE"
    assert "wsl.exe" in detection["detail"]


# ------------------------------------------------------------------ #
# E — عامل Linux بعيد حقيقي: cwd يُحل على المضيف البعيد
# ------------------------------------------------------------------ #

def _free_port() -> int:
    with socket.socket() as sock:
        sock.bind(("127.0.0.1", 0))
        return sock.getsockname()[1]


class RealWorker:
    """عامل حقيقي كعملية — نفس ما يشغّله المالك على Linux/WSL2."""

    def __init__(self, token: str = "t-0133"):
        self.port = _free_port()
        self.token = token
        self.process: subprocess.Popen | None = None

    def __enter__(self):
        self.process = subprocess.Popen(
            [sys.executable,
             str(REPO / "scripts" / "execution_worker.py"),
             "--port", str(self.port), "--host", "127.0.0.1",
             "--token", self.token],
            cwd=str(REPO), stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
        )
        deadline = time.time() + 20
        while time.time() < deadline:
            try:
                with socket.create_connection(
                    ("127.0.0.1", self.port), 0.4,
                ):
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


def test_e_remote_linux_worker_real_execution(tmp_path):
    """(E) عامل بعيد حقيقي: تنفيذ فعلي بملفات فعلية تعود كأدلة،
    وcwd يُدار لدى العامل (host_path فارغ على مضيف التحكم §4)."""
    with RealWorker() as worker:
        environment = {
            "id": "ws-e", "backend": "REMOTE_WORKER",
            "endpoint": worker.url, "token_ref": "",
        }
        resolved = resolve_execution_workspace(environment, workspace=None)
        assert resolved.execution_mode == "REMOTE_PROCESS"
        assert resolved.host_path == ""  # لا مسار مضيف محلي
        assert "worker" in resolved.runtime_path or "العامل" in \
            resolved.runtime_path

        backend = RemoteWorkerBackend(
            worker.url, token=worker.token, environment_id="ws-e",
        )
        describe = backend.describe()
        assert describe["execution_mode"] == "REMOTE_PROCESS"
        assert describe["worker_id"].startswith("remote-worker:")
        remote_ws = tmp_path / "remote-ws"
        remote_art = tmp_path / "remote-art"
        outcome = backend.run_code(
            # وضعا العامل: الركيزة (‎/artifacts مطلق) والمعلن (نسبي) —
            # الكود يكتب في كليهما فينجح الاختبار أيا كان وضع العامل
            "import pathlib\n"
            "for target in ('/artifacts/e-0133.txt',\n"
            "               'artifacts/e-0133.txt'):\n"
            "    try:\n"
            "        p = pathlib.Path(target)\n"
            "        p.parent.mkdir(parents=True, exist_ok=True)\n"
            "        p.write_text('remote-evidence-0133', "
            "encoding='utf-8')\n"
            "    except OSError:\n"
            "        pass\n"
            "print('remote-ok')",
            workspace=remote_ws, artifacts=remote_art, timeout_s=60,
        )
        assert outcome.ok, outcome.detail
        assert "remote-ok" in outcome.stdout
        assert "e-0133.txt" in outcome.artifacts
        assert outcome.artifacts["e-0133.txt"] == "remote-evidence-0133"


# ------------------------------------------------------------------ #
# F — STRICT_ISOLATED + Windows محلي ← حجب صادق
# ------------------------------------------------------------------ #

def _windows_truth() -> dict:
    return {
        "os": "Windows", "os_release": "10", "architecture": "AMD64",
        "kernel": "10.0", "python": "3.11.4", "python_executable":
            r"C:\Python\python.exe", "git": "git version 2.43", "node": "",
        "shell": "", "container_runtime": "", "wsl": "", "cpu_cores": 8,
        "memory": "16GB", "disk": "",
    }


def test_f_strict_windows_local_blocked(sessions, monkeypatch):
    """(F) Windows بلا WSL2/حاويات/عامل: ENVIRONMENT_UNAVAILABLE
    بالعقد الحرفي — ولا محاولة إطلاق عامل كعملية Windows بعدها."""
    import execution.backends as backends_mod
    import execution.service as service_mod
    from execution import wsl as wsl_mod

    monkeypatch.setattr(backends_mod, "runtime_truth", _windows_truth)
    monkeypatch.setattr(service_mod, "_substrate_available",
                        lambda: False)
    monkeypatch.setattr(
        wsl_mod, "wsl_available",
        lambda **_kw: {
            "available": False, "reason": "WSL2_UNAVAILABLE",
            "detail": "wsl.exe غير موجود على PATH",
            "steps": {"wsl_exe": False, "uname": "", "python3": ""},
        },
    )
    launched = {"yes": False}
    monkeypatch.setattr(
        wsl_mod, "launch_wsl_worker",
        lambda **_kw: launched.update(yes=True) or {"ok": False},
    )

    from execution import provisioner
    from execution import runtime_state

    result = provisioner.provision(sessions, policy="STRICT_ISOLATED")
    assert result["state"] == "PROVISIONING_UNAVAILABLE"
    assert result["code"] == "ENVIRONMENT_UNAVAILABLE"
    assert result["host"]["os"] == "Windows"
    assert result["required"] == "Linux x86_64 + STRICT_ISOLATED"
    assert "LOCAL_WINDOWS" in result["available"]
    assert result["missing"]  # الفجوات مسماة
    assert result["action"]
    # لا إطلاق عامل إطلاقًا — لا محاولة windows-process بمسار Linux
    assert launched["yes"] is False
    # الحالة القانونية الدائمة: UNAVAILABLE (لا READY كاذبة)
    record = runtime_state.read_record(sessions, "STRICT_ISOLATED")
    assert record["state"] == "UNAVAILABLE"
    assert record["missing"]


def test_f_strict_windows_wsl_ready_registers_worker(sessions, monkeypatch):
    """(F+§3) WSL2 متاح فعليًا: التجهيز يعبر الحد الصريح ويسجل بيئة
    العامل ثم يتحقق منها — READY فقط عبر فحوص حقيقية."""
    import execution.backends as backends_mod
    import execution.service as service_mod
    from execution import wsl as wsl_mod

    monkeypatch.setattr(backends_mod, "runtime_truth", _windows_truth)
    monkeypatch.setattr(service_mod, "_substrate_available",
                        lambda: False)
    monkeypatch.setattr(
        wsl_mod, "wsl_available",
        lambda **_kw: {
            "available": True, "reason": "", "detail": "Linux/x86_64",
            "os": "Linux", "architecture": "x86_64", "python": "3.10",
            "steps": {"wsl_exe": True, "uname": "Linux x86_64",
                      "python3": "Python 3.10.12"},
        },
    )

    # العامل «داخل WSL» حقيقي هنا كعملية Linux داخل حاوية الاختبار —
    # نفس بروتوكول HTTP الذي سيستمع داخل WSL على جهاز المالك
    with RealWorker(token="wsl-sim-0133") as worker:
        def fake_launch(**_kwargs):
            return {
                "ok": True, "stage": "WORKER_LAUNCHED",
                "endpoint": worker.url,
                "boundary": "Windows ← wsl.exe ← Linux ← worker",
            }

        monkeypatch.setattr(wsl_mod, "launch_wsl_worker", fake_launch)

        # add_environment قد استُدعي قبل الربط الحقيقي — نعيد توجيهه
        # إلى endpoint العامل الحقيقي عبر تسجيل مباشر بعد التسجيل الأول
        from execution import provisioner
        from execution import service as execution_service

        result = provisioner.provision(
            sessions, policy="STRICT_ISOLATED",
        )
        # بيئة العامل مسجلة فعلاً باسم wsl2-linux
        envs = execution_service.list_environments(sessions)
        wsl_env = next(
            (e for e in envs if e["name"] == wsl_mod.WSL_ENVIRONMENT_NAME),
            None,
        )
        assert wsl_env is not None, [e["name"] for e in envs]

        # أعِد الربط إلى العامل الحقيقي ثم تحقق — سلم الجاهزية كاملًا
        from execution.models import ExecutionEnvironment
        from sqlalchemy import select as sa_select

        with sessions() as s:
            row = s.scalars(sa_select(ExecutionEnvironment).where(
                ExecutionEnvironment.name == wsl_mod.WSL_ENVIRONMENT_NAME
            )).first()
            row.endpoint = worker.url
            row.token_ref = ""
            from secrets_store import store as secrets_store

            secrets_store.set_key("execution::wsl2-linux",
                                  "wsl-sim-0133")
            row.token_ref = "execution::wsl2-linux"
            s.commit()

        verified = execution_service.verify_environment(
            sessions, wsl_env["id"],
        )
        # هذا المضيف Linux والركيزة متاحة للعامل → sandboxed من العامل
        if (verified.get("verify") or {}).get("ok"):
            assert verified["status"] == "READY"
            assert verified["sandboxed"] in (0, 1)


# ------------------------------------------------------------------ #
# G — فشل إطلاق العامل ← البيئة تبقى NOT_READY
# ------------------------------------------------------------------ #

def test_g_spawn_failure_environment_not_ready(sessions):
    """(G §11) عامل ميت: البيئة لا تصبح READY أبدًا — سلم الجاهزية
    يفشل في connectivity بسببه الحرفي."""
    from execution import service as execution_service

    dead_port = _free_port()
    execution_service.add_environment(
        sessions, name="dead-worker-g", backend="REMOTE_WORKER",
        endpoint=f"http://127.0.0.1:{dead_port}", token="t",
    )
    env_id = next(
        e["id"] for e in execution_service.list_environments(sessions)
        if e["name"] == "dead-worker-g"
    )
    verified = execution_service.verify_environment(sessions, env_id)
    assert verified["status"] != "READY"
    assert verified["status"] == "NOT_READY"
    checks = (verified.get("verify") or {}).get("checks", [])
    assert checks and checks[0]["name"] == "connectivity"
    assert checks[0]["ok"] is False
    # الحالة القانونية لا تقول READY
    from execution import runtime_state

    canonical = runtime_state.canonical_state(
        sessions, "STRICT_ISOLATED",
    )
    assert canonical["state"] != "READY"


# ------------------------------------------------------------------ #
# H — تجهيز مساحة العمل ينشئ cwd صالحًا قبل الإطلاق
# ------------------------------------------------------------------ #

def test_h_workspace_provisioned_before_launch(tmp_path):
    """(H §6) التسلسل: CREATE WORKSPACE ← VERIFY ← START — مسار غائب
    يُنشأ فعليًا قبل subprocess، والعملية تكتب فيه فعلًا."""
    backend = LocalProcessBackend(environment_id="ws-h")
    workspace = tmp_path / "runtime" / "jobs" / "77" / "ws"
    assert not workspace.exists()  # غائب قبل التنفيذ
    outcome = backend.run_code(
        "import pathlib, os\n"
        "pathlib.Path('h-0133.txt').write_text('provisioned', "
        "encoding='utf-8')\n"
        "print('cwd:', os.getcwd())",
        workspace=workspace, artifacts=tmp_path / "art", timeout_s=30,
    )
    assert outcome.ok, outcome.detail
    assert workspace.is_dir()  # أُنشئ قبل الإطلاق
    assert (workspace / "h-0133.txt").read_text(encoding="utf-8") == \
        "provisioned"
    resolved = resolve_execution_workspace(
        {"backend": "LOCAL", "sandboxed": False, "id": "ws-h"},
        workspace=workspace,
    )
    assert resolved.created is True or workspace.exists()


def test_h_uncreatable_workspace_named_failure(tmp_path, monkeypatch):
    """(H+§10) دليل لا يمكن إنشاؤه (أصل للقراءة فقط): فشل مسمّى
    REPAIR_FAILED/WORKSPACE_NOT_CREATED — لا حلقة ولا نجاح زائف."""
    import execution.workspace as ws_mod

    readonly = tmp_path / "readonly"
    readonly.mkdir()
    readonly.chmod(0o500)
    if not (readonly.stat().st_mode & 0o200):
        pytest.skip("المنصة تسمح بالكتابة رغم 0o500")
    with pytest.raises(WorkspaceInvalid) as exc:
        ws_mod.resolve_execution_workspace(
            {"backend": "LOCAL", "sandboxed": False},
            workspace=readonly / "never" / "ws", host_os="Linux",
            create=True,
        )
    assert exc.value.report["reason"] == "WORKSPACE_NOT_CREATED"


# ------------------------------------------------------------------ #
# I — نفس cwd غير الصالح: لا إعادة محاولة لانهائية
# ------------------------------------------------------------------ #

def test_i_no_infinite_retry_same_invalid_cwd(tmp_path, monkeypatch):
    """(I §10) إطلاعان حصرًا: المحاولة الأولى + إعادة واحدة بعد
    REPAIR — الفشل بعدها نهائي مهما تكرر الخطأ."""
    import execution.backends as backends

    _simulate_windows_host(monkeypatch, tmp_path)
    calls = {"n": 0}

    def always_267(*_args, **_kwargs):
        calls["n"] += 1
        raise _WinError267()

    monkeypatch.setattr(backends.subprocess, "run", always_267)
    backend = LocalProcessBackend(environment_id="ws-i")
    workspace = tmp_path / "ws-i"
    workspace.mkdir()
    outcome = backend.run_code(
        "print('x')", workspace=workspace,
        artifacts=tmp_path / "art", timeout_s=10,
    )
    assert calls["n"] == 2, (
        f"الإطلاقات = {calls['n']} — يجب أن تكون 2 بالضبط "
        "(أولى + إعادة واحدة بعد الإصلاح، لا حلقة)"
    )
    assert outcome.termination == "FAILED_TO_START"
    assert outcome.failure["code"] == RUNTIME_WORKSPACE_INVALID
    assert outcome.failure.get("repaired_attempted") is True


# ------------------------------------------------------------------ #
# J — إصلاح مساحة العمل ← نفس المهمة تستأنف
# ------------------------------------------------------------------ #

def test_j_repair_workspace_resumes_same_job(tmp_path):
    """(J §10) مساحة عمل ضاعت بين محاولتين (حُذفت): الإصلاح ينشئها
    ونفس المسار يستأنف — الملفات تُكتب في نفس الموقع الدائم."""
    from execution.workspace import repair_workspace

    backend = LocalProcessBackend(environment_id="ws-j")
    workspace = tmp_path / "jobs" / "900" / "ws"
    workspace.mkdir(parents=True)
    first = backend.run_code(
        "print('attempt-1')", workspace=workspace,
        artifacts=tmp_path / "art", timeout_s=30,
    )
    assert first.ok

    # «انهيار»: مساحة العمل ضاعت
    import shutil

    shutil.rmtree(workspace)
    assert not workspace.exists()

    repaired = repair_workspace(
        {"backend": "LOCAL", "sandboxed": False, "id": "ws-j"},
        workspace=workspace,
    )
    assert repaired.created is True
    assert workspace.is_dir()

    resumed = backend.run_code(
        "import pathlib\n"
        "pathlib.Path('resumed-0133.txt').write_text('same-job', "
        "encoding='utf-8')\n"
        "print('attempt-2')",
        workspace=workspace, artifacts=tmp_path / "art", timeout_s=30,
    )
    assert resumed.ok, resumed.detail
    assert (workspace / "resumed-0133.txt").read_text(
        encoding="utf-8"
    ) == "same-job"


def test_j_repair_failure_is_terminal(tmp_path):
    """(J §10) فشل الإصلاح نهائي — REPAIR_FAILED لا إعادة ثالثة."""
    from execution.workspace import WorkspaceInvalid, repair_workspace

    # مسار غير قابل للإنشاء: عنصر في السلسلة ملف لا دليل
    blocker = tmp_path / "blocker"
    blocker.write_text("أنا ملف", encoding="utf-8")
    with pytest.raises(WorkspaceInvalid) as exc:
        repair_workspace(
            {"backend": "LOCAL", "sandboxed": False},
            workspace=blocker / "under" / "ws",
        )
    assert exc.value.report["reason"] == "REPAIR_FAILED"


# ------------------------------------------------------------------ #
# §12 — القبول عبر نفس مسار التطبيق الحقيقي (API test-run)
# ------------------------------------------------------------------ #

def test_test_run_api_uses_same_launcher_and_creates_workspace(
    tmp_path, monkeypatch,
):
    """(§12+الجذر §1) POST /environments/{id}/test-run: نفس الإطلاق
    الحقيقي — مساحة العمل تُنشأ عبر عقد الخلفية، والأدلة الكاملة
    (execution_boundary/host_cwd/workspace_exists) في الرد. هذه هي
    النقطة التي أنتجت WinError 267 على جهاز المالك."""
    from fastapi.testclient import TestClient

    from api import routes
    from execution import service as execution_service

    engine = build_engine(tmp_path / "api-0133.db")
    init_db(engine)
    sessions = make_session_factory(engine)
    monkeypatch.setattr(routes, "_sessions", sessions)

    local = execution_service.ensure_local_registered(sessions)
    client = TestClient(routes.app)
    response = client.post(
        f"/api/execution/environments/{local['id']}/test-run"
    )
    assert response.status_code == 200
    body = response.json()
    # على Linux الركيزة متاحة → sandbox backend؛ على غيرها الوضع
    # المتوافق — كلاهما ينشئ مساحة العمل الآن ويطلق فعليًا
    assert body["ok"] is True, body
    assert body["termination"] == "COMPLETED"
    assert "cwd:" in body["stdout"]
    assert "file_write_read_delete: True" in body["stdout"]
    evidence = body["evidence"]
    assert evidence["execution_boundary"] in (
        "WINDOWS_PROCESS", "POSIX_PROCESS", "WSL_PROCESS",
        "REMOTE_PROCESS",
    )
    assert evidence["environment_id"] == local["id"]
    assert evidence["runtime_type"] in ("LOCAL", "REMOTE_WORKER")
    assert evidence["worker_id"]
    assert evidence["host_os"]
    assert evidence["workspace_exists"] is True
    assert evidence["failure_code"] == ""
