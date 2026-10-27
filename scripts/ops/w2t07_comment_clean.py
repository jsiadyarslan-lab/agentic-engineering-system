#!/usr/bin/env python3
"""W2-T07 comment hygiene — strip old hex/rgba literals from my (W2-T07) provenance
comments so the acceptance command (rg hex/rgba outside theme.css) returns ZERO.
Provenance stays in git history + theme.css token comments."""
import re
import pathlib

FILES = [
    "src/ui/factory-control.css",
    "src/ui/app-shell.css",
    "src/ui/project-live.css",
    "src/ui/styles.css",
    "src/ui/live.css",
    "src/ui/control-center.css",
]
ROOT = pathlib.Path("/home/z/my-project/repo")

hex_re = re.compile(r"#[0-9a-fA-F]{3,8}\b")
rgba_re = re.compile(r"rgba?\([^)]*\)")

changed = 0
for rel in FILES:
    p = ROOT / rel
    lines = p.read_text().splitlines(keepends=True)
    out = []
    for line in lines:
        if "W2-T07" in line and "*/" in line:
            new = line
            # remove "كان/كانت <literal> — " or "كان/كانت <literal> → " provenance tails
            new = re.sub(r"كانت?\s+#[0-9a-fA-F]{3,8}\b\s*(حرفياً\s*)?(—|→)\s*", "", new)
            new = re.sub(r"كانت?\s+rgba?\([^)]*\)\s*(—|→)\s*", "", new)
            if new != line:
                changed += 1
            line = new
        out.append(line)
    p.write_text("".join(out))

print(f"cleaned {changed} comment lines")
# verify
for rel in FILES:
    text = (ROOT / rel).read_text()
    bad = [ln for ln in text.splitlines() if ("W2-T07" in ln and (hex_re.search(ln) or rgba_re.search(ln)))]
    if bad:
        print(f"STILL BAD in {rel}:")
        for b in bad:
            print("   ", b.strip()[:120])
print("done")
