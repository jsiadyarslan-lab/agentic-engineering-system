"""تحقق من اتساق مشروع 11: حالة المشروع مقابل جلسة التخطيط والخطة."""

import json
import sqlite3
import urllib.request

c = sqlite3.connect("file:runtime/agent_hub_v2.db?mode=ro", uri=True)
c.row_factory = sqlite3.Row

print("--- projects")
for r in c.execute("select id,name,status,current_plan_id,updated_at,"
                   "substr(coalesce(last_error,''),1,160) le "
                   "from projects order by id desc limit 6"):
    print(dict(r))

print("--- plans columns")
print([x[1] for x in c.execute("PRAGMA table_info(plans)")])
print("--- plans")
for r in c.execute("select id,project_id,version,status,created_at from plans "
                   "order by id desc limit 6"):
    print(dict(r))

print("--- project_events for 11 (last 25)")
for r in c.execute("select id,kind,created_at from project_events "
                   "where project_id=11 order by id desc limit 25"):
    print(dict(r))

with urllib.request.urlopen("http://127.0.0.1:8010/api/projects/11",
                            timeout=20) as response:
    body = json.loads(response.read().decode("utf-8", "replace"))
print("--- API project 11")
print(json.dumps(body, ensure_ascii=False)[:1200])
