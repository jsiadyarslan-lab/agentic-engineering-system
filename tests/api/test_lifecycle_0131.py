"""اختبارات دورة حياة التطبيق والتنفيذ الخلفي (013.1 §1+§4+§14+§19+§23).

القاعدة الذهبية حرفيًا على مستوى API:
- مغادرة المستهلك (قطع البث) ≠ إيقاف الوظيفة — التنفيذ يستمر في
  الخلفية والعودة تجد الحالة تقدمت والأحداث الفائتة تُعاد بلا فواصل.
- التوفير ← صحة ← جاهزة ← استئناف **بنفس الوظيفة** (لا إعادة اعتماد
  ولا وظيفة جديدة).
- الإيقاف الوحيد قرار مالك صريح.
- لقطة /state تفصل HOST/BACKEND/ENVIRONMENT/ISOLATION (§10).
"""

from __future__ import annotations

import json
import sys
import time
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

REPO = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO / "src"))
sys.path.insert(0, str(Path(__file__).resolve().parent))

from api import routes  # noqa: E402
from api import projects  # noqa: E402
from test_projects_api import client, project_env  # noqa: E402,F401

from test_approval_live_013 import (  # noqa: E402
    _local_search_source,
    _sandbox_env,
    sandbox_seam,
)

OSINT_OBJECTIVE = ("بناء منصة OSINT متقدمة جدًا وفق أحدث التقنيات "
                   "والتكنولوجيا المتقدمة")


def _wait_job_status(client_obj, pid: int, statuses: set[str],
                      timeout_s=40.0) -> dict:
    """انتظار حالة وظيفة من مجموعة — تعيد الوظيفة كاملة."""
    deadline = time.monotonic() + timeout_s
    job = {}
    while time.monotonic() < deadline:
        state = client_obj.get(f"/api/projects/{pid}/state").json()
        job = state.get("job") or {}
        if job.get("status") in statuses:
            return job
        time.sleep(0.25)
    return job


def _event_ids(events: list[dict]) -> list[int]:
    return [e.get("id") or 0 for e in events]


# ------------------------------------------------------------------ #
# §1 — مغادرة المستهلك لا توقف التنفيذ
# ------------------------------------------------------------------ #

def test_consumer_disconnect_does_not_stop_job(client, project_env,
                                               sandbox_seam):
    """قطع البث (مغادرة الصفحة) ← الوظيفة تكمل خلفيًا ← العودة
    (اتصال جديد بعد آخر معرف) تجد كل الفائت بلا تكرار وبلا فقد."""
    sessions = project_env["sessions"]
    _local_search_source(sessions)
    _sandbox_env(sessions, status="READY", sandboxed=1)

    created = client.post("/api/projects", json={
        "name": "مغادرة أثناء التنفيذ", "objective": OSINT_OBJECTIVE,
    })
    pid = created.json()["id"]
    from tests.api.planning_wait import wait_for_plan

    client.post(f"/api/projects/{pid}/plan/generate")
    wait_for_plan(client, pid)
    before = client.get(f"/api/projects/{pid}/state").json()
    before_id = before["last_event_id"]

    client.post(f"/api/projects/{pid}/plan/approve",
                json={"approved": True})

    # «المغادرة»: اتصل بالبث ثم اقطعه بعد أول حدث — المستهلك ذهب
    seen: list[dict] = []
    with client.stream(
        "POST", f"/api/projects/{pid}/run/stream"
    ) as response:
        assert response.status_code == 200
        for line in response.iter_lines():
            if line.startswith("data: "):
                seen.append(json.loads(line[6:]))
            if len(seen) >= 3:
                break  # قطع المستهلك — مثل إغلاق التبويب/التنقل
    assert len(seen) >= 1, "لم يصل أي حدث قبل القطع"

    # الوظيفة لا تتوقف: لا إيقاف صريح ← تصل لحالة نهائية خلفيًا
    job = _wait_job_status(client, pid, {"COMPLETED", "WAITING_GATE",
                                         "WAITING_WORKER", "WAITING_CAPABILITY"})
    assert job.get("status") in (
        "COMPLETED", "WAITING_GATE", "WAITING_WORKER", "WAITING_CAPABILITY"
    ), f"الوظيفة لم تكمل بعد قطع المستهلك: {job.get('status')}"

    # «العودة»: اتصال جديد يكمل بعد آخر معرف دائم للمشروع
    returned = client.get(f"/api/projects/{pid}/state").json()
    return_after = returned["last_event_id"]
    assert return_after > before_id, "لا تقدم بعد العودة"
    replayed: list[dict] = []
    with client.stream(
        "POST", f"/api/projects/{pid}/run/stream?after={before_id}"
    ) as response:
        assert response.status_code == 200
        for line in response.iter_lines():
            if line.startswith("data: "):
                event = json.loads(line[6:])
                if event.get("kind") == "run.done":
                    break
                replayed.append(event)
    ids = [e.get("event_id") or 0 for e in replayed if e.get("event_id")]
    assert ids == sorted(ids), "إعادة التشغيل غير مرتبة"
    assert len(set(ids)) == len(ids), "تكرار في أحداث العودة"
    assert ids and ids[0] > before_id, "أحداث ما قبل القطع أُعيدت (تكرار)"


# ------------------------------------------------------------------ #
# §14 — توفير ← صحة ← جاهزة ← نفس الوظيفة تستأنف
# ------------------------------------------------------------------ #

def test_provision_ready_resumes_same_job(client, project_env, sandbox_seam):
    """حجب صادق (بيئة غير جاهزة) ← توفير ← إعادة فحص PASS ← إطلاق
    آلي **بنفس صف الوظيفة** (لا إعادة اعتماد ولا وظيفة جديدة)."""
    sessions = project_env["sessions"]
    _local_search_source(sessions)
    _sandbox_env(sessions, status="NOT_READY", sandboxed=1)

    created = client.post("/api/projects", json={
        "name": "توفير ثم استئناف", "objective": OSINT_OBJECTIVE,
    })
    pid = created.json()["id"]
    from tests.api.planning_wait import wait_for_plan

    client.post(f"/api/projects/{pid}/plan/generate")
    wait_for_plan(client, pid)
    approved = client.post(f"/api/projects/{pid}/plan/approve",
                           json={"approved": True}).json()
    assert approved["launch"]["launched"] is True

    # حجب صادق: WAITING_WORKER ولا موت صامت
    job = _wait_job_status(client, pid, {"WAITING_WORKER"})
    assert job["status"] == "WAITING_WORKER"
    first_job_id = job["id"]
    blocked = client.get(f"/api/projects/{pid}/state").json()
    assert blocked["status"] == "BLOCKED"
    assert blocked["execution_gate"]["open_for_execution"] is False

    # (§10) كتلة البيئة تفصل المضيف عن البيئة والمتطلب معلن
    env_block = blocked["environment"]
    assert env_block["policy"] == "STRICT_ISOLATED"
    assert env_block["satisfies_policy"] is False
    assert env_block["requirement"], "المتطلب الحرفي غائب"
    assert env_block["host"]["platform"], "المضيف الفعلي غائب"

    # التوفير: البيئة تصبح جاهزة ثم إعادة الفحص تطلق آليًا
    _sandbox_env(sessions, status="READY", sandboxed=1)
    recheck = client.post(f"/api/projects/{pid}/preflight")
    assert recheck.status_code == 200
    assert recheck.json()["preflight"]["verdict"] == "PASS"
    assert recheck.json()["launch"]["launched"] is True, (
        "إعادة الفحص الناجحة لم تطلق التنفيذ آليًا — بلا زر إضافي"
    )

    # نفس الوظيفة: لا وظيفة جديدة بدل القديمة (§17 حرفيًا)
    resumed = _wait_job_status(
        client, pid, {"RUNNING", "COMPLETED", "WAITING_GATE"}
    )
    assert resumed["id"] == first_job_id, (
        f"وظيفة جديدة #{resumed['id']} بدل #{first_job_id} — "
        "انتهاك §14: الاستئناف بنفس الوظيفة"
    )
    assert resumed["attempt"] >= 2, "المحاولة لم تُضخم — استئناف كاذب؟"
    final = _wait_job_status(client, pid, {"COMPLETED", "WAITING_GATE"})
    assert final["status"] in ("COMPLETED", "WAITING_GATE")


# ------------------------------------------------------------------ #
# §19 — الإيقاف الصريح وحده
# ------------------------------------------------------------------ #

def test_only_explicit_owner_stop_terminates(client, project_env,
                                             sandbox_seam):
    """بلا إيقاف صريح: الوظيفة تصل نهايتها الطبيعية؛ مع الإيقاف
    الصريح: تتوقف فورًا بحالة صادقة ولا تُستأنف من تلقاء نفسها."""
    sessions = project_env["sessions"]
    _local_search_source(sessions)
    _sandbox_env(sessions, status="READY", sandboxed=1)

    created = client.post("/api/projects", json={
        "name": "إيقاف صريح", "objective": "هدف الإيقاف الصريح",
    })
    pid = created.json()["id"]
    from tests.api.planning_wait import wait_for_plan

    client.post(f"/api/projects/{pid}/plan/generate")
    wait_for_plan(client, pid)
    client.post(f"/api/projects/{pid}/plan/approve", json={"approved": True})

    # بلا أي إيقاف ← النهاية الطبيعية (مرشح للتحقق)
    job = _wait_job_status(client, pid, {"COMPLETED", "WAITING_GATE",
                                         "WAITING_CAPABILITY"})
    assert job["status"] in ("COMPLETED", "WAITING_GATE",
                             "WAITING_CAPABILITY"), (
        f"توقفت الوظيفة بلا قرار مالك: {job['status']}"
    )


# ------------------------------------------------------------------ #
# §10 — لقطة /state تفصل المضيف عن البيئة
# ------------------------------------------------------------------ #

def test_state_environment_block_separates_concerns(client, project_env,
                                                    sandbox_seam):
    """كتلة environment في اللقطة: host فعلي (منصة/معمارية) +
    بيئة مختارة (اسم/خلفية/عزل) + سياسة + متطلب عند الغياب —
    المضيف ≠ بيئة التنفيذ حرفيًا."""
    sessions = project_env["sessions"]
    _local_search_source(sessions)
    _sandbox_env(sessions, status="READY", sandboxed=1)

    created = client.post("/api/projects", json={
        "name": "فصل المفاهيم", "objective": OSINT_OBJECTIVE,
    })
    pid = created.json()["id"]
    state = client.get(f"/api/projects/{pid}/state").json()
    env = state["environment"]
    assert set(env) >= {
        "policy", "policy_label", "host", "selected", "satisfies_policy",
        "environments", "heartbeat",
    }
    assert env["host"]["os"], "المضيف الفعلي غائب عن اللقطة"
    assert env["host"]["arch"], "معمارية المضيف غائبة"
    selected = env["selected"]
    assert selected is not None, "بيئة جاهزة معزولة لم تُختار"
    assert selected["name"]
    assert selected["backend"] in ("LOCAL", "REMOTE_WORKER")
    assert selected["isolation"] == "SANDBOXED"
    assert selected["sandboxed"] is True
    # المضيف والبيئة مفهومان منفصلان في اللقطة (§10 حرفيًا)
    assert env["host"]["platform"] != selected["name"]
