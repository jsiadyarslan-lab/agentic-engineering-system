"""أدوات اختبار EOE المشتركة — ركيزة حقيقية + مستودعات اختبار حقيقية."""
from __future__ import annotations

import subprocess
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "src"))

from substrate.factory import (  # noqa: E402
    default_sandbox_images,
    make_sandbox_manager,
    sandbox_git_image,
    substrate_available,
    substrate_failure_reason,
)

FIXTURES = Path(__file__).parent / "fixtures"
V1_DB_DIR = Path("/home/z/my-project/agent-hub/runtime/db")


def _git(repo: Path, *args: str) -> subprocess.CompletedProcess:
    return subprocess.run(
        ["git", "-C", str(repo), *args],
        capture_output=True, text=True, timeout=30, check=False,
    )


def _session_skip_reason() -> str:
    return "لا ركيزة عزل متاحة على هذا المضيف — " + substrate_failure_reason()


@pytest.fixture(scope="session")
def sandbox_manager():
    """مدير ركيزة بصورتين: python (الافتراضية) و git (للدفع).

    AES-EXP-04 §3.3: الصور والمدير من المصنع الواحد (محلي x86_64 أو
    bwrap بقدرات مثبتة) — خارج التوفر: تخطٍ صادق ببيان السبب.
    """
    if not substrate_available():
        pytest.skip(_session_skip_reason())
    images = {**default_sandbox_images(), "git": sandbox_git_image()}
    manager = make_sandbox_manager(images=images)
    if manager is None:  # pragma: no cover — تناقض مع substrate_available
        pytest.skip(_session_skip_reason())
    return manager


@pytest.fixture()
def repo_factory(tmp_path):
    """مصنع مستودعات git حقيقية للاختبارات (بملفات وremote اختياري)."""
    def _make(subdir, *, files=None, remote=None, branch="main"):
        return make_repo(
            tmp_path / subdir, files=files, remote=remote, branch=branch
        )
    return _make


@pytest.fixture()
def jarvis_order() -> str:
    """نص أمر المالك — LESSON POPULATION REALITY AUDIT."""
    return (FIXTURES / "jarvis_prime_order.md").read_text(encoding="utf-8")


def make_repo(path: Path, *, files: dict[str, str] | None = None,
              remote: Path | None = None, branch: str = "main") -> Path:
    """مستودع git حقيقي للاختبار — بملفات والتزام أولي وremote اختياري."""
    path.mkdir(parents=True, exist_ok=True)
    _git(path, "init", "-b", branch)
    _git(path, "config", "user.email", "test@eoe.local")
    _git(path, "config", "user.name", "EOE Test")
    for name, content in (files or {"README.md": "test repo\n"}).items():
        target = path / name
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(content, encoding="utf-8")
    _git(path, "add", "-A")
    _git(path, "commit", "-m", "init")
    if remote is not None:
        bare = remote
        bare.mkdir(parents=True, exist_ok=True)
        subprocess.run(
            ["git", "init", "--bare", "-b", branch, str(bare)],
            capture_output=True, timeout=30, check=True,
        )
        _git(path, "push", str(bare), f"HEAD:refs/heads/{branch}")
        _git(path, "remote", "add", "origin", str(bare))
    return path
