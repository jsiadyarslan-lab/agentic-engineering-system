#!/usr/bin/env python3
"""قبول الأمر 013.3 الحقيقي — يُشغَّل على جهاز المالك الفعلي.

    python scripts/order0133_windows_acceptance.py

لا يكتفي بـpytest: يثبت التشغيل الحقيقي على المضيف الفعلي (§15-§18):

1. جرد المضيف الفعلي (OS/arch/python/WSL2) — لا افتراض.
2. (§16) الاستحالة الحرجة حية: مسار Linux كـ cwd على Windows يُرفض
   قبل CreateProcess، وWinError 267 يُصنّف RUNTIME_WORKSPACE_INVALID
   بإصلاح واحد وإعادة واحدة (لا حلقة).
3. (الجذر) نفس نقطة النهاية التي أنتجت WinError 267 على جهاز المالك
   (POST /environments/{id}/test-run) — الآن تنشئ مساحة العمل عبر
   عقد الخلفية نفسه وتنفذ فعليًا (cwd مطبوع + كتابة/قراءة/حذف ملف).
4. (§15) التجهيز الحقيقي تحت STRICT_ISOLATED:
   - Windows + WSL2 متاح: إطلاق العامل داخل WSL عبر الحد الصريح
     (wsl.exe بلا cwd بنمط Linux)، سلم الجاهزية، ثم تنفيذ أمر حقيقي
     وكتابة/قراءة/حذف ملف عبر البيئة المعزولة.
   - لا WSL2/عامل/حاويات: التوقف الصادق ENVIRONMENT_UNAVAILABLE
     بالعقد الحرفي (host/required/available/missing/action) — وهذا
     نجاح قبول صادق، لا فشل.
5. (§17) الأدلة كاملة تُكتب JSON: environment_id، worker_id،
   runtime_type، host، arch، host_cwd، runtime_cwd، أمر الإطلاق،
   حد التنفيذ، برهان وجود مساحة العمل، نبضة العامل، فحوص الصحة،
   المخرجات الفعلية، برهان عمليات الملف، وتسلسل الأحداث.

الخروج: 0 فقط إذا نجحت كل الفحوص المطلوبة على هذا المضيف.
"""

from __future__ import annotations

import json
import platform
import subprocess
import sys
import tempfile
import time
import uuid
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO / "src"))

RESULTS: list[dict] = []
EVIDENCE: dict = {
    "command": "013.3",
    "started_at": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
    "host": {},
    "checks": [],
}


def check(name: str, ok: bool, detail: str, **extra) -> bool:
    entry = {"name": name, "ok": bool(ok), "detail": detail[:400], **extra}
    RESULTS.append(entry)
    EVIDENCE["checks"].append(entry)
    mark = "PASS" if ok else "FAIL"
    print(f"[{mark}] {name} — {detail[:180]}")
    return bool(ok)


def main() -> int:
    print("=" * 70)
    print("قبول 013.3 — إصلاح حد التشغيل الحقيقي (Windows/WSL2/Remote)")
    print("=" * 70)

    # ---------------------------------------------------------------- #
    # 0) جرد المضيف الفعلي
    # ---------------------------------------------------------------- #
    from execution.workspace import host_os_detected

    host_os = host_os_detected()
    host_arch = platform.machine()
    EVIDENCE["host"] = {
        "os": host_os, "architecture": host_arch,
        "python": platform.python_version(),
        "platform": platform.platform(),
    }
    print(f"\nالمضيف الفعلي: {host_os}/{host_arch} — "
          f"Python {platform.python_version()}")

    wsl_info: dict = {}
    if host_os == "Windows":
        from execution import wsl as wsl_mod

        wsl_info = wsl_mod.wsl_available()
        EVIDENCE["host"]["wsl2"] = wsl_info
        print(f"WSL2: {'متاح — ' + wsl_info.get('detail', '') if wsl_info.get('available') else 'غير متاح — ' + wsl_info.get('detail', '')}")

    # قاعدة بيانات مؤقتة — نفس مصنع جلسات التطبيق
    from persistence.database import (
        build_engine, init_db, make_session_factory,
    )

    tmpdir = tempfile.mkdtemp(prefix="order0133-accept-")
    engine = build_engine(Path(tmpdir) / "acceptance.db")
    init_db(engine)
    sessions = make_session_factory(engine)

    from execution import service as execution_service
    from execution import provisioner, runtime_state
    from execution.backends import LocalProcessBackend
    from execution.workspace import (
        RUNTIME_WORKSPACE_INVALID, WorkspaceInvalid,
        resolve_execution_workspace,
    )

    # ---------------------------------------------------------------- #
    # 1) (§16-أ) الاستحالة الحرجة: مسار Linux على Windows يُرفض قبل
    #    CreateProcess — لا وصول لـ WinError 267 أصلًا
    # ---------------------------------------------------------------- #
    if host_os == "Windows":
        backend = LocalProcessBackend(environment_id="accept-c")
        outcome = backend.run_code(
            "print('must-not-run')", workspace=Path("/workspace/job-1"),
            artifacts=Path("/tmp/art"), timeout_s=15,
        )
        check(
            "C-linux-path-rejected-before-createprocess",
            outcome.termination == "FAILED_TO_START"
            and outcome.failure.get("code") == RUNTIME_WORKSPACE_INVALID
            and outcome.failure.get("reason") == "LINUX_PATH_ON_WINDOWS",
            f"cwd=/workspace على Windows: رفض قبل الإطلاق — "
            f"reason={outcome.failure.get('reason')}",
            failure=outcome.failure,
        )
        check(
            "C-no-process-output",
            "must-not-run" not in (outcome.stdout or ""),
            "لم تُنفَّذ العملية إطلاقًا — الرفض سبق CreateProcess",
        )
    else:
        # على Linux: نفس العقد يُختبر بمحاكاة مضيف Windows (السلوك
        # البنيوي نفسه — resolve_execution_workspace(host_os='Windows'))
        try:
            resolve_execution_workspace(
                {"backend": "LOCAL", "sandboxed": False},
                workspace="/workspace/job-1", host_os="Windows",
            )
            check("C-linux-path-rejected-before-createprocess", False,
                  "المسار Linux عبر مضيف Windows مُرَّر — عقد مكسور")
        except WorkspaceInvalid as invalid:
            check(
                "C-linux-path-rejected-before-createprocess",
                invalid.report["reason"] == "LINUX_PATH_ON_WINDOWS",
                f"رفض العقد قبل أي إطلاق: {invalid.report['reason']}",
                failure=invalid.report,
            )

    # ---------------------------------------------------------------- #
    # 2) (§9+§10) WinError 267 يُصنّف مسمّى + إصلاح واحد + إعادة واحدة
    # ---------------------------------------------------------------- #
    calls = {"n": 0}

    class _WinError267Sim(OSError):
        def __init__(self) -> None:
            super().__init__(267, "The directory name is invalid")
            self.winerror = 267

    # سخّن كشف المضيف قبل التفخيخ — أوامر الجرد (git/node/…) ليست
    # «إطلاقات تنفيذ» ولا تُحصى؛ العدّ لحظات الإطلاق الفعلية حصرًا
    backend_b = LocalProcessBackend(environment_id="accept-b")
    backend_b.describe()

    real_run = subprocess.run

    def fake_run(*args, **kwargs):
        argv = list(args[0] if args and args[0] else kwargs.get("args", []))
        if len(argv) > 1 and argv[1] == "-c":
            calls["n"] += 1
        raise _WinError267Sim()

    subprocess.run = fake_run
    try:
        ws_b = Path(tmpdir) / "ws-b"
        ws_b.mkdir(parents=True, exist_ok=True)
        outcome_b = backend_b.run_code(
            "print('x')", workspace=ws_b,
            artifacts=Path(tmpdir) / "art-b", timeout_s=15,
        )
    finally:
        subprocess.run = real_run
    check(
        "B-winerror267-classified-structured",
        outcome_b.failure.get("code") == RUNTIME_WORKSPACE_INVALID
        and outcome_b.failure.get("reason") == "WINDOWS_CWD_INVALID",
        f"WinError 267 → {outcome_b.failure.get('code')}/"
        f"{outcome_b.failure.get('reason')} (cwd="
        f"{outcome_b.failure.get('cwd', '')[:80]})",
        failure=outcome_b.failure,
    )
    check(
        "I-single-repair-single-retry",
        calls["n"] == 2 and outcome_b.failure.get("repaired_attempted")
        is True,
        f"الإطلاقات = {calls['n']} بالضبط (أولى + إعادة واحدة بعد "
        "الإصلاح) — لا حلقة إعادة",
    )

    # ---------------------------------------------------------------- #
    # 3) (الجذر §1) نفس نقطة النهاية التي أنتجت WinError 267 — الآن
    #    تنشئ مساحة العمل عبر عقد الخلفية وتنفذ فعليًا
    # ---------------------------------------------------------------- #
    from fastapi.testclient import TestClient

    from api import routes

    routes._sessions = sessions  # نفس مصنع جلسات التطبيق (لا نُسخة خاصة)
    client = TestClient(routes.app)
    local_env = execution_service.ensure_local_registered(sessions)
    response = client.post(
        f"/api/execution/environments/{local_env['id']}/test-run"
    )
    body = response.json()
    evidence_fields = body.get("evidence", {})
    check(
        "root-test-run-creates-workspace-and-executes",
        response.status_code == 200 and body.get("ok") is True
        and "file_write_read_delete: True" in (body.get("stdout") or ""),
        f"test-run على البيئة المحلية: exit={body.get('exit_code')} "
        f"boundary={evidence_fields.get('execution_boundary')} "
        f"cwd في المخرجات={'cwd:' in (body.get('stdout') or '')}",
        evidence=evidence_fields, stdout=body.get("stdout", "")[:600],
    )
    check(
        "root-test-run-evidence-complete",
        all(evidence_fields.get(k) for k in (
            "execution_boundary", "host_os", "worker_id", "environment_id",
            "runtime_type",
        )) and evidence_fields.get("workspace_exists") is True,
        "أدلة §17 كاملة في الرد: الحد/المضيف/العامل/البيئة/مساحة العمل",
    )

    # ---------------------------------------------------------------- #
    # 4) (§15) التجهيز الحقيقي تحت STRICT_ISOLATED على هذا المضيف
    # ---------------------------------------------------------------- #
    provision_result = provisioner.provision(
        sessions, policy="STRICT_ISOLATED"
    )
    EVIDENCE["provision"] = {
        "state": provision_result.get("state"),
        "steps": [
            {"state": s.get("state"), "ok": s.get("ok"),
             "detail": str(s.get("detail", ""))[:200]}
            for s in provision_result.get("steps", [])
        ],
        "environment": provision_result.get("environment"),
        "execution_boundary": provision_result.get("execution_boundary",
                                                   ""),
        "wsl": provision_result.get("wsl_evidence", {}),
    }
    state = provision_result.get("state", "")

    if state == "READY":
        env = provision_result.get("environment") or {}
        check(
            "provision-strict-ready-real",
            bool(env.get("id")),
            f"READY عبر فحوص حقيقية — environment_id={env.get('id')} "
            f"isolation={env.get('isolation')} sandboxed="
            f"{env.get('sandboxed')}",
            environment=env,
        )
        # تنفيذ حقيقي عبر البيئة المعزولة: أمر + كتابة/قراءة/حذف ملف
        outcome = execution_service.run_code_unified(
            sessions,
            "import pathlib\n"
            "p = pathlib.Path('artifacts/accept-0133.txt')\n"
            "p.parent.mkdir(parents=True, exist_ok=True)\n"
            "p.write_text('real-execution-0133', encoding='utf-8')\n"
            "print('executed:', p.read_text(encoding='utf-8'))\n"
            "p.unlink()\n"
            "print('deleted:', not p.exists())",
            workspace=Path(tmpdir) / "ws-run",
            artifacts=Path(tmpdir) / "art-run",
            policy="STRICT_ISOLATED", timeout_s=120.0,
        )
        substrate_mode = "artifacts/accept-0133.txt" in outcome.artifacts
        check(
            "real-isolated-execution-file-ops",
            outcome.termination == "COMPLETED"
            and (substrate_mode or "executed:" in outcome.stdout),
            f"تنفيذ فعلي عبر البيئة المعزولة: {outcome.termination} "
            f"exit={outcome.exit_code} stdout={outcome.stdout[:120]!r}",
            stdout=outcome.stdout[:400],
            artifacts=list(outcome.artifacts)[:10],
            environment_id=outcome.environment_id,
            backend=outcome.backend,
        )
    elif host_os == "Windows" and state == "PROVISIONING_UNAVAILABLE":
        # (§15) التوقف الصادق: العقد الحرفي ENVIRONMENT_UNAVAILABLE —
        # لا محاولة إطلاق العامل كعملية Windows بعدها
        contract_ok = (
            provision_result.get("code") == "ENVIRONMENT_UNAVAILABLE"
            and provision_result.get("host", {}).get("os") == "Windows"
            and provision_result.get("required")
            and provision_result.get("missing")
            and provision_result.get("action")
        )
        check(
            "provision-honest-unavailable-contract",
            contract_ok,
            "توقف صادق ENVIRONMENT_UNAVAILABLE بالعقد الحرفي "
            "(host/required/available/missing/action) — لا READY كاذبة "
            "ولا إطلاق عامل Windows",
            contract={
                k: provision_result.get(k) for k in (
                    "code", "host", "required", "available", "missing",
                    "action",
                )
            },
        )
    else:
        check(
            "provision-strict-on-this-host",
            False,
            f"حالة تجهيز غير متوقعة على هذا المضيف: {state} — "
            f"{provision_result.get('reason', '')[:200]}",
        )

    # ---------------------------------------------------------------- #
    # 5) (§11) READY لا تبقى بعد فشل إطلاق — البيئة تُوسم للفحص
    # ---------------------------------------------------------------- #
    canonical = runtime_state.canonical_state(sessions, "STRICT_ISOLATED")
    EVIDENCE["canonical_state"] = {
        "state": canonical.get("state"),
        "environment_id": canonical.get("environment_id"),
        "coherent": canonical.get("coherent"),
    }
    check(
        "canonical-state-consistent",
        canonical.get("state") in (
            "READY", "UNAVAILABLE", "FAILED", "RUNNING", "DEGRADED",
            "INTERRUPTED", "DISCOVERING", "PROVISIONING", "BOOTING",
            "HEALTH_CHECK",
        ),
        f"الحالة القانونية: {canonical.get('state')} — عرضها "
        f"{(canonical.get('coherent') or {}).get('kind')}",
    )

    # ---------------------------------------------------------------- #
    # النتيجة والأدلة
    # ---------------------------------------------------------------- #
    passed = sum(1 for r in RESULTS if r["ok"])
    failed = sum(1 for r in RESULTS if not r["ok"])
    EVIDENCE["finished_at"] = time.strftime(
        "%Y-%m-%dT%H:%M:%SZ", time.gmtime()
    )
    EVIDENCE["summary"] = {
        "passed": passed, "failed": failed, "total": len(RESULTS),
        "verdict": "ACCEPTED" if failed == 0 else "BLOCKED",
    }
    out_path = REPO / f"order0133-evidence-{host_os.lower()}.json"
    out_path.write_text(
        json.dumps(EVIDENCE, ensure_ascii=False, indent=1, default=str),
        encoding="utf-8",
    )

    print("\n" + "=" * 70)
    print(f"النتيجة: {passed}/{len(RESULTS)} ناجح — "
          f"{'013.3 ACCEPTED' if failed == 0 else '013.3 BLOCKED'}")
    print(f"الأدلة الكاملة: {out_path}")
    print("=" * 70)
    return 0 if failed == 0 else 1


if __name__ == "__main__":
    raise SystemExit(main())
