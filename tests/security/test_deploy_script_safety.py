# -*- coding: utf-8 -*-
"""سلامة سكربتات النشر — AES-P0-CONTAINMENT-PR-REMEDIATION-1113-R1 (fix 5).

تُختبر البنية بالاستيراد والتحليل فقط — لا يُشغَّل أي سكربت نشر في هذه
المهمة ولا تُنفَّذ أي عمليات POST على أي خدمة (قيد الأمر R1).
"""
import importlib.util
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]
OC3 = REPO_ROOT / "w2t25-monitor-v2" / "apply_owner_console_v3.py"
AM2 = REPO_ROOT / "w2t25-monitor-v2" / "apply_monitor_v2.py"


def _load(path: Path):
    spec = importlib.util.spec_from_file_location(path.stem + "_r1test", str(path))
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def test_owner_console_import_is_side_effect_free():
    """قراءة الاعتماد كسولة — الاستيراد وحده لا يفتح أي ملف أسرار ولا يتصل بشيء."""
    mod = _load(OC3)
    assert callable(mod.load_token)


def test_owner_console_default_checks_are_get_only():
    mod = _load(OC3)
    default = mod.verification_checks(with_post=False, confirm=False)
    assert default is not None
    assert list(default) == list(mod.GET_CHECKS)
    for name, cmd in default:
        assert "-X POST" not in cmd, (name, cmd)
        assert "POST" not in cmd.replace("POST_CHECKS", ""), (name, cmd)


def test_owner_console_incomplete_optin_is_refused():
    mod = _load(OC3)
    assert mod.verification_checks(with_post=True, confirm=False) is None


def test_owner_console_dual_optin_unlocks_post_checks():
    mod = _load(OC3)
    both = mod.verification_checks(with_post=True, confirm=True)
    assert both is not None
    names = [n for n, _ in both]
    assert [n for n, _ in mod.POST_CHECKS] and all(
        n in names for n in [n for n, _ in mod.POST_CHECKS])


def test_owner_console_post_checks_are_only_state_changing_paths():
    mod = _load(OC3)
    for name, cmd in mod.POST_CHECKS:
        assert "127.0.0.1:8765" in cmd
        assert any(seg in cmd for seg in ("gates", "owner-mode", "plan/delete")), name


def test_owner_console_token_never_in_url_or_argv():
    mod = _load(OC3)
    for name, cmd in mod.GET_CHECKS + mod.POST_CHECKS:
        if "X-Access-Key" in cmd:
            # الترويسة تُمرر عبر stdin (-H @-) — القيمة ليست في argv
            assert cmd.count("-H @-") >= 1, (name, cmd)
            assert "$W2T25_MONITOR_TOKEN" in cmd
        assert "k=" not in cmd.replace("=", "").replace("==", "") or "?" not in cmd, (name, cmd)


def test_owner_console_source_has_dual_flags_and_warning():
    src = OC3.read_text(encoding="utf-8")
    assert "--with-post-checks" in src
    assert "--confirm-post-changes" in src
    assert "REFUSED" in src
    assert "WARNING" in src
    # لا توكن حرفي في المصدر — المصدر من متغير بيئة/ملف أسرار فقط
    assert 'TOKEN = "' not in src


def test_monitor_v2_import_is_side_effect_free_and_get_only():
    mod = _load(AM2)
    assert callable(mod.load_token)
    src = AM2.read_text(encoding="utf-8")
    assert "-X POST" not in src
    assert "-H @-" in src          # الترويسة عبر stdin
    assert "-H \"" not in src.replace('-H @-', "")  # لا ترويسة مباشرة في argv


def test_monitor_v2_no_query_string_auth():
    src = AM2.read_text(encoding="utf-8")
    assert "?k=" not in src
    assert "K=" not in src.replace("KEY", "").replace("OK", "")
