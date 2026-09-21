"""اختبار مصفوفة القدرات والفحص المسبق (الأمر 010 §18+§26-§30).

- المصفوفة: Required/Available/Decision لكل قدرة (§26).
- اختيار البيئة يظهر في النتيجة (§18) — لا بيئة افتراضية غير موجودة.
- قرارات واعية بالقدرات: بحث معطل + جلب جاهز → مهمة البحث تُحجب
  ومهمة الجلب تستمر (§23-§24+§39.8).
- إجراء المالك يسمي المسار الحقيقي (§30).
"""

from __future__ import annotations

import datetime as _dt
import sys
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO / "src"))

from persistence.database import (  # noqa: E402
    build_engine, init_db, make_session_factory,
)
from readiness import preflight, registry  # noqa: E402
from readiness.probes import ProbeResult  # noqa: E402


@pytest.fixture()
def sessions(tmp_path):
    engine = build_engine(tmp_path / "preflight-test.db")
    init_db(engine)
    factory = make_session_factory(engine)
    registry.ensure_capabilities(factory)
    return factory


def _set_status(sessions, capability_id, status, reason=""):
    registry.record_probe(sessions, capability_id, ProbeResult(
        status=status, reason=reason,
        checked_at=_dt.datetime.now(_dt.timezone.utc).isoformat(),
    ))


def _seamed_probe(sessions, capability_id, **_kwargs):
    """مسبار مضبوط: يقرأ الحالة المرادة من خريطة ثابتة — المسار نفسه
    (record_probe) بلا شبكة حية (الاختبار العزلي معلن)."""
    return registry.record_probe(sessions, capability_id, ProbeResult(
        status=_SEAMED_STATUSES.get(capability_id, "READY"),
        reason="مضبوط للاختبار",
        checked_at=_dt.datetime.now(_dt.timezone.utc).isoformat(),
    ))


_SEAMED_STATUSES: dict[str, str] = {}


def _use_seamed(**statuses):
    _SEAMED_STATUSES.clear()
    _SEAMED_STATUSES.update(statuses)
    return _seamed_probe if statuses else None


def test_matrix_has_required_available_decision(sessions):
    _set_status(sessions, "sandbox", "READY")
    _set_status(sessions, "filesystem", "READY")
    _set_status(sessions, "network_dns", "READY")
    _set_status(sessions, "network_https", "READY")
    _set_status(sessions, "shell", "READY")
    _set_status(sessions, "persistence", "READY")
    result = preflight.task_preflight(
        sessions, "مهمة حسابية عادية تمامًا", llm_ready=True,
        run_probe_fn=_use_seamed(),
    )
    assert "web_search" not in result["required"], (
        "الهدف لا يتطلب البحث — غيّر الصياغة"
    )
    matrix = result["matrix"]
    assert matrix, "لا مصفوفة"
    for row in matrix:
        for key in ("capability", "capability_id", "required",
                    "available", "decision"):
            assert key in row
        assert row["decision"] in ("PROCEED", "BLOCK")
    ready = [r for r in matrix if r["available"] == "READY"]
    assert ready and all(r["decision"] == "PROCEED" for r in ready)


def test_environment_selection_appears_in_result(sessions):
    """§18: البيئة المختارة تُسمّى — لا تنفيذ عبر بيئة غير معلنة."""
    from execution import service as execution_service

    result = preflight.task_preflight(
        sessions, "مهمة", llm_ready=True, force=True,
    )
    # في بيئة الاختبار: local-linux مسجلة UNKNOWN → ليست جاهزة → None
    assert "environment" in result
    env = result["environment"]
    if env is not None:
        assert env["name"] and env["backend"]
        assert "sandboxed" in env
    # بعد جعلها READY عبر التحقق الحقيقي (محاكاة) تظهر بالاسم
    execution_service.ensure_local_registered(sessions)
    from execution.models import ExecutionEnvironment
    from sqlalchemy import select as sa_select

    with sessions() as s:
        row = s.scalars(sa_select(ExecutionEnvironment).where(
            ExecutionEnvironment.name == "local-linux")).first()
        row.status = "READY"
        s.commit()
    result2 = preflight.task_preflight(sessions, "مهمة", llm_ready=True)
    assert result2["environment"] is not None
    assert result2["environment"]["name"] == "local-linux"


def test_search_blocked_goal_blocks_but_fetch_only_goal_proceeds(sessions):
    """§39.8 الجوهر: البحث معطل ≠ الإنترنت مقطوع — مهمة الجلب تستمر."""
    # شبكة وجلب وملفات جاهزة؛ البحث معطل (كل المزودين)
    for cap in ("sandbox", "filesystem", "network_dns", "network_https",
                "shell", "persistence"):
        _set_status(sessions, cap, "READY")
    _set_status(sessions, "web_search", "NOT_READY",
                "كل مزودي البحث غير جاهزين")
    _set_status(sessions, "web_fetch", "READY")

    # هدف OSINT (يطلب البحث جوهريًا) → BLOCKED بقرار واعٍ
    osint = preflight.task_preflight(
        sessions, "ابنِ منصة OSINT متقدمة ببحث ومصادر", llm_ready=True,
        run_probe_fn=_use_seamed(web_search="NOT_READY"),
    )
    assert osint["verdict"] == "BLOCKED"
    blocked_ids = {b["capability_id"] for b in osint["blocked"]}
    assert "web_search" in blocked_ids
    assert "web_fetch" not in blocked_ids  # الجلب جاهز فلا يُحجب
    row = [r for r in osint["matrix"] if r["capability_id"] == "web_search"][0]
    assert row["decision"] == "BLOCK"

    # هدف بلا بحث (جلب مباشر) → يمر — القدرات منفصلة (§23)
    fetch_only = preflight.task_preflight(
        sessions, "اجلب صفحة الوثائق من رابط معطى وحللها واكتب تقريرًا", llm_ready=True,
        run_probe_fn=_use_seamed(web_search="NOT_READY"),
    )
    assert fetch_only["verdict"] == "PASS", fetch_only["summary"]
    assert "web_search" not in fetch_only["required"]


def test_owner_action_names_real_paths(sessions):
    """§30: إجراء المالك يسمي ما هو مفقود ولماذا وكيف يوفره."""
    result = preflight.task_preflight(
        sessions, "مهمة", llm_ready=True,
        run_probe_fn=_use_seamed(sandbox="NOT_READY"),
    )
    sandbox_block = [
        b for b in result["blocked"] if b["capability_id"] == "sandbox"
    ][0]
    action = sandbox_block["owner_action"]
    assert action and "OWNER ACTION REQUIRED" in action
    assert "execution_worker.py" in action  # المسار الحقيقي
    assert "REMOTE_WORKER" in action
    assert "تحقق" in action


def test_preflight_events_carry_matrix_and_environment(sessions):
    """§29: الأحداث الحية تحمل المصفوفة — الواجهة تعرضها بلا طلب إضافي."""
    for cap in ("sandbox", "filesystem", "network_dns", "network_https",
                "shell", "persistence"):
        _set_status(sessions, cap, "READY")
    result = preflight.task_preflight(
        sessions, "مهمة عادية", llm_ready=True,
        run_probe_fn=_use_seamed(),
    )
    events = preflight.preflight_events(result)
    kinds = [e["kind"] for e in events]
    assert kinds[0] == "preflight.started"
    assert "preflight.passed" in kinds
    passed = [e for e in events if e["kind"] == "preflight.passed"][0]
    assert passed["details"]["matrix"], "المصفوفة غائبة من الحدث"
    assert "environment" in passed["details"]
