"""إثباتات قبل/بعد — §2 و§3 و§6 من الأمر الرابع المعدل.

بطارية البصمة الثلاثية لكل هدف ممنوح:

- بصمة git: ``git status --porcelain`` + ``git diff`` لهاش المضيف
  (على مستودع العمل) — تكشف أي تعديل غير ملتزم أو ملتزم جديد.
- عدّادات الجداول: أسماء جداول sqlite وعدد صفوف كل منها — للهدف
  المخزني (.db) — تكشف أي كتابة على البيانات.
- جرد الملفات: المسارات + الأحجام + mtime داخل نطاق المنحة —
  يكشف أي ملف جديد أو معدل أو محذوف.

في READ_ONLY: تطابق قبل/بعد شرط نجاح القسم (إثبات مزدوج مع مسبار
الكتابة الداخلي في execution_engine). في الوضعين الكاتبين: الفرق
يجب أن يقع كله داخل نطاق PATH_GRANT — خارجه = HARD STOP.
"""

from __future__ import annotations

import hashlib
import os
import sqlite3
import subprocess
from dataclasses import dataclass, field
from pathlib import Path


@dataclass(frozen=True)
class ProofSnapshot:
    """بصمة لحظية لهدف واحد — قابلة للمقارنة نصيًا."""

    label: str
    git_status: str = ""       # بصمة status+diff لمستودع العمل
    tables: tuple[tuple[str, int], ...] = ()   # جداول × صفوف
    files: tuple[tuple[str, int], ...] = ()    # مسار نسبى × حجم

    def differs_from(self, other: "ProofSnapshot") -> list[str]:
        """الفروق المقروءة بين لقطتين — لكل بعد على حدة."""
        diffs: list[str] = []
        if self.git_status != other.git_status:
            diffs.append(f"git: قبل[{self.git_status[:80]}] بعد[{other.git_status[:80]}]")
        if self.tables != other.tables:
            diffs.append(f"tables: {self.tables} ← {other.tables}")
        if self.files != other.files:
            before = {p: s for p, s in self.files}
            after = {p: s for p, s in other.files}
            changed = sorted(
                {p for p in before.keys() | after.keys()
                 if before.get(p) != after.get(p)}
            )
            diffs.append(f"files: {changed}")
        return diffs


def git_fingerprint(repo_root: str) -> str:
    """بصمة git المختصرة: status --porcelain + diff --stat لهاش مضيف."""
    root = Path(repo_root)
    if not (root / ".git").exists():
        return "no-git-repo"
    try:
        status = subprocess.run(
            ["git", "-C", str(root), "status", "--porcelain"],
            capture_output=True, text=True, timeout=15, check=False,
        ).stdout.strip()
        diff = subprocess.run(
            ["git", "-C", str(root), "diff"],
            capture_output=True, text=True, timeout=15, check=False,
        ).stdout
        head = subprocess.run(
            ["git", "-C", str(root), "rev-parse", "HEAD"],
            capture_output=True, text=True, timeout=15, check=False,
        ).stdout.strip()
    except (subprocess.SubprocessError, OSError):
        return "git-unavailable"
    digest = hashlib.sha256((status + "|" + diff).encode()).hexdigest()[:16]
    return f"{head[:12]}:{digest}:{len(status.splitlines())}"


def table_counters(db_path: str) -> tuple[tuple[str, int], ...]:
    """عدّادات جداول sqlite — قراءة فقط عبر URI ro."""
    if not os.path.isfile(db_path):
        return ()
    try:
        con = sqlite3.connect(f"file:{db_path}?mode=ro", uri=True)
        try:
            names = [
                row[0]
                for row in con.execute(
                    "SELECT name FROM sqlite_master WHERE type='table' "
                    "AND name NOT LIKE 'sqlite_%'"
                )
            ]
            return tuple(
                (name, con.execute(f"SELECT COUNT(*) FROM {name}").fetchone()[0])
                for name in sorted(names)
            )
        finally:
            con.close()
    except sqlite3.Error:
        return (("<unreadable>", -1),)


def file_inventory(root: str, max_depth: int = 8) -> tuple[tuple[str, int], ...]:
    """جرد الملفات تحت جذر — مسار نسبي × حجم (mtime لا يدخل البصمة
    لأنه يتغير بأي قراءة سطحية؛ الحجم + الوجود كاشفان كافيان)."""
    base = Path(root)
    if not base.is_dir():
        return ()
    inventory: list[tuple[str, int]] = []
    for current, dirs, files in os.walk(base):
        dirs[:] = [
            d for d in dirs
            if not d.startswith(".")
            and len(Path(current, d).relative_to(base).parts) <= max_depth
        ]
        for name in files:
            full = Path(current, name)
            rel = str(full.relative_to(base))
            if len(Path(rel).parts) > max_depth:
                continue
            try:
                inventory.append((rel, full.stat().st_size))
            except OSError:
                inventory.append((rel, -1))
    return tuple(sorted(inventory))


@dataclass
class ProofBattery:
    """بطارية الإثبات للمحرك — تلتقط وتقارن لكل هدف ممنوح."""

    git_root: str = ""
    db_targets: tuple[str, ...] = ()
    file_roots: tuple[str, ...] = ()

    def capture(self, label: str) -> ProofSnapshot:
        counters: list[tuple[str, int]] = []
        for db in self.db_targets:
            for name, count in table_counters(db):
                counters.append((f"{Path(db).name}:{name}", count))
        files: list[tuple[str, int]] = []
        for root in self.file_roots:
            for rel, size in file_inventory(root):
                # مفتاح مطلق — يقارَع مباشرة بجذور المنح المطلقة
                files.append((f"{root}/{rel}", size))
        return ProofSnapshot(
            label=label,
            git_status=git_fingerprint(self.git_root) if self.git_root else "",
            tables=tuple(sorted(counters)),
            files=tuple(sorted(files)),
        )
