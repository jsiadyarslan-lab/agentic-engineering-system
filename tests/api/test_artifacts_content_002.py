"""(AES-ORACLE-UI-RUNTIME-002 §4+§6) عقد محتوى المخرجات — فتح/تنزيل حقيقي.

تغطي هذه المجموعة بنود الأمر:
- استرجاع الملف من المشروع الصحيح مع مطابقة المحتوى (بند 7+8).
- معاينة inline وتنزيل attachment بالترويسات الصحيحة (§4).
- ملف مفقود أو مرجع غير صالح دون انهيار (بند 9): 404 صادق.
- تجاوز المسار مرفوض (لا ملفات خارج المشروع).
- تعارض البصمة = 409 — لا محتوى مُختلق بعد الاعتماد.
- فتح الملف لا يغيّر سجل الدليل (البصمة باقية كما هي).
"""

from __future__ import annotations

import hashlib
import sys
from pathlib import Path

import pytest

pytest.importorskip("httpx", reason="TestClient يتطلب httpx")

REPO = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO / "src"))

from api import routes  # noqa: E402
from fastapi.testclient import TestClient  # noqa: E402
from workflow import service as wf_service  # noqa: E402


def _make_project(client: TestClient) -> int:
    resp = client.post("/api/projects", json={
        "name": "مخرجات القبول 002",
        "objective": "التحقق من عقد محتوى المخرجات من الرابط",
    })
    assert resp.status_code in (200, 201), resp.text
    return int(resp.json()["id"])


def _make_evidence(sessions, project_id: int, step_id: int = 5) -> int:
    return int(wf_service.create_evidence(
        sessions,
        execution_id=9, step_id=step_id, project_id=project_id,
        files={}, tool_calls=[], verification={},
        review_result={"verdict": "PASS"}, commit="",
        evidence_path="", evidence_sha256="", verdict="PASS",
        artifacts=[],
    ))


def _register_file(sessions, evidence_id: int, name: str,
                   content: bytes, project_id: int, step_id: int = 5):
    """اكتب الملف في مساحة عمل الخطوة وسجّله في الدليل ببصمته."""
    ws = Path("runtime") / "projects" / str(project_id) / "steps" \
        / str(step_id)
    ws.mkdir(parents=True, exist_ok=True)
    (ws / name).write_bytes(content)
    evidence = wf_service.get_evidence(sessions, evidence_id)
    files = dict(evidence.get("files") or {})
    files[name] = {"sha256": hashlib.sha256(content).hexdigest(),
                   "bytes": len(content)}
    # تحديث السجل عبر القناة الرسمية الوحيدة المتاحة للاختبار —
    # نعيد إنشاء سجل جديد بالملفات المطلوبة (السجل دائم لا يُعدّل)
    new_id = int(wf_service.create_evidence(
        sessions,
        execution_id=9, step_id=step_id, project_id=project_id,
        files=files, tool_calls=[], verification={},
        review_result={"verdict": "PASS"}, commit="",
        evidence_path="", evidence_sha256="", verdict="PASS",
        artifacts=[],
    ))
    return new_id


@pytest.fixture()
def client(api_env):
    return TestClient(routes.app)


def test_content_inline_matches_record_and_headers(
        client, api_env, tmp_path):
    """(بند 8) المعاينة: 200 + محتوى مطابق + ترويسة inline + نوع صحيح."""
    pid = _make_project(client)
    eid = _make_evidence(api_env["sessions"], pid)
    content = "# تقرير القبول\n\nسطر عربي وآخر إنجليزي.\n".encode("utf-8")
    eid2 = _register_file(api_env["sessions"], eid, "report.md",
                          content, pid)
    resp = client.get(
        f"/api/projects/{pid}/evidence/{eid2}/files/report.md/content")
    assert resp.status_code == 200, resp.text
    assert resp.content == content
    assert resp.headers["content-type"].startswith("text/markdown")
    assert resp.headers["content-disposition"].startswith("inline")
    assert resp.headers["x-evidence-sha256"] == \
        hashlib.sha256(content).hexdigest()
    # لا مسار داخلي مطلق في الاستجابة
    assert str(tmp_path) not in resp.text


def test_download_uses_attachment_disposition(client, api_env, tmp_path):
    """(§4) التنزيل: ?download=1 → attachment باسم الملف."""
    pid = _make_project(client)
    eid = _register_file(
        api_env["sessions"], _make_evidence(api_env["sessions"], pid),
        "notes.md", b"hello download", pid)
    resp = client.get(
        f"/api/projects/{pid}/evidence/{eid}/files/notes.md/content"
        "?download=1")
    assert resp.status_code == 200
    assert resp.headers["content-disposition"].startswith("attachment")
    assert "notes.md" in resp.headers["content-disposition"]


def test_pdf_served_as_pdf(client, api_env):
    """(§4) PDF يُقدَّم application/pdf ليُعاين متصفحيًا لا نصًا خامًا."""
    pid = _make_project(client)
    pdf_bytes = b"%PDF-1.4 fake-for-test\n"
    eid = _register_file(
        api_env["sessions"], _make_evidence(api_env["sessions"], pid),
        "out.pdf", pdf_bytes, pid)
    resp = client.get(
        f"/api/projects/{pid}/evidence/{eid}/files/out.pdf/content")
    assert resp.status_code == 200
    assert resp.headers["content-type"].startswith("application/pdf")


def test_wrong_project_rejected(client, api_env):
    """(§4) المخرج يُطلب من المشروع الصحيح حصرًا — مشروع آخر = 404."""
    pid = _make_project(client)
    other_pid = _make_project(client)
    eid = _register_file(
        api_env["sessions"], _make_evidence(api_env["sessions"], pid),
        "secret.md", b"private", pid)
    resp = client.get(
        f"/api/projects/{other_pid}/evidence/{eid}/files/secret.md/content")
    assert resp.status_code == 404


def test_missing_file_is_honest_404(client, api_env):
    """(بند 9) السجل موجود والملف مفقود = 404 صادق لا رابط وهمي."""
    pid = _make_project(client)
    eid = _register_file(
        api_env["sessions"], _make_evidence(api_env["sessions"], pid),
        "ghost.md", b"will vanish", pid)
    ws = Path("runtime") / "projects" / str(pid) / "steps" / "5"
    (ws / "ghost.md").unlink()
    resp = client.get(
        f"/api/projects/{pid}/evidence/{eid}/files/ghost.md/content")
    assert resp.status_code == 404
    assert "مفقود" in resp.json()["detail"]


def test_name_not_in_record_rejected(client, api_env):
    """ما لم يُثبت لا يُعرض: اسم ليس في سجل الدليل = 404."""
    pid = _make_project(client)
    eid = _make_evidence(api_env["sessions"], pid)
    resp = client.get(
        f"/api/projects/{pid}/evidence/{eid}/files/nope.md/content")
    assert resp.status_code == 404


def test_path_traversal_rejected(client, api_env):
    """(§4) لا تجاوز مجلد العمل: اسم بمسار = 400."""
    pid = _make_project(client)
    eid = _make_evidence(api_env["sessions"], pid)
    resp = client.get(
        f"/api/projects/{pid}/evidence/{eid}/files/"
        "sub%2F..%2F..%2Fetc%2Fpasswd/content")
    assert resp.status_code in (400, 404)
    if resp.status_code == 400:
        assert "غير صالح" in resp.json()["detail"]


def test_hash_mismatch_rejected_409(client, api_env):
    """(§4) المحتوى تغيّر بعد الاعتماد = 409 — لا محتوى غير مُوثّق."""
    pid = _make_project(client)
    eid = _register_file(
        api_env["sessions"], _make_evidence(api_env["sessions"], pid),
        "tamper.md", b"original", pid)
    ws = Path("runtime") / "projects" / str(pid) / "steps" / "5"
    (ws / "tamper.md").write_bytes("tampered!".encode("utf-8"))
    resp = client.get(
        f"/api/projects/{pid}/evidence/{eid}/files/tamper.md/content")
    assert resp.status_code == 409


def test_opening_file_does_not_mutate_evidence(client, api_env):
    """(§4) فتح الملف لا يغيّر سجل الأدلة ولا بصمته."""
    pid = _make_project(client)
    eid = _register_file(
        api_env["sessions"], _make_evidence(api_env["sessions"], pid),
        "stable.md", b"stable content", pid)
    before = wf_service.get_evidence(api_env["sessions"], eid)
    client.get(
        f"/api/projects/{pid}/evidence/{eid}/files/stable.md/content")
    after = wf_service.get_evidence(api_env["sessions"], eid)
    assert before == after
