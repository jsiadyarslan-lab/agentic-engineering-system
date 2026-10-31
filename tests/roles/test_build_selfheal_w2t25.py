"""اختبارات الإصلاح الذاتي لسكربت البناء (W2-T25 — قياس 802/807/849).

الدافع المقيس: ثلاث خطط ماتت بنمط واحد — `npm run build` بلا سكربت
build في package.json. العقد الأصلي: شفاء مقيد (build حصرًا، إطار
معروف، package.json صالح، إعادة مرة واحدة، تسجيل self_heal كامل).
القياس 849 (v91): tsconfig.json كُتب قبل next.config فلم يُعرف
الإطار من ملف إعداده وبقي الفشل الصادق — الكشف يُكمل من اعتماديات
package.json (next/astro في dependencies أو devDependencies).
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO / "src"))

from roles.build_selfheal import heal_and_rerun  # noqa: E402

_GREET = ["/bin/sh", "-c", "echo healed-build; exit 0"]
_FAIL = ["/bin/sh", "-c", "echo boom >&2; exit 3"]
_MISSING = b'npm error Missing script: "build"\nnpm error   npm run\n'


def _pkg(tmp_path: Path, **extra) -> Path:
    pkg = {"name": "x", "version": "0.0.1"}
    pkg.update(extra)
    p = tmp_path / "package.json"
    p.write_text(json.dumps(pkg), encoding="utf-8")
    return p


def _rerun(workdir, command="npm run build", stderr=_MISSING,
           argv=_GREET):
    return heal_and_rerun(workdir, command, stderr, argv, {}, 30.0)


def test_heals_via_next_config_file(tmp_path):
    """next.config موجود → build=next build ويُعاد الأمر بنجاح."""
    (tmp_path / "next.config.js").write_text("module.exports = {}\n")
    _pkg(tmp_path)
    out = _rerun(tmp_path)
    assert out is not None and out[0] == 0
    assert out[4]["script_command"] == "next build"
    assert out[4]["healed"] is True


def test_heals_via_package_deps_without_config(tmp_path):
    """قياس 849: لا next.config بعد، وnext في dependencies → شفاء."""
    _pkg(tmp_path, dependencies={"next": "14.2.0", "react": "^18"})
    out = _rerun(tmp_path)
    assert out is not None and out[0] == 0
    assert json.loads((tmp_path / "package.json").read_text())[
        "scripts"]["build"] == "next build"


def test_heals_via_dev_deps_astro(tmp_path):
    """astro في devDependencies وحدها → astro build."""
    _pkg(tmp_path, devDependencies={"astro": "^4"})
    out = _rerun(tmp_path)
    assert out is not None and out[4]["script_command"] == "astro build"


def test_existing_build_script_untouched(tmp_path):
    """سكربت build موجود فعلًا → لا شفاء ولا مساس بالملف."""
    _pkg(tmp_path, scripts={"build": "webpack"})
    before = (tmp_path / "package.json").read_text()
    assert _rerun(tmp_path) is None
    assert (tmp_path / "package.json").read_text() == before


def test_corrupt_package_json_honest_failure(tmp_path):
    """package.json تالفة → None والملف كما هو."""
    (tmp_path / "package.json").write_text("{not json", encoding="utf-8")
    assert _rerun(tmp_path) is None


def test_no_known_framework_no_guess(tmp_path):
    """لا ملف إعداد ولا اعتمادية معروفة → لا تخمين أعمى."""
    _pkg(tmp_path, dependencies={"lodash": "^4"})
    assert _rerun(tmp_path) is None


def test_other_stderr_not_healed(tmp_path):
    """خطأ غير «Missing script» → فشل صادق يبقى كما هو."""
    _pkg(tmp_path, dependencies={"next": "14"})
    assert _rerun(tmp_path, stderr=b"TypeError: boom\n") is None


def test_non_build_script_not_healed(tmp_path):
    """«npm run lint» → خارج نطاق الشفاء حصرًا (سكربت غير build)."""
    _pkg(tmp_path, dependencies={"next": "14"})
    assert _rerun(tmp_path, command="npm run lint") is None


def test_rerun_failure_recorded_honestly(tmp_path):
    """الشفاء أضاف السكربت ثم أُعيد الأمر ففشل → الخماسية بفشل صادق."""
    _pkg(tmp_path, dependencies={"next": "14"})
    out = _rerun(tmp_path, argv=_FAIL)
    assert out is not None and out[0] == 3
    assert out[4]["healed"] is True
    assert b"boom" in out[2]


def test_scripts_non_dict_rejected(tmp_path):
    """scripts بنية شاذة (نص) → لا دخول ولا شفاء."""
    _pkg(tmp_path, scripts="not-a-dict", dependencies={"next": "14"})
    assert _rerun(tmp_path) is None


def test_heal_record_shape(tmp_path):
    """سجل self_heal كامل الحقول ليعرف المراجع ما جرى."""
    _pkg(tmp_path, dependencies={"next": "14"})
    out = _rerun(tmp_path)
    rec = out[4]
    assert set(rec) == {"healed", "added_script", "script_command",
                        "package_json"}
    assert rec["added_script"] == "build"
    assert rec["package_json"].endswith("package.json")


# ——— قياس 863 (v92): مديرو حزم آخرون وسلاسل فقد أخرى ———

_PNPM_MISSING = ('Error: ERR_PNPM_RECURSIVE_EXEC_FIRST_FAIL\n\n'
                 '  \u00d7 Command "build" not found\n').encode("utf-8")
_YARN_MISSING = b'error Command "build" not found.'


def test_pnpm_build_heals(tmp_path):
    """قياس 863: `pnpm build` بسلسلة pnpm → شفاء من الاعتماديات."""
    _pkg(tmp_path, dependencies={"next": "14.2.0"})
    out = _rerun(tmp_path, command="pnpm build", stderr=_PNPM_MISSING)
    assert out is not None and out[0] == 0
    assert out[4]["script_command"] == "next build"
    assert json.loads((tmp_path / "package.json").read_text())[
        "scripts"]["build"] == "next build"


def test_pnpm_run_build_and_yarn_build_heal(tmp_path):
    """`pnpm run build` و`yarn build` بنمط فقد السكربت عند كل منهما."""
    _pkg(tmp_path, devDependencies={"astro": "^4"})
    assert _rerun(tmp_path, command="pnpm run build",
                  stderr=_PNPM_MISSING)[4]["script_command"] == "astro build"
    _pkg(tmp_path, dependencies={"next": "14"})
    out = _rerun(tmp_path, command="yarn build", stderr=_YARN_MISSING)
    assert out is not None and out[4]["script_command"] == "next build"


def test_bun_and_npm_run_build_still_heal(tmp_path):
    """`bun build` و`npm run build` يبقيان داخل النطاق بعد التوسعة."""
    _pkg(tmp_path, dependencies={"next": "14"})
    assert _rerun(tmp_path, command="bun build",
                  stderr=_YARN_MISSING) is not None
    assert _rerun(tmp_path, command="npm run build") is not None


def test_unknown_pm_and_non_build_scripts_rejected(tmp_path):
    """مدير مجهول أو سكربت غير build → لا دخول حتى بسلسلة خطأ مطابقة."""
    _pkg(tmp_path, dependencies={"next": "14"})
    assert _rerun(tmp_path, command="deno build",
                  stderr=_YARN_MISSING) is None
    assert _rerun(tmp_path, command="pnpm lint",
                  stderr=_PNPM_MISSING) is None
    assert _rerun(tmp_path, command="pnpm test",
                  stderr=b'Missing script: "test"') is None


def test_pnpm_build_existing_script_untouched(tmp_path):
    """`pnpm build` والسكربت موجود فعلًا → لا شفاء ولا مساس."""
    _pkg(tmp_path, scripts={"build": "vite build"},
        dependencies={"next": "14"})
    before = (tmp_path / "package.json").read_text()
    assert _rerun(tmp_path, command="pnpm build",
                  stderr=_PNPM_MISSING) is None
    assert (tmp_path / "package.json").read_text() == before
