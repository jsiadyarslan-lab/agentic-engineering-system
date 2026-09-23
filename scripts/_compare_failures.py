"""Compare baseline vs current pytest failure lists (diagnostics only)."""
import re
import sys

def load(path):
    out = set()
    raw = open(path, "rb").read()
    for enc in ("utf-8-sig", "utf-16", "utf-8", "latin-1"):
        try:
            text = raw.decode(enc)
        except (UnicodeDecodeError, UnicodeError):
            continue
        found = set()
        for line in text.splitlines():
            m = re.match(r"^(?:FAILED|ERROR)\s+(\S+)", line.strip())
            if m:
                found.add(m.group(1))
        if found:
            return found
        out = found
    return out

base = load(sys.argv[1])
cur = load(sys.argv[2])
only_cur = sorted(cur - base)
fixed = sorted(base - cur)
print(f"baseline failures: {len(base)}")
print(f"current  failures: {len(cur)}")
print(f"--- NEW (regressions): {len(only_cur)} ---")
for t in only_cur:
    print("  +", t)
print(f"--- FIXED (baseline-only): {len(fixed)} ---")
for t in fixed:
    print("  -", t)
