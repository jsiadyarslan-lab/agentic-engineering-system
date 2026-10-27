#!/usr/bin/env python3
"""AES-011 — merge aes-live-reconciliation-011 into main (ff-only, ref update force=false)."""
import json
import subprocess
import urllib.request

REPO = "jsiadyarslan-lab/agentic-engineering-system"


def get_token():
    url = subprocess.run(
        ["git", "-C", "/home/z/my-project/repo", "remote", "get-url", "origin"],
        capture_output=True, text=True, check=True).stdout.strip()
    _proto, rest = url.split("//", 1)
    return rest.split("@", 1)[0] if "@" in rest else None


TOKEN = get_token()
HEAD_SHA = "947e6e55e9d53517b7424ab0a932fef4941d0635"


def api(path, method="GET", body=None):
    req = urllib.request.Request(
        f"https://api.github.com{path}", method=method,
        data=json.dumps(body).encode() if body else None,
        headers={"Authorization": f"token {TOKEN}",
                 "User-Agent": "aes-011-merge",
                 "Accept": "application/vnd.github+json"})
    try:
        with urllib.request.urlopen(req) as r:
            return r.status, json.loads(r.read() or b"{}")
    except urllib.error.HTTPError as e:
        return e.code, json.loads(e.read() or b"{}")


# 1) preconditions
st, main = api(f"/repos/{REPO}/git/ref/heads/main")
assert st == 200 and main["object"]["sha"] == "4568ed5dcba44c6bbb112107830b9a2eb1ab5a9f", main
print(f"main before: {main['object']['sha']}")

st, cmp = api(f"/repos/{REPO}/compare/4568ed5dcba44c6bbb112107830b9a2eb1ab5a9f...{HEAD_SHA}")
assert st == 200, cmp
print(f"ahead={cmp['ahead_by']} behind={cmp['behind_by']} merge_base_commit={cmp['merge_base_commit']['sha'][:12]}")
assert cmp["behind_by"] == 0 and cmp["merge_base_commit"]["sha"] == main["object"]["sha"], \
    "not a fast-forward — abort"

# 2) ff-only ref update (force=false)
st, upd = api(f"/repos/{REPO}/git/refs/heads/main", method="PATCH",
              body={"sha": HEAD_SHA, "force": False})
print(f"ref update: {st}")
assert st == 200, upd

st, main2 = api(f"/repos/{REPO}/git/ref/heads/main")
print(f"main after: {main2['object']['sha']}")
assert main2["object"]["sha"] == HEAD_SHA
print("MERGE OK (ff) — main =", HEAD_SHA)
