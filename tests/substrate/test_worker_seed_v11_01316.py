"""اختبارات بذر الملفات في بروتوكول العامل v1.1 (013.16 §1).

الفجوة الموثقة قبل الإصلاح (دليل حي: protocol_v1_gap_prior_failure_*
— دورة mission-ca7172c1f346 انتهت HARD STOP بفشلين تنفيذيين
FileNotFoundError): بروتوكول v1 يعطي كل تشغيل مجلد أدلة مؤقتًا فارغًا
لدى العامل، فتعمل كتابة الملف (يعيدها في الاستجابة) لكن «اكتب ثم شغّل»
مستحيل. البذر (v1.1) يكتب ملفات الطالب في مجلد أدوات التشغيل قبل
الإقلاع — تُختبر هنا عبر الوحدة نفسها التي ينفذ بها العامل داخل
الركيزة الحقيقية على هذه الجلسة.
"""

from __future__ import annotations

import base64
import importlib.util
import sys
from pathlib import Path

_WORKER_PATH = (
    Path(__file__).resolve().parents[2] / "scripts" / "execution_worker.py"
)


def _load_worker_module():
    spec = importlib.util.spec_from_file_location(
        "execution_worker_01316", _WORKER_PATH
    )
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def _b64(text: str) -> str:
    return base64.b64encode(text.encode()).decode()


def test_safe_seed_name_refuses_escapes():
    """أسماء البذر: المسار النسبي الآمن يقبل، والهروب/المطلق يُرفض."""
    worker = _load_worker_module()
    assert worker._safe_seed_name("tool.py") is not None
    assert worker._safe_seed_name("sub/dir/file.csv") is not None
    assert worker._safe_seed_name("../escape.txt") is None
    assert worker._safe_seed_name("/etc/passwd") is None
    assert worker._safe_seed_name("") is None
    assert worker._safe_seed_name("a" * 201) is None


def test_write_then_run_sequence_through_worker_substrate():
    """التسلسل الكامل عبر وحدة العامل: كتابة في تشغيل، بذر وتشغيل في
    التشغيل التالي — الكود الثاني يرى ملفات الأول داخل ‎/artifacts."""
    worker = _load_worker_module()

    # (1) تشغيل كتابة v1 — ملف يُعاد في الاستجابة
    write_code = (
        "import pathlib\n"
        "target = pathlib.Path('/artifacts/note.txt')\n"
        "target.write_text('written in run one', encoding='utf-8')\n"
        "print('wrote')\n"
    )
    first = worker._run_in_substrate(write_code, 60.0)
    assert first["exit_code"] == 0, first["stderr"]
    returned = {
        item["name"]: base64.b64decode(item["b64"]).decode()
        for item in first["artifacts"]
    }
    assert returned["note.txt"] == "written in run one"

    # (2) قبل v1.1: التشغيل التالي لا يرى الملف (مجلد مؤقت فارغ)
    read_code = (
        "import pathlib\n"
        "print(pathlib.Path('/artifacts/note.txt').read_text())\n"
    )
    without_seed = worker._run_in_substrate(read_code, 60.0)
    assert without_seed["exit_code"] != 0
    assert "FileNotFoundError" in without_seed["stderr"]

    # (3) v1.1: بذر الملف المرجَع — التشغيل يراه
    with_seed = worker._run_in_substrate(
        read_code, 60.0, {"note.txt": _b64(returned["note.txt"])}
    )
    assert with_seed["exit_code"] == 0, with_seed["stderr"]
    assert "written in run one" in with_seed["stdout"]


def test_seed_oversize_and_invalid_entries_skipped():
    """حدود البذر: ملف فوق 256KB ومدخل تالف يُتجاهلان بلا انفجار."""
    worker = _load_worker_module()
    code = (
        "import pathlib\n"
        "print(sorted(p.name for p in pathlib.Path('/artifacts').iterdir()))\n"
    )
    result = worker._run_in_substrate(code, 60.0, {
        "ok.txt": _b64("small"),
        "big.bin": _b64("x" * 262_145),
        "../escape": _b64("no"),
        "bad.b64": "not-base64!!",
    })
    assert result["exit_code"] == 0, result["stderr"]
    assert "['ok.txt']" in result["stdout"]
