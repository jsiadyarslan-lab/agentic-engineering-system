"""إثبات سالب 2: لا هروب إلى نظام ملفات المضيف.

الركيزة تعزل نظام الملفات (pivot_root + ربط للقراءة فقط). البرنامج
داخل العزل يحاول قراءة /etc/passwd وملفَ sentinel موجودًا فعلًا على
المضيف خارج مساحة العمل — يجب أن يفشل الاثنان، وألا يتغير الـsentinel.
"""

from __future__ import annotations

from tests.substrate.conftest import read_stdout, run_in_sandbox


def test_no_filesystem_escape(adapter, tmp_path):
    # ملف sentinel حقيقي على المضيف خارج مساحة العمل
    sentinel = tmp_path.parent / f"v2-sentinel-{id(tmp_path)}.txt"
    sentinel.write_text("SECRET-HOST-DATA", encoding="utf-8")

    code = f'''
import sys
results = []
for label, p in (("passwd", "/etc/passwd"), ("sentinel", {str(sentinel)!r})):
    try:
        with open(p, "rb") as f:
            f.read(16)
        results.append(label + ":READ")
    except Exception as e:
        results.append(label + ":" + type(e).__name__)
with open("/artifacts/escape_report.txt", "w") as f:
    f.write("\\n".join(results))
escaped = any(r.endswith(":READ") for r in results)
print("RESULTS:", results)
raise SystemExit(0 if escaped else 7)  # 0 = قرأ المضيف (سيئ)
'''
    try:
        record, artifacts = run_in_sandbox(
            adapter, tmp_path, code, sandbox_id="neg-fs-001"
        )
        stdout = read_stdout(artifacts)

        # 1) كل محاولات القراءة فشلت داخل العزل
        assert record.exit_code == 7, f"داخل العزل: {stdout!r}"
        assert ":READ" not in stdout, f"قرأ البرنامج ملف المضيف! {stdout!r}"

        # 2) تقرير الحجز يوثق الفشلين بالنوع (دليل مرجعي)
        report = (artifacts / "escape_report.txt").read_text(encoding="utf-8")
        assert "passwd:" in report and "sentinel:" in report
        assert ":READ" not in report

        # 3) ملف المضيف لم يُمس
        assert sentinel.read_text(encoding="utf-8") == "SECRET-HOST-DATA"
    finally:
        sentinel.unlink(missing_ok=True)
