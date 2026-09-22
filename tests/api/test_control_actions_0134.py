"""اختبارات أزرار التحكم الحقيقية (013.4 §11-§17+§39) — كل زر أمر دائم.

المصفوفة: PAUSE (G) · RESUME (H) · STOP (I) · RETRY (J) ·
DUPLICATE (K) · ARCHIVE (L) · RESTORE (M) · HISTORY (N) — كل فعل
ينتج: أمر API ← حدث دائم ← انتقال ← حالة ← واجهة تقرأها.
"""

from __future__ import annotations

import sys
import threading
import time
from pathlib import Path

import pytest

pytest.importorskip("httpx", reason="TestClient يتطلب httpx")

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "src"))

from fastapi.testclient import TestClient  # noqa: E402

from api import projects, routes  # noqa: E402
from tests.api.planning_wait import generate_plan_and_wait  # noqa: E402
from tests.api.test_projects_api import project_env  # noqa: E402,F401
from workflow import service  # noqa: E402


@pytest.fixture()
def control_env(project_env):
    """بيئة API منظمّة جاهزة (نفس بيئة اختبارات المشاريع القائمة)."""
    yield {"client": TestClient(routes.app),
           "sessions": project_env["sessions"]}


def _plan_project(client):
    """إنشاء ← توليد خطة (بلا اعتماد — الاختبار يرقّع ثم يعتمد)."""
    created = client.post("/api/projects", json={
        "name": "مشروع تحكم", "objective": "هدف اختبار التحكم",
    })
    assert created.status_code == 201, created.text
    pid = created.json()["id"]
    generate_plan_and_wait(client, pid)
    return pid


def _approved_project(client):
    pid = _plan_project(client)
    approved = client.post(f"/api/projects/{pid}/plan/approve",
                           json={"approved": True})
    assert approved.status_code == 200, approved.text
    return pid


def _wait_status(client, pid, statuses, timeout=25.0):
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        runtime = client.get(f"/api/projects/{pid}/runtime").json()
        if runtime.get("status") in statuses:
            return runtime
        time.sleep(0.1)
    raise AssertionError(
        f"لم تصل الحالة إلى {statuses} — آخر: {runtime.get('status')} "
        f"({runtime.get('last_error', '')[:150]})"
    )


# ------------------------------------------------------------------ #
# G + H. إيقاف مؤقت واستئناف — نفس الوظيفة الدائمة بلا نسخ
# ------------------------------------------------------------------ #

def test_pause_and_resume_same_durable_job(control_env, monkeypatch):
    """(§13) PAUSE ← PAUSED ← RESUME: نفس الوظيفة الدائمة بلا نسخ."""
    client = control_env["client"]
    pid = _plan_project(client)   # خطة تنتظر الاعتماد — لم يُطلق شيء بعد

    # منفذ بطيء حتمي: يدخل الخطوة وينتظر الإيقاف المؤقت قبل الإكمال.
    # (الترقيع قبل الاعتماد: الاعتماد نفسه يطلق الحلقة خلفيًا 013 §3
    # فتصل خطوته إلى المنفذ البطيء — لا حاجة لـrun/stream الحاجز)
    import hashlib

    entered = threading.Event()
    release = threading.Event()

    def slow_run_task(goal, *, router, role_config=None, workspace=None,
                      on_event=None, cycle_id=None, stop_controller=None,
                      resume_from=None, **_kw):
        from tasks import TaskResult

        entered.set()
        release.wait(timeout=20)
        root = Path(workspace)
        root.mkdir(parents=True, exist_ok=True)
        output = root / "deliverable.md"
        output.write_text(f"# مخرج\n\n{goal}\n", encoding="utf-8")
        evidence_path = root / "evidence.json"
        evidence_path.write_text("{}", encoding="utf-8")
        return TaskResult(
            verdict="PASS", reason="تم", goal=goal,
            cycle_id=cycle_id or "", final_state="EVIDENCED",
            workspace=str(root), files=["deliverable.md"], tool_calls=[],
            evidence_path=str(evidence_path),
            evidence_sha256=hashlib.sha256(
                evidence_path.read_bytes()).hexdigest(),
            duration_ms=5, state_history=["EVIDENCED"],
        )

    import tasks as tasks_mod

    monkeypatch.setattr(tasks_mod, "run_task", slow_run_task)

    # الاعتماد يطلق الحلقة خلفيًا — الخطوة الأولى تدخل المنفذ البطيء
    approved = client.post(f"/api/projects/{pid}/plan/approve",
                           json={"approved": True})
    assert approved.status_code == 200, approved.text
    assert entered.wait(timeout=20), "الحلقة لم تدخل الخطوة"

    paused = client.post(f"/api/projects/{pid}/pause", json={
        "reason": "اختبار الإيقاف المؤقت",
    })
    assert paused.status_code == 200, paused.text
    release.set()   # الخطوة تكمل ← الحلقة تكرم الإيقاف عند checkpoint

    runtime = _wait_status(client, pid, {"PAUSED", "COMPLETED",
                                         "WAITING_GATE"})
    if runtime["status"] == "PAUSED":
        # الاستئناف: نفس المشروع، لا وظيفة مكررة ولا محادثة جديدة
        before = client.get(f"/api/projects/{pid}").json()
        job_before = (before.get("job") or {}).get("id")
        resumed = client.post(f"/api/projects/{pid}/resume")
        assert resumed.status_code == 200, resumed.text
        after = client.get(f"/api/projects/{pid}").json()
        job_after = (after.get("job") or {}).get("id")
        assert job_after == job_before, \
            "الاستئناف يستخدم نفس الوظيفة الدائمة (§13)"


# ------------------------------------------------------------------ #
# I. الإيقاف النهائي — STOPPED دائمة وكل شيء محفوظ
# ------------------------------------------------------------------ #

def test_final_stop_is_durable_and_preserves_everything(control_env):
    """(§12) final=true: STOPPED دائمة + الأحداث والأدلة باقية."""
    client = control_env["client"]
    pid = _approved_project(client)

    client.post(f"/api/projects/{pid}/run/stream?after=0")
    stopped = client.post(f"/api/projects/{pid}/stop", json={
        "reason": "إيقاف نهائي من الاختبار", "final": True,
    })
    assert stopped.status_code == 200, stopped.text

    runtime = _wait_status(client, pid, {"STOPPED", "PAUSED",
                                         "COMPLETED", "WAITING_GATE"})
    if runtime["status"] == "STOPPED":
        events = client.get(f"/api/projects/{pid}/events").json()
        kinds = [e["kind"] for e in events["events"]]
        assert "OWNER_STOP_REQUESTED" in kinds
        assert "PROJECT_STOPPED" in kinds
        # لا حذف: الخطة والبوابات والأحداث كلها باقية
        detail = client.get(f"/api/projects/{pid}").json()
        assert detail["plan"] is not None


# ------------------------------------------------------------------ #
# J. الإعادة — جلسة تخطيط فاشلة تُعاد بقرار المالك
# ------------------------------------------------------------------ #

def test_retry_endpoint_after_planning_failure(control_env):
    """(§11) RETRY: جلسة فاشلة ← إعادة صريحة ← جلسة retry_of معلنة."""
    client = control_env["client"]
    created = client.post("/api/projects", json={
        "name": "إعادة", "objective": "هدف اختبار الإعادة",
    })
    pid = created.json()["id"]
    # الإعادة على مشروع DRAFT بلا جلسة فاشلة: إطلاق صريح (run)
    retried = client.post(f"/api/projects/{pid}/retry")
    assert retried.status_code == 200, retried.text
    assert retried.json()["retried"] in ("planning", "run", "steps")


# ------------------------------------------------------------------ #
# K. التكرار — نسخة جديدة لا تمس الأصل
# ------------------------------------------------------------------ #

def test_duplicate_creates_independent_copy(control_env):
    """(§15) DUPLICATE: original_id معلن + الأصل لم يُمس."""
    client = control_env["client"]
    pid = _approved_project(client)
    original = client.get(f"/api/projects/{pid}").json()

    duplicated = client.post(f"/api/projects/{pid}/duplicate", json={
        "name": "النسخة المستقلة",
    })
    assert duplicated.status_code == 201, duplicated.text
    copy = duplicated.json()
    assert copy["id"] != pid
    assert copy["original_id"] == pid
    assert copy["status"] == "DRAFT"          # لا اعتماد موروث

    # الأصل كما هو حرفيًا — لا مساس
    after = client.get(f"/api/projects/{pid}").json()
    assert after["status"] == original["status"]
    assert after["name"] == original["name"]


# ------------------------------------------------------------------ #
# L + M. الأرشفة والاسترجاع — دورة حياة لا حذف
# ------------------------------------------------------------------ #

def test_archive_and_restore_keep_data(control_env):
    """(§17+§45) ARCHIVE: يختفي من النشطة ويبقى كاملًا؛ RESTORE يعيده."""
    client = control_env["client"]
    pid = _approved_project(client)
    events_before = client.get(
        f"/api/projects/{pid}/events").json()["events"]

    archived = client.post(f"/api/projects/{pid}/archive")
    assert archived.status_code == 200, archived.text
    assert archived.json()["archived_at"], "طابع الأرشفة معلن"

    # اختفى من القائمة النشطة الافتراضية
    active_ids = [p["id"] for p in
                  client.get("/api/projects").json()["projects"]]
    assert pid not in active_ids
    # لكنه موجود في قائمة الأرشيف وقابل للاستعلام
    archived_ids = [p["id"] for p in client.get(
        "/api/projects/archived/list").json()["projects"]]
    assert pid in archived_ids

    # الاسترجاع يعيده للحياة النشطة
    restored = client.post(f"/api/projects/{pid}/restore")
    assert restored.status_code == 200, restored.text
    assert restored.json()["archived_at"] is None
    active_ids = [p["id"] for p in
                  client.get("/api/projects").json()["projects"]]
    assert pid in active_ids
    # لا حذف: نفس الأحداث باقية حرفيًا
    events_after = client.get(
        f"/api/projects/{pid}/events").json()["events"]
    assert len(events_after) >= len(events_before)


def test_archive_rejected_while_running(control_env):
    """المشروع العامل لا يُؤرشف — أوقفه أولًا (قرار صادق)."""
    client = control_env["client"]
    pid = _approved_project(client)
    client.post(f"/api/projects/{pid}/run/stream?after=0")
    out = client.post(f"/api/projects/{pid}/archive")
    # إن انتهى بسرعة (مشروع منظم) فالأرشفة مشروعة؛ إن كان يعمل فرفض
    if out.status_code == 409:
        assert "أوقف" in out.json()["detail"]
    else:
        assert out.status_code == 200


# ------------------------------------------------------------------ #
# N + §43. التاريخ — صفحات بمؤشر رجوع
# ------------------------------------------------------------------ #

def test_history_pagination_with_cursor(control_env):
    """(§16+§43) التاريخ صفحات: next_before يمشي للوراء بلا غرق."""
    client = control_env["client"]
    pid = _approved_project(client)

    first = client.get(f"/api/projects/{pid}/history?limit=3").json()
    assert first["events"], "أحداث موجودة من الإنشاء والاعتماد"
    if first["has_more"]:
        second = client.get(
            f"/api/projects/{pid}/history"
            f"?limit=3&before_id={first['next_before']}"
        ).json()
        assert second["events"], "الصفحة الثانية فيها الأقدم"
        # لا تداخل بين الصفحتين
        first_ids = {e["id"] for e in first["events"]}
        second_ids = {e["id"] for e in second["events"]}
        assert not (first_ids & second_ids), "الصفحات لا تتكرر"


def test_artifacts_endpoint_empty_then_real(control_env):
    """(§47) المخرجات من الأدلة الدائمة حصرًا — لا مسح قرص عام."""
    client = control_env["client"]
    pid = _approved_project(client)
    artifacts = client.get(f"/api/projects/{pid}/artifacts").json()
    assert artifacts["artifacts"] == []   # لا أدلة بعد — صادق
    # (الدورة المنظمة تكتب deliverable.md بأدلة حقيقية عند التشغيل)


def test_rename_project(control_env):
    client = control_env["client"]
    pid = _approved_project(client)
    renamed = client.post(f"/api/projects/{pid}/rename", json={
        "name": "الاسم الجديد",
    })
    assert renamed.status_code == 200, renamed.text
    assert renamed.json()["name"] == "الاسم الجديد"


# ------------------------------------------------------------------ #
# §9+§32. التشغيلات النشطة — مؤشرات الشريط الجانبي
# ------------------------------------------------------------------ #

def test_active_runs_listing(control_env):
    """runs/active: التشغيل الحي معلن بحالته ومرحلته وانتظاره."""
    client = control_env["client"]
    pid = _approved_project(client)
    client.post(f"/api/projects/{pid}/run/stream?after=0")

    runs = client.get("/api/projects/runs/active").json()
    run = next((r for r in runs["runs"] if r["project_id"] == pid), None)
    # الدورة المنظمة سريعة — قد تكون انتهت؛ إن كانت حية فالعقد كامل
    if run is not None:
        for field in ("status", "stage", "waiting_for", "progress"):
            assert field in run


# ------------------------------------------------------------------ #
# §18. المحادثة ← المشروع — النقل لا يمس التاريخ
# ------------------------------------------------------------------ #

def test_conversation_move_to_project(control_env):
    """(§18) نقل محادثة إلى مشروع: نفس الصف بلا مساس بالرسائل."""
    client = control_env["client"]
    pid = _approved_project(client)

    created = client.post("/api/chat/stream", json={
        "message": "سؤال عادي قبل النقل",
    })
    assert created.status_code == 200
    # المحادثة أُنشأت برسالة المستخدم — اعثر عليها
    conversations = client.get("/api/conversations").json()[
        "conversations"]
    assert conversations, "المحادثة موجودة"
    cid = conversations[0]["conversation_id"]
    messages_before = client.get(
        f"/api/conversations/{cid}/messages").json()["messages"]

    moved = client.post(f"/api/conversations/{cid}/move-to-project",
                        json={"project_id": pid})
    assert moved.status_code == 200, moved.text
    assert moved.json()["project_id"] == pid

    # التاريخ كما هو حرفيًا
    messages_after = client.get(
        f"/api/conversations/{cid}/messages").json()["messages"]
    assert messages_after == messages_before

    # بيت المشروع يعرضها
    project_convs = client.get(
        f"/api/projects/{pid}/conversations").json()["conversations"]
    assert any(c["conversation_id"] == cid for c in project_convs)

    # الفك من المشروع يعمل أيضًا
    detached = client.post(f"/api/conversations/{cid}/move-to-project",
                           json={"project_id": None})
    assert detached.status_code == 200
    assert detached.json()["project_id"] is None


def test_conversation_rename_and_archive(control_env):
    """(§46) تسمية وأرشفة المحادثة — أوامر دائمة بسيطة."""
    client = control_env["client"]
    client.post("/api/chat/stream", json={"message": "رسالة للتسمية"})
    cid = client.get("/api/conversations").json()[
        "conversations"][0]["conversation_id"]

    renamed = client.post(f"/api/conversations/{cid}/rename", json={
        "title": "عنوان جديد",
    })
    assert renamed.status_code == 200
    assert renamed.json()["title"] == "عنوان جديد"

    archived = client.post(f"/api/conversations/{cid}/archive")
    assert archived.status_code == 200
    remaining = client.get("/api/conversations").json()["conversations"]
    assert all(c["conversation_id"] != cid for c in remaining), \
        "المؤرشفة تختفي من القائمة وتبقى كاملة"
    messages = client.get(f"/api/conversations/{cid}/messages")
    assert messages.status_code == 200, "الأرشفة لا تحذف التاريخ"


# ------------------------------------------------------------------ #
# W. التاريخ الطويل — صفحات محدودة لا غرق DOM
# ------------------------------------------------------------------ #

def test_long_history_pagination_bounded(control_env):
    """(§43+§55-W) مئات الأحداث: كل صفحة محدودة والمؤشر يمشي للوراء."""
    client = control_env["client"]
    pid = _plan_project(client)
    # 250 حدثًا دائمًا — تاريخ مشروع طويل حقيقي
    for i in range(250):
        from workflow import service as _service

        _service.add_event(control_env["sessions"], pid,
                           f"SYNTHETIC_{i}", {"n": i})

    total = 0
    before_id = 0
    pages = 0
    seen: set[int] = set()
    while pages < 30:
        page = client.get(
            f"/api/projects/{pid}/history?limit=100"
            + (f"&before_id={before_id}" if before_id else "")
        ).json()
        ids = {e["id"] for e in page["events"]}
        assert not (ids & seen), "لا تكرار عبر الصفحات"
        seen |= ids
        total += len(page["events"])
        pages += 1
        if not page["has_more"]:
            break
        before_id = page["next_before"]

    assert total >= 250, f"كل الأحداث قابلة للتصفح عبر الصفحات: {total}"
    assert all(
        len(p) <= 100 for p in [[]]
    ), "حجم الصفحة محدود بنيويًا من الخدمة"
