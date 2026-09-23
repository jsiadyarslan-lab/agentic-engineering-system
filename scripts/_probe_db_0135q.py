"""مسبار قراءة فقط — شكل القاعدة الحية قبل سكربت الفوضى."""
import sqlite3

con = sqlite3.connect("file:runtime/agent_hub_v2.db?mode=ro", uri=True)
tables = [r[0] for r in con.execute(
    "select name from sqlite_master where type='table' order by name")]
print("TABLES:", tables)
print("planning_sessions cols:",
      [r[1] for r in con.execute("pragma table_info(planning_sessions)")])
print("planning rows:", con.execute(
    "select count(*) from planning_sessions").fetchone()[0])
print("last planning:", con.execute(
    "select id,project_id,state,error_class,error_detail,actual_provider,"
    "actual_model,reasoning_chars,plan_id,finished_at,started_at,"
    "heartbeat_at,hard_deadline_at,attempt from planning_sessions "
    "order by id desc limit 5").fetchall())
print("last projects:", con.execute(
    "select id,name,status,last_error from projects order by id desc "
    "limit 5").fetchall())
print("project_events cols:", [r[1] for r in con.execute(
    "pragma table_info(project_events)")])
print("last events:", con.execute(
    "select id,project_id,kind,created_at from project_events order by id "
    "desc limit 8").fetchall())
