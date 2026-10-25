"""(AES-LIVE-FACTORY-E2E-001 المرحلة 4+§6) عقود مساحة المشاهدة الحية.

تغطي بنود أمر القبول:
- المعاينة (4أ): meta صادقة قبل أول index.html، خدمة الملفات بنوع
  محتوى صحيح للعربي RTL، أحدث خطوة تظلل الأقدم، رفض العبور
  خارج مساحة المشروع، و404 صادقة للمفقود.
- ملفات مساحة العمل (4ج+4د): قائمة بإسناد الدور من سجل التنفيذات
  وعدد نسخ الفروق، وخدمة الملف والنسخة بذات عقد الاحتواء.
- متصفح الوكيل (4ب): اللقطات من أحداث المشروع الدائمة حصرًا،
  تقديم الصورة بمطابقة البصمة، وتعديلها بعد الحدث = 409 لا
  صورة مختلقة، ومشروع آخر = 404.
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


@pytest.fixture()
def client(api_env):
    return TestClient(routes.app)


def _make_project(client: TestClient) -> int:
    resp = client.post("/api/projects", json={
        "name": "قبول المعاينة الحية",
        "objective": "التحقق من عقود مساحة المشاهدة الحية",
    })
    assert resp.status_code in (200, 201), resp.text
    return int(resp.json()["id"])


def _write_step_file(project_id: int, step_id: int, rel: str,
                     content: bytes) -> None:
    target = (Path("runtime") / "projects" / str(project_id)
              / "steps" / str(step_id) / rel)
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_bytes(content)


# ---------------- (4أ) المعاينة ----------------

def test_preview_meta_empty_is_honest(client, api_env):
    """قبل أول index.html: available=false بسبب حرفي — لا وعد واجهة."""
    pid = _make_project(client)
    resp = client.get(f"/api/projects/{pid}/preview")
    assert resp.status_code == 200
    body = resp.json()
    assert body["available"] is False
    assert "index.html" in body["reason"]
    assert body["entry"] == f"/api/projects/{pid}/preview/index.html"


def test_preview_meta_and_file_serve_with_rtl_charset(client, api_env):
    """index.html فعلية: meta متاحة + خدمة text/html بترميز utf-8."""
    pid = _make_project(client)
    html = ("<!doctype html><html dir='rtl' lang='ar'>"
             "<head><meta charset='utf-8'><title>أخبار</title></head>"
             "<body><h1>الرئيسية</h1></body></html>").encode("utf-8")
    _write_step_file(pid, 5, "index.html", html)
    _write_step_file(pid, 5, "css/style.css",
                     b"body { direction: rtl; }")
    meta = client.get(f"/api/projects/{pid}/preview").json()
    assert meta["available"] is True
    assert meta["step_id"] == 5
    names = {f["path"] for f in meta["files"]}
    assert {"index.html", "css/style.css"} <= names

    resp = client.get(f"/api/projects/{pid}/preview/index.html")
    assert resp.status_code == 200
    assert resp.content == html
    assert resp.headers["content-type"].startswith("text/html")
    assert "charset=utf-8" in resp.headers["content-type"]

    css = client.get(f"/api/projects/{pid}/preview/css/style.css")
    assert css.status_code == 200
    assert css.headers["content-type"].startswith("text/css")


def test_preview_newest_step_shadows_older(client, api_env):
    """الموقع عبر خطوات: أحدث خطوة تُخدَّم لكل ملف موجود فيها."""
    pid = _make_project(client)
    _write_step_file(pid, 5, "index.html", b"<h1>v1</h1>")
    _write_step_file(pid, 9, "index.html", b"<h1>v2</h1>")
    meta = client.get(f"/api/projects/{pid}/preview").json()
    assert meta["step_id"] == 9
    resp = client.get(f"/api/projects/{pid}/preview/index.html")
    assert resp.content == b"<h1>v2</h1>"
    # ملف موجود في الخطوة القديمة فقط — يُخدَّم منها
    _write_step_file(pid, 5, "legacy.js", b"// old")
    legacy = client.get(f"/api/projects/{pid}/preview/legacy.js")
    assert legacy.status_code == 200
    assert legacy.content == b"// old"


def test_preview_traversal_and_hidden_rejected(client, api_env):
    """عبور المسار ورمل الركيزة مرفوضان قبل أي لمسة قرص."""
    pid = _make_project(client)
    _write_step_file(pid, 5, "index.html", b"<h1>x</h1>")
    _write_step_file(pid, 5, "_ws/secret.txt", b"secret")
    for bad in ("../other/index.html", "..%2f..%2fetc/passwd",
                "_ws/secret.txt", "styles/../../x"):
        resp = client.get(
            f"/api/projects/{pid}/preview/{bad}")
        assert resp.status_code in (400, 404), bad


def test_preview_missing_file_is_404_honest(client, api_env):
    pid = _make_project(client)
    resp = client.get(f"/api/projects/{pid}/preview/ghost.html")
    assert resp.status_code == 404
    assert "غير موجود" in resp.json()["detail"]


# ---------------- (4ج+4د) ملفات مساحة العمل ----------------

def test_workspace_files_listing_with_role_and_versions(client, api_env):
    """القائمة: ملفات فعلية + إسناد دور من التنفيذات + نسخ الفروق."""
    pid = _make_project(client)
    _write_step_file(pid, 5, "index.html", b"<h1>v1</h1>")
    _write_step_file(pid, 5, "_versions/index.html.v1", b"<h1>v0</h1>")
    _write_step_file(pid, 5, "_versions/index.html.v2", b"<h1>v1</h1>")
    _write_step_file(pid, 7, "about.html", "<p>حول</p>".encode("utf-8"))
    # تنفيذ حقيقي يوثق دور الخطوة 5
    with api_env["sessions"]() as session:
        from workflow.models import Execution

        session.add(Execution(step_id=5, status="COMPLETED",
                              agent_role="implementer"))
        session.commit()

    resp = client.get(f"/api/projects/{pid}/workspace-files")
    assert resp.status_code == 200
    body = resp.json()
    by_path = {(f["step_id"], f["path"]): f for f in body["files"]}
    entry = by_path[(5, "index.html")]
    assert entry["agent_role"] == "implementer"
    assert entry["versions"] == 2
    about = by_path[(7, "about.html")]
    assert about["versions"] == 0
    # رمل الركيزة لا يُدرج في الملفات أبداً
    assert all(f["path"].split("/")[0] != "_ws"
               for f in body["files"])


def test_workspace_file_serves_current_and_version(client, api_env):
    """خدمة الملف الحالي ونسخة الفرق — بذات عقد الاحتواء."""
    pid = _make_project(client)
    _write_step_file(pid, 5, "index.html", b"<h1>current</h1>")
    _write_step_file(pid, 5, "_versions/index.html.v1",
                     b"<h1>previous</h1>")
    cur = client.get(
        f"/api/projects/{pid}/workspace-file?step_id=5&path=index.html")
    assert cur.status_code == 200
    assert cur.content == b"<h1>current</h1>"
    prev = client.get(
        f"/api/projects/{pid}/workspace-file"
        "?step_id=5&path=_versions/index.html.v1")
    assert prev.status_code == 200
    assert prev.content == b"<h1>previous</h1>"
    bad = client.get(
        f"/api/projects/{pid}/workspace-file"
        "?step_id=5&path=_ws/anything")
    assert bad.status_code == 400
    escape = client.get(
        f"/api/projects/{pid}/workspace-file"
        "?step_id=5&path=../../x")
    assert escape.status_code in (400, 404)


# ---------------- (4ب) متصفح الوكيل ----------------

def _png_bytes() -> bytes:
    return (b"\x89PNG\r\n\x1a\n" + b"\x00" * 64 + b"fake-screenshot")


def _add_screenshot_event(api_env, project_id: int, path: Path) -> int:
    payload = {
        "step_id": 5, "execution_id": 9, "session_id": "s-test",
        "url": "http://127.0.0.1:8011/api/projects/"
               f"{project_id}/preview/index.html",
        "summary": "الصفحة الرئيسية",
        "detail": {
            "file": str(path), "bytes": path.stat().st_size,
            "sha256": hashlib.sha256(path.read_bytes()).hexdigest(),
            "url": "about:blank", "kind": "browser.screenshot",
        },
    }
    return int(wf_service.add_event(
        api_env["sessions"], project_id, "BROWSER_SCREENSHOT", payload))


def test_browser_activity_lists_from_durable_events(client, api_env):
    """اللقطات والخط الزمني من الأحداث الدائمة حصرًا + روابط تقديم."""
    pid = _make_project(client)
    shot_dir = Path("runtime") / "browser" / "s-test"
    shot_dir.mkdir(parents=True, exist_ok=True)
    shot = shot_dir / "shot-1.png"
    shot.write_bytes(_png_bytes())
    event_id = _add_screenshot_event(api_env, pid, shot)

    wf_service.add_event(api_env["sessions"], pid, "BROWSER_NAVIGATE", {
        "step_id": 5, "execution_id": 9, "session_id": "s-test",
        "url": f"http://127.0.0.1:8011/api/projects/{pid}"
               "/preview/index.html", "summary": "",
        "detail": {},
    })

    resp = client.get(f"/api/projects/{pid}/browser-activity")
    assert resp.status_code == 200
    body = resp.json()
    assert len(body["screenshots"]) == 1
    assert body["screenshots"][0]["id"] == event_id
    assert body["screenshots"][0]["image_url"] == \
        f"/api/projects/{pid}/browser-screenshots/{event_id}"
    assert any(t["kind"] == "BROWSER_NAVIGATE" for t in body["timeline"])

    img = client.get(
        f"/api/projects/{pid}/browser-screenshots/{event_id}")
    assert img.status_code == 200
    assert img.headers["content-type"] == "image/png"
    assert img.content == shot.read_bytes()
    assert img.headers["x-screenshot-sha256"] == \
        hashlib.sha256(shot.read_bytes()).hexdigest()


def test_browser_screenshot_tamper_is_409(client, api_env):
    """تعديل اللقطة بعد الحدث = 409 — لا صورة مختلقة بعلم المصنع."""
    pid = _make_project(client)
    shot_dir = Path("runtime") / "browser" / "s-test"
    shot_dir.mkdir(parents=True, exist_ok=True)
    shot = shot_dir / "shot-2.png"
    shot.write_bytes(_png_bytes())
    event_id = _add_screenshot_event(api_env, pid, shot)
    shot.write_bytes(_png_bytes() + b"tampered")
    resp = client.get(
        f"/api/projects/{pid}/browser-screenshots/{event_id}")
    assert resp.status_code == 409


def test_browser_screenshot_cross_project_404(client, api_env):
    """حدث مشروع آخر لا يُخدَّم عبر مشروعي — لا كشف متقاطع."""
    pid_a = _make_project(client)
    pid_b = _make_project(client)
    shot_dir = Path("runtime") / "browser" / "s-test"
    shot_dir.mkdir(parents=True, exist_ok=True)
    shot = shot_dir / "shot-3.png"
    shot.write_bytes(_png_bytes())
    event_id = _add_screenshot_event(api_env, pid_a, shot)
    resp = client.get(
        f"/api/projects/{pid_b}/browser-screenshots/{event_id}")
    assert resp.status_code == 404


def test_browser_screenshot_outside_sandbox_rejected(client, api_env):
    """مسار خارج رمل runtime/browser مرفوض — لا قرص عام."""
    pid = _make_project(client)
    (Path("runtime")).mkdir(parents=True, exist_ok=True)
    outside = Path("runtime") / "evil.png"
    outside.write_bytes(_png_bytes())
    payload = {
        "step_id": 5, "execution_id": 9, "session_id": "s-x",
        "url": "", "summary": "",
        "detail": {"file": str(outside),
                   "bytes": outside.stat().st_size,
                   "sha256": hashlib.sha256(
                       outside.read_bytes()).hexdigest()},
    }
    event_id = int(wf_service.add_event(
        api_env["sessions"], pid, "BROWSER_SCREENSHOT", payload))
    resp = client.get(
        f"/api/projects/{pid}/browser-screenshots/{event_id}")
    assert resp.status_code == 400


def test_browser_activity_empty_is_honest(client, api_env):
    """لا نشاط متصفح بعد: قوائم فارغة صادقة — لا اصطناع."""
    pid = _make_project(client)
    resp = client.get(f"/api/projects/{pid}/browser-activity")
    assert resp.status_code == 200
    assert resp.json()["screenshots"] == []
    assert resp.json()["timeline"] == []


# ---------------- (4ب) استثناء متصفح المصنع المحلي ----------------

def test_browser_policy_local_app_exception(monkeypatch):
    """الاستثناء: مغلق افتراضياً؛ يفتح منفذ المصنع وحده لا غير."""
    import sys as _sys
    _sys.path.insert(0, str(REPO / "src"))
    from browser.policy import BrowserPolicy, PolicyViolation

    monkeypatch.delenv("AES_BROWSER_ALLOW_LOCAL_APP", raising=False)
    policy = BrowserPolicy()
    for url in ("http://127.0.0.1:8011/x", "http://localhost:8011/x"):
        with pytest.raises(PolicyViolation):
            policy.check_url(url)

    monkeypatch.setenv("AES_BROWSER_ALLOW_LOCAL_APP", "8011")
    assert policy.check_url(
        "http://127.0.0.1:8011/api/projects/9/preview/index.html"
    ) == "127.0.0.1"
    assert policy.check_url("http://localhost:8011/y") == "localhost"
    for bad in ("http://127.0.0.1:8010/x", "http://localhost:9090/y",
                "http://10.0.0.64:8011/z", "http://127.0.0.2:8011/w",
                "file:///etc/passwd"):
        with pytest.raises(PolicyViolation):
            policy.check_url(bad)

    monkeypatch.setenv("AES_BROWSER_ALLOW_LOCAL_APP", "8011/")
    with pytest.raises(PolicyViolation):
        policy.check_url("http://127.0.0.1:9090/x")
