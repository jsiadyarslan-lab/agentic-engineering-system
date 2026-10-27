#!/usr/bin/env python3
"""AES-011 — functional proof of commit-based asset versioning (in-process)."""
import hashlib
import re
import subprocess
import sys

sys.path.insert(0, "/home/z/my-project/wt-011/src")
sys.path.insert(0, "/home/z/my-project/wt-011")

from fastapi.testclient import TestClient  # noqa: E402
import api.routes as routes  # noqa: E402

VER = routes._ASSET_VERSION
print(f"[version] _ASSET_VERSION = {VER!r}")

sha = subprocess.run(["git", "rev-parse", "--short=8", "HEAD"],
                     cwd="/home/z/my-project/wt-011",
                     capture_output=True).stdout.decode().strip()
print(f"[version] git short sha   = {sha!r}")
assert VER == sha, "version must equal git short sha in this repo"

c = TestClient(routes.app)

# 1) HTML served with versioned URLs + correct headers
r = c.get("/")
assert r.status_code == 200
body = r.content
n_new = body.count(f"?v={VER}".encode())
n_old = body.count(b"?v=4.0.0")
print(f"[html] status=200  ?v={VER} x{n_new}   leftover ?v=4.0.0 x{n_old}")
assert n_new >= 27 and n_old == 0
assert r.headers["cache-control"] == "no-cache"
assert r.headers["etag"] == f'"ui{VER}"'
print(f"[html] cache-control=no-cache  etag={r.headers['etag']}")

# 2) conditional revalidation of the HTML (the owner's stale-HTML killer)
r304 = c.get("/", headers={"If-None-Match": f'"ui{VER}"'})
print(f"[html] conditional GET -> {r304.status_code}")
assert r304.status_code == 304

# 3) per-type cache policy
cases = [
    (f"/static/theme.css?v={VER}", "public, max-age=31536000, immutable"),
    (f"/static/app.js?v={VER}", "public, max-age=31536000, immutable"),
    ("/static/theme.css?v=4.0.0", "no-cache"),      # stale/foreign version
    ("/static/theme.css", "no-cache"),               # unversioned
    ("/static/fonts/fonts.css", "no-cache"),         # fonts loaded from CSS
]
for path, expect in cases:
    rr = c.get(path)
    got = rr.headers.get("cache-control")
    mark = "OK" if got == expect else "FAIL"
    print(f"[policy] {mark} {path:42s} -> {got}")
    assert got == expect, (path, got, expect)

# 4) served bytes == git blob bytes (substitution touches HTML only)
blob = subprocess.run(["git", "show", "HEAD:src/ui/theme.css"],
                      cwd="/home/z/my-project/wt-011", capture_output=True).stdout
served = c.get(f"/static/theme.css?v={VER}").content
print(f"[bytes] theme.css served sha256={hashlib.sha256(served).hexdigest()[:16]} "
      f"git-blob sha256={hashlib.sha256(blob).hexdigest()[:16]}")
assert served == blob

blob_idx = subprocess.run(["git", "show", "HEAD:src/ui/index.html"],
                          cwd="/home/z/my-project/wt-011", capture_output=True).stdout
assert body != blob_idx and b"?v=" + VER.encode() in body
print("[bytes] index.html served != file-on-disk (substituted) as designed")
print("\nALL FUNCTIONAL CHECKS PASSED")
