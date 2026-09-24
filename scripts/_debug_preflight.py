"""Debug the sandbox preflight issue."""
from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))
sys.path.insert(0, str(ROOT / "tests"))

import tempfile
import sqlalchemy as sa
from persistence.database import build_engine, init_db, make_session_factory
from execution import service as execution_service
from execution import policy as execution_policy
from execution.models import ExecutionEnvironment
from providers_registry import registry
from readiness import preflight as preflight_mod


def main():
    with tempfile.TemporaryDirectory() as tmp:
        db_path = Path(tmp) / "test.db"
        engine = build_engine(db_path)
        init_db(engine)
        sessions = make_session_factory(engine)
        registry.ensure_seeded(sessions)

        # Ensure local environment
        execution_service.ensure_local_registered(sessions)
        
        # List environments before
        envs = execution_service.list_environments(sessions)
        print("Before sandbox_env:")
        for e in envs:
            print(f"  {e['name']}: status={e['status']}, sandboxed={e['sandboxed']}, is_default={e['is_default']}")
        
        # Apply sandbox_env like the test
        with sessions() as s:
            row = s.scalars(sa.select(ExecutionEnvironment).where(
                ExecutionEnvironment.name.in_(("local-linux", "local-windows"))
            )).first()
            print(f"\nRow found: {row.name if row else None}")
            if row:
                row.status = "READY"
                row.sandboxed = 1
                s.commit()
                print(f"Updated: status={row.status}, sandboxed={row.sandboxed}")
        
        # List after
        envs = execution_service.list_environments(sessions)
        print("\nAfter sandbox_env:")
        for e in envs:
            print(f"  {e['name']}: status={e['status']}, sandboxed={e['sandboxed']}, is_default={e['is_default']}")
        
        # Select with policy
        selected = execution_service.select_environment(sessions, policy="STRICT_ISOLATED")
        print(f"\nselect_environment(STRICT_ISOLATED): {selected['name'] if selected else None}")
        
        # Select without policy
        selected_no_policy = execution_service.select_environment(sessions)
        print(f"select_environment(no policy): {selected_no_policy['name'] if selected_no_policy else None}")
        
        # Run preflight
        print("\n--- Running preflight ---")
        result = preflight_mod.task_preflight(
            sessions,
            goal="بناء منصة OSINT",
            policy="STRICT_ISOLATED",
            force=True,
        )
        print(f"Verdict: {result['verdict']}")
        print(f"Summary: {result['summary']}")
        for cap in result.get('capabilities', []):
            if cap['capability_id'] == 'sandbox':
                print(f"Sandbox capability: status={cap['status']}, ok={cap['ok']}, reason={cap.get('reason')}")


if __name__ == "__main__":
    main()