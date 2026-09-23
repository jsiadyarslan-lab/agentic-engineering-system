"""شكل حمولة message_delta في القاعدة — لأخذ نص الجواب من البث بدقة."""
import json
import sqlite3

con = sqlite3.connect("file:runtime/agent_hub_v2.db?mode=ro", uri=True)
rows = con.execute(
    "SELECT seq, payload FROM events "
    "WHERE cycle_id='chat-16' AND kind='message_delta' ORDER BY seq LIMIT 3"
).fetchall()
for seq, payload in rows:
    data = json.loads(payload or "{}")
    print(seq, "| top-level keys:", sorted(data.keys()))
    print("   details keys:", sorted((data.get("details") or {}).keys()))
    for key in ("delta", "text", "content", "chunk"):
        if key in data:
            print(f"   {key} = {str(data[key])[:70]!r}")
    for key in ("delta", "text", "content", "chunk"):
        if key in (data.get("details") or {}):
            print(f"   details.{key} = {str(data['details'][key])[:70]!r}")
