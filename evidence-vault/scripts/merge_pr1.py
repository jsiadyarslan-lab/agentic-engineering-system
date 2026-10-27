#!/usr/bin/env python3
"""Phase 3 of AES-UI-PREMIUM-REDESIGN-005: un-draft PR #1 and merge it
into main with a history-preserving merge commit.

Subcommands:
  undraft    mark PR #1 ready for review (GraphQL)
  merge      merge PR #1 (merge_method=merge) after verifying head sha
  state      print PR #1 state + main head
"""
import json
import subprocess
import sys
import urllib.request
import urllib.error

REPO = "jsiadyarslan-lab/agentic-engineering-system"
API = "https://api.github.com"
EXPECTED_HEAD = "d55f4bba6b2f0133b446a1b6ba3d51105305eb64"


def get_token():
    url = subprocess.run(
        ["git", "-C", "/home/z/my-project/repo", "remote", "get-url", "origin"],
        capture_output=True, text=True, check=True,
    ).stdout.strip()
    _proto, rest = url.split("//", 1)
    if "@" in rest:
        return rest.split("@", 1)[0]
    raise SystemExit("no token found in remote url")


def request(path, method="GET", body=None):
    data = json.dumps(body).encode() if body is not None else None
    req = urllib.request.Request(
        API + path,
        data=data,
        headers={
            "Authorization": "token " + get_token(),
            "Accept": "application/vnd.github+json",
            "User-Agent": "aes-005-merge",
            "Content-Type": "application/json",
        },
        method=method,
    )
    try:
        with urllib.request.urlopen(req) as resp:
            return json.loads(resp.read() or b"{}")
    except urllib.error.HTTPError as e:
        raise SystemExit(f"HTTP {e.code} on {method} {path}: {e.read().decode(errors='replace')[:600]}")


def graphql(query):
    req = urllib.request.Request(
        API + "/graphql",
        data=json.dumps({"query": query}).encode(),
        headers={
            "Authorization": "token " + get_token(),
            "User-Agent": "aes-005-merge",
            "Content-Type": "application/json",
        },
        method="POST",
    )
    try:
        with urllib.request.urlopen(req) as resp:
            return json.loads(resp.read() or b"{}")
    except urllib.error.HTTPError as e:
        raise SystemExit(f"HTTP {e.code} on graphql: {e.read().decode(errors='replace')[:600]}")


def get_pr():
    return request(f"/repos/{REPO}/pulls/1")


def cmd_undraft():
    pr = get_pr()
    if not pr.get("draft"):
        print(f"PR #1 already ready (draft=False), state={pr['state']}")
        return
    node_id = pr["node_id"]
    result = graphql(
        'mutation { markPullRequestReadyForReview('
        f'input: {{pullRequestId: "{node_id}"}}) '
        '{ pullRequest { number isDraft state } } }'
    )
    if "errors" in result:
        raise SystemExit(f"GraphQL errors: {result['errors']}")
    pr_info = result["data"]["markPullRequestReadyForReview"]["pullRequest"]
    print(f"PR #{pr_info['number']}: isDraft={pr_info['isDraft']} state={pr_info['state']}")


def cmd_merge():
    pr = get_pr()
    print(f"PR #1 before merge: state={pr['state']} draft={pr['draft']} merged={pr['merged']}")
    print(f"head: {pr['head']['sha']}")
    if pr["head"]["sha"] != EXPECTED_HEAD:
        raise SystemExit(f"ABORT: PR head {pr['head']['sha']} != expected {EXPECTED_HEAD}")
    if pr["merged"]:
        print("already merged — nothing to do")
        return
    result = request(f"/repos/{REPO}/pulls/1/merge", method="PUT", body={
        "sha": EXPECTED_HEAD,
        "merge_method": "merge",
        "commit_title": "merge(aes-integration-004): AES-UI-PREMIUM-REDESIGN-005 release — first executor + UI redesign (d55f4bb)",
    })
    print(f"merge result: {json.dumps(result, indent=2)}")
    main = request(f"/repos/{REPO}/branches/main")
    print(f"\nmain head after merge: {main['commit']['sha']}")
    print(f"main head message: {main['commit']['commit']['message'][:120]}")


def cmd_state():
    pr = get_pr()
    print(f"PR #1: state={pr['state']} draft={pr['draft']} merged={pr['merged']} "
          f"merge_commit_sha={pr.get('merge_commit_sha')}")
    print(f"head: {pr['head']['ref']} @ {pr['head']['sha']}")
    print(f"base: {pr['base']['ref']} @ {pr['base']['sha']}")
    main = request(f"/repos/{REPO}/branches/main")
    print(f"main: {main['commit']['sha']}")


if __name__ == "__main__":
    cmd = sys.argv[1] if len(sys.argv) > 1 else "state"
    if cmd == "undraft":
        cmd_undraft()
    elif cmd == "merge":
        cmd_merge()
    elif cmd == "state":
        cmd_state()
    else:
        raise SystemExit(f"unknown subcommand: {cmd}")
