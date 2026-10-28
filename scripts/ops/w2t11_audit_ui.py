# -*- coding: utf-8 -*-
"""W2-T11 — تدقيق وصولية الواجهة الحي على الإنتاج (عبر نفق SSH قراءة-فقط).

أربع مجموعات فحص على الواجهة الحقيقية (http://127.0.0.1:18910 → 8010):
  A) تباين النصوص المحسوبة (WCAG 1.4.3: 4.5:1 عادي / 3:1 كبير) مع تركيب
     الشفافيات وopacity.
  B) أهداف اللمس ≥44px تحت محاكاة لمس خشنة (390×844 has_touch).
  C) مؤشر تركيز لوحة المفاتيح: Tab عبر العناصر القابلة للتركيز —
     كل عنصر يجب أن يُظهر outline/ring عند :focus-visible.
  D) نص حالة بجانب كل نقطة دلالية (قواعد لكل صنف نقطة).

انضباط الجلسة: لا كتابة على الخادم إطلاقًا (GETs فقط عبر النفق) —
النقرات تقتصر على التنقل بين المشاهد (قراءة).
"""
from __future__ import annotations

import json
import socket
import sys
import threading
import time
from pathlib import Path

import paramiko
from playwright.sync_api import sync_playwright

HOST = "92.5.14.150"
USER = "opc"
KEY_PATH = "/tmp/oracle_key"
LOCAL_PORT = 18910
REMOTE = ("127.0.0.1", 8010)
BASE = f"http://127.0.0.1:{LOCAL_PORT}"
LABEL = sys.argv[1] if len(sys.argv) > 1 else "before"
EVID = Path(f"/home/z/my-project/download/aes-remediation/W2-T11")
SHOTS = EVID / f"shots_{LABEL}"
JSON_OUT = EVID / f"ui_runtime_audit_{LABEL}.json"

# ---------------------------------------------------------------- نفق SSH
class Tunnel:
    def __init__(self):
        self.cli = paramiko.SSHClient()
        self.cli.set_missing_host_key_policy(paramiko.AutoAddPolicy())
        self.cli.connect(HOST, username=USER, key_filename=KEY_PATH,
                         look_for_keys=False, allow_agent=False, timeout=20)
        self.tr = self.cli.get_transport()
        self.tr.set_keepalive(15)
        self.srv = socket.socket()
        self.srv.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        self.srv.bind(("127.0.0.1", LOCAL_PORT))
        self.srv.listen(16)
        self.alive = True
        threading.Thread(target=self._accept, daemon=True).start()

    def _accept(self):
        while self.alive:
            try:
                fd, _ = self.srv.accept()
            except OSError:
                return
            try:
                chan = self.tr.open_channel("direct-tcpip", REMOTE, fd.getpeername())
            except Exception:
                fd.close()
                continue
            threading.Thread(target=Tunnel._io, args=(fd, chan), daemon=True).start()

    @staticmethod
    def _io(fd, chan):
        """قارئان فوريان لكل اتجاه — لا انتظار إغلاق طرف قبل بدء الآخر."""
        def fd_to_chan():
            try:
                while True:
                    data = fd.recv(65536)
                    if not data:
                        break
                    chan.sendall(data)
            except Exception:
                pass
            finally:
                try:
                    chan.shutdown_write()
                except Exception:
                    pass

        def chan_to_fd():
            try:
                while True:
                    data = chan.recv(65536)
                    if not data:
                        break
                    fd.sendall(data)
            except Exception:
                pass
            finally:
                try:
                    fd.shutdown(socket.SHUT_WR)
                except Exception:
                    pass

        t1 = threading.Thread(target=fd_to_chan, daemon=True)
        t2 = threading.Thread(target=chan_to_fd, daemon=True)
        t1.start()
        t2.start()
        t1.join()
        t2.join()
        try:
            fd.close()
        except Exception:
            pass
        try:
            chan.close()
        except Exception:
            pass

    def exec(self, cmd: str) -> str:
        _, out, err = self.cli.exec_command(cmd, timeout=30)
        return (out.read() + err.read()).decode("utf-8", "replace").strip()

    def close(self):
        self.alive = False
        try:
            self.srv.close()
        except Exception:
            pass
        self.cli.close()


# ---------------------------------------------------------------- JS الفحوص
JS_LIB = r"""
() => {
  const parseColor = s => {
    const m = (s||'').match(/rgba?\(([^)]+)\)/);
    if (!m) return null;
    const p = m[1].split(',').map(x => parseFloat(x.trim()));
    return {r: p[0], g: p[1], b: p[2], a: p.length > 3 ? p[3] : 1};
  };
  const lum = c => {
    const f = v => { v /= 255; return v <= 0.04045 ? v/12.92 : Math.pow((v+0.055)/1.055, 2.4); };
    return 0.2126*f(c.r) + 0.7152*f(c.g) + 0.0722*f(c.b);
  };
  const blend = (over, under) => ({
    r: over.r*over.a + under.r*(1-over.a),
    g: over.g*over.a + under.g*(1-over.a),
    b: over.b*over.a + under.b*(1-over.a), a: 1});
  const ratio = (a, b) => { const la=lum(a), lb=lum(b);
    return (Math.max(la,lb)+0.05)/(Math.min(la,lb)+0.05); };
  const hex = c => '#' + [c.r,c.g,c.b].map(v => Math.round(v).toString(16).padStart(2,'0')).join('');
  window.__a11y = {parseColor, lum, blend, ratio, hex};
}
"""

JS_CONTRAST = r"""
() => {
  const {parseColor, lum, blend, ratio, hex} = window.__a11y;
  const out = {checked: 0, skipped: {gradient: 0, transparentBg: 0, fontSize0: 0}, failures: []};
  const els = document.querySelectorAll('body *');
  for (const el of els) {
    if (!(el.getClientRects().length)) continue;
    if (el.closest('[aria-hidden="true"]')) continue;
    if (el.closest('[disabled]') || el.disabled) continue;
    if (el.closest('[hidden]')) continue;
    const own = [...el.childNodes].some(n => n.nodeType === 3 && n.textContent.trim());
    if (!own) continue;
    const cs = getComputedStyle(el);
    if (cs.display === 'none' || cs.visibility === 'hidden') continue;
    if (parseFloat(cs.fontSize) === 0) { out.skipped.fontSize0++; continue; }  /* نص مخفي بتصميم (فواصل) */
    const fg = parseColor(cs.color);
    if (!fg) continue;
    // ---- الخلفية الفعالة عبر الأسلاف + opacity
    let opSelf = 1;
    let node = el, layers = [], grad = false;
    while (node && node instanceof Element) {
      const s = getComputedStyle(node);
      if (s.backgroundImage !== 'none') { grad = true; break; }
      const bg = parseColor(s.backgroundColor);
      if (bg && bg.a > 0) layers.push({c: bg, op: opSelf});
      opSelf *= parseFloat(s.opacity || '1');
      node = node.parentElement;
    }
    if (grad) { out.skipped.gradient++; continue; }
    if (!layers.length) { out.skipped.transparentBg++; continue; }
    let acc = {r:255, g:255, b:255, a:1};
    for (const L of layers.reverse()) {
      const eff = {r: L.c.r, g: L.c.g, b: L.c.b, a: L.c.a * L.op};
      acc = blend(eff, acc);
    }
    const bgc = {r: acc.r, g: acc.g, b: acc.b, a: 1};
    const fgEff = blend({r: fg.r, g: fg.g, b: fg.b, a: fg.a * opSelf}, bgc);
    const fs = parseFloat(cs.fontSize);
    const fwRaw = cs.fontWeight;
    const fw = fwRaw === 'bold' ? 700 : (isNaN(parseFloat(fwRaw)) ? 400 : parseFloat(fwRaw));
    const large = fs >= 24 || (fw >= 600 && fs >= 18.66);
    const req = large ? 3 : 4.5;
    const r = ratio(fgEff, bgc);
    out.checked++;
    if (r < req - 0.005) {
      const path = el.tagName.toLowerCase()
        + (el.id ? '#'+el.id : '')
        + (el.classList.length ? '.'+[...el.classList].slice(0,3).join('.') : '');
      out.failures.push({path, text: el.textContent.trim().slice(0, 40),
        fs, fw, fg: hex(fgEff), bg: hex(bgc), ratio: Math.round(r*100)/100, req});
    }
  }
  return out;
}
"""

JS_TOUCH = r"""
() => {
  const out = {checked: 0, exemptions: 0, failures: [], exempt_notes: []};
  const sel = 'button, a[href], [role="button"], [role="tab"], [role="switch"],'
    + ' [role="checkbox"], [role="radio"], input:not([type="hidden"]), select, textarea,'
    + ' [tabindex]:not([tabindex="-1"])';
  for (const el of document.querySelectorAll(sel)) {
    if (!(el.getClientRects().length)) continue;
    const cs = getComputedStyle(el);
    if (cs.display === 'none' || cs.visibility === 'hidden' || cs.pointerEvents === 'none') continue;
    if (el.disabled || el.closest('[disabled]')) continue;
    let target = el;
    const t = (el.getAttribute('type') || '').toLowerCase();
    if ((t === 'checkbox' || t === 'radio')) {
      const wrap = el.closest('label') || document.querySelector(`label[for="${el.id}"]`);
      if (wrap) target = wrap;
    }
    let exempt = null;
    if (el.tagName === 'A' && el.closest('.bubble-body, .md, .markdown, .msg-body')) {
      exempt = 'رابط داخل نثر الرسائل — معفى (WCAG 2.5.8 استثناء السطر)';
    }
    const rect = target.getBoundingClientRect();
    const w = Math.round(rect.width), h = Math.round(rect.height);
    const path = target.tagName.toLowerCase()
      + (target.id ? '#'+target.id : '')
      + (target.classList.length ? '.'+[...target.classList].slice(0,3).join('.') : '');
    out.checked++;
    if (exempt) { out.exemptions++; out.exempt_notes.push(path + ' — ' + exempt); continue; }
    if (w < 44 || h < 44) {
      out.failures.push({path, w, h, kind: (w < 44 && h < 44) ? 'كلاهما' : (w < 44 ? 'العرض' : 'الارتفاع')});
    }
  }
  return out;
}
"""

JS_FOCUSABLES = r"""
() => {
  const sel = 'button, a[href], [role="button"], [role="tab"], [role="switch"],'
    + ' [role="checkbox"], [role="radio"], input:not([type="hidden"]), select, textarea,'
    + ' [tabindex]:not([tabindex="-1"])';
  const out = [];
  for (const el of document.querySelectorAll(sel)) {
    if (!(el.getClientRects().length)) continue;
    const cs = getComputedStyle(el);
    if (cs.display === 'none' || cs.visibility === 'hidden') continue;
    if (el.disabled || el.closest('[disabled]')) continue;
    out.push(el.tagName.toLowerCase() + (el.id ? '#'+el.id : '')
      + (el.classList.length ? '.'+[...el.classList].slice(0,2).join('.') : ''));
  }
  return out;
}
"""

JS_FOCUS_ITER = r"""
() => {
  const sel = 'button, a[href], [role="button"], [role="tab"], [role="switch"],'
    + ' [role="checkbox"], [role="radio"], input:not([type="hidden"]), select, textarea,'
    + ' [tabindex]:not([tabindex="-1"])';
  const res = [];
  for (const el of document.querySelectorAll(sel)) {
    if (!(el.getClientRects().length)) continue;
    const cs = getComputedStyle(el);
    if (cs.display === 'none' || cs.visibility === 'hidden') continue;
    if (el.disabled || el.closest('[disabled]')) continue;
    el.focus();
    const s = getComputedStyle(document.activeElement);
    const outlineW = parseFloat(s.outlineWidth) || 0;
    const hasOutline = s.outlineStyle !== 'none' && outlineW > 0;
    const hasRing = s.boxShadow !== 'none';
    res.push({path: el.tagName.toLowerCase() + (el.id ? '#'+el.id : '')
      + (el.classList.length ? '.'+[...el.classList].slice(0,2).join('.') : ''),
      focused: document.activeElement === el,
      indicator: !!(hasOutline || hasRing),
      detail: hasOutline ? ('outline ' + s.outlineWidth + ' ' + s.outlineColor)
        : (hasRing ? 'ring' : 'NONE')});
  }
  if (document.activeElement) document.activeElement.blur();
  return res;
}
"""

JS_ACTIVE_FOCUS = r"""
() => {
  const ae = document.activeElement;
  if (!ae || ae === document.body) return null;
  const cs = getComputedStyle(ae);
  return {path: ae.tagName.toLowerCase() + (ae.id ? '#'+ae.id : '')
      + (ae.classList.length ? '.'+[...ae.classList].slice(0,2).join('.') : ''),
    outline: cs.outlineStyle + ' ' + cs.outlineWidth + ' ' + cs.outlineColor,
    outlineWidthPx: parseFloat(cs.outlineWidth) || 0,
    boxShadow: cs.boxShadow};
}
"""

JS_DOTS = r"""
() => {
  const txt = s => (s || '').trim();
  const rowTextBeyond = (dot, root) => {
    if (!root) return '';
    const clone = root.cloneNode(true);
    const d = clone.contains ? null : null;
    clone.querySelectorAll('.pj-dot,.status-dot,.cap-dot,.cc-run-dot,.pl-exec-dot,.pl-flow-dot,.fc-row-live-dot,.beat-dot,.wf-stage-dot,.wf-history-dot,.substrate-dot,.proj-run-dot').forEach(x => x.remove());
    return txt(clone.textContent);
  };
  const rules = {
    '.pj-dot': d => !!txt(d.textContent) || !!txt((d.parentElement || {}).querySelector?.('.pj-status')?.textContent || ''),
    '.status-dot': d => !!txt(d.textContent) || !!rowTextBeyond(d, d.parentElement),
    '.cap-dot': d => !!txt(d.closest('.cap-head')?.querySelector('.cap-status')?.textContent),
    '.cc-run-dot': d => !!txt(d.textContent) && !!txt(d.closest('.cc-run-card')?.textContent),
    '.fc-row-live-dot': d => d.getAttribute('aria-hidden') === 'true'
        && !!txt(d.closest('.fc-run-row, .fc-mission-row')?.querySelector('.fc-run-status, .fc-mission-status')?.textContent),
    '.substrate-dot': d => { const l = document.getElementById('substrate-label');
        return !!txt(l?.textContent) && txt(l?.textContent) !== 'الركيزة: …'; },
    '.pl-flow-dot': d => !!txt(d.textContent) || !!txt(d.parentElement?.querySelector('.pl-flow-label')?.textContent),
    '.pl-exec-dot': d => !!txt(d.textContent) && !!txt(d.parentElement?.textContent),
    '.beat-dot': d => !!txt(d.parentElement?.textContent),
    '.wf-stage-dot': d => !!txt(d.textContent),
    '.wf-history-dot': d => !!txt(d.textContent) && !!txt(d.parentElement?.querySelector('.wf-history-text')?.textContent),
    '.proj-run-dot': d => !!txt(d.textContent) || !!txt(d.title),
  };
  const out = {found: 0, failures: []};
  for (const [cls, rule] of Object.entries(rules)) {
    for (const d of document.querySelectorAll(cls)) {
      if (!(d.getClientRects().length)) continue;
      out.found++;
      let ok = false, why = '';
      try { ok = !!rule(d); } catch (e) { why = String(e); }
      if (!ok) {
        out.failures.push({cls, path: d.tagName.toLowerCase()
          + (d.parentElement ? ' في ' + d.parentElement.tagName.toLowerCase()
             + (d.parentElement.className ? '.' + String(d.parentElement.className).split(' ')[0] : '') : '')
          + (why ? ' — ' + why : ''), note: 'لا نص حالة ظاهر بجوار النقطة'});
      }
    }
  }
  return out;
}
"""

VIEWS = {
    "chat": None,
    "project": ".pj-item",
    "runs": '.side-nav-item[data-nav="runs"]',
    "factory": '.side-nav-item[data-nav="factory"]',
    "settings": "#settings-open",
}


def settle(page, ms=1800):
    page.wait_for_timeout(ms)


def main() -> int:
    EVID.mkdir(parents=True, exist_ok=True)
    SHOTS.mkdir(parents=True, exist_ok=True)
    tun = Tunnel()
    prod = {
        "git_head": tun.exec("git -C /opt/agentic-engineering-system rev-parse HEAD"),
        "health": tun.exec("curl -s -o /dev/null -w '%{http_code}' http://127.0.0.1:8010/health"),
        "services": tun.exec("systemctl is-active agentic nginx searxng search-api"),
        "ui_mtime_theme": tun.exec("stat -c '%Y' /opt/agentic-engineering-system/src/ui/theme.css"),
    }
    print("[prod]", json.dumps(prod, ensure_ascii=False))

    report = {"task": "W2-T11", "label": LABEL, "base": BASE, "prod": prod,
              "views": {}, "focus": None, "touch": {}, "screenshots": []}

    with sync_playwright() as p:
        browser = p.chromium.launch()
        # ===== سطح المكتب =====
        ctx = browser.new_context(viewport={"width": 1440, "height": 900})
        page = ctx.new_page()
        page.goto(BASE, wait_until="domcontentloaded", timeout=45000)
        page.evaluate(JS_LIB)
        settle(page, 2500)

        for name in ("chat", "project", "runs", "factory", "settings"):
            try:
                if VIEWS[name]:
                    page.click(VIEWS[name], timeout=6000)
                    settle(page, 2200)
                v = {"contrast": page.evaluate(JS_CONTRAST), "dots": page.evaluate(JS_DOTS)}
                report["views"][name] = v
                shot = str(SHOTS / f"desktop_{name}.png")
                page.screenshot(path=shot, full_page=False)
                report["screenshots"].append(shot)
                print(f"[view {name}] contrast: {v['contrast']['checked']} فحص / "
                      f"{len(v['contrast']['failures'])} إخفاق · نقاط: {v['dots']['found']} / "
                      f"{len(v['dots']['failures'])} بلا نص")
            except Exception as e:
                report["views"][name] = {"error": str(e)[:200]}
                print(f"[view {name}] خطأ: {e}")

        # ===== التركيز بلوحة المفاتيح (مشهد المحادثة) =====
        try:
            if VIEWS["chat"]:
                page.click('.side-nav-item[data-nav="chat"]', timeout=5000)
                settle(page, 1200)
            # (1) تغطية كاملة: focus() لكل عنصر قابل للتركيز — بعد Tab واحدة
            # لإثبات نمط لوحة المفاتيح (يُطابق :focus-visible في كروميوم)
            page.keyboard.press("Tab")
            page.wait_for_timeout(80)
            page.evaluate("document.activeElement && document.activeElement.blur()")
            coverage = page.evaluate(JS_FOCUS_ITER)
            no_ind = [c for c in coverage if not c["indicator"]]
            not_focused = [c for c in coverage if not c["focused"]]
            # (2) توثيق ترتيب Tab الفعلي (سجل التنقل بلوحة المفاتيح)
            order, body_hits = [], 0
            page.keyboard.press("Tab")
            for _ in range(60):
                page.wait_for_timeout(50)
                info = page.evaluate(JS_ACTIVE_FOCUS)
                if info is None:
                    body_hits += 1
                    if body_hits >= 3 or len(order) > 5:
                        break
                else:
                    body_hits = 0
                    if info["path"] in order:
                        break
                    order.append(info["path"])
                page.keyboard.press("Tab")
            # (3) لقطة بصرية لحلقة التركيز على زر مرئي
            try:
                page.evaluate("() => { const b = document.querySelector('#send') || document.querySelector('button'); b && b.focus(); }")
                page.wait_for_timeout(150)
                shot = str(SHOTS / "desktop_focus_ring.png")
                page.screenshot(path=shot)
                report["screenshots"].append(shot)
            except Exception:
                pass
            report["focus"] = {"coverage_count": len(coverage),
                               "no_indicator": no_ind,
                               "not_focused": not_focused,
                               "tab_order": order}
            print(f"[focus] تغطية {len(coverage)} · بلا مؤشر: {len(no_ind)} · "
                  f"غير قابل للتركيز: {len(not_focused)} · ترتيب Tab: {len(order)}")
        except Exception as e:
            report["focus"] = {"error": str(e)[:200]}
            print(f"[focus] خطأ: {e}")
        ctx.close()

        # ===== الجوال (لمس خشن) =====
        mob = browser.new_context(viewport={"width": 390, "height": 844},
                                  is_mobile=True, has_touch=True,
                                  device_scale_factor=2)
        mp = mob.new_page()
        mp.goto(BASE, wait_until="domcontentloaded", timeout=45000)
        mp.evaluate(JS_LIB)
        settle(mp, 2500)
        coarse = mp.evaluate("() => matchMedia('(pointer: coarse)').matches")
        report["touch"]["pointer_coarse_matches"] = coarse
        print(f"[touch] pointer:coarse = {coarse}")
        try:
            report["touch"]["chat"] = mp.evaluate(JS_TOUCH)
            print(f"[touch chat] {report['touch']['chat']['checked']} عنصرًا · "
                  f"{len(report['touch']['chat']['failures'])} دون 44px")
        except Exception as e:
            report["touch"]["chat"] = {"error": str(e)[:200]}
        try:
            mp.evaluate("() => { const el = document.querySelector('.pj-item'); el && el.click(); }")
            settle(mp, 2200)
            report["touch"]["project"] = mp.evaluate(JS_TOUCH)
            print(f"[touch project] {report['touch']['project']['checked']} عنصرًا · "
                  f"{len(report['touch']['project']['failures'])} دون 44px")
        except Exception as e:
            report["touch"]["project"] = {"error": str(e)[:200]}
        for nm, act in (("chat", None),):
            pass
        try:
            shot = str(SHOTS / "mobile_chat.png")
            mp.goto(BASE, wait_until="domcontentloaded")
            settle(mp, 1500)
            mp.screenshot(path=shot)
            report["screenshots"].append(shot)
        except Exception:
            pass
        mob.close()
        browser.close()

    tun.close()
    report["generated_at"] = time.strftime("%Y-%m-%d %H:%M:%S UTC", time.gmtime())
    JSON_OUT.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"\nالدليل: {JSON_OUT}")
    fails = sum(len(v.get("contrast", {}).get("failures", [])) for v in report["views"].values() if isinstance(v, dict))
    dots = sum(len(v.get("dots", {}).get("failures", [])) for v in report["views"].values() if isinstance(v, dict))
    tf = sum(len(t.get("failures", [])) for t in report["touch"].values() if isinstance(t, dict))
    fi = len((report.get("focus") or {}).get("no_indicator", []))
    print(f"الخلاصة: تباين {fails} · نقاط بلا نص {dots} · لمس {tf} · تركيز بلا مؤشر {fi}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
