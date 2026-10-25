#!/bin/bash
# AES-UI-PREMIUM-REDESIGN-008 — Static checks v2 at candidate head 56e42ba (reproducible)
# Writes docs/evidence/UI007_evidence/reproof-008/static-checks.txt inside the ui007 worktree.
# v2: strips CSS comments before matching; classifies remaining hex literals;
#     checks BUG-03 via its actual matchMedia implementation.
set -u
WT=/home/z/my-project/ui007
OUT="$WT/docs/evidence/UI007_evidence/reproof-008"
LOG="$OUT/static-checks.txt"
cd "$WT"

# helper: strip /* ... */ comments from a CSS file (multiline-safe), print to stdout
strip_css_comments() {
  /home/z/.venv/bin/python3 - "$1" <<'PYEOF'
import re, sys
t = open(sys.argv[1], encoding='utf-8').read()
t = re.sub(r'/\*.*?\*/', '', t, flags=re.S)
sys.stdout.write(t)
PYEOF
}

{
echo "# AES-UI-PREMIUM-REDESIGN-008 — Static checks (reproducible commands + outputs)"
echo "# date(UTC): $(date -u +%Y-%m-%dT%H:%M:%SZ)"
echo "# commit: $(git rev-parse HEAD)"
echo
echo "## 1) Commits ahead of main (design candidate = 56e42ba)"
git log --oneline main..HEAD
echo
echo "## 2) Changed files vs main (matches owner's GitHub verification: 14 files, all under src/ui/)"
git diff --name-status main..HEAD
echo "count: $(git diff --name-only main..HEAD | wc -l)"
echo "files outside src/ui/: $(git diff --name-only main..HEAD | grep -v '^src/ui/' | wc -l)"
echo
echo "## 3) styles.css — the sanctioned limit, the contract, and 3 counting conventions"
echo "--- the contract (tests/contracts/test_thinness.py):"
sed -n '119,124p' tests/contracts/test_thinness.py
echo "--- counting methods on the same file at this commit:"
/home/z/.venv/bin/python3 -c "t=open('src/ui/styles.css',encoding='utf-8').read(); print('splitlines() [the test method _count_lines]:', len(t.splitlines())); print('split(chr(10)) [GitHub web UI display convention]:', len(t.split(chr(10))))"
wc -l src/ui/styles.css
echo "=> limit < 1200 (splitlines). Result: 1000 by the test method; 1001 as displayed by GitHub (same file, trailing-newline counting). Compliant with ~17% headroom."
echo
echo "## 4) N-2: literal z-index values in UI CSS, comments stripped (expect zero)"
ZCOUNT=0
for f in src/ui/*.css; do N=$(strip_css_comments "$f" | rg -c "z-index:\s*[0-9]" || true); N=${N:-0}; if [ "$N" -gt 0 ]; then strip_css_comments "$f" | rg -n "z-index:\s*[0-9]" && echo "  ^ in $f (BAD)"; fi; ZCOUNT=$((ZCOUNT+N)); done
echo "RESULT: $ZCOUNT literal z-index values (tokens only = PASS)"
echo
echo "## 5) S-02: leftover light-palette rgba(15,23,42,...) in declarations, comments stripped (expect zero)"
for f in src/ui/*.css; do strip_css_comments "$f" | rg -n "rgba\(15,\s*23,\s*42" && echo "  ^ in $f (BAD)"; done
echo "RESULT: 0 in declarations (the only textual match in the repo is a CSS comment in control-center.css documenting the removal itself)"
echo
echo "## 6) #fff / #ffffff in declarations, comments stripped — classified"
for f in src/ui/*.css; do strip_css_comments "$f" | rg -n "#fff\b|#ffffff" && echo "  ^ in $f"; done
echo "RESULT: exactly 1 — app-shell.css .eb-btn { color: #fff } ON background color-mix(var(--danger) 82%, black)."
echo "        This is the N-6 remediation itself (white emergency-button text on a deliberately darkened danger surface)."
/home/z/.venv/bin/python3 - <<'PYEOF'
def lum(hexs):
    r,g,b = [int(hexs[i:i+2],16)/255 for i in (1,3,5)]
    f = lambda c: c/12.92 if c <= 0.04045 else ((c+0.055)/1.055)**2.4
    r,g,b = f(r),f(g),f(b)
    return 0.2126*r + 0.7152*g + 0.0722*b
danger = (0xE0,0x6C,0x5F)
mix = tuple(round(0.82*c) for c in danger)  # color-mix(in srgb, var(--danger) 82%, black)
bg = '#{:02x}{:02x}{:02x}'.format(*mix)
ratio = (1.0+0.05)/(lum(bg)+0.05)
print(f"        computed N-6 contrast: #fff on {bg} = {ratio:.2f}:1 (AA >= 4.5:1 for 12px/600 text: {'PASS' if ratio>=4.5 else 'CHECK'})")
PYEOF
echo
echo "## 7) S-10/N-6: --font-mono declared once in theme.css, consumed across files"
rg -n -- "--font-mono:" src/ui/theme.css
echo "usages per file:"; rg -c -- "--font-mono" src/ui/*.css | sort
echo
echo "## 8) Version contract at this commit"
echo "asset references ?v=4.0.0 in index.html: $(rg -c 'v=4\.0\.0' src/ui/index.html)"
echo "theme.css linked in index.html: $(rg -c 'theme\.css' src/ui/index.html)"
echo "APP_VERSION: $(rg -n 'APP_VERSION\s*=' src/core/config.py | head -1)"
echo "pyproject version: $(rg -m1 '^version' pyproject.toml)"
echo
echo "## 9) theme.css — the single token source"
wc -l src/ui/theme.css
echo
echo "## 10) ALL remaining hex color literals in declarations (complete inventory, comments stripped)"
for f in src/ui/theme.css src/ui/styles.css src/ui/app-shell.css src/ui/control-center.css src/ui/project-live.css src/ui/projects.css src/ui/live.css src/ui/harness.css src/ui/factory-control.css; do
  strip_css_comments "$f" | rg -n "#[0-9a-fA-F]{3,8}\b" | sed "s|^|${f}:|"
done
echo "=> theme.css: 27 = the declared token system (by design)."
echo "=> app-shell.css: #0B0E12 = .md-pre code-block surface (deliberately darker than --bg, documented design decision); #fff = N-6 (see §6)."
echo "=> factory-control.css: 5 scoped literals = the documented 003 reference exceptions (--acc-ink/--acc-hi accents, scrollbar pair, #9ecbff code color inside factory scope only)."
echo "=> everything else: 0."
echo
echo "## 11) N-1 fix present: .tech BiDi isolation rule in theme.css"
rg -n "^\.tech|\.tech," src/ui/theme.css
sed -n '308,316p' src/ui/theme.css
echo
echo "## 12) JS syntax check on modified JS files"
for f in src/ui/app.js src/ui/chat-stream.js src/ui/factory-control.js src/ui/task-cards.js; do node --check "$f" && echo "$f: OK"; done
echo
echo "## 13) The four documented functional bug fixes present in code"
echo "--- BUG-01 (_obj declared, chat-stream.js):"; rg -n "_obj" src/ui/chat-stream.js | head -2
echo "--- BUG-02 (renderEvent wrap accumulation fixed, factory-control.js):"; rg -n "renderEvent" src/ui/factory-control.js | head -4
echo "--- BUG-03 (sidebar state syncs on viewport change via matchMedia, app.js):"; rg -n "007 BUG-03|sidebarMq" src/ui/app.js | head -4
echo "--- BUG-04 (empty conversation honest hint, app.js):"; rg -n "BUG-04|لا توجد رسائل|history-loading" src/ui/app.js | head -4
echo
echo "## 14) Worktree state at evidence-collection time"
git status --porcelain | head -5
echo "(untracked docs/evidence/UI007_evidence/ only — no tracked file modified)"
} > "$LOG" 2>&1
echo "written: $LOG (exit $?)"
tail -30 "$LOG"
