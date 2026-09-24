"""Show the live execution environments and how they fare under each policy."""
from __future__ import annotations

import json
import sqlite3
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

DB = Path("runtime/agent_hub_v2.db")


def main() -> None:
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    con = sqlite3.connect(DB)
    con.row_factory = sqlite3.Row
    print("=== execution_environments ===")
    cols = [r[1] for r in con.execute("pragma table_info(execution_environments)")]
    for row in con.execute("select * from execution_environments order by id"):
        d = dict(zip(cols, row))
        for key in ("profile_json", "last_probe_detail"):
            try:
                d[key] = json.loads(d.get(key) or "{}")
            except ValueError:
                pass
        print(json.dumps(d, ensure_ascii=False, default=str, indent=1)[:1200])

    print("\n=== runtime_state_records ===")
    cols = [r[1] for r in con.execute("pragma table_info(runtime_state_records)")]
    for row in con.execute("select * from runtime_state_records order by id desc limit 4"):
        print(json.dumps(dict(zip(cols, row)), ensure_ascii=False, default=str)[:900])

    print("\n=== runtime_truth from backends ===")
    from execution.backends import runtime_truth, discover_environments  # noqa: PLC0415
    truth = runtime_truth()
    print(json.dumps(truth, ensure_ascii=False, default=str, indent=1)[:1200])

    print("\n=== service.list_environments ===")
    from persistence.database import build_engine, init_db, make_session_factory  # noqa: PLC0415
    from execution import service as execution_service  # noqa: PLC0415
    engine = build_engine(DB)
    init_db(engine)
    sessions = make_session_factory(engine)
    for env in execution_service.list_environments(sessions):
        print(json.dumps(env, ensure_ascii=False, default=str)[:600])

    print("\n=== eligibility per policy ===")
    from execution import policy as execution_policy  # noqa: PLC0415
    envs = execution_service.list_environments(sessions)
    for pol in execution_policy.POLICIES:
        chosen = execution_service.select_environment(sessions, policy=pol)
        print(f"  {pol}: selected={chosen.get('name') if chosen else None}")
        for env in envs:
            print(f"     {env.get('name'):<24} "
                  f"satisfies={execution_policy.environment_satisfies(env, pol)}")


if __name__ == "__main__":
    main()
