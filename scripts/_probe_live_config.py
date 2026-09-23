"""Dump live runtime truth: planning sessions, projects, and recent LLM calls."""
from __future__ import annotations

import json
import sqlite3
from pathlib import Path

DB = Path("runtime/agent_hub_v2.db")


def cols(con: sqlite3.Connection, table: str) -> list[str]:
    return [r[1] for r in con.execute(f"pragma table_info({table})")]


def dump(con: sqlite3.Connection, table: str, limit: int = 8) -> None:
    cs = cols(con, table)
    print(f"\n=== {table} ===")
    print("   cols:", ", ".join(cs))
    try:
        for row in con.execute(f"select * from {table} order by rowid desc limit {limit}"):
            d = dict(zip(cs, row))
            print("  ", json.dumps(d, ensure_ascii=False, default=str)[:400])
    except Exception as exc:  # noqa: BLE001
        print("   ERR", exc)


def main() -> None:
    con = sqlite3.connect(DB)
    for table in ("planning_sessions", "projects", "provider_configurations", "conversations", "messages"):
        dump(con, table)


if __name__ == "__main__":
    main()
