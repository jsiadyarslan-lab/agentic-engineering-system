"""Full baseline-vs-current failure diff for 013.5.

The previous checker only looked at a hand-written SUSPECTS list. A real
regression claim needs the whole failure set compared, so this script diffs
every FAILED/ERROR test id between the recorded baseline (9057c8d) and the
current full-suite log.
"""
from __future__ import annotations

import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
BASE = ROOT / "runtime" / "_baseline_9057c8d.txt"
CUR = ROOT / "runtime" / "logs" / "fullsuite-0135.log"

ID = re.compile(r"^(?:FAILED|ERROR)\s+(\S+)")


def load(path: Path) -> str:
    raw = path.read_bytes()
    for enc in ("utf-16", "utf-8-sig", "utf-8", "cp1256"):
        try:
            text = raw.decode(enc)
            if text.count("\x00") < 10:
                return text
        except UnicodeDecodeError:
            continue
    return raw.decode("utf-8", "replace")


def ids(text: str) -> set[str]:
    out: set[str] = set()
    for line in text.splitlines():
        m = ID.match(line.strip())
        if m:
            out.add(m.group(1))
    return out


def main() -> int:
    cur_path = Path(sys.argv[1]) if len(sys.argv) > 1 else CUR
    base = ids(load(BASE))
    cur = ids(load(cur_path))
    new = sorted(cur - base)
    fixed = sorted(base - cur)

    print(f"baseline failures : {len(base)}")
    print(f"current  failures : {len(cur)}")
    print(f"NEW failures (regressions) : {len(new)}")
    for t in new:
        print(f"   + {t}")
    print(f"no-longer-failing : {len(fixed)}")
    for t in fixed[:25]:
        print(f"   - {t}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
