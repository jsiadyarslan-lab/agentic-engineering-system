#!/usr/bin/env python3
"""AES-UI-PREMIUM-REDESIGN-009 — FINAL CI VERIFICATION & MERGE READINESS.

Read-only audit tool. Subcommands:
  pr          PR #3 full state: draft/merged/head/base/commits/mergeable
  runs        all workflow runs for branch aes-ui-premium-redesign-007,
              annotated with head_sha match against 4568ed5
  jobs RUNID  jobs + per-step conclusions for one run
  joblog JOBID  download one job's log to stdout (handles Azure 302)
NO write operations in this tool (unlike ci_closeout.py).
"""
import json
import subprocess
import sys
import urllib.request
import urllib.error

REPO = "jsiadyarslan-lab/agentic-engineering-system"
HEAD_SHA = "4568ed5dcba44c6bbb112107830b9a2eb1ab5a9f"
BRANCH = "aes-ui-premium-redesign-007"
API = "https://api.github.com"


def get_token():
    url = subprocess.run(
        ["git", "-C", "/home/z/my-project/repo", "remote", "get-url", "origin"],
        capture_output=True, text=True, check=True,
    ).stdout.strip()
    _proto, rest = url.split("//", 1)
    if "@" in rest:
        return rest.split("@", 1)[0]
    raise SystemExit("no token found in remote url")


def request(path, method="GET", body=None, raw=False):
    data = json.dumps(body).encode() if body is not None else None
    req = urllib.request.Request(
        API + path,
        data=data,
        headers={
            "Authorization": "token " + get_token(),
            "Accept": "application/vnd.github+json",
            "User-Agent": "aes-audit-009",
            "Content-Type": "application/json",
        },
        method=method,
    )
    try:
        with urllib.request.urlopen(req) as resp:
            payload = resp.read()
            return payload if raw else json.loads(payload or b"{}")
    except urllib.error.HTTPError as e:
        raise SystemExit(f"HTTP {e.code} on {method} {path}: {e.read().decode(errors='replace')[:600]}")


def cmd_pr():
    pr = request(f"/repos/{REPO}/pulls/3")
    print("=== PR #3 ===")
    for k in ("state", "draft", "merged", "merged_at", "title", "created_at",
              "updated_at", "closed_at", "mergeable_state", "commits", "additions",
              "deletions", "changed_files"):
        print(f"{k}: {pr.get(k)}")
    print(f"base: {pr['base']['ref']} @ {pr['base']['sha']}")
    print(f"head: {pr['head']['ref']} @ {pr['head']['sha']}")
    print(f"head_matches_4568ed5: {pr['head']['sha'] == HEAD_SHA}")
    print(f"url: {pr.get('html_url')}")

    print("\n=== PR #3 COMMITS ===")
    commits = request(f"/repos/{REPO}/pulls/3/commits?per_page=100")
    for c in commits:
        msg_first = c["commit"]["message"].splitlines()[0]
        print(f"{c['sha']} | {c['commit']['author']['name']} | {c['commit']['author']['date']} | {msg_first[:90]}")

    print("\n=== PR #3 STATUS CHECKS (combined) ===")
    try:
        comb = request(f"/repos/{REPO}/commits/{pr['head']['sha']}/status")
        print(f"combined state: {comb.get('state')} (total {len(comb.get('statuses', []))})")
        for st in comb.get("statuses", []):
            print(f"  - {st.get('context')}: {st.get('state')} | {st.get('description', '')[:80]} | target: {st.get('target_url')}")
    except SystemExit as e:
        print(f"(combined status unavailable: {e})")

    print("\n=== PR #3 CHECK RUNS ===")
    checks = request(f"/repos/{REPO}/commits/{pr['head']['sha']}/check-runs?per_page=100")
    for cr in checks.get("check_runs", []):
        print(f"  - [{cr.get('status')}/{cr.get('conclusion')}] {cr.get('name')} | started={cr.get('started_at')} completed={cr.get('completed_at')} | {cr.get('html_url')}")


def cmd_runs():
    print(f"=== ALL RUNS FOR BRANCH {BRANCH} ===")
    runs = request(f"/repos/{REPO}/actions/runs?branch={BRANCH}&per_page=100")
    for r in runs.get("workflow_runs", []):
        match = "== HEAD 4568ed5" if r["head_sha"] == HEAD_SHA else f"  (other head {r['head_sha'][:12]})"
        print(f"run {r['id']} | #{r['run_number']} | event={r['event']} | {r['status']}/{r.get('conclusion')} "
              f"| branch={r['head_branch']} | head={r['head_sha'][:12]} {match}")
        print(f"      title: {r.get('display_title', '')[:100]}")
        print(f"      started={r.get('run_started_at')} updated={r.get('updated_at')}")
        print(f"      url: {r.get('html_url')}")
    print(f"\ntotal: {runs.get('total_count')}")


def cmd_jobs(run_id):
    jobs = request(f"/repos/{REPO}/actions/runs/{run_id}/jobs")
    run = request(f"/repos/{REPO}/actions/runs/{run_id}")
    print(f"=== RUN {run_id} ===")
    for k in ("display_title", "event", "status", "conclusion", "head_branch",
              "head_sha", "path", "run_started_at", "updated_at", "html_url"):
        print(f"{k}: {run.get(k)}")
    print("\n=== JOBS ===")
    for job in jobs.get("jobs", []):
        print(f"job {job['id']} | name={job['name']} | runner={job.get('runner_name')} | "
              f"labels={job.get('labels')} | status={job['status']} | conclusion={job.get('conclusion')}")
        for step in job.get("steps", []):
            print(f"  - step {step['number']:>2} '{step['name']}' status={step['status']} conclusion={step.get('conclusion')}")


class NoRedirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        return None


def cmd_joblog(job_id):
    token = get_token()
    req = urllib.request.Request(
        f"{API}/repos/{REPO}/actions/jobs/{job_id}/logs",
        headers={
            "Authorization": "token " + token,
            "Accept": "application/vnd.github+json",
            "User-Agent": "aes-audit-009",
        },
        method="GET",
    )
    opener = urllib.request.build_opener(NoRedirect)
    location = None
    try:
        with opener.open(req) as resp:
            sys.stdout.buffer.write(resp.read())
            return
    except urllib.error.HTTPError as e:
        if e.code in (301, 302, 303, 307, 308) and "Location" in e.headers:
            location = e.headers["Location"]
        else:
            raise
    req2 = urllib.request.Request(location, headers={"User-Agent": "aes-audit-009"})
    with urllib.request.urlopen(req2) as resp2:
        sys.stdout.buffer.write(resp2.read())


if __name__ == "__main__":
    cmd = sys.argv[1] if len(sys.argv) > 1 else "pr"
    if cmd == "pr":
        cmd_pr()
    elif cmd == "runs":
        cmd_runs()
    elif cmd == "jobs":
        cmd_jobs(sys.argv[2])
    elif cmd == "joblog":
        cmd_joblog(sys.argv[2])
    else:
        raise SystemExit(f"unknown subcommand: {cmd}")
