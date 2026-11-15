#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
R1 §4 — إعادة توليد MANIFEST.json و SHA256SUMS لحزمة أدلة rearchitecture-001
بعد تعديلات R1 (يشمل أدلة r1/ الجديدة). نفس بنية الملفين الأصليين.
"""

import hashlib
import json
import time
from pathlib import Path

EV = Path("/home/z/my-project/r1fix/docs/rearchitecture-001")

# اجمع كل الملفات (باستثناء الشاهدَين نفسيهما ثم يُضافان)
skip_names = {"SHA256SUMS", "MANIFEST.json"}
entries = []
for p in sorted(EV.rglob("*")):
    if p.is_file() and p.name not in skip_names:
        entries.append(p)

# بصمات كل الملفات (بما فيها الشاهدَان في النهاية)
def sha256_of(path):
    h = hashlib.sha256()
    with open(path, "rb") as f:
        for chunk in iter(lambda: f.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()

files_meta = [{"path": str(p.relative_to(EV)), "bytes": p.stat().st_size}
              for p in entries]

old_manifest = json.loads((EV / "MANIFEST.json").read_text(encoding="utf-8"))

r1_audit = json.loads((EV / "r1" / "audit.json").read_text(encoding="utf-8"))
r1_shots = sorted(p.name for p in (EV / "r1" / "screenshots").glob("*.png"))
n_r1_audit_shots = sum(1 for s in r1_shots if "_" in s and not s.startswith("R1"))
n_r1_func_shots = sum(1 for s in r1_shots if s.startswith("R1") and not s.startswith("R1F_M"))
n_r1_drawer_shots = sum(1 for s in r1_shots if s.startswith("R1F_M"))

manifest = {
    "generated_at_utc": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
    "before_provenance": old_manifest["before_provenance"],
    "counts": {
        **old_manifest["counts"],
        "r1_audit_shots_51": n_r1_audit_shots,
        "r1_functional_shots": n_r1_func_shots,
        "r1_drawer_flow_shots": n_r1_drawer_shots,
    },
    "audit": old_manifest["audit"],
    "audit_r1": {
        "shots": r1_audit["summary"]["shots"],
        "overflow_failures": r1_audit["summary"]["overflow_failures"],
        "mobile_drawer_open_failures": r1_audit["summary"]["mobile_drawer_open_failures"],
        "js_error_failures": r1_audit["summary"]["js_error_failures"],
        "mobile_drawer_flow": r1_audit["summary"]["mobile_drawer_flow"],
    },
    "files": files_meta + [
        {"path": "MANIFEST.json", "bytes": None},  # يُملأ أدناه بعد التوليد
    ],
    "r1_note": "R1 evidence regenerated after FIX A/B/C — semantic truth & evidence reconciliation",
}

# SHA256SUMS: كل الملفات مرتبة (المسارات النسبية) — الشاهدَان ضمنها
all_for_sums = sorted(
    [p for p in EV.rglob("*") if p.is_file() and p.name != "SHA256SUMS"],
    key=lambda p: str(p.relative_to(EV)),
)
lines = []
for p in all_for_sums:
    lines.append("%s  %s" % (sha256_of(p), str(p.relative_to(EV))))
(EV / "SHA256SUMS").write_text("\n".join(lines) + "\n", encoding="utf-8")

# MANIFEST أخيرًا: حجمه الحقيقي بعد كتابة SHA256SUMS، وبصمته لا تدخل في ملفها
manifest["files"] = [
    {"path": str(p.relative_to(EV)), "bytes": p.stat().st_size}
    for p in sorted([q for q in EV.rglob("*") if q.is_file() and q.name != "MANIFEST.json"],
                    key=lambda q: str(q.relative_to(EV)))
]
(EV / "MANIFEST.json").write_text(
    json.dumps(manifest, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")

print("SHA256SUMS lines:", len(lines) + 1, "(+MANIFEST.json not self-hashed)")
print("MANIFEST files:", len(manifest["files"]))
print("counts:", json.dumps(manifest["counts"], ensure_ascii=False))
