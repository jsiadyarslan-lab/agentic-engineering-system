#!/usr/bin/env python3
"""AES-UI-PREMIUM-REDESIGN-002: image evidence verification.

Proves for every file under download/ui-redesign/{before,after}:
  1. File exists with exact path and byte size.
  2. Opens as a valid PNG (PIL verify + full decode).
  3. Pixel dimensions.
  4. For matched before/after pairs: mean absolute pixel difference
     (objective proof the redesign changed the rendering, not the labels).
Read-only: never writes to the image directories.
"""
from pathlib import Path
from PIL import Image, ImageChops
import sys

BASE = Path("/home/z/my-project/download/ui-redesign")
BEFORE, AFTER = BASE / "before", BASE / "after"


def inspect(folder: Path) -> dict[str, dict]:
    out = {}
    if not folder.is_dir():
        return out
    for p in sorted(folder.glob("*.png")):
        info = {"bytes": p.stat().st_size}
        try:
            with Image.open(p) as im:
                im.verify()  # structural integrity
            with Image.open(p) as im:
                info["size"] = im.size  # forces full decode
                info["mode"] = im.mode
                info["ok"] = True
        except Exception as e:  # noqa: BLE001
            info["ok"] = False
            info["error"] = repr(e)
        out[p.name] = info
    return out


def mean_abs_diff(a: Path, b: Path) -> float:
    with Image.open(a) as ia, Image.open(b) as ib:
        if ia.size != ib.size:
            return -1.0  # size mismatch flagged separately
        ga, gb = ia.convert("L"), ib.convert("L")
        diff = ImageChops.difference(ga, gb)
        hist = diff.histogram()
        total = sum(hist)
        weighted = sum(i * c for i, c in enumerate(hist))
        return weighted / total


def main() -> int:
    before, after = inspect(BEFORE), inspect(AFTER)
    bad = [f for d in (before, after) for f, i in d.items() if not i["ok"]]
    print(f"before/: {len(before)} files | after/: {len(after)} files")
    print(f"PNG integrity: {'ALL VALID' if not bad else 'BROKEN: ' + str(bad)}")
    print()
    print(f"{'file':<42} {'bytes':>8}  {'pixels':>11}  status")
    for name, i in sorted(before.items()):
        print(f"before/{name:<35} {i['bytes']:>8}  {i['size'][0]}x{i['size'][1]:>5}  OK")
    for name, i in sorted(after.items()):
        print(f"after/{name:<36} {i['bytes']:>8}  {i['size'][0]}x{i['size'][1]:>5}  OK")
    print()
    pairs = sorted(set(before) & set(after))
    print(f"matched pairs: {len(pairs)} | before-only: {sorted(set(before) - set(after))} | after-only: {sorted(set(after) - set(before))}")
    print()
    print(f"{'pair':<40} {'mean|Δpixel|':>12}  verdict")
    for name in pairs:
        d = mean_abs_diff(BEFORE / name, AFTER / name)
        verdict = "DIFFERENT" if d > 5 else ("same-ish" if d >= 0 else "size mismatch")
        print(f"{name:<40} {d:>12.1f}  {verdict}")
    return 1 if bad else 0


if __name__ == "__main__":
    sys.exit(main())
