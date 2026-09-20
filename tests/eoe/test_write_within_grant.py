"""§10.4 — test_write_within_grant: WRITE_LOCAL داخل النطاق وخارجه.

داخل PATH_GRANT = نجاح بإثبات نطاق؛ خارجه = HARD STOP آلي.
"""
from __future__ import annotations

from pathlib import Path


from eoe.eoe_engine import EoeEngine

ORDER_TEMPLATE = """# EXECUTION ORDER — WRITE_TEST
### §0 — عقد التنفيذ الصلب
1. المستودع: owner/write-test — الفرع: main — الوضع: {mode}.
2. الهدف: تعديل ملف داخل المنحة.
3. المنح المطلوبة:
   - PATH_GRANT قراءة وكتابة على {grant_root}
4. الأوامر المسموحة: python فقط.
### §1 — الكتابة داخل النطاق
المتطلبات:
1. كتابة ملف output.txt بمحتوى محدد.
الهبوط:
- {landing_path}
الأوامر:
- python -c "open('/artifacts/output.txt','w').write('from-eoe')"
### §9 — القالب الإلزامي للتقرير
```
VERDICT: PASS / HARD STOP
FILES_CHANGED (§1): الملفات
GRANTS_USED: المنح المستخدمة
PUSHES: الدفعات
HARD STOPS FIRED: عدد أو NONE
```
**END OF ORDER**
"""


def _run(order_text, sandbox_manager, tmp_path):
    events: list[tuple[str, dict]] = []
    engine = EoeEngine(
        sandbox_manager,
        grantor_key=b"wt-grantor",
        approval_key=b"wt-approval",
        on_event=lambda kind, payload: events.append((kind, payload)),
        work_base=str(tmp_path / "eoe-work"),
        working_repo=str(tmp_path / "repo"),
    )
    result = engine.run_order(
        order_text,
        approve_grants=lambda proposals: [
            engine._grantor.approve(g) for g in proposals
        ],
    )
    return engine, result, events


def test_write_local_within_grant_succeeds(sandbox_manager, tmp_path, repo_factory):
    """كتابة داخل PATH_GRANT = نجاح + إثبات نطاق + FILES_CHANGED صادق."""
    repo = repo_factory("repo")
    target_dir = repo / "docs"
    target_dir.mkdir(exist_ok=True)
    order = ORDER_TEMPLATE.format(
        mode="WRITE_LOCAL", grant_root=str(target_dir),
        landing_path=str(target_dir / "output.txt"),
    )
    engine, result, events = _run(order, sandbox_manager, tmp_path)
    assert result.verdict == "PASS", result.hard_stops
    # الملف كُتب فعلاً داخل المنحة
    written = target_dir / "output.txt"
    assert written.exists()
    assert written.read_text(encoding="utf-8") == "from-eoe"
    # إثبات النطاق: FILES_CHANGED يذكر الملف داخل المنحة
    files_line = next(
        line for line in result.report.lines if line.startswith("FILES_CHANGED")
    )
    assert "output.txt" in files_line
    # المنح مستخدمة ومسجلة
    grants_line = next(
        line for line in result.report.lines if line.startswith("GRANTS_USED")
    )
    assert "كتابة" in grants_line
    # لا دفع في WRITE_LOCAL
    pushes_line = next(
        line for line in result.report.lines if line.startswith("PUSHES")
    )
    assert pushes_line.endswith("NONE")


def test_write_outside_grant_is_hard_stop(sandbox_manager, tmp_path, repo_factory):
    """كتابة خارج PATH_GRANT = HARD STOP — الملف لا يهبط أبدًا."""
    repo = repo_factory("repo")
    granted = repo / "allowed"
    granted.mkdir(exist_ok=True)
    outside = repo / "forbidden"
    outside.mkdir(exist_ok=True)
    # المنحة على allowed لكن الهبوط المعلن في forbidden — عبر محرك
    # التنفيذ مباشرة: هذا بالضبط ما يفحصه `_custody_exit` (الأمر لا
    # يستطيع التصريح بهبوط خارجي دون أن يرفضه فحص القبول).
    from eoe.access_gateway import (
        AccessAdmission, AccessLedger, GrantorService,
    )
    from eoe.execution_engine import (
        ExecutionEngine, IsolationLevel, SectionExecutionPlan,
    )
    from eoe.order_parser import AccessRequest, GrantKind

    grantor = GrantorService(b"x")
    ledger = AccessLedger()
    admission = AccessAdmission(ledger, grantor)
    ledger.register(
        grantor.approve(
            grantor.propose(
                AccessRequest(kind=GrantKind.PATH_GRANT, scope="read_write",
                              target=str(granted))
            )
        )
    )
    engine = ExecutionEngine(
        sandbox_manager, admission,
        command_whitelist=("python",), work_base=str(tmp_path / "ee"),
    )
    plan = SectionExecutionPlan(
        section_number=1,
        commands=(
            ("python", "-c",
             "open('/artifacts/output.txt','w').write('x')"),
        ),
        isolation=IsolationLevel.BUILD_ISOLATION,
        writes=(str(outside / "output.txt"),),   # هبوط خارج المنحة
    )
    try:
        engine.run_section(plan)
        raised = None
    except Exception as error:  # noqa: BLE001
        raised = error
    assert raised is not None, "كتابة خارج المنحة لم تُوقف!"
    assert "خارج نطاق" in str(raised) or "HARD STOP" in str(raised)
    # والملف المحرم لم يُلمس أبدًا
    assert not (outside / "output.txt").exists()
    # ولم يهبط حتى داخل المنحة (لا شيء كُتب)
    assert not (granted / "output.txt").exists()
