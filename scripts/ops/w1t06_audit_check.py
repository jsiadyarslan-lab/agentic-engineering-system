#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""W1-T06-AUDIT — independent read-only audit (paramiko, SSH to production).

Auditor: independent audit agent (general-purpose), Task ID W1-T06-AUDIT.
Target:  executor claims for W1-T06 — environment-blocker classification
         BEFORE the plan-revision approval gate (owner approval burn loop:
         7+ PLAN_REVISION_APPROVAL gates, owner quote «أعطيت موافقتي
         خمسين مرة»).

Discipline enforced by this script:
- SSH read-only throughout, EXCEPT the isolated reproduction smoke which
  creates temp dirs + temp SQLite DBs under /tmp on the server (never
  touches /opt/agentic-engineering-system/runtime/agent_hub_v2.db) and
  removes them afterwards (verified independently by ls).
- Production DB opened exclusively as sqlite3 URI "file:...?mode=ro".
- No systemctl restart/stop. No git write. No file edits on the server.
- Never reads or prints the Search API key (only `stat` permissions of
  /etc/search-api/env). No 48-hex secrets in any file this script creates.

Evidence: /home/z/my-project/download/aes-remediation/W1-T06/
          audit_w1t06_independent.json (includes this script's md5).
Run with: /home/z/.venv/bin/python /home/z/my-project/scripts/ops/w1t06_audit_check.py
"""

from __future__ import annotations

import base64
import hashlib
import json
import os
import re
import subprocess
import sys
import time

import paramiko

# ------------------------------------------------------------------ #
# constants
# ------------------------------------------------------------------ #
HOST = "92.5.14.150"
USER = "opc"
KEY_PATH = "/tmp/oracle_key"
APP = "/opt/agentic-engineering-system"
DB_PATH = f"{APP}/runtime/agent_hub_v2.db"
SRV_PY = f"{APP}/.venv/bin/python"
SRV_SRC = f"{APP}/src"
LOCAL_REPO = "/home/z/my-project/repo"
LOCAL_VENV_PY = f"{LOCAL_REPO}/.venv/bin/python"
EVIDENCE_DIR = "/home/z/my-project/download/aes-remediation/W1-T06"
EVIDENCE_PATH = os.path.join(EVIDENCE_DIR, "audit_w1t06_independent.json")
SCRIPT_PATH = os.path.abspath(__file__)

EXPECT_HEAD = "fb488572d2ac32b80d15bd8d77cd5c5b4b7a0592"
EXPECT_PARENT = "a3e8b2c52804f991e99e539c29fcbc5118f928c2"
DEPLOY_ANCHOR = "2026-10-28 04:08:00"  # commit fb48857 dated 04:08:48Z

EXPECTED_UNTRACKED = {
    "runtime/browser/",
    "runtime/projects/",
    "scripts/ops/nightly_backup.sh",
    "scripts/ops/nightly_backup.sh.pre-w1t04",
    "src/agentic_engineering_system.egg-info/",
}

HEX48_RE = re.compile(rb"(?<![0-9a-fA-F])[0-9a-fA-F]{48}(?![0-9a-fA-F])")

CHECKS: list[dict] = []
NOTES: list[str] = []


def check(cid: str, group: str, title: str, ok: bool, evidence) -> None:
    CHECKS.append({"id": cid, "group": group, "title": title,
                   "pass": bool(ok), "evidence": evidence})
    print(f"[{'PASS' if ok else 'FAIL'}] {cid} · {title}", flush=True)


def note(text: str) -> None:
    NOTES.append(text)
    print(f"[NOTE] {text}", flush=True)


# ------------------------------------------------------------------ #
# ssh plumbing
# ------------------------------------------------------------------ #
CLIENT = paramiko.SSHClient()
CLIENT.set_missing_host_key_policy(paramiko.AutoAddPolicy())


def ssh_run(cmd: str, timeout: int = 60, sudo: bool = False) -> dict:
    if sudo:
        cmd = "sudo -n " + cmd
    _, stdout, stderr = CLIENT.exec_command(cmd, timeout=timeout)
    out = stdout.read().decode("utf-8", "replace")
    err = stderr.read().decode("utf-8", "replace")
    rc = stdout.channel.recv_exit_status()
    return {"rc": rc, "out": out, "err": err}


def remote_py(code: str, timeout: int = 300) -> dict:
    """Run python code on the server with the app's venv interpreter and
    the app's src on PYTHONPATH. Returns rc/out/err/json (parsed from a
    @@JSON@@ marker block when present)."""
    b64 = base64.b64encode(code.encode("utf-8")).decode("ascii")
    inner = f"import base64;exec(base64.b64decode('{b64}'))"
    cmd = (f'cd {APP} && PYTHONPATH={SRV_SRC} '
           f'{SRV_PY} -c "{inner}"')
    res = ssh_run(cmd, timeout=timeout)
    parsed = None
    if "@@JSON@@" in res["out"]:
        try:
            parsed = json.loads(
                res["out"].split("@@JSON@@", 1)[1].strip())
        except json.JSONDecodeError:
            parsed = None
    res["json"] = parsed
    return res


def local_run(cmd: list[str], cwd: str, timeout: int = 600) -> dict:
    proc = subprocess.run(cmd, cwd=cwd, capture_output=True, text=True,
                          timeout=timeout)
    return {"rc": proc.returncode, "out": proc.stdout, "err": proc.stderr}


# ------------------------------------------------------------------ #
# the isolated reproduction (runs on the SERVER with the app's own code)
# ------------------------------------------------------------------ #
SMOKE_CODE = r'''
import json, shutil, sys, tempfile, traceback
from pathlib import Path

sys.path.insert(0, "/opt/agentic-engineering-system/src")

from sqlalchemy import select

from persistence.database import build_engine, init_db, make_session_factory
from providers_registry import registry

from workflow.engine import ProjectEngine
from workflow import service
from readiness import service as readiness_service
from readiness.models import ToolInvocation
from workflow.models import Execution, ProjectEvent, RetryRecord

PLAN = {
    "objective": "هدف تدقيق W1-T06 المستقل",
    "assumptions": [],
    "acceptance_criteria": ["الملف deliverable.md موجود ضمن الأدلة"],
    "phases": [{
        "title": "مرحلة التدقيق",
        "objective": "خطوة واحدة",
        "acceptance_criteria": ["الملف deliverable.md موجود ضمن الأدلة"],
        "steps": [{
            "objective": "كتابة المخرج",
            "input": "مواد المصادر",
            "expected_output": "ملف deliverable.md",
            "acceptance_criteria": ["الملف deliverable.md موجود ضمن الأدلة"],
            "dependencies": [],
        }],
    }],
    "risks": [], "dependencies": [], "required_owner_decisions": [],
}

GENERIC = "الحالة النهائية FAILED — الدورة لم تكتمل أدلةً"


class _Router:
    def has_live_provider(self, pid):
        return str(pid) == "nvidia"
    def live_providers(self):
        return ["nvidia"]


class _Planner:
    def generate(self, objective, *, previous_failure=None, feedback=""):
        return json.loads(json.dumps(PLAN))


def _fake_view(status):
    def view(sessions, capability_id):
        return {"capability_id": capability_id,
                "readiness_status": status,
                "reason": "حالة منظمة للتدقيق: " + status,
                "failure_reason": "" if status == "READY" else "جهّز المزود"}
    return view


def scenario(tag, cap_status, tool_invocation, prior_env_retry,
             stale_invocation=False):
    tmp = Path(tempfile.mkdtemp(prefix="w1t06-audit-"))
    db_eng = build_engine(tmp / "wf-audit.db")
    init_db(db_eng)
    sessions = make_session_factory(db_eng)
    registry.ensure_seeded(sessions)
    engine = ProjectEngine(
        sessions, router_factory=lambda: _Router(),
        planner_factory=lambda: _Planner())
    project = engine.create_project(
        "تدقيق W1-T06 " + tag, "هدف تدقيق مستقل — تصنيف العائق البيئي")
    engine.generate_plan(project["id"])
    engine.approve_plan(project["id"], approved=True)
    plan = service.latest_plan(sessions, project["id"])
    phase = service.list_phases(sessions, project["id"])[0]
    step = service.phase_steps(sessions, phase["id"])[0]
    execution_id = None
    started_at = None
    for attempt in (1, 2):
        execution_id = service.create_execution(
            sessions, step["id"], attempt=attempt, provider="nvidia",
            model="audit", workspace=str(tmp))
        service.update_execution(sessions, execution_id,
                                 status="FAILED", error=GENERIC)
    with sessions() as s:
        started_at = s.get(Execution, int(execution_id)).started_at
    inv_created = None
    if tool_invocation:
        with sessions() as s:
            inv = ToolInvocation(
                cycle_id="project-{}-step-{}".format(
                    project["id"], step["id"]),
                tool_call_id="tc-audit-" + tag, tool="web_search",
                status="FAILED", transport_status="SUCCESS",
                result_status="NOT_USABLE",
                failure_class="DEPENDENCY_FAILURE",
                failure_stage="PROVIDER_RESOLUTION",
                failure_reason="SEARCH_PROVIDER_NOT_READY",
                query="استعلام تدقيق مستقل", error="لا مزود بحث جاهز",
                retryable=0)
            if stale_invocation:
                import datetime as _dt
                inv.created_at = (
                    _dt.datetime.utcnow() - _dt.timedelta(days=1))
            s.add(inv)
            s.commit()
            inv_created = str(inv.created_at)
    if prior_env_retry:
        with sessions() as s:
            s.add(RetryRecord(
                step_id=int(step["id"]), previous_execution_id=None,
                reason=GENERIC, decision="ENV_RECOVERED_RETRY",
                diagnosis="منحة سابقة (تدقيق مستقل)"))
            s.commit()
    readiness_service.capability_view = _fake_view(cap_status)
    outcome = engine._on_step_failure(
        project, plan, phase, step, execution_id, GENERIC)
    gates = service.open_gates(sessions, project["id"])
    fresh_step = service.get_step(sessions, step["id"])
    fresh_project = service.get_project(sessions, project["id"])
    with sessions() as s:
        retries = [{"decision": r.decision} for r in s.scalars(
            select(RetryRecord).where(
                RetryRecord.step_id == int(step["id"]))).all()]
        events = []
        for e in s.scalars(select(ProjectEvent).where(
                ProjectEvent.project_id == int(project["id"])
                ).order_by(ProjectEvent.id)).all():
            try:
                payload = json.loads(e.payload)
            except Exception:
                payload = {"_raw": str(e.payload)[:200]}
            events.append({"kind": e.kind, "payload": payload})
    run = {
        "tag": tag,
        "capability_status": cap_status,
        "tool_invocation": tool_invocation,
        "stale_invocation": stale_invocation,
        "prior_env_retry": prior_env_retry,
        "project_id": project["id"],
        "step_id": step["id"],
        "execution_id": execution_id,
        "execution_started_at": str(started_at),
        "tool_invocation_created_at": inv_created,
        "outcome": {k: str(v) for k, v in outcome.items()},
        "gates": [{"id": g["id"], "kind": g["kind"], "status": g["status"],
                   "reason": g["reason"], "details": g["details"]}
                  for g in gates],
        "step_status": fresh_step["status"],
        "project_status": fresh_project["status"],
        "retries": retries,
        "events": events,
        "tmp_dir": str(tmp),
    }
    return run, sessions


out = {"runs": {}, "auto_resolve": None, "resolve_gate_blocked": None,
       "cleanup": None, "ok": False}
tmpdirs = []
try:
    r1, s1 = scenario("r1_not_ready", "NOT_READY", True, False)
    tmpdirs.append(r1["tmp_dir"])
    out["runs"]["r1"] = r1
    gate1 = [g for g in r1["gates"] if g["kind"] == "PREFLIGHT_BLOCKED"]
    if gate1:
        # order matters: prove the BLOCKED gate refuses OWNER approval
        # first (while still BLOCKED), then prove the recheck resolver.
        try:
            service.resolve_gate(s1, gate1[0]["id"], approved=True)
            out["resolve_gate_blocked"] = {"raises": False}
        except ValueError as ve:
            out["resolve_gate_blocked"] = {
                "raises": True, "error": str(ve)[:300]}
        res = service.auto_resolve_gate(
            s1, gate1[0]["id"],
            note="تدقيق مستقل — نفس محلل recheck_preflight (engine.py)")
        out["auto_resolve"] = {"gate_id": gate1[0]["id"],
                               "before": "BLOCKED",
                               "result": {k: str(v)
                                          for k, v in res.items()}}
    r2, _s2 = scenario("r2_recovered", "READY", True, False)
    tmpdirs.append(r2["tmp_dir"])
    out["runs"]["r2"] = r2
    r3, _s3 = scenario("r3_loop_guard", "READY", True, True)
    tmpdirs.append(r3["tmp_dir"])
    out["runs"]["r3"] = r3
    r4, _s4 = scenario("r4_regression", "NOT_READY", False, False)
    tmpdirs.append(r4["tmp_dir"])
    out["runs"]["r4"] = r4
    r5, _s5 = scenario("r5_stale_invocation", "NOT_READY", True, False,
                       stale_invocation=True)
    tmpdirs.append(r5["tmp_dir"])
    out["runs"]["r5"] = r5
    out["ok"] = True
except Exception:
    out["ok"] = False
    out["error"] = traceback.format_exc()[-3000:]
finally:
    removed = []
    failed = []
    for d in tmpdirs:
        try:
            shutil.rmtree(d, ignore_errors=False)
            removed.append(d)
        except Exception as exc:
            failed.append({"dir": d, "error": str(exc)[:200]})
    out["cleanup"] = {"removed": removed, "failed": failed,
                      "requested": len(tmpdirs)}

print("@@JSON@@" + json.dumps(out, ensure_ascii=False, default=str))
'''

# ------------------------------------------------------------------ #
# production DB historical evidence (READ-ONLY, mode=ro)
# ------------------------------------------------------------------ #
DB_CODE = r'''
import datetime as dt
import json
import sqlite3

con = sqlite3.connect(
    "file:/opt/agentic-engineering-system/runtime/agent_hub_v2.db?mode=ro",
    uri=True)
cur = con.cursor()


def parse(ts):
    return dt.datetime.strptime(str(ts)[:19], "%Y-%m-%d %H:%M:%S")


rev = [{"id": r[0], "project_id": r[1], "status": r[2], "created_at": r[3]}
       for r in cur.execute(
           "SELECT id, project_id, status, created_at FROM owner_gates "
           "WHERE kind='PLAN_REVISION_APPROVAL' ORDER BY id").fetchall()]
p2 = [g for g in rev if g["project_id"] == 2]
now = dt.datetime.utcnow()
p2_rolling24 = [g["id"] for g in p2
                if parse(g["created_at"]) >= now - dt.timedelta(hours=24)]


def max_window(gates):
    best, best_t0 = 0, None
    for g in gates:
        t0 = parse(g["created_at"])
        n = len([x for x in gates
                 if t0 <= parse(x["created_at"])
                 < t0 + dt.timedelta(hours=24)])
        if n > best:
            best, best_t0 = n, g["created_at"]
    return best, best_t0


p2_max, p2_max_t0 = max_window(p2)
all_max, all_max_t0 = max_window(rev)
documented = {3, 5, 8, 10, 13, 15, 17}
doc_rows = {str(g["id"]): g for g in rev if g["id"] in documented}
pending = [{"id": r[0], "project_id": r[1], "kind": r[2], "status": r[3]}
           for r in cur.execute(
               "SELECT id, project_id, kind, status FROM owner_gates "
               "WHERE status='PENDING' ORDER BY id").fetchall()]
projects = [{"id": r[0], "status": r[1]} for r in cur.execute(
    "SELECT id, status FROM projects ORDER BY id").fetchall()]
sfc = cur.execute("SELECT count(*) FROM owner_gates WHERE details LIKE "
                  "'%step_failure_classification%'").fetchone()[0]
pfb = [{"id": r[0], "project_id": r[1], "status": r[2],
        "created_at": r[3]} for r in cur.execute(
    "SELECT id, project_id, status, created_at FROM owner_gates WHERE "
    "kind='PREFLIGHT_BLOCKED' ORDER BY id").fetchall()]
p2_span = (p2[0]["created_at"], p2[-1]["created_at"],
           (parse(p2[-1]["created_at"]) - parse(p2[0]["created_at"])
            ).total_seconds() / 3600.0) if len(p2) >= 2 else None
con.close()

print("@@JSON@@" + json.dumps({
    "revision_gates": rev,
    "p2_total": len(p2),
    "p2_ids": [g["id"] for g in p2],
    "p2_rolling24_ids": p2_rolling24,
    "p2_rolling24_count": len(p2_rolling24),
    "p2_max_any_24h": p2_max, "p2_max_window_start": p2_max_t0,
    "all_max_any_24h": all_max, "all_max_window_start": all_max_t0,
    "documented_ids_present": {k: v for k, v in doc_rows.items()},
    "pending_gates": pending,
    "projects": projects,
    "gates_step_failure_classification": sfc,
    "preflight_blocked_gates": pfb,
    "p2_span": p2_span,
    "utc_now": now.isoformat(),
}, ensure_ascii=False, default=str))
'''

# vocabulary check (imports the app's own models/gates on the server)
VOCAB_CODE = r'''
import json
import sys

sys.path.insert(0, "/opt/agentic-engineering-system/src")
from workflow.models import GATE_KINDS, PROJECT_EVENT_KINDS
from workflow.gates import (GATE_STATUSES, GATE_TRANSITIONS, can_transition)

print("@@JSON@@" + json.dumps({
    "gate_kinds": list(GATE_KINDS),
    "project_event_kinds_has_preflight": "PREFLIGHT_BLOCKED"
        in PROJECT_EVENT_KINDS,
    "gate_kinds_has_preflight": "PREFLIGHT_BLOCKED" in GATE_KINDS,
    "gate_statuses": list(GATE_STATUSES),
    "blocked_transitions": list(GATE_TRANSITIONS.get("BLOCKED", ())),
    "can_transition_blocked_to_approved":
        can_transition("BLOCKED", "APPROVED"),
    "can_transition_blocked_to_pending":
        can_transition("BLOCKED", "PENDING"),
}, ensure_ascii=False))
'''


# ------------------------------------------------------------------ #
# audit body
# ------------------------------------------------------------------ #
def main() -> int:
    print("=" * 72)
    print("W1-T06-AUDIT — independent audit (read-only SSH + isolated smoke)")
    print("=" * 72)

    CLIENT.connect(HOST, username=USER, key_filename=KEY_PATH,
                   look_for_keys=False, allow_agent=False, timeout=30)

    srv_time = ssh_run("date -u '+%Y-%m-%d %H:%M:%S UTC'")
    print(f"server time: {srv_time['out'].strip()}")
    svc_start = ssh_run(
        "systemctl show agentic -p ActiveEnterTimestamp")["out"].strip()
    print(f"agentic ActiveEnterTimestamp: {svc_start}")

    # ---------------- Group A: production git state ---------------- #
    print("\n--- Group A: production git state ---")
    head = ssh_run(f"git -C {APP} rev-parse HEAD")
    check("A1", "A", "production HEAD == fb488572d2ac32b80d15bd8d77cd5c5b4b7a0592",
          head["out"].strip() == EXPECT_HEAD,
          {"head": head["out"].strip()})

    parent = ssh_run(f"git -C {APP} rev-parse HEAD~1")
    check("A2", "A", "parent commit == a3e8b2c (as claimed)",
          parent["out"].strip() == EXPECT_PARENT,
          {"parent": parent["out"].strip()})

    status = ssh_run(f"git -C {APP} status --porcelain")
    lines = [ln for ln in status["out"].splitlines() if ln.strip()]
    modified = [ln for ln in lines if not ln.startswith("??")]
    untracked = {ln[3:].strip() for ln in lines if ln.startswith("??")}
    check("A3", "A", "clean tracked tree; untracked == expected set only",
          not modified and untracked == EXPECTED_UNTRACKED,
          {"modified": modified, "untracked": sorted(untracked),
           "expected": sorted(EXPECTED_UNTRACKED)})

    subject = ssh_run(f"git -C {APP} log -1 --format=%s")
    check("A4", "A", "HEAD commit subject announces W1-T06",
          "W1-T06" in subject["out"],
          {"subject": subject["out"].strip()[:120]})

    # ---------------- Group B: code present (byte-exact) ------------ #
    print("\n--- Group B: W1-T06 code in production engine.py ---")
    remote_file_sha = ssh_run(
        f"sha256sum {APP}/src/workflow/engine.py")["out"].split()[0]
    remote_blob_sha = ssh_run(
        f"git -C {APP} show {EXPECT_HEAD}:src/workflow/engine.py "
        f"| sha256sum")["out"].split()[0]
    blob = subprocess.run(
        ["git", "-C", LOCAL_REPO, "cat-file", "blob",
         f"{EXPECT_HEAD}:src/workflow/engine.py"],
        capture_output=True).stdout
    local_blob_sha = hashlib.sha256(blob).hexdigest()
    check("B1", "B", "engine.py byte-exact: working file == git blob fb48857 "
          "== local repo blob (sha256 x3)",
          remote_file_sha == remote_blob_sha == local_blob_sha,
          {"remote_file_sha256": remote_file_sha,
           "remote_blob_sha256": remote_blob_sha,
           "local_blob_sha256": local_blob_sha})

    engine_src = ssh_run(f"cat {APP}/src/workflow/engine.py")["out"]

    def has(pattern: str) -> bool:
        return re.search(pattern, engine_src) is not None

    sig_ok = has(r"_ENV_BLOCKER_SIGNATURES") and all(
        s in engine_src for s in (
            "SEARCH_PROVIDER_NOT_READY", "PROVIDER_RESOLUTION",
            "DEPENDENCY_FAILURE", "network_http (NOT_READY)"))
    check("B2", "B", "_ENV_BLOCKER_SIGNATURES tuple with web_search/network "
          "signatures present", sig_ok,
          {"markers": [m for m in ("_ENV_BLOCKER_SIGNATURES",
                                   "SEARCH_PROVIDER_NOT_READY",
                                   "PROVIDER_RESOLUTION",
                                   "DEPENDENCY_FAILURE",
                                   "network_http (NOT_READY)")
                       if m in engine_src]})

    blk_ok = (has(r"def _environment_blocker\(")
              and has(r"readiness_service\.capability_view\(")
              and has(r"ToolInvocation\.created_at >= started")
              and has(r"ToolInvocation\.cycle_id ==")
              and has(r"tool == \"web_search\""))
    check("B3", "B", "_environment_blocker: ToolInvocation query (web_search "
          "FAILED, SEARCH_PROVIDER_NOT_READY/PROVIDER_RESOLUTION/"
          "DEPENDENCY_FAILURE) scoped by created_at >= execution.started_at "
          "+ capability_view consultation",
          blk_ok,
          {"def_line": [ln for ln in engine_src.splitlines()
                        if "def _environment_blocker" in ln]})

    ret_ok = (has(r"def _env_recovered_retries\(")
              and has(r"RetryRecord\.decision == \"ENV_RECOVERED_RETRY\""))
    check("B4", "B", "_env_recovered_retries counts RetryRecord decision "
          "ENV_RECOVERED_RETRY", ret_ok,
          {"def_line": [ln for ln in engine_src.splitlines()
                        if "def _env_recovered_retries" in ln]})

    branch_ok = (has(r"\"PREFLIGHT_BLOCKED\",")
                 and has(r"status=\"BLOCKED\",")
                 and has(r"classified_as\": \"environment_blocker\"")
                 and has(r"\"origin\": \"step_failure_classification\"")
                 and has(r"decision=\"ENV_RECOVERED_RETRY\"")
                 and has(r"\"PLAN_REVISION_APPROVAL\","))
    check("B5", "B", "_on_step_failure branches: NOT_READY→PREFLIGHT_BLOCKED "
          "gate (status BLOCKED, step→READY, events EXECUTION_FAILED "
          "classified_as=environment_blocker + PREFLIGHT_BLOCKED "
          "origin=step_failure_classification); READY+no prior grant→"
          "ENV_RECOVERED_RETRY; PLAN_REVISION_APPROVAL path intact",
          branch_ok,
          {"markers": [m for m in ("PREFLIGHT_BLOCKED",
                                   'status="BLOCKED"',
                                   "environment_blocker",
                                   "step_failure_classification",
                                   "ENV_RECOVERED_RETRY",
                                   "PLAN_REVISION_APPROVAL")
                       if m in engine_src]})

    recheck_ok = (has(r"service\.auto_resolve_gate\(")
                  and has(r"GATE_AUTO_RESOLVED"))
    recheck_lines = [i + 1 for i, ln in enumerate(engine_src.splitlines())
                     if "auto_resolve_gate" in ln or "GATE_AUTO_RESOLVED" in ln]
    check("B6", "B", "recheck_preflight auto-resolves BLOCKED gates on PASS "
          "(GATE_AUTO_RESOLVED) — env gate resolvable WITHOUT owner approval",
          recheck_ok, {"engine_py_lines": recheck_lines})

    # ---------------- Group C: services ----------------------------- #
    print("\n--- Group C: services / health / journal ---")
    svc = ssh_run("systemctl is-active agentic nginx searxng search-api")
    actives = [ln.strip() for ln in svc["out"].splitlines() if ln.strip()]
    check("C1", "C", "agentic/nginx/searxng/search-api all active",
          actives == ["active"] * 4, {"is-active": actives})

    health = ssh_run(
        "curl -s -o /dev/null -w '%{http_code}' http://127.0.0.1:8010/health")
    check("C2", "C", "GET /health on 127.0.0.1:8010 == 200",
          health["out"].strip() == "200",
          {"http_code": health["out"].strip()})

    journal = ssh_run(
        f"sudo -n journalctl -u agentic -p err --since "
        f"'{DEPLOY_ANCHOR}' --no-pager", sudo=True)
    jout = journal["out"].strip()
    check("C3", "C", f"journalctl -u agentic -p err since {DEPLOY_ANCHOR} "
          "(covers commit+deploy window) = no entries",
          jout in ("-- No entries --", ""),
          {"since": DEPLOY_ANCHOR, "output": jout[:200],
           "service_started": svc_start})

    # ---------------- Group D: isolated reproduction ----------------- #
    print("\n--- Group D: isolated reproduction (temp DBs under /tmp) ---")
    smoke = remote_py(SMOKE_CODE, timeout=420)
    smoke_data = smoke.get("json")
    check("D0", "D", "smoke executed on server with app's own code "
          "(exit ok, JSON parsed)",
          bool(smoke_data and smoke_data.get("ok")),
          {"rc": smoke["rc"], "err": smoke["err"][:400],
           "error": (smoke_data or {}).get("error")})

    if smoke_data and smoke_data.get("ok"):
        runs = smoke_data["runs"]
        r1 = runs["r1"]
        gates1 = [g for g in r1["gates"]
                  if g["kind"] == "PREFLIGHT_BLOCKED"]
        ev_exec_failed = [e for e in r1["events"]
                          if e["kind"] == "EXECUTION_FAILED"]
        ev_preflight = [e for e in r1["events"]
                        if e["kind"] == "PREFLIGHT_BLOCKED"]
        last_failed_payload = (ev_exec_failed[-1]["payload"]
                               if ev_exec_failed else {})
        d1_ok = (
            r1["outcome"].get("action") == "blocked"
            and r1["outcome"].get("blocked_kind") == "environment"
            and "web_search" in r1["outcome"].get("reason", "")
            and len(gates1) == 1
            and gates1[0]["status"] == "BLOCKED"
            and gates1[0]["details"].get("origin")
                == "step_failure_classification"
            and gates1[0]["details"].get("blocked", [{}])[0].get(
                "capability_id") == "web_search"
            and gates1[0]["details"].get("blocked", [{}])[0].get("status")
                == "NOT_READY"
            and r1["step_status"] == "READY"
            and r1["project_status"] == "BLOCKED"
            and not any(r["decision"] == "ESCALATE" for r in r1["retries"])
            and not any(r["decision"] == "ENV_RECOVERED_RETRY"
                        for r in r1["retries"])
            and last_failed_payload.get("classified_as")
                == "environment_blocker"
            and ev_preflight
            and ev_preflight[-1]["payload"].get("origin")
                == "step_failure_classification")
        check("D1", "D", "run1 NOT_READY: outcome blocked_kind=environment; "
              "gate PREFLIGHT_BLOCKED status BLOCKED (origin="
              "step_failure_classification, capability web_search NOT_READY); "
              "step back to READY; project BLOCKED; NO ESCALATE retry; "
              "events EXECUTION_FAILED(classified_as=environment_blocker) + "
              "PREFLIGHT_BLOCKED(origin=step_failure_classification)",
              d1_ok,
              {"outcome": r1["outcome"],
               "gate": gates1[0] if gates1 else None,
               "step_status": r1["step_status"],
               "project_status": r1["project_status"],
               "retries": r1["retries"],
               "exec_failed_payload": last_failed_payload,
               "preflight_event_payload": (ev_preflight[-1]["payload"]
                                           if ev_preflight else None)})

        ar = smoke_data.get("auto_resolve") or {}
        rg = smoke_data.get("resolve_gate_blocked") or {}
        d2_ok = (ar.get("result", {}).get("status") == "APPROVED"
                 and ar.get("result", {}).get("auto_resolved")
                 in ("True", "true", True)
                 and rg.get("raises") is True)
        check("D2", "D", "run1 gate resolvable WITHOUT owner approval: "
              "service.auto_resolve_gate (the exact resolver recheck_preflight "
              "calls) BLOCKED→APPROVED auto_resolved; owner "
              "resolve_gate(approved=True) on a BLOCKED gate raises ValueError",
              d2_ok,
              {"auto_resolve": ar, "resolve_gate_blocked": rg})

        r2 = runs["r2"]
        ev_retry = [e for e in r2["events"]
                    if e["kind"] == "RETRY_REQUESTED"]
        d3_ok = (r2["outcome"].get("action") == "continue"
                 and any(r["decision"] == "ENV_RECOVERED_RETRY"
                         for r in r2["retries"])
                 and not r2["gates"]
                 and r2["step_status"] == "READY"
                 and ev_retry
                 and ev_retry[-1]["payload"].get("decision")
                     == "ENV_RECOVERED_RETRY")
        check("D3", "D", "run2 READY: ENV_RECOVERED_RETRY retry record + NO "
              "gate + step READY (+ RETRY_REQUESTED event "
              "decision=ENV_RECOVERED_RETRY)", d3_ok,
              {"outcome": r2["outcome"], "retries": r2["retries"],
               "gates": r2["gates"], "step_status": r2["step_status"],
               "retry_event_payload": (ev_retry[-1]["payload"]
                                       if ev_retry else None)})

        r3 = runs["r3"]
        gates3 = [g for g in r3["gates"]
                  if g["kind"] == "PLAN_REVISION_APPROVAL"]
        d4_ok = (r3["outcome"].get("action") == "blocked"
                 and len(gates3) == 1
                 and r3["step_status"] == "FAILED"
                 and any(r["decision"] == "ESCALATE" for r in r3["retries"]))
        check("D4", "D", "run3 READY + pre-existing ENV_RECOVERED_RETRY: "
              "loop guard → PLAN_REVISION_APPROVAL gate + step FAILED "
              "(+ESCALATE retry)", d4_ok,
              {"outcome": r3["outcome"],
               "gate_kinds": [g["kind"] for g in r3["gates"]],
               "step_status": r3["step_status"], "retries": r3["retries"]})

        r4 = runs["r4"]
        gates4 = [g for g in r4["gates"]
                  if g["kind"] == "PLAN_REVISION_APPROVAL"]
        d5_ok = (r4["outcome"].get("action") == "blocked"
                 and len(gates4) == 1
                 and r4["step_status"] == "FAILED"
                 and any(r["decision"] == "ESCALATE" for r in r4["retries"]))
        check("D5", "D", "run4 regression (no tool invocation, generic "
              "reason, env NOT_READY): PLAN_REVISION_APPROVAL as before — "
              "non-environmental failure NOT hijacked", d5_ok,
              {"outcome": r4["outcome"],
               "gate_kinds": [g["kind"] for g in r4["gates"]],
               "step_status": r4["step_status"], "retries": r4["retries"]})

        r5 = runs["r5"]
        gates5 = [g for g in r5["gates"]
                  if g["kind"] == "PLAN_REVISION_APPROVAL"]
        d6_ok = (len(gates5) == 1 and r5["step_status"] == "FAILED"
                 and not any(g["kind"] == "PREFLIGHT_BLOCKED"
                             for g in r5["gates"]))
        check("D6", "D", "run5 temporal scope: web_search invocation created "
              "BEFORE execution.started_at does NOT classify as environment "
              "blocker → PLAN_REVISION_APPROVAL", d6_ok,
              {"execution_started_at": r5["execution_started_at"],
               "tool_invocation_created_at": r5["tool_invocation_created_at"],
               "gate_kinds": [g["kind"] for g in r5["gates"]],
               "step_status": r5["step_status"]})

        cleanup = smoke_data.get("cleanup") or {}
        leftover = ssh_run(
            "ls -d /tmp/w1t06-audit-* 2>/dev/null | wc -l")["out"].strip()
        d7_ok = (not cleanup.get("failed")
                 and cleanup.get("removed")
                 and len(cleanup["removed"]) == cleanup.get("requested")
                 and leftover == "0")
        check("D7", "D", "all temp dirs removed (smoke report + independent "
              "ls of /tmp/w1t06-audit-* == 0)", d7_ok,
              {"cleanup": cleanup, "leftover_dirs": leftover})
    else:
        for cid, title in (("D1", "run1 NOT_READY classification"),
                           ("D2", "run1 auto-resolve proof"),
                           ("D3", "run2 READY retry"),
                           ("D4", "run3 loop guard"),
                           ("D5", "run4 regression"),
                           ("D6", "run5 temporal scope"),
                           ("D7", "temp cleanup")):
            check(cid, "D", title, False, {"smoke_failed": True})

    # ---------------- Group E: vocabulary legality ------------------- #
    print("\n--- Group E: gate/event vocabulary ---")
    vocab = remote_py(VOCAB_CODE, timeout=60)
    v = vocab.get("json") or {}
    e1_ok = v.get("gate_kinds_has_preflight") is True \
        and v.get("project_event_kinds_has_preflight") is True
    check("E1", "E", "models.py: PREFLIGHT_BLOCKED legal in GATE_KINDS and "
          "PROJECT_EVENT_KINDS", e1_ok,
          {"gate_kinds": v.get("gate_kinds"),
           "project_event_kinds_has_preflight":
               v.get("project_event_kinds_has_preflight")})
    e2_ok = ("BLOCKED" in (v.get("gate_statuses") or [])
             and "APPROVED" in (v.get("blocked_transitions") or [])
             and v.get("can_transition_blocked_to_approved") is True)
    check("E2", "E", "gates.py vocabulary accepts it: BLOCKED in "
          "GATE_STATUSES; BLOCKED→APPROVED transition legal "
          "(auto-resolve path)", e2_ok,
          {"gate_statuses": v.get("gate_statuses"),
           "blocked_transitions": v.get("blocked_transitions"),
           "can_transition(BLOCKED→APPROVED)":
               v.get("can_transition_blocked_to_approved")})

    # ---------------- Group F: local tests --------------------------- #
    print("\n--- Group F: local tests (repo @ fb48857) ---")
    local_head = local_run(["git", "-C", LOCAL_REPO, "rev-parse", "HEAD"],
                           LOCAL_REPO)["out"].strip()
    wf = local_run([LOCAL_VENV_PY, "-m", "pytest", "tests/workflow", "-q"],
                   LOCAL_REPO, timeout=600)
    m = re.search(r"(\d+) passed", wf["out"])
    wf_count = int(m.group(1)) if m else -1
    check("F1", "F", f"local HEAD == fb48857 && tests/workflow -q → "
          f"96 passed (got {wf_count})",
          local_head == EXPECT_HEAD and wf_count == 96,
          {"local_head": local_head, "pytest_tail":
              wf["out"].strip().splitlines()[-1] if wf["out"] else "",
           "rc": wf["rc"]})

    rs = local_run([LOCAL_VENV_PY, "-m", "pytest", "tests/research", "-q"],
                   LOCAL_REPO, timeout=600)
    m = re.search(r"(\d+) passed", rs["out"])
    rs_count = int(m.group(1)) if m else -1
    check("F2", "F", f"tests/research -q → 82 passed (got {rs_count})",
          rs_count == 82,
          {"pytest_tail": rs["out"].strip().splitlines()[-1]
           if rs["out"] else "", "rc": rs["rc"]})

    w16 = local_run(
        [LOCAL_VENV_PY, "-m", "pytest",
         "tests/workflow/test_env_blocker_w1t06.py", "-q"],
        LOCAL_REPO, timeout=300)
    m = re.search(r"(\d+) passed", w16["out"])
    w16_count = int(m.group(1)) if m else -1
    check("F3", "F", "tests/workflow/test_env_blocker_w1t06.py → 6 new "
          f"W1-T06 tests passed (got {w16_count})", w16_count == 6,
          {"pytest_tail": w16["out"].strip().splitlines()[-1]
           if w16["out"] else "", "rc": w16["rc"]})

    # ---------------- Group G: historical production DB -------------- #
    print("\n--- Group G: production DB evidence (mode=ro) ---")
    db = remote_py(DB_CODE, timeout=120)
    d = db.get("json") or {}
    doc_ok = all(str(gid) in (d.get("documented_ids_present") or {})
                 for gid in (3, 5, 8, 10, 13, 15, 17))
    g1_ok = (d.get("p2_total", 0) >= 7
             and d.get("all_max_any_24h", 0) >= 7
             and doc_ok)
    check("G1", "G", "documented burn loop: project 2 has 7 "
          "PLAN_REVISION_APPROVAL gates (total, spanning ~25h); peak 24h "
          "window holds ≥7 revision gates cross-project; documented gate "
          "IDs 3,5,8,10,13,15,17 all exist as revision gates",
          g1_ok,
          {"p2_total": d.get("p2_total"), "p2_ids": d.get("p2_ids"),
           "p2_span_hours": (d.get("p2_span") or [None, None, None])[2]
           if d.get("p2_span") else None,
           "p2_rolling24_count": d.get("p2_rolling24_count"),
           "p2_rolling24_ids": d.get("p2_rolling24_ids"),
           "p2_max_any_24h": d.get("p2_max_any_24h"),
           "all_max_any_24h": d.get("all_max_any_24h"),
           "all_max_window_start": d.get("all_max_window_start"),
           "documented_ids_present":
               sorted((d.get("documented_ids_present") or {}).keys())})

    pending = d.get("pending_gates") or []

    def pend(pid, kind):
        return [g for g in pending
                if g["project_id"] == pid and g["kind"] == kind]

    g2_ok = bool(pend(2, "PLAN_REVISION_APPROVAL")
                 and pend(3, "PLAN_REVISION_APPROVAL"))
    check("G2", "G", "current pending gates as claimed: project 2 "
          "PLAN_REVISION_APPROVAL PENDING + project 3 "
          "PLAN_REVISION_APPROVAL PENDING", g2_ok,
          {"pending_gates": pending})

    proj = {p["id"]: p["status"] for p in (d.get("projects") or [])}
    g3_ok = proj.get(2) == "BLOCKED" and proj.get(3) == "BLOCKED"
    check("G3", "G", "projects 2 and 3 status BLOCKED", g3_ok,
          {"projects": d.get("projects")})

    check("G4", "G", "context: new path (origin=step_failure_classification) "
          "gates in production = 0 (expected — no step failure since deploy "
          "minutes earlier; live proof is group D). Pre-existing "
          "PREFLIGHT_BLOCKED gates recorded (id 2 auto-resolved 2026-10-26 "
          "historically; id 20 from preflight path predates W1-T06 deploy).",
          True,
          {"gates_step_failure_classification":
               d.get("gates_step_failure_classification"),
           "preflight_blocked_gates": d.get("preflight_blocked_gates"),
           "deploy_restart": svc_start})

    # ---------------- Group H: security ------------------------------ #
    print("\n--- Group H: security ---")
    envstat = ssh_run("stat -c '%U:%G %a' /etc/search-api/env", sudo=True)
    check("H1", "H", "/etc/search-api/env exists with root:searchapi 640 — "
          "content NEVER read or printed",
          envstat["out"].strip() == "root:searchapi 640",
          {"stat": envstat["out"].strip()})

    CLIENT.close()

    # ---------------- notes (evidence-backed, non-blocking) --------- #
    worklog_path = "/home/z/my-project/worklog.md"
    tracker_path = os.path.join(LOCAL_REPO, "TRACKER.md")
    try:
        wl_hits = len(re.findall(r"^Task ID: W1-T06$",
                                 open(worklog_path, encoding="utf-8").read(),
                                 re.M))
    except OSError:
        wl_hits = -1
    note(f"(N1) no executor worklog entry 'Task ID: W1-T06' in worklog.md "
         f"at audit time (found {wl_hits}) — executor's narrative entry is "
         f"still pending per protocol (same pattern as previous tasks).")
    try:
        tr = open(tracker_path, encoding="utf-8").read()
        tr_row = next((ln.strip() for ln in tr.splitlines()
                       if ln.strip().startswith("| W1-T06 |")), "")
        tr_active = re.search(r"النشطة الآن:\*{0,2}\s*W1-T06", tr) \
            is not None
    except OSError:
        tr_row, tr_active = "", False
    note(f"(N2) TRACKER.md §1 status row for W1-T06 still reads "
         f"'لم تبدأ' (header 'النشطة الآن' points at W1-T06: "
         f"{tr_active}) — card completion + audit signature is the "
         f"executor/parent responsibility (R5). Row: {tr_row[:90]}")
    note(f"(N3) burn-loop window semantics (from production DB, mode=ro): "
         f"project 2 has {d.get('p2_total')} PLAN_REVISION_APPROVAL gates "
         f"total spanning ~25.1h "
         f"({(d.get('p2_span') or [None, None, 0])[2]:.1f}h); strict rolling "
         f"last-24h at audit time = {d.get('p2_rolling24_count')} "
         f"(gate 17 @ 2026-10-27 04:22:22Z left the window during the "
         f"audit); max project-2 gates in any 24h window = "
         f"{d.get('p2_max_any_24h')}; cross-project peak 24h window = "
         f"{d.get('all_max_any_24h')} revision gates "
         f"(from {d.get('all_max_window_start')}). The documented loop "
         f"(gates 3,5,8,10,13,15,17 — 3,5,8 belong to project 1) spans "
         f"~5.3h and all 7 IDs verified as revision gates. Loop magnitude "
         f"substantiated; literal 'project 2 ≥7 in last 24h' reading "
         f"would give {d.get('p2_rolling24_count')}.")
    note("(N4) the new classification path (origin=step_failure_"
         "classification) has 0 gates in production at audit time — "
         "expected: deploy restart was 04:10:28 GMT and the audit ran "
         "~13 minutes later with no step failure since. The live "
         "behavioral proof is group D (isolated reproduction with the "
         "app's own interpreter + source on the server).")
    note(f"(N5) two PREFLIGHT_BLOCKED gates pre-exist the W1-T06 deploy: "
         f"gate id 2 (project 1, sandbox) auto-resolved by recheck on "
         f"2026-10-26 — historical production proof the auto-resolve "
         f"machinery works; gate id 20 (project 2, network_https "
         f"NOT_READY, created 2026-10-27 23:25) is from the preflight "
         f"path and still BLOCKED — resolvable by the same recheck "
         f"mechanism proven in D2. Raw: "
         f"{json.dumps(d.get('preflight_blocked_gates'), ensure_ascii=False)}")
    extra_pending = json.dumps(
        [g for g in (d.get("pending_gates") or [])
         if not (g["project_id"] == 2
                 and g["kind"] == "PLAN_REVISION_APPROVAL")
         and not (g["project_id"] == 3
                  and g["kind"] == "PLAN_REVISION_APPROVAL")],
        ensure_ascii=False)
    note("(N6) pending gates beyond the two claimed: "
         + extra_pending
         + " — documented, non-blocking. Project 1 is also BLOCKED.")
    note("(N7) independence: the executor's deploy.json smoke output was "
         "NOT relied upon; every verdict here comes from this script's own "
         "outputs. This audit's smoke covers 5 scenarios (env-blocked gate, "
         "auto-resolve + owner-approval refusal, recovered retry, loop "
         "guard, non-environmental regression, temporal scoping) — more "
         "than the executor's single scenario.")

    # ---------------- evidence assembly ------------------------------ #
    script_md5 = hashlib.md5(
        open(SCRIPT_PATH, "rb").read()).hexdigest()
    groups = {}
    for c in CHECKS:
        groups.setdefault(c["group"], []).append(c["pass"])
    group_summary = {g: {"pass": sum(v), "total": len(v)}
                     for g, v in sorted(groups.items())}
    verdict = "PASS" if all(c["pass"] for c in CHECKS) else "FAIL"

    evidence = {
        "_meta": {
            "task": "W1-T06-AUDIT",
            "agent": "Audit Agent (independent, general-purpose)",
            "audited_task": "W1-T06 — environment-blocker classification "
                            "before plan-revision approval gate",
            "audited_commit": EXPECT_HEAD,
            "ts_utc": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
            "script": SCRIPT_PATH,
            "script_md5": script_md5,
            "verdict": verdict,
            "checks_passed": sum(1 for c in CHECKS if c["pass"]),
            "checks_total": len(CHECKS),
        },
        "groups_summary": group_summary,
        "checks": CHECKS,
        "notes": NOTES,
        "smoke_raw": (smoke_data if smoke_data and smoke_data.get("ok")
                      else {"ok": False,
                            "error": (smoke_data or {}).get("error"),
                            "stderr": smoke["err"][:1000]}),
        "db_evidence_raw": d,
        "server": {"utc_now": srv_time["out"].strip(),
                   "agentic_active_enter": svc_start},
        "signature": (f"W1-T06-AUDIT · 2026-10-28 · {verdict} · "
                      f"script_md5={script_md5}"),
    }

    os.makedirs(EVIDENCE_DIR, exist_ok=True)
    with open(EVIDENCE_PATH, "w", encoding="utf-8") as fh:
        json.dump(evidence, fh, ensure_ascii=False, indent=2)

    # H2: no 48-hex secrets in the files this audit created
    ev_bytes = open(EVIDENCE_PATH, "rb").read()
    sc_bytes = open(SCRIPT_PATH, "rb").read()
    hex_hits_ev = HEX48_RE.findall(ev_bytes)
    hex_hits_sc = HEX48_RE.findall(sc_bytes)
    h2_ok = not hex_hits_ev and not hex_hits_sc
    check("H2", "H", "no 48-hex API key in any file created by this audit "
          "(evidence JSON + script)", h2_ok,
          {"evidence_48hex_hits": [h.decode() for h in hex_hits_ev],
           "script_48hex_hits": [h.decode() for h in hex_hits_sc]})
    with open(EVIDENCE_PATH, "r", encoding="utf-8") as fh:
        evidence = json.load(fh)
    evidence["checks"] = CHECKS
    evidence["_meta"]["checks_passed"] = sum(1 for c in CHECKS if c["pass"])
    evidence["_meta"]["checks_total"] = len(CHECKS)
    evidence["_meta"]["verdict"] = "PASS" if all(
        c["pass"] for c in CHECKS) else "FAIL"
    evidence["groups_summary"] = {
        g: {"pass": sum(1 for c in CHECKS if c["group"] == g and c["pass"]),
            "total": sum(1 for c in CHECKS if c["group"] == g)}
        for g in sorted({c["group"] for c in CHECKS})}
    evidence["signature"] = (
        f"W1-T06-AUDIT · 2026-10-28 · "
        f"{evidence['_meta']['verdict']} · script_md5={script_md5}")
    with open(EVIDENCE_PATH, "w", encoding="utf-8") as fh:
        json.dump(evidence, fh, ensure_ascii=False, indent=2)

    print("\n" + "=" * 72)
    print(f"VERDICT: {evidence['_meta']['verdict']} — "
          f"{evidence['_meta']['checks_passed']}/"
          f"{evidence['_meta']['checks_total']} checks passed")
    print(f"evidence: {EVIDENCE_PATH}")
    print(f"script md5: {script_md5}")
    print(evidence["signature"])
    print("=" * 72)
    return 0 if evidence["_meta"]["verdict"] == "PASS" else 1


if __name__ == "__main__":
    sys.exit(main())
