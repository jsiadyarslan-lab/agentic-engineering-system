# -*- coding: utf-8 -*-
"""الأمر 013.12 — إغلاق حدود الثقة قبل التجربة الحقيقية (D1+D2+D3).

المصدر: أمر 013.12 (حكم التحكيم على 013.11: ACCEPTED WITH CORRECTIVE
ADDENDUM REQUIRED). ثلاثة إصلاحات محددة:
  D1  هوية الدليل إلزامية تحت STRICT_ISOLATED (غائب/غير صالح/مختلف
      ← حجب صادق عبر البوابة الموحدة لا دوال منفردة).
  D2  اختبار العزل الحي للعامل البعيد (isolation_probe داخل الركيزة
      نفسها بتحدي جديد لكل تحقق — الغموض ليس نجاحًا).
  D3  صدق نتيجة التنفيذ (لا FAILURE_UNCODED في النجاح، بيانات العملية
      والإصلاح في حقليها المستقلين).

حد الاختبار الحي: مضيف Windows بلا ركيزة — العامل الحقيقي يُختبر هنا
في وضع subprocess المعلن (بروتوكول HTTP فعلي)، واختبار العزل داخل
ركيزة Linux حية يُسجل NOT RUN (§4 حرفيًا: لا يُوصف بأنه متحقق حيًا).
"""

import datetime as _dt
import json as _json
import sys
import threading
import uuid as _uuid
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "src"))

from execution import policy as execution_policy  # noqa: E402


def _now() -> _dt.datetime:
    return _dt.datetime.now(_dt.timezone.utc)


# ------------------------------------------------------------------ #
# بنية الاختبار — قاعدة معزولة (نمط 013.11 المعتمد)
# ------------------------------------------------------------------ #

@pytest.fixture()
def env_db(tmp_path, monkeypatch):
    from persistence.database import build_engine, init_db, make_session_factory
    from providers_registry import registry
    from execution import service as execution_service

    monkeypatch.chdir(tmp_path)
    engine = build_engine(tmp_path / "trust-01312.db")
    init_db(engine)
    sessions = make_session_factory(engine)
    registry.ensure_seeded(sessions)
    monkeypatch.setattr(execution_service, "_substrate_available",
                        lambda: False)
    return sessions


def _evidence(*, backend="REMOTE_WORKER", sandboxed=True, env_id=1,
              age_s=0.0, challenge_id=None, mutate=None, drop_time=False):
    verified_at = (
        (_now() - _dt.timedelta(seconds=age_s)).isoformat()
        if not drop_time else None
    )
    ev = execution_policy.valid_evidence(
        backend, sandboxed, environment_id=env_id,
        verified_at=verified_at, challenge_id=challenge_id,
    )
    if drop_time:
        ev.pop("last_verified_at")
    if mutate is not None:
        ev["checks"] = mutate(ev["checks"])
    return ev


def _seed(sessions, *, status="HEALTHY", sandboxed=True,
          backend="REMOTE_WORKER", evidence=None, name=None,
          make_default=True, port=9831, bind_identity=True):
    """بذر بيئة بتحكم كامل: الحالة/العزل/الأدلة (قاموس to_dict كامل).

    bind_identity=False للبذر بأدلة **بلا** ربط هوية — لعزل عيب الهوية
    قيد الاختبار حصرًا (D1): المسار الحقيقي (verify_environment) يحقن
    الهوية دائمًا عند الكتابة.
    """
    import sqlalchemy as sa

    from execution.models import ExecutionEnvironment

    label = name or f"seed-01312-{backend}-{sandboxed}"
    detail = dict(evidence) if evidence else execution_policy.valid_evidence(
        backend, sandboxed, environment_id=1)
    stored_at = detail.get("last_verified_at")
    if isinstance(stored_at, str) and stored_at:
        stored_at = _dt.datetime.fromisoformat(stored_at)
    with sessions() as s:
        row = ExecutionEnvironment(
            name=label, backend=backend,
            endpoint=(f"http://127.0.0.1:{port}" if backend == "REMOTE_WORKER"
                      else None),
            status=status, sandboxed=1 if sandboxed else 0,
            is_default=1 if make_default else 0,
            last_verified_at=stored_at,
            last_probe_detail=_json.dumps(detail, ensure_ascii=False),
        )
        s.add(row)
        s.flush()
        if bind_identity and isinstance(detail.get("profile"), dict):
            detail["profile"]["environment_id"] = row.id
            row.last_probe_detail = _json.dumps(detail, ensure_ascii=False)
        s.commit()
        return row.id


# ================================================================== #
# D1 — إلزامية هوية أدلة الجاهزية تحت STRICT (الحالات الست الإلزامية)
# ================================================================== #

def test_d1_matching_identity_allows_selection(env_db):
    """D1-أ: هوية صحيحة ومطابقة + بقية الأدلة كاملة → يُسمح بالاختيار."""
    from execution import service as execution_service

    evidence = _evidence(env_id=1)
    env_id = _seed(env_db, evidence=evidence, name="worker-match")
    env = execution_service.get_environment(env_db, env_id)
    verdict = execution_policy.readiness(env, "STRICT_ISOLATED")
    assert verdict["ready"] is True, verdict["blockers"]
    assert verdict["evidence"]["identity_ok"] is True
    selected = execution_service.select_environment(
        env_db, policy="STRICT_ISOLATED")
    assert selected is not None and selected["id"] == env_id


def test_d1_missing_identity_blocks_under_strict(env_db):
    """D1-ب: هوية غائبة ← حجب صادق بـ VERIFICATION_IDENTITY_MISSING."""
    from execution import service as execution_service

    evidence = _evidence(env_id=1)
    evidence["profile"].pop("environment_id")
    env_id = _seed(env_db, evidence=evidence, name="worker-noid", bind_identity=False)
    env = execution_service.get_environment(env_db, env_id)
    verdict = execution_policy.readiness(env, "STRICT_ISOLATED")
    assert verdict["ready"] is False
    assert any(b.startswith("VERIFICATION_IDENTITY_MISSING")
               for b in verdict["blockers"]), verdict["blockers"]
    # توافق COMPATIBLE موثق: نفس السجل بلا هوية لا يُحجب بسبب الهوية
    compat = execution_policy.readiness(env, "COMPATIBLE_LOCAL")
    assert compat["ready"] is True
    assert not any(b.startswith("VERIFICATION_IDENTITY")
                   for b in compat["blockers"])


def test_d1_unparseable_identity_blocks(env_db):
    """D1-ج: هوية غير صالحة/غير قابلة للتحليل ← حجب صادق."""
    from execution import service as execution_service

    evidence = _evidence(env_id=1)
    evidence["profile"]["environment_id"] = {"bad": "shape"}
    env_id = _seed(env_db, evidence=evidence, name="worker-badid", bind_identity=False)
    env = execution_service.get_environment(env_db, env_id)
    verdict = execution_policy.readiness(env, "STRICT_ISOLATED")
    assert verdict["ready"] is False
    assert any(b.startswith("VERIFICATION_IDENTITY")
               for b in verdict["blockers"]), verdict["blockers"]


def test_d1_foreign_identity_blocks(env_db):
    """D1-د: هوية تخص بيئة أخرى ← حجب صادق (فاسد تحت أي سياسة)."""
    from execution import service as execution_service

    evidence = _evidence(env_id=1)
    env_id = _seed(env_db, evidence=evidence, name="worker-thief")
    with env_db() as s:
        from execution.models import ExecutionEnvironment
        import sqlalchemy as sa
        row = s.scalars(sa.select(ExecutionEnvironment).where(
            ExecutionEnvironment.id == env_id)).one()
        detail = _json.loads(row.last_probe_detail)
        detail["profile"]["environment_id"] = env_id + 100  # بيئة أخرى
        row.last_probe_detail = _json.dumps(detail, ensure_ascii=False)
        s.commit()
    env = execution_service.get_environment(env_db, env_id)
    for policy_name in ("STRICT_ISOLATED", "COMPATIBLE_LOCAL"):
        verdict = execution_policy.readiness(env, policy_name)
        assert verdict["ready"] is False, (policy_name, verdict["blockers"])
        assert any(b.startswith("VERIFICATION_IDENTITY_MISMATCH")
                   for b in verdict["blockers"])
        assert verdict["evidence"]["identity_ok"] is False


def test_d1_evidence_of_a_cannot_provision_b(env_db):
    """D1-هـ: دليل البيئة A لا يمكن استخدامه لتجهيز البيئة B."""
    from execution import service as execution_service

    evidence_a = _evidence(env_id=1, challenge_id="challenge-of-A")
    id_a = _seed(env_db, evidence=evidence_a, name="worker-A",
                 make_default=False, port=9832)
    id_b = _seed(env_db, evidence=None, name="worker-B",  # بلا أدلة
                 make_default=False, port=9833)
    with env_db() as s:
        from execution.models import ExecutionEnvironment
        import sqlalchemy as sa
        row_a = s.get(ExecutionEnvironment, id_a)
        evidence_a = _json.loads(row_a.last_probe_detail)
        row_b = s.get(ExecutionEnvironment, id_b)
        # محاولة الاستعارة: انسخ أدلة A حرفيًا إلى صف B
        row_b.last_probe_detail = row_a.last_probe_detail
        row_b.last_verified_at = row_a.last_verified_at
        row_b.status = "HEALTHY"
        s.commit()
    env_b = execution_service.get_environment(env_db, id_b)
    verdict = execution_policy.readiness(env_b, "STRICT_ISOLATED")
    assert verdict["ready"] is False
    assert any(b.startswith("VERIFICATION_IDENTITY_MISMATCH")
               for b in verdict["blockers"]), verdict["blockers"]
    assert verdict["evidence"]["identity_ok"] is False
    # والاختيار لا يعيد B ولا A بأدلة B
    assert execution_service.select_environment(
        env_db, policy="STRICT_ISOLATED") is None or (
        execution_service.select_environment(
            env_db, policy="STRICT_ISOLATED")["id"] == id_a
    )


def test_d1_no_consumer_bypasses_identity_rejection(env_db):
    """D1-و: runtime-state وpreflight وresolve_executor لا يتجاوزون
    رفض الهوية — كلهم عبر البوابة الموحدة نفسها."""
    from execution import runtime_state
    from execution import service as execution_service
    from readiness import preflight

    evidence = _evidence(env_id=1)
    evidence["profile"].pop("environment_id")  # غياب الهوية
    _seed(env_db, evidence=evidence, name="worker-noid-gate", bind_identity=False)
    # 1) resolve_executor (مسار المنفذ الحقيقي): (بيئة, منفذ) = (None, None)
    environment, backend = execution_service.resolve_executor(
        env_db, policy="STRICT_ISOLATED")
    assert environment is None and backend is None
    # 2) runtime-state — الحجب حرفي الظهور عبر القناة القانونية
    canonical = runtime_state.canonical_state(env_db, "STRICT_ISOLATED")
    assert canonical["state"] != "READY", canonical
    assert "VERIFICATION_IDENTITY_MISSING" in _json.dumps(
        canonical, default=str), canonical
    # 3) preflight — محجوب (قدرة sandbox مشتقة من الأدلة نفسها)
    result = preflight.task_preflight(
        env_db, "مهمة تتطلب بيئة معزولة",
        run_probe_fn=_neutral_probe)
    assert result["verdict"] == "BLOCKED", result


def _neutral_probe(sessions, capability_id, **_kwargs):
    """مسبار سجلي محايد (نمط 013.11): القدرات غير البيئية جاهزة، وقدرة
    sandbox تُشتق من سجل البيئات عبر البوابة الموحدة نفسها (readiness
    تحت STRICT) كي ينعزل قياس هذه الحالات على المتغير قيد الاختبار."""
    from readiness import registry as readiness_registry
    from readiness.probes import ProbeResult

    if capability_id == "sandbox":
        from execution import service as execution_service

        ready = any(
            execution_policy.readiness(e, "STRICT_ISOLATED")["ready"]
            for e in execution_service.list_environments(sessions)
        )
        return readiness_registry.record_probe(
            sessions, capability_id,
            ProbeResult(
                status="READY" if ready else "NOT_READY",
                reason="مشتقة من سجل البيئات عبر البوابة الموحدة",
                checked_at=_now().isoformat(),
                details={"derived": True},
            ),
        )
    return readiness_registry.record_probe(
        sessions, capability_id,
        ProbeResult(status="READY", reason="محايد لهذا الاختبار",
                    checked_at=_now().isoformat()),
    )


# ================================================================== #
# D2 — اختبار العزل الحي للعامل البعيد (isolation_probe)
# ================================================================== #

class _StubWorkerHandler(BaseHTTPRequestHandler):
    """عامل HTTP حقيقي على منفذ سريع — عقد البروتوكول v1 + D2."""

    server_version = "stub-worker-01312/1.0"
    behavior: dict = {}

    def _send(self, status, payload):
        body = _json.dumps(payload, ensure_ascii=False).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def _authorized(self):
        token = self.behavior.get("token", "")
        if not token:
            return True
        return self.headers.get("Authorization", "") == f"Bearer {token}"

    def log_message(self, fmt, *args):  # noqa: A003
        pass

    def do_GET(self):  # noqa: N802
        if not self._authorized():
            self._send(401, {"error": "توكن غير صالح"})
            return
        if self.path == "/health":
            self._send(200, {"ok": True, "uptime_s": 5, "active_runs": 0,
                             "backend_mode": self.behavior.get(
                                 "mode", "subprocess")})
        elif self.path == "/capabilities":
            self._send(200, {
                "backend_id": "stub-worker/1.0", "os": "Linux",
                "architecture": "x86_64", "runtime": "python 3.11",
                "sandboxed": self.behavior.get("sandboxed", False),
                "worker_pid": 4242, "worker_id": "stub-worker:pid=4242",
                "isolation_probe": self.behavior.get(
                    "isolation_probe_advertised", "supported"),
            })
        else:
            self._send(404, {"error": f"مسار غير معروف: {self.path}"})

    def do_POST(self):  # noqa: N802
        if not self._authorized():
            self._send(401, {"error": "توكن غير صالح"})
            return
        length = int(self.headers.get("Content-Length") or 0)
        payload = _json.loads(self.rfile.read(length) or b"{}")
        if self.path == "/probe":
            self._send(200, {
                "ok": True, "backend_mode": self.behavior.get(
                    "mode", "subprocess"),
                "checks": [
                    {"name": "boot", "ok": True, "detail": "subprocess mode"},
                    {"name": "write+execute", "ok": True, "detail": "exit=0"},
                    {"name": "capture", "ok": True, "detail": "exec-ok"},
                ],
            })
        elif self.path == "/probe_isolation":
            challenge = str(payload.get("challenge_id") or "")
            mode = self.behavior.get("isolation", "blocked")
            now_iso = _now().isoformat()
            if mode == "missing":
                self._send(404, {"error": "مسار غير معروف: /probe_isolation"})
                return
            if mode == "stale":
                self._send(200, {
                    "ok": True, "verdict": "BLOCKED",
                    "challenge_id": "old-challenge-not-mine",
                    "worker_id": "stub-worker:pid=4242",
                    "verified_at": now_iso,
                    "detail": "نتيجة قديمة تعيد استخدامها",
                })
                return
            if mode == "aged":
                self._send(200, {
                    "ok": True, "verdict": "BLOCKED",
                    "challenge_id": challenge,
                    "worker_id": "stub-worker:pid=4242",
                    "verified_at": (
                        _now() - _dt.timedelta(seconds=600)).isoformat(),
                    "detail": "نتيجة قديمة الزمن",
                })
                return
            if mode == "future":
                self._send(200, {
                    "ok": True, "verdict": "BLOCKED",
                    "challenge_id": challenge,
                    "worker_id": "stub-worker:pid=4242",
                    "verified_at": (
                        _now() + _dt.timedelta(seconds=900)).isoformat(),
                    "detail": "زمن مستقبلي مزور",
                })
                return
            verdict = {
                "broken": "BROKEN",
                "inconclusive": "INCONCLUSIVE",
                "not_isolated": "NOT_ISOLATED_MODE",
                "blocked": "BLOCKED",
            }[mode]
            self._send(200, {
                "ok": verdict == "BLOCKED",
                "verdict": verdict,
                "challenge_id": challenge,
                "worker_id": "stub-worker:pid=4242",
                "verified_at": now_iso,
                "target": f"127.0.0.1:{self.server.server_address[1]}",
                "detail": f"stub verdict {verdict}",
            })
        else:
            self._send(404, {"error": f"مسار غير معروف: {self.path}"})


@pytest.fixture()
def stub_worker():
    """عامل HTTP حقيقي على منفذ عابر — سلوك قابل للضبط لكل حالة."""
    made = {}

    def make(**behavior):
        _StubWorkerHandler.behavior = behavior
        server = ThreadingHTTPServer(("127.0.0.1", 0), _StubWorkerHandler)
        thread = threading.Thread(target=server.serve_forever, daemon=True)
        thread.start()
        port = server.server_address[1]
        made["server"] = server
        made["port"] = port
        return f"http://127.0.0.1:{port}"

    yield make
    server = made.get("server")
    if server is not None:
        server.shutdown()
        server.server_close()


def _verify_worker(endpoint, *, token="", env_id=1):
    from execution.backends import RemoteWorkerBackend

    backend = RemoteWorkerBackend(
        environment_id=str(env_id), endpoint=endpoint, token=token)
    return backend.verify()


def test_d2_isolated_worker_with_live_probe_is_valid(env_db, stub_worker):
    """D2-1: عامل بالركيزة يجتاز اختبار العزل الحي ← دليل صالح للعزل."""
    endpoint = stub_worker(sandboxed=True, isolation="blocked")
    result = _verify_worker(endpoint)
    names = [c["name"] for c in result.checks]
    assert "isolation_probe" in names, names
    probe_check = [c for c in result.checks
                   if c["name"] == "isolation_probe"][0]
    assert probe_check["ok"] is True, probe_check
    assert result.ok is True and result.status == "READY"
    # والأدلة تمنح الجاهزية الصارمة عبر البوابة الموحدة
    evidence = result.to_dict()
    evidence["last_verified_at"] = _now().isoformat()
    env_id = _seed(env_db, evidence=evidence, name="worker-live-probe")
    from execution import service as execution_service
    env = execution_service.get_environment(env_db, env_id)
    verdict = execution_policy.readiness(env, "STRICT_ISOLATED")
    assert verdict["ready"] is True, verdict["blockers"]
    assert verdict["evidence"]["isolation_proof"] is True


def test_d2_subprocess_worker_declared_not_isolated(env_db, stub_worker):
    """D2-2: عامل subprocess يعلن عدم العزل ← لا يكتسب أهلية STRICT."""
    endpoint = stub_worker(sandboxed=False, isolation="not_isolated")
    result = _verify_worker(endpoint)
    names = [c["name"] for c in result.checks]
    assert "isolation_probe" not in names, names  # عقد المتوافق: 7 فحوص
    assert len(names) == 7
    assert result.ok is True  # صادق في وضعه المتوافق
    # لكنه بلا عزل: STRICT لا تمنحه أهلية أصلًا
    env = {"id": 1, "name": "worker-sub", "backend": "REMOTE_WORKER",
           "status": "HEALTHY", "sandboxed": False,
           "last_verified_at": _now().isoformat(),
           "last_probe_detail": result.to_dict()}
    verdict = execution_policy.readiness(env, "STRICT_ISOLATED")
    assert verdict["eligible"] is False
    assert verdict["ready"] is False


def test_d2_sandboxed_claim_without_probe_rejected(env_db, stub_worker):
    """D2-3: يدّعي sandboxed=True دون فحص العزل المطلوب ← مرفوض."""
    # (أ) عامل بروتوكول قديم: /probe_isolation 404
    endpoint = stub_worker(sandboxed=True, isolation="missing")
    result = _verify_worker(endpoint)
    probe_check = [c for c in result.checks
                   if c["name"] == "isolation_probe"]
    assert probe_check and probe_check[0]["ok"] is False
    assert result.ok is False and result.status == "NOT_READY"
    # (ب) أدلة مزروعة بلا فحص المسبار إطلاقًا ← لا STRICT عبر البوابة
    evidence = _evidence(env_id=1)
    evidence["checks"] = [c for c in evidence["checks"]
                          if c["name"] != "isolation_probe"]
    env = {"id": 1, "name": "worker-claim", "backend": "REMOTE_WORKER",
           "status": "HEALTHY", "sandboxed": True,
           "last_verified_at": _now().isoformat(),
           "last_probe_detail": evidence}
    verdict = execution_policy.readiness(env, "STRICT_ISOLATED")
    assert verdict["ready"] is False
    assert any(b.startswith("VERIFICATION_REQUIRED_MISSING")
               for b in verdict["blockers"])
    assert any(b.startswith("VERIFICATION_ISOLATION_PROOF_MISSING")
               for b in verdict["blockers"])


def test_d2_stale_or_unbound_challenge_rejected():
    """D2-4: فحص عزل قديم أو غير مرتبط بالتحدي الجاري ← مرفوض."""
    from execution.backends import validate_isolation_probe_response

    fresh = {"ok": True, "verdict": "BLOCKED", "worker_id": "w:1",
             "verified_at": _now().isoformat()}
    # تحدٍّ آخر (نتيجة قديمة يُعاد استخدامها)
    ok, detail = validate_isolation_probe_response(
        {**fresh, "challenge_id": "not-my-challenge"},
        challenge_id="current-challenge")
    assert ok is False and "تحدي" in detail
    # بلا تحدي أصلًا
    ok, detail = validate_isolation_probe_response(
        {**fresh}, challenge_id="current-challenge")
    assert ok is False
    # نتيجة قديمة الزمن (مربوطة بالتحدي لكن عمرها تجاوز)
    ok, detail = validate_isolation_probe_response(
        {**fresh, "challenge_id": "current-challenge",
         "verified_at": (_now() - _dt.timedelta(seconds=600)).isoformat()},
        challenge_id="current-challenge")
    assert ok is False and "قديمة" in detail
    # زمن مستقبلي مزور
    ok, detail = validate_isolation_probe_response(
        {**fresh, "challenge_id": "current-challenge",
         "verified_at": (_now() + _dt.timedelta(seconds=900)).isoformat()},
        challenge_id="current-challenge")
    assert ok is False and "مستقبلي" in detail
    # زمن غير قابل للتحليل
    ok, detail = validate_isolation_probe_response(
        {**fresh, "challenge_id": "current-challenge",
         "verified_at": "not-a-timestamp"},
        challenge_id="current-challenge")
    assert ok is False
    # بلا هوية عامل
    ok, detail = validate_isolation_probe_response(
        {"ok": True, "verdict": "BLOCKED",
         "challenge_id": "current-challenge",
         "verified_at": _now().isoformat()},
        challenge_id="current-challenge")
    assert ok is False and "هوية" in detail
    # والسليم يُقبل: تحدٍّ مطابق + زمن حاضر + BLOCKED
    ok, detail = validate_isolation_probe_response(
        {**fresh, "challenge_id": "current-challenge"},
        challenge_id="current-challenge")
    assert ok is True


def test_d2_probe_fail_or_inconclusive_never_ready(env_db, stub_worker):
    """D2-5: فشل منع الشبكة (BROKEN) أو عدم الحسم (INCONCLUSIVE) ← لا READY."""
    for mode, expected_fragment in (("broken", "BROKEN"),
                                    ("inconclusive", "INCONCLUSIVE")):
        endpoint = stub_worker(sandboxed=True, isolation=mode)
        result = _verify_worker(endpoint)
        probe_check = [c for c in result.checks
                       if c["name"] == "isolation_probe"][0]
        assert probe_check["ok"] is False, (mode, probe_check)
        assert expected_fragment in probe_check["detail"]
        assert result.ok is False and result.status == "NOT_READY"
        # وعبر البوابة: لا جاهزية صارمة حتى لو توهم أحدهم الإعلان
        evidence = result.to_dict()
        evidence["last_verified_at"] = _now().isoformat()
        env = {"id": 1, "name": f"worker-{mode}", "backend": "REMOTE_WORKER",
               "status": "HEALTHY", "sandboxed": True,
               "last_verified_at": evidence["last_verified_at"],
               "last_probe_detail": evidence}
        verdict = execution_policy.readiness(env, "STRICT_ISOLATED")
        assert verdict["ready"] is False, mode


def test_d2_connectivity_or_auth_failure_never_ready(stub_worker):
    """D2-6: فشل اتصال العامل أو رفض المصادقة ← لا READY."""
    # اتصال: لا عامل على المنفذ إطلاقًا
    result = _verify_worker("http://127.0.0.1:9871")
    assert result.ok is False
    assert result.checks[0]["name"] == "connectivity"
    assert result.checks[0]["ok"] is False
    # مصادقة: توكن مرفوض 401
    endpoint = stub_worker(sandboxed=True, isolation="blocked", token="s3cret")
    result = _verify_worker(endpoint, token="wrong-token")
    by_name = {c["name"]: c for c in result.checks}
    assert by_name["authentication"]["ok"] is False
    assert result.ok is False and result.status == "NOT_READY"


def test_d2_probe_failure_keeps_mission_gate_closed(env_db, stub_worker):
    """D2-7: نجاح بقية الفحوص مع فشل فحص العزل ← بوابة المهمة مغلقة."""
    from execution import service as execution_service
    from readiness import preflight

    endpoint = stub_worker(sandboxed=True, isolation="inconclusive")
    result = _verify_worker(endpoint)
    evidence = result.to_dict()
    evidence["last_verified_at"] = _now().isoformat()
    # بقية السلم ناجحة فعلًا (7 فحوص صحيحة) والمسبار وحده فاشل
    non_probe = [c for c in result.checks if c["name"] != "isolation_probe"]
    assert all(c["ok"] for c in non_probe)
    _seed(env_db, evidence=evidence, name="worker-gate-closed")
    environment, backend = execution_service.resolve_executor(
        env_db, policy="STRICT_ISOLATED")
    assert environment is None and backend is None, "بوابة المهمة لا تُفتح"
    pf = preflight.task_preflight(
        env_db, "مهمة تتطلب بيئة معزولة",
        run_probe_fn=_neutral_probe)
    assert pf["verdict"] == "BLOCKED", pf


def test_d2_real_worker_script_refuses_isolation_claim_in_subprocess_mode():
    """D2-8 (بروتوكول حقيقي): سكربت العامل الفعلي في وضع subprocess المعلن
    يرفض أي ادعاء عزل — NOT_ISOLATED_MODE ليس نجاحًا.

    هذا اختبار مسار المنتج على HTTP فعلي مع السكربت الحقيقي (لا stub)
    — يثبت صدق الرفض؛ اختبار الركيزة الحية يتطلب Linux ويُسجل NOT RUN.
    """
    import socket
    import subprocess
    import time as _time
    import urllib.request

    worker_script = (
        Path(__file__).resolve().parents[2] / "scripts" / "execution_worker.py"
    )
    with socket.socket() as probe_sock:
        probe_sock.bind(("127.0.0.1", 0))
        port = probe_sock.getsockname()[1]
    process = subprocess.Popen(
        [sys.executable, str(worker_script),
         "--port", str(port), "--host", "127.0.0.1",
         "--token", "test-token-01312"],
        stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
    )
    try:
        base = f"http://127.0.0.1:{port}"
        ready = False
        deadline = _time.monotonic() + 20
        while _time.monotonic() < deadline and not ready:
            try:
                req = urllib.request.Request(
                    f"{base}/health",
                    headers={"Authorization": "Bearer test-token-01312"})
                with urllib.request.urlopen(req, timeout=2) as resp:
                    ready = _json.loads(resp.read()).get("ok") is True
            except OSError:
                _time.sleep(0.2)
        assert ready, "العامل الحقيقي لم يقبل الاتصال"
        req = urllib.request.Request(
            f"{base}/probe_isolation", method="POST",
            data=_json.dumps({"challenge_id": _uuid.uuid4().hex}).encode(),
            headers={"Authorization": "Bearer test-token-01312",
                     "Content-Type": "application/json"})
        with urllib.request.urlopen(req, timeout=30) as resp:
            payload = _json.loads(resp.read())
        # الرفض الصادق: العامل بلا عزل لا يصادر نتيجة عزل
        assert payload["verdict"] == "NOT_ISOLATED_MODE", payload
        assert payload["ok"] is False
        assert payload["challenge_id"]  # التحدي وُثق في الرد
        assert payload["worker_id"]
        assert payload["verified_at"]
    finally:
        process.terminate()
        try:
            process.wait(timeout=10)
        except subprocess.TimeoutExpired:
            process.kill()


# ================================================================== #
# (013.15) الاختباران الحيّان على Linux/ركيزة — كانا placeholder
# يفشل بعناد على Linux حتى يتوفر مضيف ركيزة حقيقي (دلالة 013.12 §4).
# توفر المضيف الآن فعليًا، فصار الجسد برهانًا حيًا كاملًا: عامل حقيقي
# في وضع الركيزة على قناة 127.0.0.1 محمية، توكن يولَّد وقت التشغيل
# (لا نص حرفي في Git أبدًا). يبقى skipif(not linux) كما هو (على
# Windows: NOT RUN صادق)، وعلى Linux بلا ركيزة: skip صادق معلن —
# أبدًا لا يتحول SKIP إلى PASS.
# ================================================================== #

import contextlib  # noqa: E402 — قسم 013.15 الحي


def _substrate_ok_on_this_host() -> bool:
    """هل ركيزة Linux الحقيقية متاحة فعلًا هنا؟ قياس لا افتراض."""
    repo = Path(__file__).resolve().parents[2]
    sys.path.insert(0, str(repo / "src"))
    try:
        from substrate.local_substrate import default_local_images
        return bool(default_local_images())
    except Exception:  # noqa: BLE001
        return False


def _worker_call(method, base, auth, path, payload=None):
    import urllib.request  # noqa: E402 — قسم 013.15 الحي
    data = _json.dumps(payload).encode() if payload is not None else None
    headers = dict(auth)
    if data is not None:
        headers["Content-Type"] = "application/json"
    req = urllib.request.Request(
        base + path, data=data, headers=headers, method=method)
    with urllib.request.urlopen(req, timeout=90) as resp:
        return _json.loads(resp.read())


@contextlib.contextmanager
def _live_worker():
    """يطلق العامل الحقيقي (سكربت المصدر نفسه) في وضع الركيزة على
    قناة 127.0.0.1 محمية؛ التوكن يولَّد وقت التشغيل ولا يُطبع ولا
    يُكتب في أي ملف أبدًا."""
    import secrets as _secrets  # noqa: E402 — قسم 013.15 الحي
    import socket as _socket
    import subprocess as _subprocess
    import time as _time_mod
    repo = Path(__file__).resolve().parents[2]
    with _socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        port = s.getsockname()[1]
    token = _secrets.token_urlsafe(24)
    proc = _subprocess.Popen(
        [sys.executable, str(repo / "scripts" / "execution_worker.py"),
         "--port", str(port), "--host", "127.0.0.1", "--token", token],
        cwd=str(repo), stdout=_subprocess.DEVNULL,
        stderr=_subprocess.DEVNULL,
    )
    base = f"http://127.0.0.1:{port}"
    auth = {"Authorization": f"Bearer {token}"}
    try:
        deadline = _time_mod.monotonic() + 25
        ready = False
        while _time_mod.monotonic() < deadline and not ready:
            try:
                ready = _worker_call(
                    "GET", base, auth, "/health").get("ok") is True
            except OSError:
                _time_mod.sleep(0.2)
        assert ready, "العامل الحي لم يقبل الاتصال خلال 25ث"
        yield base, auth
    finally:
        proc.terminate()
        try:
            proc.wait(timeout=10)
        except _subprocess.TimeoutExpired:
            proc.kill()
            proc.wait(timeout=5)


@pytest.mark.skipif(
    not sys.platform.startswith("linux"),
    reason="اختبار العزل الحي يتطلب ركيزة Linux (substrate) — "
           "المضيف الحالي Windows: يُسجل NOT RUN ولا يُوصف بأنه متحقق حيًا "
           "(013.12 §4 حرفيًا).",
)
def test_d2_live_substrate_isolation_probe_on_linux():
    """D2-ح (حي — 013.15): العامل الحقيقي على Linux/ركيزة يجتاز المسبار
    الحي: منع شبكة مؤكد من داخل الركيزة (verdict=BLOCKED بتحدٍ متكرر)
    مع بقاء قناة التحكم المصرح بها متاحة خارجها.

    وهو أيضًا اختبار الانحدار لعيب 013.15: قالب المسبار كان يستقبل
    الهدف سلسلة "host:port" بدل زُبع (host, port) فينفجر داخل
    الركيزة بـ ValueError ويرجع INCONCLUSIVE (الدليل:
    docs/evidence/order01315/worker_probe_bug_baseline_622be149.json).
    يُشغل على مضيف ركيزة عند توفره فقط."""
    if not _substrate_ok_on_this_host():
        pytest.skip("NOT RUN — لا ركيزة على هذا المضيف (لا محاكاة)")
    with _live_worker() as (base, auth):
        health = _worker_call("GET", base, auth, "/health")
        assert health["backend_mode"] == "substrate", health
        caps = _worker_call("GET", base, auth, "/capabilities")
        assert caps["sandboxed"] is True, caps
        assert caps["isolation"] == "linux-namespaces+seccomp", caps
        challenge = _uuid.uuid4().hex
        iso = _worker_call(
            "POST", base, auth, "/probe_isolation",
            {"challenge_id": challenge})
        assert iso["ok"] is True, iso
        assert iso["verdict"] == "BLOCKED", iso
        assert iso["challenge_id"] == challenge, iso
        assert iso["challenge_echoed"] is True, iso
        # قناة التحكم المصرح بها متاحة خارج العزل
        assert iso["control_proof"]["ok"] is True, iso
        assert iso["probe_errno"], iso
        assert iso["worker_id"] and iso["verified_at"], iso


# ================================================================== #
# D3 — صدق نتيجة التنفيذ (لا FAILURE_UNCODED في النجاح)
# ================================================================== #

def test_d3_success_has_no_fake_failure_and_keeps_process_info(tmp_path):
    """D3-1: نجاح التنفيذ المحلي المتوافق ← لا حقل فشل مضلل ولا
    FAILURE_UNCODED — ومعلومات العملية في حقلها المستقل."""
    from execution.backends import LocalProcessBackend

    workspace = tmp_path / "ws"
    workspace.mkdir()
    artifacts = tmp_path / "art"
    artifacts.mkdir()
    backend = LocalProcessBackend(environment_id="d3-success")
    outcome = backend.run_code(
        "print('d3-ok')", workspace=workspace, artifacts=artifacts,
        timeout_s=30,
    )
    assert outcome.ok is True
    assert outcome.termination == "COMPLETED" and outcome.exit_code == 0
    assert outcome.failure == {}, "لا قاموس فشل في نتيجة ناجحة"
    assert "FAILURE_UNCODED" not in outcome.detail
    assert "FAILURE_UNCODED" not in outcome.stderr
    # معلومات العملية محفوظة في موضعها الصحيح — لا تمحيها
    assert isinstance(outcome.process_info.get("pid"), int)
    assert outcome.repair == {}


def test_d3_launch_failure_without_code_gets_fallback_and_keeps_cause(
        monkeypatch):
    """D3-2: فشل إطلاع بلا failure.code ← رمز بديل صريح مع السبب الأصلي،
    وبلا بيانات عملية في فشل لم يُطلق أصلًا."""
    import execution.backends as backends_mod
    import execution.workspace as workspace_mod
    from execution.backends import FAILURE_CODE_FALLBACK, LocalProcessBackend

    def hostile_classify(error, *, cwd, **_kw):
        return {"cwd": cwd}  # تقرير معيب: بلا code ولا reason ولا host

    def hostile_popen(*_args, **_kwargs):
        raise FileNotFoundError(2, "No such file or directory", "/gone/ws")

    monkeypatch.setattr(
        workspace_mod, "classify_process_oserror", hostile_classify)
    monkeypatch.setattr(backends_mod.subprocess, "Popen", hostile_popen)

    backend = LocalProcessBackend(environment_id="d3-fallback")
    gone = Path("/gone/ws")  # Windows يطبّعه — القارنة من نفس Path
    exit_code, _stdout, stderr, detail, failure_report, process = (
        backend._run("print('x')", [], workspace=gone, timeout_s=5.0)
    )
    assert exit_code == -1 and detail == "startup"
    assert "FAILED_TO_START" in stderr
    assert "No such file or directory" in stderr, "السبب الخام ظاهر"
    assert FAILURE_CODE_FALLBACK in stderr, "رمز بديل معلن بدل انهيار"
    assert failure_report == {"cwd": str(gone)}, "التقرير الأصلي سليم"
    assert process == {}, "لا بيانات عملية لفشل لم يُطلق أصلًا"


def test_d3_success_after_repair_keeps_repair_out_of_failure(
        tmp_path, monkeypatch):
    """D3-3: نجاح مع إعادة إصلاح مساحة العمل ← بيانات الإصلاح محفوظة
    مصنفة إصلاحًا لا فشلًا (حقل repair المستقل)."""
    import execution.workspace as workspace_mod
    from execution.backends import LocalProcessBackend

    workspace = tmp_path / "ws"
    workspace.mkdir()
    artifacts = tmp_path / "art"
    artifacts.mkdir()

    backend = LocalProcessBackend(environment_id="d3-repair")
    calls = {"n": 0}
    real_run = backend._run

    def flaky_run(code, args, *, workspace, timeout_s):
        calls["n"] += 1
        if calls["n"] == 1:
            # أول إطلاق: فشل cwd يصنف تقرير مساحة عمل (عقد الستية D3)
            return (-1, "", "FAILED_TO_START: WinError 267", "startup",
                    {"code": "RUNTIME_WORKSPACE_INVALID",
                     "reason": "WINDOWS_CWD_INVALID", "cwd": str(workspace),
                     "host": "Windows",
                     "execution_mode": "WINDOWS_PROCESS"},
                    {})
        return real_run(code, args, workspace=workspace, timeout_s=timeout_s)

    monkeypatch.setattr(backend, "_run", flaky_run)
    monkeypatch.setattr(
        workspace_mod, "repair_workspace",
        lambda *a, **k: type("R", (), {
            "host_path": str(workspace),
            "preflight": {"repaired": True, "cwd_exists": True},
        })(),
    )
    outcome = backend.run_code(
        "print('repaired-ok')", workspace=workspace, artifacts=artifacts,
        timeout_s=30,
    )
    assert calls["n"] == 2, "أولى + إعادة واحدة (لا حلقة)"
    assert outcome.ok is True
    assert outcome.termination == "COMPLETED" and outcome.exit_code == 0
    # الإصلاح موثق في حقل الإصلاح — والفشل فارغ في النجاح
    assert outcome.repair.get("attempted") is True
    assert outcome.failure == {}, "لا فشل مصطنع بعد نجاح الإصلاح"
    assert "FAILURE_UNCODED" not in outcome.detail
    assert "REPAIR_WORKSPACE" in outcome.detail, "أثر الإصلاح ظاهر"
    assert isinstance(outcome.process_info.get("pid"), int)


@pytest.mark.skipif(
    not sys.platform.startswith("linux"),
    reason="تنفيذ معزول حي يتطلب ركيزة Linux — المضيف Windows: "
           "NOT RUN (يُغطى عقد الركيزة باختباراتها الخاصة على مضيف ركيزة).",
)
def test_d3_isolated_success_contract_on_linux():
    """D3-4 (حي — 013.15): عقد نتيجة ناجحة معزولة عبر /run في وضع
    الركيزة: نجاح حقيقي يُبلَّغ نجاحًا — مخرجات فعلية وartifacts حقيقية
    مقروءة، لا حقول فشل مضللة ولا FAILURE_UNCODED، والسجل نفسه يصرّح
    sandboxed=true من الوضع الفعلي لا من قيمة ثابتة.
    يُشغل على مضيف ركيزة عند توفره فقط."""
    if not _substrate_ok_on_this_host():
        pytest.skip("NOT RUN — لا ركيزة على هذا المضيف (لا محاكاة)")
    import base64 as _b64
    with _live_worker() as (base, auth):
        caps = _worker_call("GET", base, auth, "/capabilities")
        assert caps["sandboxed"] is True, caps
        assert caps["isolation"] == "linux-namespaces+seccomp", caps
        code = (
            "import pathlib, sys\n"
            "p = pathlib.Path('/artifacts/d3-success.txt')\n"
            "p.write_text('d3-ok', encoding='utf-8')\n"
            "print('D3_MARKER:', p.read_text(encoding='utf-8'))\n"
            "print('PY:', sys.version_info[:3])\n"
        )
        run = _worker_call(
            "POST", base, auth, "/run",
            {"run_id": "d3-live-" + _uuid.uuid4().hex[:8],
             "code": code, "timeout_s": 60})
        assert run["sandboxed"] is True, run
        assert run["exit_code"] == 0, run
        assert run["termination"] == "COMPLETED", run
        assert "D3_MARKER: d3-ok" in run["stdout"], run
        assert "PY:" in run["stdout"], run
        assert "FAILURE_UNCODED" not in run["stderr"], run
        assert "FAILURE_UNCODED" not in str(run.get("detail", "")), run
        arts = {a["name"]: a for a in run.get("artifacts", [])}
        assert "d3-success.txt" in arts, sorted(arts)
        assert _b64.b64decode(
            arts["d3-success.txt"]["b64"]).decode("utf-8") == "d3-ok"
        assert isinstance(run["duration_ms"], int) and run["duration_ms"] >= 0
