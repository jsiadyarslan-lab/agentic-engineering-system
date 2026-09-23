"""Trace a single contaminated message through events (diagnostics only)."""
import json
import sqlite3
import sys

db = sys.argv[1] if len(sys.argv) > 1 else "runtime/agent_hub_v2.db"
needle = sys.argv[2] if len(sys.argv) > 2 else "msg-97b852e902"
con = sqlite3.connect(db)
con.row_factory = sqlite3.Row
rows = con.execute(
    "select rowid, * from events where cast(payload as text) like ? order by rowid",
    (f"%{needle}%",)).fetchall()
print("matching rows:", len(rows))
seen_cycles = {}
for row in rows:
    p = json.loads(row["payload"])
    key = (p.get("cycle_id"), p.get("seq"))
    seen_cycles.setdefault(p.get("cycle_id"), []).append(p.get("seq"))
    if len(seen_cycles[p.get("cycle_id")]) <= 3:
        print("----")
        print(json.dumps({k: v for k, v in p.items()
                          if k not in ("delta", "text", "content")},
                         ensure_ascii=False)[:500])
        print("delta:", str(p.get("delta") or p.get("text") or "")[:200])
for c, seqs in seen_cycles.items():
    print("CYCLE", c, "count", len(seqs), "seq range",
          (min(s for s in seqs if s is not None) if any(
              s is not None for s in seqs) else None),
          (max(s for s in seqs if s is not None) if any(
              s is not None for s in seqs) else None))

print("=" * 70)
# distinct cycle_ids present in the events table
from collections import Counter
counter = Counter()
for row in con.execute("select payload from events"):
    try:
        p = json.loads(row["payload"])
    except Exception:  # noqa: BLE001
        continue
    counter[str(p.get("cycle_id"))] += 1
print("cycle_id histogram:", counter.most_common(30))
