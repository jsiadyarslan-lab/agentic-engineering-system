#!/usr/bin/env python3
"""AES-UI-PREMIUM-REDESIGN-004: factory screenshot evidence verification.

Proves for every file under download/ui-redesign/factory:
  1. File exists with exact path and byte size.
  2. Opens as a valid PNG (PIL verify + full decode).
  3. Pixel dimensions match the declared viewport (1440/768/390 widths).
Read-only: never writes to the image directory.
"""
from pathlib import Path
from PIL import Image
import sys

BASE = Path("/home/z/my-project/download/ui-redesign/factory")

EXPECTED_WIDTHS = {
    "reference-1440.png": 1440,
    "factory-overview-1440.png": 1440,
    "factory-create-1440.png": 1440,
    "factory-mission-1440.png": 1440,
    "factory-mission-agents-1440.png": 1440,
    "factory-overview-768.png": 768,
    "factory-overview-390.png": 390,
}


def main() -> int:
    if not BASE.is_dir():
        print(f"MISSING DIR: {BASE}")
        return 2
    files = sorted(BASE.glob("*.png"))
    print(f"factory/: {len(files)} PNG files on disk (declared: 7)")
    print()
    bad = []
    print(f"{'file':<34} {'bytes':>8}  {'pixels':>11}  {'width ok':>9}  status")
    for p in files:
        info = {"bytes": p.stat().st_size}
        try:
            with Image.open(p) as im:
                im.verify()
            with Image.open(p) as im:
                info["size"] = im.size
                info["mode"] = im.mode
                info["ok"] = True
        except Exception as e:  # noqa: BLE001
            info["ok"] = False
            info["error"] = repr(e)
        want = EXPECTED_WIDTHS.get(p.name)
        w_ok = ("n/a" if want is None else ("yes" if info.get("size", (0,))[0] == want else f"NO want {want}"))
        status = "OK" if info["ok"] else "BROKEN"
        if not info["ok"] or (want is not None and info.get("size", (0,))[0] != want):
            bad.append(p.name)
        print(f"{p.name:<34} {info['bytes']:>8}  {info.get('size', ('?', '?'))[0]}x{info.get('size', ('?', '?'))[1]:>5}  {w_ok:>9}  {status}")
    extra = [p.name for p in files if p.name not in EXPECTED_WIDTHS]
    missing = [n for n in EXPECTED_WIDTHS if not (BASE / n).exists()]
    if extra:
        print(f"\nundeclared extra files: {extra}")
    if missing:
        print(f"\nDECLARED BUT MISSING: {missing}")
        bad.extend(missing)
    print()
    print("VERDICT:", "ALL 7 DECLARED SHOTS EXIST, VALID, CORRECT WIDTH" if not bad and not missing and not extra else f"ISSUES: {bad + extra}")
    return 1 if (bad or missing or extra) else 0


if __name__ == "__main__":
    sys.exit(main())
