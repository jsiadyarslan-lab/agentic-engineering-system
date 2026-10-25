"""الأمر 011 — ترقيم أصول الواجهة ببصمة الالتزام + سياسة كاش لكل نوع.

خلفية الأمر (AES-UI-LIVE-RECONCILIATION-011): الروابط المرقّمة في
index.html كانت ثابتة النص (?v=4.0.0) قبل إعادة التصميم وبعدها —
فانهارت طبقة الدفاع الثانية إلى الترويسات وحدها، وأي انحدار مستقبلي
في السياسة يعيد «الواجهة القديمة بعد التحديث». هذه العقود تثبت:

1. الخدمة تعيد ترقيم كل روابط الأصول وقت الطلب بهوية الإصدار الحي
   (بصمة الالتزام) — الملف على القرص يبقى حرفيًا كما تقرأه اختبارات
   البنية الأخرى.
2. etag الصفحة مشتق من البايتات المخدومة فيتغير مع كل إصدار،
   والتحقق الشرطي يعيد 304 للمطابق و200 لحامل النسخة القديمة.
3. سياسة الكاش لكل نوع: أصل مرقّم بهوية الإصدار الحي = تخزين طويل
   آمن؛ وما عداها (أو ترقيم غير حي) = no-cache تحقق رخيص.
"""

from __future__ import annotations

import subprocess
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parents[2]


def _git_blob(rel: str) -> bytes | None:
    try:
        proc = subprocess.run(
            ["git", "show", f"HEAD:{rel}"],
            cwd=REPO, capture_output=True, timeout=10,
        )
    except OSError:
        return None
    return proc.stdout if proc.returncode == 0 else None


@pytest.fixture()
def ui_client(api_env):
    from fastapi.testclient import TestClient

    from api import routes

    return TestClient(routes.app), routes


def test_asset_version_matches_commit_or_fingerprint():
    """هوية الإصدار 8 خانات hex: بصمة الالتزام حيث git متاح وإلا بصمة المحتوى."""
    import api.routes as routes

    ver = routes._ASSET_VERSION
    assert len(ver) == 8 and all(c in "0123456789abcdef" for c in ver)
    sha = subprocess.run(["git", "rev-parse", "--short=8", "HEAD"],
                         cwd=REPO, capture_output=True)
    if sha.returncode == 0:
        assert ver == sha.stdout.decode().strip(), \
            "في مستودع git يجب أن تكون الهوية بصمة الالتزام الحي"


def test_index_serves_current_version_urls_not_stale_literal(ui_client):
    """كل روابط الأصول تُخدم مرقّمة بهوية الإصدار الحي — صفر ?v=4.0.0."""
    client, routes = ui_client
    ver = routes._ASSET_VERSION
    r = client.get("/")
    assert r.status_code == 200
    assert r.text.count(f"?v={ver}") >= 27, "روابط الأصول غير مرقّمة بالإصدار الحي"
    assert "?v=4.0.0" not in r.text, "بقي ترقيم حرفي قديم في HTML المخدوم"
    # الملف على القرص يبقى حرفيًا (اختبارات البنية الأخرى تعتمد ذلك)
    disk = (REPO / "src" / "ui" / "index.html").read_text(encoding="utf-8")
    assert disk != r.text


def test_index_etag_version_derived_and_conditional(ui_client):
    """etag مشتق من البايتات المخدومة: مطابق=304، وحامل نسخة قديمة=200."""
    client, routes = ui_client
    ver = routes._ASSET_VERSION
    r = client.get("/")
    assert r.headers["etag"] == f'"ui{ver}"'
    assert r.headers["cache-control"] == "no-cache"
    r304 = client.get("/", headers={"If-None-Match": f'"ui{ver}"'})
    assert r304.status_code == 304
    stale = client.get("/", headers={"If-None-Match": '"ui00000000"'})
    assert stale.status_code == 200
    assert f"?v={ver}".encode() in stale.content


def test_cache_policy_per_asset_type(ui_client):
    """مرقّم حي = immutable طويل؛ وغير مرقّم أو قديم = no-cache؛ والصفحة no-cache."""
    client, routes = ui_client
    ver = routes._ASSET_VERSION
    cases = [
        (f"/static/theme.css?v={ver}", "public, max-age=31536000, immutable"),
        (f"/static/app.js?v={ver}", "public, max-age=31536000, immutable"),
        ("/static/theme.css?v=4.0.0", "no-cache"),
        ("/static/theme.css", "no-cache"),
        ("/static/fonts/fonts.css", "no-cache"),
        ("/", "no-cache"),
    ]
    for path, expect in cases:
        got = client.get(path).headers.get("cache-control")
        assert got == expect, f"{path}: {got!r} != {expect!r}"


def test_served_css_bytes_equal_git_blob(ui_client):
    """الترقيم يلمس HTML المخدوم وحده — بايتات الأصول مطابقة لالتزام git."""
    client, _ = ui_client
    blob = _git_blob("src/ui/theme.css")
    if blob is None:  # بيئة بلا git — البصمة تغطيها اختبارات أخرى
        pytest.skip("git غير متاح")
    served = client.get("/static/theme.css").content
    assert served == blob
