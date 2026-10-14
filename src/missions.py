"""مشغّل المهمة الحية (الأمر السادس §5) — الدورة الحية كاملة حتى PDF.

المهمة الافتراضية: تقرير من صفحة واحدة عن الوضع الجيوسياسي في
الشرق الأوسط، من 5-8 مصادر موثقة، عربي RTL، PDF بحجم A4.

المسار: المفكر يخطط ← المدقق يوافق ← المنفذ يجلب ويكتب ويولّد PDF ←
المراجع يتحقق (صفحات/مصادر/ملفات) ← المُحكَّم يحسم عند الخلاف.

الناتج: runtime/missions/default/mideast_report.pdf + evidence.json
(كل ملف بـ sha256، كل استدعاء أداة موثق، المصادر بأسمائها وروابطها).

الحكم الصادق (VERDICT): PASS فقط إذا كانت الحالة النهائية EVIDENCED
أو ADJUDICATED **و** الـPDF موجود فعلًا **و** صفحة واحدة **و** 5-8
مصادر — أي خلل = HARD STOP بسبب موثق (لا ترقيع §4.3).
"""

from __future__ import annotations

import hashlib
import json
import re
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Callable

from core.orchestrator import Orchestrator
from core.state import PlanState
from core.stop_controller import SNAPSHOT_NAME, StopController
from roles.live import RoleSystemFault
from roles.tools import ToolContext

#: المهمة الافتراضية (§5.1) — حرفية من الأمر.
DEFAULT_MISSION_GOAL = (
    "تقرير من صفحة واحدة عن الوضع الجيوسياسي في الشرق الأوسط، "
    "من 5-8 مصادر موثقة، عربي RTL، PDF بحجم A4"
)

#: (013.16 §5) بصمة المهمة البرمجية على مستوى الهدف — نفس نمط بصمة
#: المنفذ (roles/implementer_live._CODE_MISSION_HINT): حكم المهمة
#: البرمجية يتبع تحقق المدقق المستقل، لا عقد PDF/المصادر التقريري.
_CODE_MISSION_GOAL_HINT = re.compile(
    r"\.py\b|transactions\.csv|python|بايثون", re.IGNORECASE
)

MISSIONS_DIR = Path("runtime") / "missions"
DEFAULT_MISSION_DIR = MISSIONS_DIR / "default"
REPORT_PDF_NAME = "mideast_report.pdf"


@dataclass
class MissionResult:
    """حصيلة المهمة — الحكم الصادق والأدلة الكاملة."""

    verdict: str                     # "PASS" | "HARD STOP" | "STOPPED"
    reason: str
    goal: str
    cycle_id: str = ""
    final_state: str = ""
    pdf_path: str = ""
    pdf_pages: int = 0
    sources: list[dict] = field(default_factory=list)
    evidence_path: str = ""
    evidence_sha256: str = ""
    duration_ms: int = 0
    events: list[dict] = field(default_factory=list)
    #: المنسق الحي — يبقى للموافقة اللاحقة (user_verifies)؛ لا يُسلَّم في الأدلة.
    orchestrator: Any = None


def _emit(on_event: Callable[[dict], None] | None, event: dict) -> None:
    if on_event is not None:
        try:
            on_event(event)
        except Exception:  # noqa: BLE001 — المستقبِل لا يكسر المهمة
            pass


def _sha256_file(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def run_mission(
    goal: str = DEFAULT_MISSION_GOAL,
    *,
    router: Any,
    mission_dir: Path | str | None = None,
    on_event: Callable[[dict], None] | None = None,
    facts_builder: Callable | None = None,
    cycle_id: str | None = None,
    stop_controller: StopController | None = None,
    resume_from: dict | None = None,
    sessions: Any = None,
) -> MissionResult:
    """تشغيل المهمة الحية كاملة — دورة الأدوار الخمسة بأدوار حية.

    router: موجّه حي (ModelRouter.build_live()). فشل بناء الأدوار أو
    أي system_fault = HARD STOP صريح بسبب موثق.
    cycle_id/stop_controller (الأمر 004): معرّف معلن للدورة + متحكم
    الإيقاف — يربط نقاط تفتيش المنسق والمنفذ الحي بطلب المالك.
    resume_from (الأمر 004): لقطة إيقاف دورة سابقة — تُحقن في دورة
    جديدة (الهدف من اللقطة إن لم يُحدد).
    sessions (013.16 §1): جلسة قاعدة الخادم — تُمرّر لسياق الأدوات
    فيمر تنفيذ أدوات المهمة عبر بيئة التنفيذ الموحدة المسجلة
    والمتحقق منها (العامل المعزول) لا بالركيزة المحلية الصامتة؛
    None (اختبارات/تشغيل مباشر) = السلوك التاريخي نفسه.
    """
    from core.wiring import build_live_orchestrator
    from core.stop_controller import load_resume_point

    if resume_from is not None:
        point = load_resume_point(resume_from)
        goal = point.goal  # هدف اللقطة هو العقد الأصلي

    started = time.monotonic()
    target_dir = Path(mission_dir) if mission_dir else DEFAULT_MISSION_DIR
    target_dir.mkdir(parents=True, exist_ok=True)
    #: سجل المهمة الكامل (دورة + أدوات) — مصدر tool_calls في الأدلة.
    mission_events: list[dict] = []

    def sink(event: dict) -> None:
        mission_events.append(event)
        _emit(on_event, event)

    sink({
        "kind": "mission.start",
        "role": "mission",
        "goal": goal,
        "mission_dir": str(target_dir),
    })

    # سياق الأدوات — المنحة: مجلد المهمة وحده؛ أحداث الأدوات تُبث فورًا
    # (013.16 §1) جلسة الخادم تُمرّر: التنفيذ عبر بيئة التنفيذ الموحدة
    ctx = ToolContext(grant_root=target_dir, sessions=sessions)

    def tool_event_sink(event: dict) -> None:
        sink({"role": "implementer", **event})

    ctx.on_event = tool_event_sink

    # الأمر 004: نقاط تفتيش الإيقاف تُربط بسياق أدوات المنفذ الحي —
    # طلب المالك يُكرَّم بين خطوات المنفذ لا بعد الدور كاملًا.
    if stop_controller is not None and cycle_id:
        ctx.stop_check = stop_controller.checker_for(cycle_id)

    # المراجع الحي يبني حقائقه الميكانيكية من مجلد المهمة الفعلي
    if facts_builder is None:
        def facts_builder(request) -> dict:
            facts: dict[str, Any] = {}
            # (013.16 §4) جرد ملفات المهمة الفعلي — بصمة وحجم لكل ملف:
            # حقائق ميكانيكية عامة للمهام البرمجية وغيرها على السواء.
            inventory: dict[str, dict] = {}
            for item in sorted(target_dir.iterdir()):
                if item.is_file() and item.name != "sources.json":
                    inventory[item.name] = {
                        "bytes": item.stat().st_size,
                        "sha256_head": hashlib.sha256(
                            item.read_bytes()
                        ).hexdigest()[:16],
                    }
            if inventory:
                facts["mission_files"] = inventory
            # (013.16 §4) رأس مخرج الأداة إن وُجد — المحتوى الفعلي
            # الذي أنتجه البرنامج لا نص النموذج؛ حكم المدقق على أرقام
            # مثبتة (الإجماليات والفئات) من الملف نفسه.
            report_path = target_dir / "report.md"
            if report_path.is_file():
                try:
                    head = report_path.read_text(encoding="utf-8")[:2000]
                    facts["report_md_head"] = head
                except (OSError, ValueError):
                    facts["report_md_head"] = None
            # (013.16 §4) عدد سجلات ملف البيانات المعلن — عدد ميكانيكي
            # يفحصه المدقق كصفحات PDF تمامًا (دليل: أمر يحدد ستة سجلات
            # سُلّمت خمسة ومرّ التحقق لأن العدد لم يكن قابلاً للفحص).
            data_path = target_dir / "transactions.csv"
            if data_path.is_file():
                try:
                    lines = [
                        line for line in
                        data_path.read_text(encoding="utf-8").splitlines()
                        if line.strip()
                    ]
                    facts["transactions_records"] = max(
                        len(lines) - 1, 0
                    )  # بدون سطر العناوين
                except (OSError, ValueError):
                    facts["transactions_records"] = -1
            pdf_files = [
                p for p in target_dir.glob("*.pdf")
            ]
            if pdf_files:
                try:
                    from pypdf import PdfReader

                    facts["pdf_pages"] = len(PdfReader(str(pdf_files[0])).pages)
                except Exception:  # noqa: BLE001 — عطل pypdf يُعلن لا يُخفى
                    facts["pdf_pages"] = -1
            sources_path = target_dir / "sources.json"
            if sources_path.is_file():
                try:
                    found = json.loads(sources_path.read_text(encoding="utf-8"))
                    facts["sources_count"] = len(found)
                except ValueError:
                    facts["sources_count"] = -1
            return facts

    try:
        orchestrator = build_live_orchestrator(
            router,
            tools_ctx=ctx,
            verifier_facts_builder=facts_builder,
            stop_controller=stop_controller,
        )
    except RoleSystemFault as fault:
        return _hard_stop(goal, str(fault), started, target_dir, [], on_event)

    try:
        cycle = orchestrator.run_cycle(
            goal,
            cycle_id=cycle_id,
            workspace_root=target_dir,  # كل أدلة التنفيذ في مجلد المهمة
            on_event=sink,
            resume_from=resume_from,
        )
    except RoleSystemFault as fault:
        # system_fault موثق (§2.3) — حدث صريح ثم HARD STOP
        _emit(on_event, {
            "kind": "role.system_fault",
            "role": getattr(fault, "role", "unknown"),
            "text": str(fault),
        })
        return _hard_stop(goal, str(fault), started, target_dir, [], on_event)
    except Exception as error:  # noqa: BLE001 — فشل صريح موثق
        _emit(on_event, {
            "kind": "role.system_fault",
            "role": "coordinator",
            "text": f"الدورة الحية فشلت: {error}",
        })
        return _hard_stop(
            goal, f"الدورة الحية فشلت: {error}", started, target_dir, [], on_event
        )

    # ---- الحصيلة: جمع الحقائق الميكانيكية من مجلد المهمة ----
    pdf_path = target_dir / REPORT_PDF_NAME
    pdf_found = max(
        (p for p in target_dir.glob("*.pdf") if p.is_file()),
        key=lambda p: p.stat().st_mtime,
        default=None,
    )
    if pdf_found is not None and not pdf_path.is_file():
        pdf_path = pdf_found
    pdf_pages = 0
    if pdf_path.is_file():
        try:
            from pypdf import PdfReader

            pdf_pages = len(PdfReader(str(pdf_path)).pages)
        except Exception:  # noqa: BLE001
            pdf_pages = -1
    sources: list[dict] = []
    sources_path = target_dir / "sources.json"
    if sources_path.is_file():
        try:
            sources = json.loads(sources_path.read_text(encoding="utf-8"))
        except ValueError:
            sources = []

    # نسخة PDF بالاسم التعاقدي إن كانت باسم مهمة مختلفة
    if pdf_path.is_file() and pdf_path.name != REPORT_PDF_NAME:
        contract_copy = target_dir / REPORT_PDF_NAME
        contract_copy.write_bytes(pdf_path.read_bytes())
        pdf_path = contract_copy

    # ---- بناء الدليل evidence.json (§5.3) ----
    evidence: dict[str, Any] = {
        "goal": goal,
        "cycle_id": cycle.cycle_id,
        "final_state": cycle.final_state.value,
        "verdict_inputs": {
            "pdf_exists": pdf_path.is_file(),
            "pdf_pages": pdf_pages,
            "sources_count": len(sources),
            "state": cycle.final_state.value,
        },
        "sources": sources,
        "files": {
            p.name: {"sha256": _sha256_file(p), "bytes": p.stat().st_size}
            for p in sorted(target_dir.iterdir())
            if p.is_file() and p.name != "evidence.json"
        },
        "tool_calls": [
            e for e in mission_events if e.get("kind") == "tool.call"
        ],
        "state_history": cycle.state_history,
        "arbiter_decisions": cycle.arbiter_decisions,
        "duration_ms": cycle.duration_ms,
    }

    # ---- الحكم الصادق (§8 + الأمر 004: STOPPED حكم مستقل لا فشل) ----
    stopped = cycle.final_state is PlanState.STOPPED
    snapshot_path = target_dir / SNAPSHOT_NAME
    stop_block: dict | None = None
    if stopped:
        # اللقطة مصدر التدقيق: من أوقف؟ متى؟ لماذا؟ وعند أي خطوة؟
        try:
            snap = json.loads(
                snapshot_path.read_text(encoding="utf-8")
            )
            stop_block = {
                "stopped_by": snap.get("stopped_by", "غير معروف"),
                "stopped_at": snap.get("stopped_at", ""),
                "reason": snap.get("stop_reason", ""),
                "state_at_stop": snap.get("state_at_stop", ""),
                "phase": snap.get("phase", ""),
                "snapshot_path": str(snapshot_path),
                "snapshot_sha256": _sha256_file(snapshot_path),
            }
        except (OSError, ValueError):
            stop_block = {"snapshot_path": str(snapshot_path), "readable": False}
        reasons = [
            f"أوقفت المهمة بأمر ({stop_block.get('stopped_by', 'غير معروف')}) "
            f"عند {stop_block.get('phase', 'خطوة غير معروفة')}"
        ]
        verdict = "STOPPED"
    elif _CODE_MISSION_GOAL_HINT.search(goal):
        # (013.16 §5) مهمة برمجية: الحكم يتبع تحقق المدقق المستقل وحده
        # (EVIDENCED = كل معايير الخطة أثبتت ميكانيكيًا) — لا اشتراط
        # PDF/مصادر لم تطلبها المهمة البرمجية أصلًا؛ دعته السابقة حكمت
        # عليها HARD STOP زورًا رغم استيفاء المعايير لأن عقد مهمة
        # التقارير (PDF صفحة واحدة + 5-8 مصادر) كان مفروضًا على الجميع.
        if cycle.final_state is PlanState.EVIDENCED:
            reasons = []
            verdict = "PASS"
        else:
            reasons = [
                f"الحالة النهائية {cycle.final_state.value} — تحقق المدقق "
                "المستقل لم يبلغ EVIDENCED"
            ]
            verdict = "HARD STOP"
    else:
        reasons = []
        if cycle.final_state not in (PlanState.EVIDENCED, PlanState.ADJUDICATED):
            reasons.append(
                f"الحالة النهائية {cycle.final_state.value} — الدورة لم تكتمل أدلةً"
            )
        if not pdf_path.is_file():
            reasons.append("PDF غير موجود في مجلد المهمة")
        elif pdf_pages != 1:
            reasons.append(f"صفحات PDF = {pdf_pages} (المطلوب 1 بالضبط — §4.3)")
        if not (5 <= len(sources) <= 8):
            reasons.append(f"عدد المصادر {len(sources)} خارج النطاق 5-8")
        verdict = "PASS" if not reasons else "HARD STOP"
    evidence["resumed_from"] = cycle.resumed_from
    if stop_block is not None:
        evidence["stop"] = stop_block
    evidence["verdict"] = verdict
    evidence["verdict_reasons"] = reasons
    evidence_path = target_dir / "evidence.json"
    evidence_path.write_text(
        json.dumps(evidence, ensure_ascii=False, indent=1), encoding="utf-8"
    )
    evidence_sha = _sha256_file(evidence_path)

    result = MissionResult(
        verdict=verdict,
        reason="؛ ".join(reasons) if reasons else "المهمة اكتملت بأدلة كاملة",
        goal=goal,
        cycle_id=cycle.cycle_id,
        final_state=cycle.final_state.value,
        pdf_path=str(pdf_path) if pdf_path.is_file() else "",
        pdf_pages=pdf_pages,
        sources=sources,
        evidence_path=str(evidence_path),
        evidence_sha256=evidence_sha,
        duration_ms=int((time.monotonic() - started) * 1000),
        events=list(cycle.events),
        orchestrator=orchestrator,
    )
    _emit(on_event, {
        "kind": "mission_done",
        "role": "mission",
        "verdict": verdict,
        "text": result.reason,
        "details": {
            "cycle_id": result.cycle_id,
            "final_state": result.final_state,
            "pdf_path": result.pdf_path,
            "pdf_pages": result.pdf_pages,
            "sources_count": len(result.sources),
            "evidence_path": result.evidence_path,
            "evidence_sha256": evidence_sha,
            "verdict_reasons": reasons,
            "duration_ms": result.duration_ms,
            "stop": stop_block,  # الأمر 004: بيانات الإيقاف أو None
        },
    })
    return result


def _hard_stop(
    goal: str,
    reason: str,
    started: float,
    target_dir: Path,
    events: list[dict],
    on_event: Callable[[dict], None] | None,
) -> MissionResult:
    """HARD STOP مبكر — دليل جزئي يُكتب والحكم صريح (لا استسلام صامت)."""
    evidence = {
        "goal": goal,
        "verdict": "HARD STOP",
        "verdict_reasons": [reason],
        "files": {
            p.name: {"sha256": _sha256_file(p), "bytes": p.stat().st_size}
            for p in sorted(target_dir.iterdir()) if p.is_file()
        },
        "events": events,
    }
    evidence_path = target_dir / "evidence.json"
    evidence_path.write_text(
        json.dumps(evidence, ensure_ascii=False, indent=1), encoding="utf-8"
    )
    result = MissionResult(
        verdict="HARD STOP",
        reason=reason,
        goal=goal,
        evidence_path=str(evidence_path),
        evidence_sha256=_sha256_file(evidence_path),
        duration_ms=int((time.monotonic() - started) * 1000),
        events=events,
    )
    _emit(on_event, {
        "kind": "mission_done",
        "role": "mission",
        "verdict": "HARD STOP",
        "text": reason,
        "details": {
            "evidence_path": result.evidence_path,
            "evidence_sha256": result.evidence_sha256,
            "verdict_reasons": [reason],
        },
    })
    return result
