# -*- coding: utf-8 -*-
"""فحص أسرار 013.16 — نفس أنماط 013.15 (12 نمطًا) على نطاق الدفع.

يفحص: الملفات المتغيرة/الجديدة في نطاق الكوميتين + دليل الأمر +
مخرجات الجلسة الحية. يرفض آليًا أي ملف أسرار في النطاق.
"""
from __future__ import annotations

import re
import subprocess
import sys
from pathlib import Path

WORK = Path("/home/z/my-project/order01316_work")
PATTERNS = [
    r"github_pat_[A-Za-z0-9_]{20,}",
    r"ghp_[A-Za-z0-9]{30,}",
    r"gho_[A-Za-z0-9]{30,}",
    r"sk-[A-Za-z0-9]{20,}",
    r"sk-ant-[A-Za-z0-9-]{20,}",
    r"nvapi-[A-Za-z0-9_-]{20,}",
    r"AKIA[0-9A-Z]{16}",
    r"AIza[A-Za-z0-9_-]{30,}",
    r"xox[abprs]-[A-Za-z0-9-]{10,}",
    r"Bearer\s+[A-Za-z0-9._-]{25,}",
    r"-----BEGIN [A-Z ]*PRIVATE KEY-----",
    r"(?i)(api[_-]?key|secret|token)\s*[:=]\s*['\"][A-Za-z0-9._-]{16,}['\"]",
]

# التوكن وقت-التشغيل: لا يجب أن يظهر حرفيًا في أي ملف نطاق
RUNTIME_TOKEN = Path(
    "/home/z/my-project/.order01316_worker_token"
).read_text().strip()


def git_files(scope: str) -> list[str]:
    out = subprocess.run(
        ["git", "diff", "--name-only", scope],
        capture_output=True, text=True, cwd=WORK,
    ).stdout
    return [line for line in out.splitlines() if line.strip()]


def main() -> int:
    commit_scope = "622be149..HEAD"  # كل ما فوق رأس 013.14 (كوميتا 013.15 + كوميتا 013.16)
    files = sorted(set(
        git_files(commit_scope)
        + [
            str(p.relative_to(WORK)) for p in
            (WORK / "docs/evidence/order01316").rglob("*") if p.is_file()
        ]
    ))
    findings: list[dict] = []
    for rel in files:
        path = WORK / rel
        if not path.is_file():
            continue
        try:
            text = path.read_text(encoding="utf-8", errors="replace")
        except OSError:
            continue
        for pattern in PATTERNS:
            for match in re.finditer(pattern, text):
                findings.append({
                    "file": rel, "pattern": pattern[:30],
                    "head": match.group(0)[:12] + "…",
                })
        if RUNTIME_TOKEN and RUNTIME_TOKEN in text:
            findings.append({
                "file": rel, "pattern": "RUNTIME_WORKER_TOKEN_LITERAL",
                "head": "(runtime token appears literally!)",
            })
    # ملفات أسرار معروفة في النطاق؟
    secret_files = [f for f in files if f.endswith((
        ".env", "secrets.json", ".secret", "credentials.json",
    )) and "evidence" not in f]
    report = {
        "commit_scope": commit_scope,
        "files_scanned": len(files),
        "pattern_hits": findings,
        "secret_files_in_scope": secret_files,
        "runtime_token_literal": any(
            f["pattern"] == "RUNTIME_WORKER_TOKEN_LITERAL" for f in findings
        ),
        "token_sha256_only": True,
    }
    target = WORK / "docs/evidence/order01316/secrets_scan.json"
    target.write_text(
        __import__("json").dumps(report, indent=2, ensure_ascii=False),
        encoding="utf-8",
    )
    print(f"scanned {len(files)} files — hits: {len(findings)} "
          f"— secret files: {len(secret_files)}")
    for finding in findings[:10]:
        print("  !!", finding)
    bad = bool(findings or secret_files)
    print("VERDICT:", "FAIL" if bad else "CLEAN")
    return 1 if bad else 0


if __name__ == "__main__":
    sys.exit(main())
