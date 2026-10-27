#!/bin/bash
# AES-AUDIT-001 — forensic code metrics for the frontend + repo (read-only, local repo @0f2d9c6)
cd /home/z/my-project/repo
echo "===== 1) FRONTEND RAW WEIGHT ====="
echo "index.html bytes: $(wc -c < src/ui/index.html)"
echo "total CSS bytes: $(git ls-files 'src/ui/*.css' | xargs cat | wc -c)"
echo "total JS bytes: $(git ls-files 'src/ui/*.js' | xargs cat | wc -c)"
echo "fonts bytes: $(git ls-files 'src/ui/fonts/*.woff2' | xargs cat | wc -c)"
echo "asset files referenced: $(grep -cE '\?v=' src/ui/index.html)"

echo
echo "===== 2) CSS FORENSICS ====="
ALLCSS=$(mktemp); git ls-files 'src/ui/*.css' | xargs cat > "$ALLCSS"
echo "css custom props defined (--x:): $(grep -oE '^\s*--[a-z0-9-]+\s*:' "$ALLCSS" | sort -u | wc -l)"
echo "!important count: $(grep -c '!important' "$ALLCSS" || true)"
echo "hardcoded hex colors: $(grep -oE '#[0-9a-fA-F]{3,8}\b' "$ALLCSS" | sort -u | wc -l)"
echo "distinct hardcoded hex values: $(grep -oE '#[0-9a-fA-F]{3,8}\b' "$ALLCSS" | sort -u | head -40 | tr '\n' ' ')"
echo "rgba() literals: $(grep -oE 'rgba?\([0-9]' "$ALLCSS" | wc -l)"
echo "z-index declarations: $(grep -oE 'z-index:\s*[0-9]+' "$ALLCSS" | sort | uniq -c | sort -rn | head -10)"
echo "media queries: $(grep -c '@media' "$ALLCSS" || true)"
echo "px literals: $(grep -oE '[0-9]+px' "$ALLCSS" | wc -l)"
echo "var() usages: $(grep -oE 'var\(--' "$ALLCSS" | wc -l)"
echo "keyframes: $(grep -c '@keyframes' "$ALLCSS" || true)"

echo
echo "===== 3) JS FORENSICS ====="
ALLJS=$(mktemp); git ls-files 'src/ui/*.js' | xargs cat > "$ALLJS"
echo "innerHTML assignments: $(grep -oE '\.innerHTML\s*=' "$ALLJS" | wc -l)"
echo "insertAdjacentHTML: $(grep -c 'insertAdjacentHTML' "$ALLJS" || true)"
echo "fetch() calls: $(grep -oE 'fetch\(' "$ALLJS" | wc -l)"
echo "addEventListener: $(grep -oE 'addEventListener\(' "$ALLJS" | wc -l)"
echo "window.* exports (globals): $(grep -oE 'window\.[A-Z][A-Za-z]+ *=' "$ALLJS" | sort | uniq -c | sort -rn | head -15)"
echo "setTimeout: $(grep -oE 'setTimeout\(' "$ALLJS" | wc -l)"
echo "setInterval: $(grep -oE 'setInterval\(' "$ALLJS" | wc -l)"
echo "console.log/warn/error: $(grep -oE 'console\.(log|warn|error)\(' "$ALLJS" | wc -l)"
echo "try/catch blocks: $(grep -oE 'catch \(?\(?[a-z]*\)?' "$ALLJS" | wc -l)"
echo "TODO/FIXME/HACK: $(grep -oiE '(TODO|FIXME|HACK|XXX)\b' "$ALLJS" | wc -l)"
echo "files >1000 lines:"; git ls-files 'src/ui/*.js' 'src/ui/*.css' | while read f; do n=$(wc -l < "$f"); [ "$n" -gt 1000 ] && echo "  $f: $n"; done

echo
echo "===== 4) BACKEND SHAPE ====="
echo "python files (src only): $(git ls-files 'src/**/*.py' | wc -l)"
echo "python LOC (src): $(git ls-files 'src/**/*.py' | xargs wc -l | tail -1)"
echo "largest python files:"; git ls-files 'src/**/*.py' | xargs wc -l | sort -rn | head -8
echo "api routes files: $(git ls-files 'src/api/*.py' | xargs wc -l | tail -1)"

echo
echo "===== 5) REPO HYGIENE ====="
echo "total tracked files: $(git ls-files | wc -l)"
echo "docs/ files: $(git ls-files docs/ | wc -l) ($(git ls-files docs/ | xargs cat 2>/dev/null | wc -c) bytes)"
echo "E10/ files: $(git ls-files E10/ | wc -l)"
echo "runtime/ tracked files: $(git ls-files runtime/ | wc -l)"
echo "experiments dirs at root: $(git ls-files | awk -F/ '{print $1}' | grep -cE '^E[0-9]|^e[0-9]|^phase' )"
echo "README files at root: $(git ls-files | grep -c 'README')"
echo "scripts/ files: $(git ls-files scripts/ | wc -l)"

echo
echo "===== 6) A11Y QUICK AUDIT (index.html) ====="
echo "aria-label attrs: $(grep -oc 'aria-label' src/ui/index.html || echo 0)"
echo "role= attrs: $(grep -oc 'role=' src/ui/index.html || echo 0)"
echo "alt= attrs: $(grep -oc 'alt=' src/ui/index.html || echo 0)"
echo "lang attr: $(grep -oE '<html[^>]*lang=[^ >]*' src/ui/index.html)"
echo "focus-visible in css: $(grep -c 'focus-visible' "$ALLCSS" || true)"
echo "prefers-reduced-motion: $(grep -c 'prefers-reduced-motion' "$ALLCSS" || true)"
rm -f "$ALLCSS" "$ALLJS"
