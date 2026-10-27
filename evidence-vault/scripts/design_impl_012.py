#!/usr/bin/env python3
"""AES-DESIGN-IMPL-012 — apply the owner-approved mockup design system.

Source of truth: the mockup the owner attached (dark #0b0e14 + blue
#58a6ff + IBM Plex Sans Arabic + radii 8/12/16 + 292px sidebar).
Every replacement is count-checked; the script aborts loudly if any
anchor is missing so nothing silently no-ops.
"""
import re
import sys
from pathlib import Path

UI = Path("/home/z/my-project/repo/src/ui")
TESTS = Path("/home/z/my-project/repo/tests/api/test_ui_structure_order010.py")

changed = {}


def sub_lines(path, pairs):
    """Line-oriented replacements with expected-count assertions.
    Idempotent: if old is gone but new is already present, count as applied."""
    text = path.read_text(encoding="utf-8")
    applied = 0
    for old, new, expect in pairs:
        n = text.count(old)
        if n == 0 and text.count(new) >= expect:
            applied += 1  # already applied by an earlier run
            continue
        if n != expect:
            sys.exit(f"ABORT {path.name}: {old!r} found {n}x, expected {expect}")
        text = text.replace(old, new)
        applied += 1
    path.write_text(text, encoding="utf-8")
    changed[path.name] = changed.get(path.name, 0) + applied


def _norm(s):
    return re.sub(r"\s+", " ", s).strip()


def sub_block(path, selector, new_block, expect=1):
    """Replace a whole CSS block: exact `selector {` (whitespace before brace
    only — so `.new-chat` does NOT match `.new-chat:hover {`).
    Idempotent: skips when new_block content (whitespace-normalized) exists."""
    text = path.read_text(encoding="utf-8")
    if _norm(new_block) in _norm(text):
        changed[path.name] = changed.get(path.name, 0) + 1
        return
    pat = re.compile(re.escape(selector) + r"\s*\{[^{}]*\}", re.DOTALL)
    found = pat.findall(text)
    if len(found) != expect:
        sys.exit(f"ABORT {path.name}: block selector {selector!r} matched {len(found)}x")
    text = pat.sub(lambda m: new_block, text, count=1)
    path.write_text(text, encoding="utf-8")
    changed[path.name] = changed.get(path.name, 0) + 1


# --------------------------------------------------------------------------
# 1) theme.css — token swap to the mockup palette
# --------------------------------------------------------------------------
theme = UI / "theme.css"
sub_lines(theme, [
    # surfaces
    ("--bg: #0D1014;", "--bg: #0b0e14;", 1),
    ("--bg-sidebar: #10141A;", "--bg-sidebar: #0f141d;", 1),
    ("--bg-raised: #141920;", "--bg-raised: #121826;", 1),
    ("--bg-elevated: #1B222A;", "--bg-elevated: #171e2c;", 1),
    ("--bg-input: #161C24;", "--bg-input: #0b0e14;", 1),
    ("--bg-hover: #1F2731;", "--bg-hover: #141b28;", 1),
    ("--bubble-user: #1E2630;", "--bubble-user: #171e2c;", 1),
    # borders
    ("--border: #2A333D;", "--border: #222a38;", 1),
    ("--border-soft: #202932;", "--border-soft: #1b2231;", 1),
    ("--border-strong: #3A4550;", "--border-strong: #2b3547;", 1),
    # text ladder (design text/mut/dim + AA-kept faint)
    ("--text: #F0F3F6;", "--text: #e9edf5;", 1),
    ("--text-mid: #A6B0BC;", "--text-mid: #9aa4b4;", 1),
    ("--text-dim: #939EA9;", "--text-dim: #75808f;", 1),
    ("--text-faint: #84909C;", "--text-faint: #707b8d;", 1),
    ("--text-disabled: #5C6670;", "--text-disabled: #4c5568;", 1),
    # accent: the single blue of the mockup
    ("--accent: #D4AC55;", "--accent: #58a6ff;", 1),
    ("--accent-strong: #E2BE6A;", "--accent-strong: #7db8ff;", 1),
    ("rgba(212, 172, 85, 0.10)", "rgba(88, 166, 255, 0.12)", 1),
    ("rgba(212, 172, 85, 0.05)", "rgba(88, 166, 255, 0.06)", 1),
    ("rgba(212, 172, 85, 0.38)", "rgba(88, 166, 255, 0.32)", 1),
    ("--accent-ink: #171307;", "--accent-ink: #04101c;", 1),
    ("--accent-agent: #58A6FF;", "--accent-agent: var(--accent);", 1),
    ("--accent-agent-soft: rgba(88, 166, 255, 0.12);", "--accent-agent-soft: var(--accent-soft);", 1),
    ("--accent-agent-border: rgba(88, 166, 255, 0.38);", "--accent-agent-border: var(--accent-border);", 1),
    # semantic states = mockup values
    ("--ok: #5CB87A;", "--ok: #43cf90;", 1),
    ("rgba(92, 184, 122, 0.10)", "rgba(67, 207, 144, 0.10)", 1),
    ("rgba(92, 184, 122, 0.35)", "rgba(67, 207, 144, 0.30)", 1),
    ("rgba(92, 184, 122, 0.14)", "rgba(67, 207, 144, 0.14)", 1),
    ("--danger: #E06C5F;", "--danger: #f06969;", 1),
    ("rgba(224, 108, 95, 0.09)", "rgba(240, 105, 105, 0.06)", 1),
    ("rgba(224, 108, 95, 0.38)", "rgba(240, 105, 105, 0.32)", 1),
    ("rgba(224, 108, 95, 0.14)", "rgba(240, 105, 105, 0.10)", 1),
    ("--warn: #D9A03F;", "--warn: #ff9e64;", 1),
    ("rgba(217, 160, 63, 0.10)", "rgba(255, 158, 100, 0.08)", 1),
    ("rgba(217, 160, 63, 0.36)", "rgba(255, 158, 100, 0.35)", 1),
    ("rgba(217, 160, 63, 0.14)", "rgba(255, 158, 100, 0.14)", 1),
    ("--info: #5B9BD5;", "--info: #6aa6ff;", 1),
    ("rgba(91, 155, 213, 0.10)", "rgba(106, 166, 255, 0.10)", 1),
    ("rgba(91, 155, 213, 0.36)", "rgba(106, 166, 255, 0.36)", 1),
    ("rgba(91, 155, 213, 0.14)", "rgba(106, 166, 255, 0.14)", 1),
    # radii 8/12/16 + design shadow + dimensions
    ("--radius-s: 6px;", "--radius-s: 8px;", 1),
    ("--radius-m: 10px;", "--radius-m: 12px;", 1),
    ("--radius-l: 14px;", "--radius-l: 16px;", 1),
    ("--shadow-2: 0 8px 24px rgba(0, 0, 0, 0.38);",
     "--shadow-2: 0 10px 34px rgba(0, 0, 0, 0.42);", 1),
    ("--chat-width: 920px;", "--chat-width: 780px;", 1),
    ("--sidebar-width: 264px;", "--sidebar-width: 292px;", 1),
    # focus/selection/scrollbar
    ("outline: 2px solid var(--accent);", "outline: 2px solid var(--info);", 1),
    ("rgba(212, 172, 85, 0.28)", "rgba(88, 166, 255, 0.28)", 1),
    ("::-webkit-scrollbar { width: 10px; height: 10px; }",
     "::-webkit-scrollbar { width: 9px; height: 9px; }", 1),
    ("background: #2C3640;", "background: #242c3b;", 1),
    ("::-webkit-scrollbar-thumb:hover { background: #3A4550; }",
     "::-webkit-scrollbar-thumb:hover { background: #2b3547; }", 1),
])

# --------------------------------------------------------------------------
# 2) styles.css — chrome blocks restyled to the mockup
# --------------------------------------------------------------------------
styles = UI / "styles.css"

sub_block(styles, ".brand-mark",
""".brand-mark {
  width: 36px;
  height: 36px;
  flex: none;
  border-radius: 11px;
  background: linear-gradient(145deg, #1d2534, #131926);
  border: 1px solid var(--border-strong);
  display: grid;
  place-items: center;
  color: var(--accent);
}
.brand-mark svg { width: 18px; height: 18px; }""")

sub_block(styles, ".brand-sub",
""".brand-sub {
  font-family: var(--font-mono);
  font-size: 9.5px;
  color: var(--text-faint);
  letter-spacing: 0.16em;
  text-transform: uppercase;
  font-weight: 500;
}""")

# .new-chat: replace the whole 4-rule family in one pass (block + .icon +
# :hover + :hover .icon) so no old rule survives after the new one.
_text = styles.read_text(encoding="utf-8")
_newchat_new = """.new-chat {
  margin: var(--sp-1) var(--sp-3) var(--sp-2);
  padding: 10px 12px;
  border-radius: var(--radius-m);
  border: 1px solid var(--border-strong);
  background: linear-gradient(180deg, #1b2334, #141b29);
  color: var(--text);
  font-size: var(--fs-13);
  font-weight: 600;
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 8px;
  transition: border-color var(--dur-fast) var(--ease), transform var(--dur-fast) var(--ease);
  text-align: start;
}

.new-chat-main { display: inline-flex; align-items: center; gap: 8px; min-width: 0; }

.new-chat .icon { color: var(--text-mid); }

.new-chat:hover {
  border-color: var(--border-focus);
  transform: translateY(-1px);
  color: var(--text);
}

.new-chat:hover .icon { color: var(--accent); }

.new-chat-key {
  font-family: var(--font-mono);
  font-size: 9.5px;
  color: var(--text-faint);
  border: 1px solid var(--border);
  border-radius: 6px;
  padding: 1px 6px;
  letter-spacing: 0.04em;
  flex: none;
}

/* البحث في الشريط الجانبي — كما في التصميم */
.side-search { position: relative; margin: 0 var(--sp-3) var(--sp-2); }
.side-search .icon {
  position: absolute;
  inset-inline-start: 10px;
  top: 50%;
  translate: 0 -50%;
  color: var(--text-faint);
  pointer-events: none;
}
.side-search input {
  width: 100%;
  padding: 8px 12px;
  padding-inline-start: 34px;
  background: var(--bg);
  border: 1px solid var(--border);
  border-radius: 10px;
  font-size: var(--fs-13);
  outline: none;
  color: var(--text);
  transition: border-color var(--dur-fast) var(--ease), box-shadow var(--dur-fast) var(--ease);
}
.side-search input:focus {
  border-color: var(--border-focus);
  box-shadow: 0 0 0 3px rgba(106, 166, 255, 0.12);
}
.side-search input::placeholder { color: var(--text-faint); }"""
_pat = re.compile(
    r"\.new-chat\s*\{.*?\.new-chat:hover \.icon \{ color: var\(--accent\); \}",
    re.DOTALL)
_hits = _pat.findall(_text)
if _norm(_newchat_new) not in _norm(_text):
    if len(_hits) != 1:
        sys.exit(f"ABORT styles.css: .new-chat family matched {len(_hits)}x")
    _text = _pat.sub(lambda m: _newchat_new, _text, count=1)
    styles.write_text(_text, encoding="utf-8")
    changed["styles.css"] = changed.get("styles.css", 0) + 1

sub_lines(styles, [
    (".side-nav-item.active { background: var(--bg-elevated); color: var(--text); }",
     ".side-nav-item.active { background: var(--bg-raised); color: var(--text); }", 1),
])

sub_block(styles, ".chat-title",
""".chat-title {
  flex: 0 1 auto;
  max-width: 46%;
  font-size: var(--fs-12);
  font-weight: 500;
  color: var(--text-mid);
  border: 1px solid var(--border);
  background: var(--bg-sidebar);
  border-radius: var(--radius-pill);
  padding: 3px 12px;
  white-space: nowrap;
  overflow: hidden;
  text-overflow: ellipsis;
}""")

sub_block(styles, ".mode-badge",
""".mode-badge {
  flex: none;
  font-size: var(--fs-11);
  font-weight: 600;
  color: var(--accent-hi, var(--accent));
  background: var(--accent-soft);
  border: 1px solid var(--accent-border);
  border-radius: var(--radius-pill);
  padding: 3px 10px;
}""")

sub_block(styles, ".bubble.user",
""".bubble.user {
  align-self: flex-end;           /* التصميم: رسالة المالك على الجهة المقابلة */
  background: var(--bubble-user);
  border: 1px solid var(--border-strong);
  border-end-end-radius: 4px;
}""")

sub_block(styles, ".composer-inner",
""".composer-inner {
  display: flex;
  align-items: flex-end;
  gap: var(--sp-2);
  border: 1px solid var(--border-strong);
  border-radius: var(--radius-l);
  background: var(--bg-raised);
  padding: 9px 10px;
  box-shadow: var(--shadow-2);
  transition: border-color var(--dur-fast) var(--ease), box-shadow var(--dur-fast) var(--ease);
}""")

sub_block(styles, ".composer-inner:focus-within",
""".composer-inner:focus-within {
  border-color: var(--border-focus);
  box-shadow: 0 0 0 3px rgba(106, 166, 255, 0.10), var(--shadow-2);
}""")

_dbd_new = """.drawer-backdrop {
  position: fixed;
  inset: 0;
  background: rgba(5, 8, 13, 0.62);
  backdrop-filter: blur(5px);
  z-index: var(--z-drawer);
  animation: fade-in var(--dur) var(--ease);
}"""
if _norm(_dbd_new) not in _norm(styles.read_text(encoding="utf-8")):
    _t = styles.read_text(encoding="utf-8")
    _p = re.compile(r"(?m)^\.drawer-backdrop \{[^{}]*\}")  # السطر غير مُزاحٍ (خارج media)
    _f = _p.findall(_t)
    if len(_f) != 1:
        sys.exit(f"ABORT styles.css: top-level .drawer-backdrop matched {len(_f)}x")
    styles.write_text(_p.sub(lambda m: _dbd_new, _t, count=1), encoding="utf-8")
    changed["styles.css"] = changed.get("styles.css", 0) + 1

sub_lines(styles, [
    (".btn.primary:hover { background: rgba(212, 172, 85, 0.17); border-color: var(--accent); }",
     ".btn.primary:hover { background: rgba(88, 166, 255, 0.17); border-color: var(--accent); }", 1),
])

# --------------------------------------------------------------------------
# 3) app-shell.css — card family + stepper + 920→780 contract
# --------------------------------------------------------------------------
shell = UI / "app-shell.css"
sub_lines(shell, [
    ("max-width: 920px;          /* §3: 820-960 — قراءة مريحة لا ضغط */",
     "max-width: 780px;          /* §3 (012): عمود التصميم 780px */", 1),
])

sub_block(shell, ".task-card",
""".task-card {
  align-self: stretch;
  border: 1px solid var(--border);
  border-radius: var(--radius-l);
  background: var(--bg-sidebar);
  overflow: hidden;
}""")

sub_block(shell, ".task-head",
""".task-head {
  display: flex;
  align-items: center;
  gap: 10px;
  padding: 12px 16px;
  background: var(--bg-raised);
  border-bottom: 1px solid var(--border);
}""")

sub_block(shell, ".task-steps",
""".task-steps {
  display: flex;
  flex-wrap: nowrap;
  overflow-x: auto;
  padding: 18px var(--sp-4) 14px;
}""")

sub_block(shell, ".step",
""".step {
  position: relative;
  display: flex;
  flex-direction: column;
  align-items: center;
  gap: 7px;
  min-width: 78px;
  padding: 0;
  border: none;
  background: none;
  font-size: var(--fs-11);
  color: var(--text-dim);
  transition: all var(--dur) var(--ease);
}

/* موصل الخطوة السابقة — يلوَّن بحالة العقدة التالية */
.step + .step::before {
  content: "";
  position: absolute;
  inset-inline-end: 100%;
  top: 13px;
  width: 16px;
  height: 2px;
  border-radius: 99px;
  background: var(--border);
}

.step + .step.done::before,
.step + .step.active::before { background: var(--ok-border); }""")

sub_block(shell, ".step .step-mark",
""".step .step-mark {
  width: 27px;
  height: 27px;
  display: grid;
  place-items: center;
  border: 1.5px solid var(--border-strong);
  border-radius: 99px;
  background: var(--bg-sidebar);
  color: var(--text-dim);
  font-size: var(--fs-11);
  line-height: 1;
}""")

sub_block(shell, ".step.active",
""".step.active { color: var(--text); }

.step.active .step-mark {
  border-color: var(--accent);
  color: var(--accent);
  background: var(--accent-soft);
  animation: ring-pulse 1.8s infinite;
}

@keyframes ring-pulse {
  0% { box-shadow: 0 0 0 0 rgba(88, 166, 255, 0.35); }
  70% { box-shadow: 0 0 0 7px transparent; }
  100% { box-shadow: 0 0 0 0 transparent; }
}""")

sub_block(shell, ".step.done",
""".step.done { color: var(--text-mid); }

.step.done .step-mark {
  border-color: var(--ok-border);
  color: var(--ok);
  background: var(--ok-soft);
}""")

# --------------------------------------------------------------------------
# 4) factory-control.css — gold remnant in scoped selection
# --------------------------------------------------------------------------
sub_lines(UI / "factory-control.css", [
    ("  background: rgba(212, 172, 85, 0.28);",
     "  background: rgba(88, 166, 255, 0.28);", 1),
])

# --------------------------------------------------------------------------
# 5) index.html — brand identity + Ctrl K + side search
# --------------------------------------------------------------------------
html = UI / "index.html"
sub_lines(html, [
    ('<span class="brand-name">Agentic Engineering</span>\n            <span class="brand-sub">System</span>',
     '<span class="brand-name">نظام الهندسة الوكيلي</span>\n            <span class="brand-sub" dir="ltr">AGENTIC ENGINEERING</span>', 1),
    ("""<button class="new-chat" id="new-chat" title="بدء محادثة جديدة">
        <span class="icon sm"><svg><use href="#i-new"/></svg></span>
        <span>محادثة جديدة</span>
      </button>""",
     """<button class="new-chat" id="new-chat" title="بدء محادثة جديدة (Ctrl+K)">
        <span class="new-chat-main">
          <span class="icon sm"><svg><use href="#i-new"/></svg></span>
          <span>محادثة جديدة</span>
        </span>
        <span class="new-chat-key" dir="ltr">Ctrl K</span>
      </button>

      <div class="side-search">
        <span class="icon sm"><svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round"><circle cx="11" cy="11" r="7"/><path d="M20 20l-3.5-3.5"/></svg></span>
        <input id="side-search" type="search" placeholder="ابحث في المحادثات والمشاريع…" aria-label="ابحث في المحادثات والمشاريع">
      </div>""", 1),
])

# --------------------------------------------------------------------------
# 6) app.js — Ctrl+K shortcut + sidebar search filter
# --------------------------------------------------------------------------
appjs = UI / "app.js"
sub_lines(appjs, [
    ('  $("new-chat").addEventListener("click", newChat);',
     '''  $("new-chat").addEventListener("click", newChat);

  // (AES-DESIGN-IMPL-012) اختصار Ctrl+K كما في التصميم
  document.addEventListener("keydown", function (e) {
    if ((e.ctrlKey || e.metaKey) && String(e.key).toLowerCase() === "k") {
      e.preventDefault();
      newChat();
    }
  });

  // (AES-DESIGN-IMPL-012) بحث الشريط الجانبي: تصفية المحادثات والمشاريع
  var sideSearch = document.getElementById("side-search");
  if (sideSearch) {
    sideSearch.addEventListener("input", function () {
      var q = this.value.trim().toLowerCase();
      var items = document.querySelectorAll("#conversations .conv-item, #projects-list .pj-item");
      items.forEach(function (el) {
        el.hidden = !!q && el.textContent.toLowerCase().indexOf(q) === -1;
      });
    });
  }''', 1),
])

# --------------------------------------------------------------------------
# 7) structure contract: 920 → 780
# --------------------------------------------------------------------------
sub_lines(TESTS, [
    ('assert "max-width: 920px" in SHELL_CSS', 'assert "max-width: 780px" in SHELL_CSS', 1),
    ("(§3) التدفق يستعمل المساحة المتاحة بعرض 820-960 لا ضغطًا.",
     "(§3) التدفق يستعمل عمود التصميم 780px لا ضغطًا.", 1),
])

print("OK — replacements applied:")
for k, v in sorted(changed.items()):
    print(f"  {k}: {v} edits")
