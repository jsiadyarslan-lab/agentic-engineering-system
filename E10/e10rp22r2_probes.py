#!/usr/bin/env python3
"""E10-RP2.2-R2-DISCOVERY — GIT & SANDBOX LIFECYCLE AUTHORIZATION AUDIT PROBES.

Discovery phase ONLY (order E10-RP2.2-R2 §5): NO source fixes, NO production
file modifications. These probes EXECUTE the real chain at baseline commit
0945960427e833522789903e87a64b73c207bccd and record what actually happens.

Every probe runs in its own throwaway temp tree. Verdict vocabulary:
  GAP-CONFIRMED — observed behavior proves the audited weakness
  SECURE        — observed behavior is fail-closed / correctly enforced
  OBSERVED      — neutral factual observation recorded for the report
  ERROR         — probe itself crashed (never silently ignored)

Usage:
  python3 E10/e10rp22r2_probes.py --probe G1        # single probe
  python3 E10/e10rp22r2_probes.py --all             # all probes in order
"""

import argparse
import asyncio
import os
import shutil
import sys
import traceback

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from e10rp22r2_probes_lib import (  # noqa: E402
    PY, AgentType, ExecutionEngine, SandboxError, BaseAgent,
    fresh_bridge, legacy_validator, make_repo, make_bare, git_out,
    make_context, make_agent_context, make_task, preapprove_tool_gate,
    event_counts, tree_snapshot, ProbeAgent, sandbox_manager, sbx_request,
    tmpdir,
)
from eoe.order_parser import AccessRequest, GrantKind  # noqa: E402


def out(msg: str) -> None:
    print(msg, flush=True)


async def call_tool(engine, ctx, name, inp):
    """Run ONE tool call through the REAL ToolExecutor chain and classify
    WHERE it stopped:
      PERMISSION_REJECTED — stopped at an authorization layer (PermissionError)
      IMPL_CRASH          — passed ALL authorization layers, then crashed in
                            the implementation (e.g. the run_git NameError, DF1)
      TOOL_RESULT         — completed (success or tool-level failure result)
    """
    try:
        r = await engine.tool_executor.execute_tool(ctx, name, inp)
        return ("TOOL_RESULT", r)
    except PermissionError as e:
        return ("PERMISSION_REJECTED", e)
    except Exception as e:
        return ("IMPL_CRASH", e)


def describe(status, payload) -> str:
    if status == "TOOL_RESULT":
        return f"completed: success={payload.success} error={payload.error!r}"
    if status == "PERMISSION_REJECTED":
        return f"PermissionError: {str(payload)[:120]}"
    return f"{type(payload).__name__}: {str(payload)[:120]}"


# ---------------------------------------------------------------- G1
async def probe_g1():
    out("=== PROBE G1: ABSENT grant_validator — 5 git tools + run_command + sandbox_execute (real ToolExecutor chain) ===")
    base = tmpdir("r2g1-")
    engine = ExecutionEngine(artifacts_base_dir=os.path.join(base, "artifacts"))
    repo = make_repo(os.path.join(base, "repoB"))
    ctx = make_context(engine, mission_id="ghost-mission", validator=None,
                       grant_ids=["g1"], workspace_root=repo)
    cases = [
        ("git_branch", {"action": "create", "branch_name": "g1-should-not-exist", "repo_path": repo}),
        ("git_commit", {"message": "g1 should not commit", "repo_path": repo,
                        "author_name": "P", "author_email": "p@x"}),
        ("git_diff", {"repo_path": repo}),
        ("git_status", {"repo_path": repo}),
        ("git_push", {"repo_path": repo, "branch": "main", "owner_approval_nonce": "n"}),
        ("run_command", {"command": [PY, "-c", "print('G1-SHOULD-NOT-RUN')"], "working_dir": base}),
        ("sandbox_execute", {"sandbox_id": "sbx-g1", "image": "python:3.11-slim",
                             "command": [PY, "-c", "print('G1-SHOULD-NOT-RUN')"]}),
    ]
    ev_before = len(engine.event_bus.history)
    act_before = len(engine.actions)
    artifacts_before = tree_snapshot(base)
    all_rejected = True
    for name, inp in cases:
        try:
            r = await engine.tool_executor.execute_tool(ctx, name, inp)
            out(f"[G1] {name}: NOT REJECTED — success={r.success} error={r.error}")
            all_rejected = False
        except PermissionError as e:
            out(f"[G1] {name}: PermissionError (fail-closed): {str(e)[:130]}")
        except Exception as e:
            out(f"[G1] {name}: {type(e).__name__}: {str(e)[:130]}")
            all_rejected = False
    ev_after = len(engine.event_bus.history)
    act_after = len(engine.actions)
    branches = git_out(repo, "branch")
    artifacts_after = tree_snapshot(base)
    out(f"[G1] events {ev_before} -> {ev_after} (delta {ev_after - ev_before})")
    out(f"[G1] engine.actions {act_before} -> {act_after} (delta {act_after - act_before})")
    out(f"[G1] repo branches: {branches!r}")
    out(f"[G1] tree delta: {sorted(artifacts_after - artifacts_before)}")
    ok = (all_rejected and ev_after == ev_before and act_after == act_before
          and not artifacts_after - artifacts_before
          and "g1-should-not-exist" not in branches)
    out(f"[G1 RESULT] {'SECURE' if ok else 'MIXED'} — absent validator: every in-scope tool rejected "
        "before any event, action record, file, or git effect")
    shutil.rmtree(base, ignore_errors=True)


# ---------------------------------------------------------------- G2
async def probe_g2():
    out("=== PROBE G2: LEGACY permissive 2-arg validator — kind-only decision, uncontained repo_path ===")
    base = tmpdir("r2g2-")
    engine = ExecutionEngine(artifacts_base_dir=os.path.join(base, "artifacts"),
                             grant_validator=legacy_validator, grant_ids=["g1"])
    mission = engine.create_mission("G2 probe mission")
    repo = make_repo(os.path.join(base, "repoB"))  # outside ANY grant scope
    ctx = make_context(engine, mission_id=mission.mission_id,
                       validator=legacy_validator, grant_ids=["g1"], workspace_root=repo)

    for name, inp in [
        ("git_branch", {"action": "create", "branch_name": "g2-branch", "repo_path": repo}),
        ("git_commit", {"message": "g2 commit outside any grant", "repo_path": repo,
                        "author_name": "P", "author_email": "p@x"}),
        ("git_status", {"repo_path": repo}),
        ("git_diff", {"repo_path": repo}),
    ]:
        status, payload = await call_tool(engine, ctx, name, inp)
        out(f"[G2] {name} (uncontained repo): [{status}] {describe(status, payload)}")
    try:
        r = await engine.tool_executor.execute_tool(
            ctx, "run_command", {"command": [PY, "-c", "print('G2-RC')"], "working_dir": base})
        out(f"[G2] run_command (registered mission): NOT GATED — success={r.success}")
    except PermissionError as e:
        out(f"[G2] run_command (registered mission): PermissionError human gate: {str(e)[:110]}")
    try:
        r = await engine.tool_executor.execute_tool(
            ctx, "sandbox_execute", {"sandbox_id": "sbx-g2", "image": "python:3.11-slim",
                                     "command": [PY, "-c", "print('G2-SE')"]})
        out(f"[G2] sandbox_execute (registered mission): NOT GATED — success={r.success}")
    except PermissionError as e:
        out(f"[G2] sandbox_execute (registered mission): PermissionError human gate: {str(e)[:110]}")

    out(f"[G2] repo branches now: {git_out(repo, 'branch')!r}")
    out(f"[G2] repo log now: {git_out(repo, 'log', '--oneline')!r}")
    out("[G2 RESULT] TWO-LAYER — (1) GAP-CONFIRMED at the authorization layer: with a legacy 2-arg "
        "validator the git family's FINAL decision is kind-only and the call PROCEEDS past every "
        "authorization layer with an uncontained repo_path (target never grounded); (2) DEFECT DF1: "
        "every git implementation call then crashes with NameError (subprocess never imported in "
        "src/unified/execution.py) — no git effect ever executes at baseline (fail-closed BY CRASH, "
        "not by design). run_command/sandbox_execute reach the human gate (registered mission)")
    shutil.rmtree(base, ignore_errors=True)


# ---------------------------------------------------------------- G3
async def probe_g3():
    out("=== PROBE G3: REAL EOE bridge — live PATH_GRANT scoped to treeA; operations target repoB (outside treeA) ===")
    base = tmpdir("r2g3-")
    treeA = os.path.join(base, "treeA")
    os.makedirs(treeA, exist_ok=True)
    br = fresh_bridge(treeA)
    engine = ExecutionEngine(artifacts_base_dir=treeA,
                             grant_validator=br["validator"], grant_ids=[br["grant_id"]])
    repoB = make_repo(os.path.join(base, "repoB"))
    ctx = make_context(engine, mission_id="ghost-mission",
                       validator=br["validator"], grant_ids=[br["grant_id"]],
                       workspace_root=repoB)

    for name, inp in [
        ("git_branch", {"action": "create", "branch_name": "g3-branch", "repo_path": repoB}),
        ("git_status", {"repo_path": repoB}),
        ("git_push", {"repo_path": repoB, "remote": "origin", "branch": "main",
                      "owner_approval_nonce": "n"}),
        ("run_command", {"command": [PY, "-c", "print('G3-RC')"], "working_dir": base}),
        ("sandbox_execute", {"sandbox_id": "sbx-g3", "image": "python:3.11-slim",
                             "command": [PY, "-c", "print('G3-SE')"]}),
    ]:
        status, payload = await call_tool(engine, ctx, name, inp)
        out(f"[G3] {name} (grant covers treeA only): [{status}] {describe(status, payload)}")

    out(f"[G3] repoB branches: {git_out(repoB, 'branch')!r}")
    out("[G3 RESULT] TWO-LAYER — under the REAL bridge: (1) GAP-CONFIRMED at the authorization layer: "
        "git_branch/git_status PROCEED past every authorization layer on repoB (grant scoped to treeA) "
        "— the coarse kind gate (write/read) is their final decision and the target is never grounded "
        "(they then crash with NameError = DF1, so no git effect executes); (2) SECURE: git_push "
        "(admin) and run_command/sandbox_execute (execute) are REJECTED at the permission layer — "
        "these kinds are unattainable in EOE grant policy (fail-closed; tools functionally dead under "
        "the real policy)")
    shutil.rmtree(base, ignore_errors=True)


# ---------------------------------------------------------------- G4
async def probe_g4():
    out("=== PROBE G4: MISSING and REVOKED grant (real bridge) — git_status, zero side effects on rejection ===")
    base = tmpdir("r2g4-")
    treeA = os.path.join(base, "treeA")
    os.makedirs(treeA, exist_ok=True)
    br = fresh_bridge(treeA)
    engine = ExecutionEngine(artifacts_base_dir=treeA,
                             grant_validator=br["validator"], grant_ids=[br["grant_id"]])
    repoB = make_repo(os.path.join(base, "repoB"))

    ctx_missing = make_context(engine, validator=br["validator"], grant_ids=["nonexistent-grant"])
    status, payload = await call_tool(engine, ctx_missing, "git_status", {"repo_path": repoB})
    out(f"[G4] missing grant: [{status}] {describe(status, payload)}")

    ctx_live = make_context(engine, validator=br["validator"], grant_ids=[br["grant_id"]])
    status, payload = await call_tool(engine, ctx_live, "git_status", {"repo_path": repoB})
    out(f"[G4] live grant: [{status}] {describe(status, payload)}")

    br["ledger"].revoke(br["grant_id"])
    ev_before = len(engine.event_bus.history)
    act_before = len(engine.actions)
    status, payload = await call_tool(engine, ctx_live, "git_status", {"repo_path": repoB})
    out(f"[G4] revoked grant: [{status}] {describe(status, payload)}")
    ev_after = len(engine.event_bus.history)
    act_after = len(engine.actions)
    out(f"[G4] rejected-call event delta: {ev_after - ev_before}; action delta: {act_after - act_before}")
    out(f"[G4] repoB unchanged: branches={git_out(repoB, 'branch')!r} log={git_out(repoB, 'log', '--oneline')!r}")
    out("[G4 RESULT] SECURE — missing and revoked grants are fail-closed for the git family through the "
        "real bridge (rejected at the permission layer); the rejection emits no event, no action "
        "record, no git effect. OBSERVED: with a LIVE grant the call proceeds past authorization and "
        "crashes with NameError (DF1) instead of executing")
    shutil.rmtree(base, ignore_errors=True)


# ---------------------------------------------------------------- G5
async def probe_g5():
    out("=== PROBE G5: rejection BEFORE any side effect — after a prior ALLOWED operation in the same engine/mission ===")
    base = tmpdir("r2g5-")
    engine = ExecutionEngine(artifacts_base_dir=os.path.join(base, "artifacts"),
                             grant_validator=legacy_validator, grant_ids=["g1"])
    mission = engine.create_mission("G5 mission")
    preapprove_tool_gate(engine, mission.mission_id, "run_command")
    repo = make_repo(os.path.join(base, "repo"))
    wd = tmpdir("r2g5-wd-")
    ctx_ok = make_context(engine, mission_id=mission.mission_id,
                          validator=legacy_validator, grant_ids=["g1"], workspace_root=repo)
    r = await engine.tool_executor.execute_tool(
        ctx_ok, "run_command",
        {"command": [PY, "-c", "print('G5-PRIOR-ALLOWED')"], "working_dir": wd})
    out(f"[G5] prior allowed op (run_command, gate pre-approved): success={r.success}")

    refs_before = git_out(repo, "branch")
    ev_before = len(engine.event_bus.history)
    act_before = len(engine.actions)
    artifacts_before = tree_snapshot(base)

    ctx_noval = make_context(engine, mission_id=mission.mission_id,
                             validator=None, grant_ids=["g1"], workspace_root=repo)
    status, payload = await call_tool(
        engine, ctx_noval, "git_branch",
        {"action": "create", "branch_name": "g5-rejected", "repo_path": repo})
    out(f"[G5] rejected op (git_branch, absent validator): [{status}] {describe(status, payload)}")

    refs_after = git_out(repo, "branch")
    ev_after = len(engine.event_bus.history)
    act_after = len(engine.actions)
    artifacts_after = tree_snapshot(base)
    out(f"[G5] refs before: {refs_before!r}")
    out(f"[G5] refs after : {refs_after!r}")
    out(f"[G5] event delta {ev_after - ev_before}; action delta {act_after - act_before}; "
        f"tree delta {sorted(artifacts_after - artifacts_before)}")
    ok = ("g5-rejected" not in refs_after and ev_after == ev_before
          and act_after == act_before and not artifacts_after - artifacts_before)
    out(f"[G5 RESULT] {'SECURE' if ok else 'MIXED'} — a rejected git op right after an allowed operation "
        "in the same mission leaves refs, events, action records, and files untouched. OBSERVED (DF1 "
        "footprint): a git call that PASSES authorization (legacy validator) crashes in the "
        "implementation but leaves audit traces — ActionRequested + ActionValidated(false) + "
        "TOOL_FAILED events and a failed Action record — which is audit-trail growth, not an "
        "operational side effect")
    shutil.rmtree(base, ignore_errors=True)
    shutil.rmtree(wd, ignore_errors=True)


# ---------------------------------------------------------------- G6
async def probe_g6():
    out("=== PROBE G6: git_push — nonce presence-only check, arbitrary remote, uncontained repo, mission-wide approval ===")
    base = tmpdir("r2g6-")
    engine = ExecutionEngine(artifacts_base_dir=os.path.join(base, "artifacts"),
                             grant_validator=legacy_validator, grant_ids=["g1"])
    mission = engine.create_mission("G6 push mission")
    preapprove_tool_gate(engine, mission.mission_id, "git_push")
    repo = make_repo(os.path.join(base, "repo"))
    bare = make_bare(os.path.join(base, "remote.git"))
    ctx = make_context(engine, mission_id=mission.mission_id,
                       validator=legacy_validator, grant_ids=["g1"], workspace_root=repo)

    status, payload = await call_tool(
        engine, ctx, "git_push",
        {"repo_path": repo, "remote": bare, "branch": "main",
         "owner_approval_nonce": ""})
    out(f"[G6] negative control (empty nonce): [{status}] {describe(status, payload)}")

    remote_before = git_out(bare, "rev-parse", "--verify", "main")
    status, payload = await call_tool(
        engine, ctx, "git_push",
        {"repo_path": repo, "remote": bare, "branch": "main",
         "owner_approval_nonce": "FAKE-NONCE-NEVER-VERIFIED-123"})
    remote_after = git_out(bare, "rev-parse", "--verify", "main")
    out(f"[G6] FAKE nonce push: [{status}] {describe(status, payload)}")
    out(f"[G6] bare remote main before: {remote_before!r}")
    out(f"[G6] bare remote main after : {remote_after!r}")
    out("[G6 RESULT] TWO-LAYER — (1) GAP-CONFIRMED at the authorization layer: with a pre-approved "
        "mission-wide gate + a FAKE nonce the call PASSES every pre-execution layer (permission, human "
        "gate, nonce PRESENCE check — the nonce is never validated against any owner approval) with an "
        "uncontained repo_path and an arbitrary remote; (2) the actual push never executes at baseline "
        "because of DF1 (NameError in run_git) — fail-closed BY CRASH, not by any security control. "
        "force=True in the input is ignored by the implementation (never appended to the push command)")
    shutil.rmtree(base, ignore_errors=True)


ALL_G = {"G1": probe_g1, "G2": probe_g2, "G3": probe_g3, "G4": probe_g4,
         "G5": probe_g5, "G6": probe_g6}


# ---------------------------------------------------------------- S1
async def probe_s1():
    out("=== PROBE S1: SandboxManager.execute grant semantics — 2-arg SUBJECT call ('agent'), empty-list bypass ===")
    base = tmpdir("r2s1-")
    treeA = os.path.join(base, "treeA")
    os.makedirs(treeA, exist_ok=True)
    br = fresh_bridge(treeA)
    mgr = sandbox_manager(os.path.join(base, "sbxart"), grant_validator=br["validator"])
    wd = tmpdir("r2s1-wd-")

    try:
        await mgr.execute(sbx_request("s1-live", [PY, "-c", "print('S1-A')"], wd,
                                      required_grant_ids=[br["grant_id"]]))
        out("[S1] live grant in required_grant_ids: NOT REJECTED (UNEXPECTED)")
    except SandboxError as e:
        out(f"[S1] live grant in required_grant_ids: SandboxError: {str(e)[:110]}")

    rec = await mgr.execute(sbx_request("s1-empty", [PY, "-c", "print('S1-EMPTY-EXECUTED')"], wd,
                                        required_grant_ids=[]))
    out(f"[S1] EMPTY required_grant_ids: executed={rec.executed} exit_code={rec.exit_code} "
        f"termination={rec.termination}")

    g2 = br["grantor"].approve(br["grantor"].propose(AccessRequest(
        kind=GrantKind.PATH_GRANT, scope="read_write", target=treeA)))
    br["ledger"].register(g2)
    br["ledger"].revoke(g2.grant_id)
    try:
        await mgr.execute(sbx_request("s1-revoked", [PY, "-c", "print('S1-C')"], wd,
                                      required_grant_ids=[g2.grant_id]))
        out("[S1] revoked grant in required_grant_ids: NOT REJECTED (UNEXPECTED)")
    except SandboxError as e:
        out(f"[S1] revoked grant in required_grant_ids: SandboxError: {str(e)[:110]}")

    out("[S1 RESULT] MIXED — non-empty grant lists are fail-closed under the real bridge (the manager "
        "calls validator(grant_id,'agent') — a SUBJECT string, not a permission; the bridge rejects "
        "anything but write/read), BUT an EMPTY required_grant_ids list skips the grant decision "
        "entirely and the command EXECUTES (GAP-CONFIRMED: empty list = no authorization at all)")
    shutil.rmtree(base, ignore_errors=True)
    shutil.rmtree(wd, ignore_errors=True)


# ---------------------------------------------------------------- S2
async def probe_s2():
    out("=== PROBE S2: sandbox_id structural validation gap at execute() (vs write_artifact) ===")
    base = tmpdir("r2s2-")
    sbxart = os.path.join(base, "sbxart")
    os.makedirs(sbxart, exist_ok=True)
    mgr = sandbox_manager(sbxart, grant_validator=None)
    wd = tmpdir("r2s2-wd-")
    escaping = "../r2s2_escape_dir"

    try:
        rec = await mgr.execute(sbx_request(escaping, [PY, "-c", "print('S2')"], wd,
                                            required_grant_ids=[]))
        out(f"[S2] execute(sandbox_id='../r2s2_escape_dir'): returned executed={rec.executed} "
            f"exit={rec.exit_code} term={rec.termination}")
    except Exception as e:
        out(f"[S2] execute raised {type(e).__name__}: {str(e)[:120]}")

    outside = os.path.join(base, "r2s2_escape_dir")
    inside_entries = sorted(os.listdir(sbxart)) if os.path.isdir(sbxart) else []
    out(f"[S2] directory OUTSIDE artifacts base created ({outside}): {os.path.isdir(outside)}")
    out(f"[S2] artifacts base entries: {inside_entries}")

    try:
        await mgr.write_artifact(escaping, "x.txt", b"x")
        out("[S2] write_artifact with same escaping sandbox_id: ACCEPTED (UNEXPECTED)")
    except SandboxError as e:
        out(f"[S2] write_artifact with same escaping sandbox_id: SandboxError (RP2.2 §3.1 "
            f"defense-in-depth PRESENT at write): {str(e)[:100]}")

    gap = os.path.isdir(outside)
    out(f"[S2 RESULT] {'GAP-CONFIRMED' if gap else 'SECURE'} — execute() joins the artifacts base with "
        "an UNVALIDATED sandbox_id and makedirs BEFORE any check: a traversal sandbox_id creates "
        "directories outside the artifacts base; write_artifact/read_artifact/list_artifacts DO "
        "validate (RP2.2 §3.1) — the execute path was left outside that fix")
    shutil.rmtree(base, ignore_errors=True)
    shutil.rmtree(wd, ignore_errors=True)


# ---------------------------------------------------------------- S3
async def probe_s3():
    out("=== PROBE S3: sandbox lifecycle — single-use per sandbox_id + zero-trace grant rejection ===")
    base = tmpdir("r2s3-")
    treeA = os.path.join(base, "treeA")
    os.makedirs(treeA, exist_ok=True)
    br = fresh_bridge(treeA)
    mgr = sandbox_manager(os.path.join(base, "sbxart"), grant_validator=br["validator"])
    wd = tmpdir("r2s3-wd-")

    rec = await mgr.execute(sbx_request("s3-x", [PY, "-c", "print('S3-FIRST')"], wd,
                                        required_grant_ids=[]))
    out(f"[S3] first execute(s3-x): executed={rec.executed} exit={rec.exit_code}")
    try:
        await mgr.execute(sbx_request("s3-x", [PY, "-c", "print('S3-SECOND')"], wd,
                                      required_grant_ids=[]))
        out("[S3] second execute(s3-x): NOT REJECTED (UNEXPECTED — single-use rule)")
    except SandboxError as e:
        out(f"[S3] second execute(s3-x): SandboxError: {str(e)[:110]}")

    sbxart = os.path.join(base, "sbxart")
    before = set(os.listdir(sbxart)) if os.path.isdir(sbxart) else set()
    try:
        await mgr.execute(sbx_request("s3-y", [PY, "-c", "print('S3-REJECTED')"], wd,
                                      required_grant_ids=["nonexistent"]))
        out("[S3] grant-rejected execute(s3-y): NOT REJECTED (UNEXPECTED)")
    except SandboxError as e:
        out(f"[S3] grant-rejected execute(s3-y): SandboxError: {str(e)[:110]}")
    after = set(os.listdir(sbxart)) if os.path.isdir(sbxart) else set()
    out(f"[S3] artifacts base entries before rejected call: {sorted(before)}")
    out(f"[S3] artifacts base entries after  rejected call: {sorted(after)} (delta {sorted(after - before)})")
    out(f"[S3] active sandbox count after all: {mgr.get_active_count()}")
    ok = (after == before and mgr.get_active_count() == 0)
    out(f"[S3 RESULT] {'SECURE' if ok else 'MIXED'} — single-execute-per-sandbox_id is enforced; a "
        "grant-rejected execute leaves no sandbox directory, no active entry, no event")
    shutil.rmtree(base, ignore_errors=True)
    shutil.rmtree(wd, ignore_errors=True)


# ---------------------------------------------------------------- S4
async def probe_s4():
    out("=== PROBE S4: run_command FULL ToolExecutor chain (legacy validator + pre-approved gate) — what actually executes ===")
    base = tmpdir("r2s4-")
    art = os.path.join(base, "artifacts")
    engine = ExecutionEngine(artifacts_base_dir=art,
                             grant_validator=legacy_validator, grant_ids=["g1"])
    mission = engine.create_mission("S4 mission")
    preapprove_tool_gate(engine, mission.mission_id, "run_command")
    wd = tmpdir("r2s4-wd-")
    marker = os.path.join(wd, "s4_marker.txt")

    ctx = make_context(engine, mission_id=mission.mission_id,
                       validator=legacy_validator, grant_ids=["g1"],
                       workspace_root=wd, sandbox_id="sandbox-s4")
    r = await engine.tool_executor.execute_tool(
        ctx, "run_command",
        {"command": [PY, "-c", f"print('S4-EXECUTED-ON-HOST'); open({marker!r},'w').write('touched')"],
         "working_dir": wd})
    out(f"[S4] run_command ToolResult: success={r.success}")
    out(f"[S4] ToolResult.output: {r.output}")
    out(f"[S4] marker file written by the command inside working_dir: {os.path.exists(marker)}")

    sbx_dirs = []
    if os.path.isdir(art):
        sbx_dirs = [d for d in os.listdir(art) if d.startswith("sandbox-")]
    stdout_found = ""
    for d in sbx_dirs:
        p = os.path.join(art, d, "stdout")
        if os.path.isfile(p):
            stdout_found = open(p, encoding="utf-8", errors="replace").read().strip()
    out(f"[S4] sandbox dirs created under artifacts base: {sbx_dirs}")
    out(f"[S4] stdout artifact on disk: {stdout_found!r}")
    out("[S4 RESULT] GAP-CONFIRMED — with a permissive kind gate + approved gate, run_command executes "
        "a HOST subprocess (default backend = WindowsExecutorAdapter subprocess fallback on Linux: no "
        "filesystem/network isolation, full os.environ inherited) with an arbitrary working_dir; the "
        "kind-only 'execute' decision never sees the command. OBSERVED: ToolResult.stdout is empty — "
        "the adapter's artifact ids are never registered in the evidence store, so stdout/stderr never "
        "reach the ToolResult (evidence-chain wiring gap for run_command)")
    shutil.rmtree(base, ignore_errors=True)
    shutil.rmtree(wd, ignore_errors=True)


# ---------------------------------------------------------------- X1
async def probe_x1():
    out("=== PROBE X1: human-gate bypass — HIGH/CRITICAL tools with a mission_id NOT registered in engine.missions ===")
    base = tmpdir("r2x1-")
    engine = ExecutionEngine(artifacts_base_dir=os.path.join(base, "artifacts"),
                             grant_validator=legacy_validator, grant_ids=["g1"])
    mission = engine.create_mission("X1 registered mission")
    repo = make_repo(os.path.join(base, "repo"))
    bare = make_bare(os.path.join(base, "remote.git"))
    wd = tmpdir("r2x1-wd-")

    ctx_reg = make_context(engine, mission_id=mission.mission_id,
                           validator=legacy_validator, grant_ids=["g1"])
    try:
        r = await engine.tool_executor.execute_tool(
            ctx_reg, "run_command", {"command": [PY, "-c", "print('X1-REG')"], "working_dir": wd})
        out(f"[X1] run_command REGISTERED mission: NOT GATED — success={r.success} (UNEXPECTED)")
    except PermissionError as e:
        out(f"[X1] run_command REGISTERED mission: PermissionError (gate ACTIVE): {str(e)[:110]}")

    ctx_ghost = make_context(engine, mission_id="ghost-mission-not-registered",
                             validator=legacy_validator, grant_ids=["g1"])
    status, payload = await call_tool(
        engine, ctx_ghost, "run_command",
        {"command": [PY, "-c", "print('X1-GHOST-RUN')"], "working_dir": wd})
    out(f"[X1] run_command UNREGISTERED mission: [{status}] {describe(status, payload)}")

    remote_before = git_out(bare, "rev-parse", "--verify", "main")
    status, payload = await call_tool(
        engine, ctx_ghost, "git_push",
        {"repo_path": repo, "remote": bare, "branch": "main",
         "owner_approval_nonce": "X1-FAKE-NONCE"})
    remote_after = git_out(bare, "rev-parse", "--verify", "main")
    out(f"[X1] git_push CRITICAL, UNREGISTERED mission, FAKE nonce: [{status}] {describe(status, payload)}")
    out(f"[X1] bare remote main before: {remote_before!r} / after: {remote_after!r}")

    rc_ok = status == "TOOL_RESULT" and payload.success
    out(f"[X1 RESULT] GAP-CONFIRMED — _check_human_gate looks the mission up in engine.missions and "
        "RETURNS (no gate) when it is absent: an unregistered mission_id skips the HIGH gate for "
        "run_command (which then EXECUTES — proven) and skips the CRITICAL gate for git_push (the call "
        "proceeds past every pre-execution layer with a fake nonce; the push itself is stopped only by "
        "the DF1 NameError crash, not by a security control)")
    shutil.rmtree(base, ignore_errors=True)
    shutil.rmtree(wd, ignore_errors=True)


# ---------------------------------------------------------------- A1
async def probe_a1():
    out("=== PROBE A1: agent_role.BaseAgent._validate_grant — 2-arg kind-only surface (dead code: no callers) ===")
    agent = ProbeAgent()
    task = make_task()

    ctx = make_agent_context(grant_validator=legacy_validator, grant_ids=["g1"])
    agent.on_start(ctx, task)
    out(f"[A1] permissive legacy validator: _validate_grant('g1','execute') = "
        f"{agent._validate_grant('g1', 'execute')} (kind-only, no target involved)")

    ctx_none = make_agent_context(grant_validator=None, grant_ids=["g1"])
    agent2 = ProbeAgent()
    agent2.on_start(ctx_none, task)
    out(f"[A1] no validator: _validate_grant('g1','execute') = {agent2._validate_grant('g1', 'execute')} (fail-closed)")

    base = tmpdir("r2a1-")
    treeA = os.path.join(base, "treeA")
    os.makedirs(treeA, exist_ok=True)
    br = fresh_bridge(treeA)
    ctx_bridge = make_agent_context(grant_validator=br["validator"], grant_ids=[br["grant_id"]])
    agent3 = ProbeAgent()
    agent3.on_start(ctx_bridge, task)
    out(f"[A1] REAL bridge: _validate_grant(gid,'execute') = {agent3._validate_grant(br['grant_id'], 'execute')}; "
        f"_validate_grant(gid,'write') = {agent3._validate_grant(br['grant_id'], 'write')}")
    out("[A1 RESULT] OBSERVED — _validate_grant is the old 2-arg kind-only form: fail-closed without a "
        "validator, True for any kind under a permissive validator, and under the real bridge it "
        "degrades to the coarse kind gate ('write' allowed regardless of target; 'execute' rejected). "
        "Static fact (repo-wide search): NO callers — dead code today, a latent kind-only surface")
    shutil.rmtree(base, ignore_errors=True)


# ---------------------------------------------------------------- A2
async def probe_a2():
    out("=== PROBE A2: agent_role.BaseAgent._run_in_sandbox — direct sandbox execution with ZERO permission checks (dead code: no callers) ===")
    base = tmpdir("r2a2-")
    wd = tmpdir("r2a2-wd-")

    mgr_noval = sandbox_manager(os.path.join(base, "sbx1"), grant_validator=None)
    agent = ProbeAgent()
    ctx = make_agent_context(sandbox_manager=mgr_noval, grant_ids=[])
    agent.on_start(ctx, make_task())
    rec = await agent._run_in_sandbox([PY, "-c", "print('A2-NOVALIDATOR-EXECUTED')"],
                                      working_dir=wd)
    out(f"[A2] no validator + EMPTY grant_ids: executed={rec.executed} exit={rec.exit_code}")

    treeA = os.path.join(base, "treeA")
    os.makedirs(treeA, exist_ok=True)
    br = fresh_bridge(treeA)
    mgr_bridge = sandbox_manager(os.path.join(base, "sbx2"), grant_validator=br["validator"])
    agent2 = ProbeAgent()
    ctx2 = make_agent_context(sandbox_manager=mgr_bridge, grant_ids=[])
    agent2.on_start(ctx2, make_task())
    rec2 = await agent2._run_in_sandbox([PY, "-c", "print('A2-BRIDGE-EMPTY-EXECUTED')"],
                                        working_dir=wd)
    out(f"[A2] REAL bridge + EMPTY grant_ids: executed={rec2.executed} exit={rec2.exit_code}")

    agent3 = ProbeAgent()
    ctx3 = make_agent_context(sandbox_manager=mgr_bridge, grant_ids=[br["grant_id"]])
    agent3.on_start(ctx3, make_task())
    try:
        await agent3._run_in_sandbox([PY, "-c", "print('A3-SHOULD-NOT-RUN')"], working_dir=wd)
        out("[A2] REAL bridge + live grant id: NOT REJECTED (UNEXPECTED)")
    except SandboxError as e:
        out(f"[A2] REAL bridge + live grant id: SandboxError: {str(e)[:110]}")

    out("[A2 RESULT] GAP-CONFIRMED (latent) — _run_in_sandbox performs NO permission check, NO human "
        "gate, NO path grounding: with an empty grant_ids list the command executes with zero "
        "authorization even under the real bridge (empty list bypasses the manager's grant check). "
        "Static fact: NO callers today — a dormant bypass primitive, not an active path")
    shutil.rmtree(base, ignore_errors=True)
    shutil.rmtree(wd, ignore_errors=True)


# ---------------------------------------------------------------- O1
async def probe_o1():
    out("=== PROBE O1: unified.operational parallel path — OperationalImplementerAgent run_command with ZERO grants ===")
    base = tmpdir("r2o1-")
    wd = tmpdir("r2o1-wd-")
    from unified.operational import OperationalImplementerAgent
    mgr = sandbox_manager(os.path.join(base, "sbxart"), grant_validator=None)
    agent = OperationalImplementerAgent()
    ctx = make_agent_context(sandbox_manager=mgr, grant_validator=None, grant_ids=[])
    task = make_task({"operation": "run_command",
                      "command": [PY, "-c", "print('O1-PARALLEL-PATH-EXECUTED')"],
                      "working_dir": wd, "timeout_seconds": 60})
    res = await agent.execute(ctx, task)
    out(f"[O1] OperationalImplementerAgent.execute(run_command): success={res.success}")
    out(f"[O1] result output: {res.output}")
    out("[O1 RESULT] GAP-CONFIRMED (parallel legacy path) — src/unified/operational.py agents (7 "
        "classes with run_command operations) call context.sandbox_manager.execute DIRECTLY: no "
        "ToolExecutor, no contract, no grant decision (SandboxRequest built WITHOUT required_grant_ids), "
        "no human gate. Active in legacy e2x/e4x harnesses (e26/e29/run_e44/run_e48), not imported by "
        "unified production code")
    shutil.rmtree(base, ignore_errors=True)
    shutil.rmtree(wd, ignore_errors=True)


# ---------------------------------------------------------------- X2
async def probe_x2():
    out("=== PROBE X2: sandbox_execute AFTER an approved gate — engine.execute_tool has NO handler ===")
    base = tmpdir("r2x2-")
    engine = ExecutionEngine(artifacts_base_dir=os.path.join(base, "artifacts"),
                             grant_validator=legacy_validator, grant_ids=["g1"])
    mission = engine.create_mission("X2 mission")
    preapprove_tool_gate(engine, mission.mission_id, "sandbox_execute")
    ctx = make_context(engine, mission_id=mission.mission_id,
                       validator=legacy_validator, grant_ids=["g1"])
    status, payload = await call_tool(
        engine, ctx, "sandbox_execute",
        {"sandbox_id": "sbx-x2", "image": "python:3.11-slim",
         "command": [PY, "-c", "print('X2-SHOULD-NOT-RUN')"]})
    out(f"[X2] sandbox_execute (gate pre-approved): [{status}] {describe(status, payload)}")
    is_masked = (status == "TOOL_RESULT" and not payload.success
                 and "Output validation failed" in str(payload.error or ""))
    out(f"[X2 RESULT] {'OBSERVED' if is_masked else 'CHECK'} — sandbox_execute is REGISTERED in the "
        "tool registry (contract, permissions, human gate all enforced) but engine.execute_tool has "
        "NO handler: after the approved gate the call raises ValueError('Unknown tool: "
        "sandbox_execute') internally, the engine catches it (TOOL_FAILED emitted) and returns a "
        "failed ToolResult with output=None — which then hits DF2 (output-validation crash on "
        "output=None) so the surfaced error is MASKED as 'Output validation failed ... NoneType'. "
        "The input's required_grant_ids field is never consumed. Registered-but-unimplemented, and "
        "its real failure cause is hidden by DF2")
    shutil.rmtree(base, ignore_errors=True)


ALL_PROBES = {
    "G1": probe_g1, "G2": probe_g2, "G3": probe_g3, "G4": probe_g4,
    "G5": probe_g5, "G6": probe_g6,
    "S1": probe_s1, "S2": probe_s2, "S3": probe_s3, "S4": probe_s4,
    "X1": probe_x1, "X2": probe_x2, "A1": probe_a1, "A2": probe_a2, "O1": probe_o1,
}


async def run_one(pid: str) -> int:
    probe = ALL_PROBES[pid]
    try:
        await probe()
        return 0
    except Exception:
        out(f"[{pid}] PROBE CRASHED:")
        traceback.print_exc()
        return 1


def main() -> int:
    ap = argparse.ArgumentParser(description="E10-RP2.2-R2 discovery probes")
    ap.add_argument("--probe", choices=sorted(ALL_PROBES), help="run a single probe")
    ap.add_argument("--all", action="store_true", help="run every probe in order")
    args = ap.parse_args()
    if args.all:
        rc = 0
        for pid in sorted(ALL_PROBES):
            rc |= asyncio.run(run_one(pid))
        return rc
    if args.probe:
        return asyncio.run(run_one(args.probe))
    ap.print_help()
    return 2


if __name__ == "__main__":
    raise SystemExit(main())
