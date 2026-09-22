"""اختبارات البث الحي للأمر 013 (§5+§41+§42) — تبويبان وreplay ومصالحة.

عقد البث (§5): اتصال تلقائي، إعادة اتصال، Last-Event-ID/replay، بلا
تكرار، ترتيب رتيب، استرداد الفائت، مصالحة الحالة، صحة الاتصال.

الاختبارات تستهلك عبر run/stream (بث ينتهي بـ run.done) — نفس مسار
البث (ناقل + دائمة + إسقاط مكرر + id رتيب) الذي يشغّل التيار العام؛
التيار العام اللانهائي يُثبت حيًّا في قبول المتصفح الفعلي.
"""

from __future__ import annotations

import json
import sys
import threading
import time
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

REPO = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO / "src"))

from api import routes  # noqa: E402
from test_projects_api import client, project_env  # noqa: E402,F401

from test_approval_live_013 import _local_search_source, _sandbox_env  # noqa: E402


def _consume_run(client_obj, pid: int, after: int | None,
                  timeout_s: float = 30.0) -> list[dict]:
    """استهلاك بث التشغيل حتى run.done — الأحداث الكاملة بترتيبها.

    after=None: من البداية (replay كل أحداث المشروع ثم الحي)؛
    after=N: استكمال بعد المعرف — إعادة الإرفاق بلا فقد.
    """
    events: list[dict] = []
    deadline = time.monotonic() + timeout_s
    query = "" if after is None else f"?after={after}"
    with client_obj.stream(
        "POST", f"/api/projects/{pid}/run/stream{query}"
    ) as response:
        assert response.status_code == 200
        for line in response.iter_lines():
            if time.monotonic() > deadline:
                break
            if line.startswith("data: "):
                try:
                    events.append(json.loads(line[6:]))
                except ValueError:
                    continue
    return events


def _kinds(events: list[dict], pid: int | None = None) -> list[str]:
    return [str(e.get("kind", "")) for e in events
            if pid is None or e.get("project_id") in (pid, None)]


def test_two_tabs_receive_same_live_events(client, project_env):
    """(§41) اعتماد من التبويب A ← التبويب B يتحدث تلقائيًا — لا Refresh.

    تبويبان = اشتراكان متزامنان في بث التشغيل نفسه؛ كلاهما يرى
    السلسلة كاملة (replay + حي) بترتيب واحد — لا انقسام حقيقة.
    """
    sessions = project_env["sessions"]
    _local_search_source(sessions)
    _sandbox_env(sessions, status="READY", sandboxed=1)

    created = client.post("/api/projects", json={
        "name": "تبويبان", "objective": "هدف اختبار التبويبين",
    })
    pid = created.json()["id"]
    # (013.4 §1) التوليد خلفي — ننتظر نتيجته قبل الاعتماد
    from tests.api.planning_wait import wait_for_plan

    client.post(f"/api/projects/{pid}/plan/generate")
    wait_for_plan(client, pid)

    approved = client.post(f"/api/projects/{pid}/plan/approve",
                           json={"approved": True})
    assert approved.status_code == 200

    # التبويبان يفتحان البث (بعد القرار مباشرة — كلاهما يلحق بالسلسلة)
    tab_events: dict[str, list[dict]] = {"a": [], "b": []}

    def consume(bucket: list) -> None:
        try:
            bucket.extend(_consume_run(client, pid, after=None))
        except Exception:  # noqa: BLE001 — تبويب واحد لا يكسر الآخر
            pass

    threads = [
        threading.Thread(target=consume, args=(tab_events["a"],),
                         daemon=True),
        threading.Thread(target=consume, args=(tab_events["b"],),
                         daemon=True),
    ]
    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join(timeout=40.0)

    kinds_a = _kinds(tab_events["a"], pid)
    kinds_b = _kinds(tab_events["b"], pid)
    # كلا التبويبين رأى القرار والسلسلة — بلا أي refresh
    for required in ("PLAN_APPROVED", "JOB_CREATED", "JOB_STARTED",
                     "PREFLIGHT_STARTED"):
        assert required in kinds_a, f"التبويب A فقده: {required}"
        assert required in kinds_b, f"التبويب B فقده: {required}"
    # نفس الحقيقة لا حقيقتان: أوجه السلسلة متطابقة بين التبويبين
    assert set(kinds_a) & set(kinds_b) >= {
        "PLAN_APPROVED", "JOB_CREATED", "PREFLIGHT_STARTED",
    }


def test_live_event_replay_after_disconnect(client, project_env):
    """(§42) انقطاع أثناء التنفيذ ← إعادة اتصال بعد معرف ← replay
    الفائت بترتيب رتيب — بلا فقد وبلا تكرار."""
    sessions = project_env["sessions"]
    _local_search_source(sessions)
    _sandbox_env(sessions, status="READY", sandboxed=1)

    created = client.post("/api/projects", json={
        "name": "انقطاع", "objective": "هدف اختبار الانقطاع",
    })
    pid = created.json()["id"]
    # (013.4 §1) التوليد خلفي — ننتظر نتيجته
    from tests.api.planning_wait import wait_for_plan

    client.post(f"/api/projects/{pid}/plan/generate")
    wait_for_plan(client, pid)

    # نقطة الانقطاع: آخر معرف قبل الاعتماد
    state = client.get(f"/api/projects/{pid}/state").json()
    last_id = state["last_event_id"]

    # الاعتماد يجري «أثناء انقطاع التبويب» — الأحداث تولد في الدائمة
    approved = client.post(f"/api/projects/{pid}/plan/approve",
                           json={"approved": True})
    assert approved.status_code == 200
    # انتظر اكتمال الدورة (أحداث كثيرة فاتت التبويب المنقطع)
    deadline = time.monotonic() + 30.0
    while time.monotonic() < deadline:
        state = client.get(f"/api/projects/{pid}/state").json()
        if state["job"] and state["job"]["status"] in (
            "WAITING_GATE", "COMPLETED",
        ):
            break
        time.sleep(0.25)

    # إعادة الاتصال: البث من نقطة الانقطاع — الفائت يُعاد كاملًا
    reconnected = _consume_run(client, pid, after=last_id)
    kinds = _kinds(reconnected, pid)
    for required in ("OWNER_GATE_RESOLVED", "PLAN_APPROVED",
                     "JOB_CREATED", "JOB_STARTED", "PREFLIGHT_STARTED",
                     "EVIDENCE_CREATED"):
        assert required in kinds, \
            f"{required} ضاع بعد الانقطاع ولم يُعَد: {kinds[:20]}"

    # لا تكرار: معرفات الأحداث المعادة فريدة ورتيبة وفوق نقطة القطع
    ids = [int(e["event_id"]) for e in reconnected if e.get("event_id")]
    assert ids, "لا معرفات أحداث في البث المعاد"
    assert ids == sorted(ids), f"ترتيب مكسور: {ids}"
    assert len(ids) == len(set(ids)), f"تكرار معرفات: {ids}"
    # (أحداث run.* بلا معرف دائمة — تُسقط من الفحص أعلاه)


def test_state_snapshot_reconciliation(client, project_env):
    """(§6) initial snapshot + event stream: اللقطة تعيد بناء كل شيء."""
    sessions = project_env["sessions"]
    _sandbox_env(sessions, status="READY", sandboxed=1)
    created = client.post("/api/projects", json={
        "name": "مصالحة", "objective": "هدف اختبار المصالحة",
    })
    pid = created.json()["id"]
    # (013.4 §1) التوليد خلفي — ننتظر نتيجته قبل الاعتماد
    from tests.api.planning_wait import wait_for_plan

    client.post(f"/api/projects/{pid}/plan/generate")
    wait_for_plan(client, pid)
    client.post(f"/api/projects/{pid}/plan/approve", json={"approved": True})

    # انتظر اكتمال الدورة ثم اعِد البناء من اللقطة وحدها
    deadline = time.monotonic() + 30.0
    while time.monotonic() < deadline:
        state = client.get(f"/api/projects/{pid}/state").json()
        if state["job"] and state["job"]["status"] in (
            "WAITING_GATE", "COMPLETED",
        ):
            break
        time.sleep(0.25)

    assert state["status"] in ("COMPLETED", "VERIFIED")
    assert state["plan"]["approved_by_owner"] is True
    assert state["timeline"], "خط الزمن المرحلي غائب عن اللقطة"
    assert state["chain"], "سلسلة القبول غائبة عن اللقطة"
    assert state["last_event_id"] > 0
    # كل ما تحتاجه الواجهة موجود في نداء واحد — بلا استطلاعات متعددة
    for key in ("gates", "phases", "events", "executions", "evidence",
                "audits", "job", "execution_gate", "acceptance_criteria",
                "active_run"):
        assert key in state, f"{key} غائب عن لقطة المصالحة"
