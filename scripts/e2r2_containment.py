#!/usr/bin/env python3
"""E2-R2 §4 — Canonical evidence containment proof harness.

Captures a complete inventory (path, size, sha256, mtime) of the canonical
evidence tree (docs/evidence/) before and after a test run, and compares them.

Exit code 0  -> CANONICAL_EVIDENCE_MUTATION = 0 (containment proven)
Exit code 1  -> canonical evidence mutated (containment FAILED)

Usage:
    python3 e2r2_containment.py before <outfile.json>
    python3 e2r2_containment.py after <outfile.json>
    python3 e2r2_containment.py compare <before.json> <after.json> <report.json>
"""
from __future__ import annotations

import hashlib
import json
import os
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
CANONICAL_ROOT = REPO_ROOT / "docs" / "evidence"


def _git_head() -> str:
    try:
        return subprocess.run(
            ["git", "rev-parse", "HEAD"], capture_output=True, text=True,
            cwd=str(REPO_ROOT), timeout=15,
        ).stdout.strip()
    except Exception:
        return "unavailable"


def snapshot(out_file: Path) -> dict:
    files = {}
    for dirpath, _dirnames, filenames in os.walk(CANONICAL_ROOT):
        for name in sorted(filenames):
            p = Path(dirpath) / name
            rel = str(p.relative_to(REPO_ROOT)).replace("\\", "/")
            h = hashlib.sha256()
            with open(p, "rb") as f:
                for chunk in iter(lambda: f.read(65536), b""):
                    h.update(chunk)
            st = p.stat()
            files[rel] = {
                "sha256": h.hexdigest(),
                "size": st.st_size,
                "mtime_ns": st.st_mtime_ns,
            }
    snap = {
        "captured_at": datetime.now(timezone.utc).isoformat(),
        "canonical_root": "docs/evidence",
        "git_head": _git_head(),
        "file_count": len(files),
        "tree_sha256": hashlib.sha256(
            "".join(f"{k}:{files[k]['sha256']}\n" for k in sorted(files)).encode("utf-8")
        ).hexdigest(),
        "files": files,
    }
    out_file.parent.mkdir(parents=True, exist_ok=True)
    out_file.write_text(json.dumps(snap, indent=2, sort_keys=True), encoding="utf-8")
    return snap


def compare(before_file: Path, after_file: Path, report_file: Path) -> dict:
    before = json.loads(before_file.read_text(encoding="utf-8"))
    after = json.loads(after_file.read_text(encoding="utf-8"))
    b_files, a_files = before["files"], after["files"]

    added = sorted(set(a_files) - set(b_files))
    removed = sorted(set(b_files) - set(a_files))
    modified = sorted(
        k for k in set(b_files) & set(a_files)
        if b_files[k]["sha256"] != a_files[k]["sha256"]
    )
    # mtime-only changes (content identical) are recorded but not counted as mutation
    touched_only = sorted(
        k for k in set(b_files) & set(a_files)
        if b_files[k]["sha256"] == a_files[k]["sha256"]
        and b_files[k]["mtime_ns"] != a_files[k]["mtime_ns"]
    )

    mutation_count = len(added) + len(removed) + len(modified)
    report = {
        "compared_at": datetime.now(timezone.utc).isoformat(),
        "before_tree_sha256": before["tree_sha256"],
        "after_tree_sha256": after["tree_sha256"],
        "before_file_count": before["file_count"],
        "after_file_count": after["file_count"],
        "added": added,
        "removed": removed,
        "modified_content": modified,
        "touched_only_identical_content": touched_only,
        "canonical_evidence_mutation": mutation_count,
        "verdict": "CONTAINMENT_PROVEN" if mutation_count == 0 else "CONTAINMENT_FAILED",
    }
    report_file.parent.mkdir(parents=True, exist_ok=True)
    report_file.write_text(json.dumps(report, indent=2, sort_keys=True), encoding="utf-8")
    return report


def main() -> int:
    if len(sys.argv) < 3:
        print(__doc__)
        return 2
    mode = sys.argv[1]
    if mode == "before" or mode == "after":
        snap = snapshot(Path(sys.argv[2]).resolve())
        print(f"[{mode}] files={snap['file_count']} tree_sha256={snap['tree_sha256']}")
        return 0
    if mode == "compare":
        report = compare(Path(sys.argv[2]).resolve(), Path(sys.argv[3]).resolve(),
                         Path(sys.argv[4]).resolve())
        print(json.dumps({k: v for k, v in report.items() if k != "files"}, indent=2))
        return 0 if report["canonical_evidence_mutation"] == 0 else 1
    print(__doc__)
    return 2


if __name__ == "__main__":
    sys.exit(main())
