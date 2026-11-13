#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""W2-T25 v3 — OWNER CONSOLE deployment (runs ON server as opc).
1) monitor.py: do_POST relay (whitelisted owner actions -> 127.0.0.1:8010)
   + GET/POST /api/owner-mode (flag file) + UI owner console section
2) w2t25_server_drive.py: owner-mode gate hold (PLAN_* gates wait for human)
   + OWNER_DIRECTIVE upgraded with binding Arabic/RTL product requirements
3) py_compile both, restart monitor service + driver, verify relay harmlessly.
Rollback: .bak_v3 copies for both files.
"""
import io, os, subprocess, sys, time

MON = "/home/opc/w2t25_monitor.py"
DRV = "/home/opc/w2t25_server_drive.py"

# AES-P0-CONTAINMENT-1113: no hardcoded credential in the repo. Read from env
# or the server's root-only secret file; never printed, never in URLs.
TOKEN = os.environ.get("W2T25_MONITOR_TOKEN") or open(
    os.environ.get("W2T25_MONITOR_TOKEN_FILE", "/etc/w2t25-monitor/monitor_token")
).read().strip()

DO_POST = '''    OWNER_PATHS = (
        "^/api/projects/3/pause$", "^/api/projects/3/resume$", "^/api/projects/3/retry$",
        "^/api/projects/3/gates/[0-9]+$", "^/api/projects/3/plan/approve$", "^/api/owner-mode$",
    )

    def do_POST(self):
        """W2-T25 v3 owner console relay — whitelisted actions only, token-gated."""
        import urllib.request, urllib.error
        u = urlparse(self.path)
        qs = parse_qs(u.query)
        path = unquote(u.path)
        if not self._auth(qs):
            self.send_response(403)
            self.send_header("Content-Length", "0")
            self.end_headers()
            return
        if not any(re.match(p, path) for p in self.OWNER_PATHS):
            self._json({"ok": False, "err": "path not allowed"}, 404)
            return
        try:
            length = int(self.headers.get("Content-Length") or 0)
        except Exception:
            length = 0
        raw = self.rfile.read(min(length, 20000)) if length else b"{}"
        if path == "/api/owner-mode":
            try:
                req = json.loads((raw or b"{}").decode("utf-8") or "{}")
                on = bool(req.get("on"))
                fp = "/home/opc/w2t25_owner_mode"
                if on:
                    with open(fp, "w") as f:
                        f.write(time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()))
                elif os.path.exists(fp):
                    os.remove(fp)
                self._json({"ok": True, "on": on})
                return
            except Exception as e:
                self._json({"ok": False, "err": str(e)}, 500)
                return
        req = urllib.request.Request(
            "http://127.0.0.1:8010" + path, data=raw if raw else b"{}",
            headers={"Content-Type": "application/json"}, method="POST")
        try:
            with urllib.request.urlopen(req, timeout=90) as r:
                body, code = r.read(), r.status
        except urllib.error.HTTPError as e:
            body, code = e.read(), e.code
        except Exception as e:
            body = json.dumps({"ok": False, "err": str(e)[:300]}).encode("utf-8")
            code = 502
        self.send_response(code)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

'''

OWNER_MODE_GET = '''        if path == "/api/owner-mode":
            self._json({"on": os.path.exists("/home/opc/w2t25_owner_mode")})
            return
'''

OWNER_SECTION = '''<section id="s-owner">
  <h2>👑 لوحة المالك — المصنع يسمعك الآن</h2>
  <p class="hint">أزرار حقيقية متصلة بواجهة المحرك مباشرة (نفس النقط التي يستعملها النظام داخليًا). الإيقاف يأخذ لقطة آمنة ويُستأنف متى شئت. <b>رفض الخطة/البوابة يُغذّي إعادة التوليد بملاحظتك</b> — استخدمه إن لم تعجبك خطة (مثال: «اجعل كل شيء عربيًا RTL»).</p>
  <div class="panel">
    <div class="footbar">
      <button class="btn primary" onclick="actPause()">⏸ إيقاف مؤقت آمن</button>
      <button class="btn" onclick="actResume()">▶ استئناف</button>
      <button class="btn" onclick="actRetry()">↻ إعادة محاولة آخر فشل</button>
      <span style="flex:1"></span>
      <label class="chip dim" style="cursor:pointer"><input type="checkbox" id="ownmode" onchange="setOwnerMode(this.checked)"> وضع المالك: البوابات وخطط الجيل الجديد تنتظر قرارك أنت</label>
    </div>
    <div style="margin-top:12px">
      <h2 style="font-size:13.5px">🚧 بوابات بانتظار قرارك الآن</h2>
      <div id="owngates"><div class="sub">…</div></div>
    </div>
    <div id="actresult" style="margin-top:8px"></div>
    <div class="sub" style="margin-top:8px">ملاحظة أمان: «التحقق النهائي» الذي يُغلق المشروع رسميًا غير معروض عمدًا — اطلبه مني حين يحين.</div>
  </div>
</section>

'''

OWNER_JS = '''async function act(path, body, confirmMsg){
  if(confirmMsg && !confirm(confirmMsg)) return;
  const box=document.getElementById('actresult');
  box.innerHTML='<div class="sub">…جارٍ التنفيذ…</div>';
  try{
    const r=await fetch(A(path),{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify(body||{})});
    let j={};try{j=await r.json()}catch(e){}
    box.innerHTML='<div class="alert">HTTP '+r.status+' — <span class="mono">'+esc(JSON.stringify(j).slice(0,500))+'</span></div>';
    tick();
  }catch(e){box.innerHTML='<div class="alert">فشل الاتصال: '+esc(String(e))+'</div>'}
}
function actPause(){const r=prompt('سبب الإيقاف المؤقت (يُسجَّل):','مراجعة يدوية من المالك');if(r===null)return;act('api/projects/3/pause',{reason:r},'إيقاف المصنع مؤقتًا بلقطة آمنة؟ يمكنك الاستئناف متى شئت.');}
function actResume(){act('api/projects/3/resume',{},'استئناف تشغيل المصنع؟');}
function actRetry(){act('api/projects/3/retry',{},'إعادة محاولة آخر فشل؟');}
function actGate(gid,approved){
  let note='';
  if(!approved){note=prompt('سبب الرفض (يُغذّي إعادة توليد الخطة — مثال: اجعل الموقع عربيًا RTL بالكامل):','');if(note===null)return;}
  act('api/projects/3/gates/'+gid,{approved:approved,note:note},approved?('الموافقة على البوابة #'+gid+'؟'):('رفض البوابة #'+gid+' يوقف المشروع بصدق. متأكد؟'));
}
async function loadOwnerMode(){try{const r=await fetch(A('api/owner-mode'));const j=await r.json();const el=document.getElementById('ownmode');if(el)el.checked=!!j.on;}catch(e){}}
function setOwnerMode(on){
  if(!confirm(on?'تفعيل وضع المالك: تتوقف الموافقة الآلية على الخطط — المصنع سيتوقف عند كل خطة جديدة بانتظارك في هذه اللوحة.':'إلغاء وضع المالك: تعود الموافقة الآلية (وضع التشغيل غير المراقب).')){document.getElementById('ownmode').checked=!on;return;}
  fetch(A('api/owner-mode'),{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({on:on})}).then(function(){tick()});
}
function renderOwner(n){
  const g=(n.gates||[]).filter(function(x){return x.status==='PENDING'||x.status==='BLOCKED';});
  const el=document.getElementById('owngates');
  if(!el)return;
  el.innerHTML=g.length?g.map(function(x){
    return '<div class="tlev"><div class="when">'+hhmm(x.created_at)+'</div><div class="what"><span class="k">'+esc(x.kind)+'</span> #'+x.id+' — '+esc(x.reason||'')+'</div><div style="flex:1"></div><button class="btn primary" onclick="actGate('+x.id+',true)">✔ موافقة</button> <button class="btn" onclick="actGate('+x.id+',false)">✖ رفض بملاحظة</button></div>';
  }).join(''):'<div class="sub">لا بوابات معلّقة الآن — المصنع يعمل بقرار التفويض القائم.</div>';
}
'''

DRV_DIRECTIVE_OLD = '"مهام برمجية معقدة» — مواصلة التنفيذ من المنفذ المفوَّض.")'
DRV_DIRECTIVE_NEW = ('"مهام برمجية معقدة» — مواصلة التنفيذ من المنفذ المفوَّض. "\n'
                     '                   "متطلبات المنتج الملزمة (تحديث المالك 2026-11-01): الموقع موقع إخباري عربي بالكامل — '
                     '<html lang=\\"ar\\" dir=\\"rtl\\"> إلزامي في كل صفحة، وكل العناوين والفقرات والمقالات وقوائم التنقل والأزرار بالعربية الفصحى، '
                     'والمقالات عربية المنطق (عنوان+مقدمة+فقرات) لا نصوص لاتينية وهمية؛ أي مخرجات إنجليزية أو LTR في واجهة الموقع تُعد فشلًا للخطوة.")')

DRV_GATES_OLD = '''            if gates:
                g = gates[0]
                gid, kind = g["id"], g["kind"]
                if gid not in handled:'''
DRV_GATES_NEW = '''            if gates:
                g = gates[0]
                gid, kind = g["id"], g["kind"]
                if (gid not in handled and os.path.exists("/home/opc/w2t25_owner_mode")
                        and kind in ("PLAN_APPROVAL", "PLAN_REVISION_APPROVAL")):
                    handled.add(gid)
                    log("action", {"what": "OWNER_MODE_HOLD#%d %s" % (gid, kind),
                                   "resp": "بوابة تنتظر قرار المالك في غرفة التحكم — لا موافقة آلية"})
                elif gid not in handled:'''

DRV_PAUSED_OLD = '''        if pstat == "PAUSED" and j.get("status") != "RUNNING":'''
DRV_PAUSED_NEW = '''        if (pstat == "PAUSED" and j.get("status") != "RUNNING"
                and not os.path.exists("/home/opc/w2t25_owner_mode")):'''


def patch_monitor():
    with io.open(MON, "r", encoding="utf-8") as f:
        src = f.read()
    if "do_POST" in src:
        print("monitor: v3 already applied")
        return True
    with io.open(MON + ".bak_v3", "w", encoding="utf-8") as f:
        f.write(src)
    marks = [
        ("    def do_GET(self):", 1),
        ('        if path == "/api/activity":', 1),
        ('<section id="s-kpis">', 1),
        ('<a href="#s-hero">⚡ الآن</a>', 1),
        ("renderClosed(s);", 1),
        ("function renderThink(n,sf,ev,s){", 1),
        ("reloadPrev();", 1),
    ]
    for m, n in marks:
        if src.count(m) != n:
            print("MON MARKER FAIL:", repr(m), src.count(m)); return False
    src = src.replace("    def do_GET(self):", DO_POST + "    def do_GET(self):", 1)
    src = src.replace('        if path == "/api/activity":', OWNER_MODE_GET + '        if path == "/api/activity":', 1)
    src = src.replace('<section id="s-kpis">', OWNER_SECTION + '<section id="s-kpis">', 1)
    src = src.replace('<a href="#s-hero">⚡ الآن</a>', '<a href="#s-hero">⚡ الآن</a>\n  <a href="#s-owner">👑 لوحة المالك</a>', 1)
    src = src.replace("renderClosed(s);", "renderClosed(s);\n renderOwner(n);", 1)
    src = src.replace("function renderThink(n,sf,ev,s){", OWNER_JS + "\nfunction renderThink(n,sf,ev,s){", 1)
    src = src.replace("reloadPrev();", "loadOwnerMode();\nreloadPrev();", 1)
    with io.open(MON, "w", encoding="utf-8") as f:
        f.write(src)
    print("monitor patched ->", len(src), "bytes")
    return True


def patch_driver():
    with io.open(DRV, "r", encoding="utf-8") as f:
        src = f.read()
    changed = False
    if "متطلبات المنتج الملزمة" not in src:
        with io.open(DRV + ".bak_v3", "w", encoding="utf-8") as f:
            f.write(src)
        if src.count(DRV_DIRECTIVE_OLD) != 1:
            print("DRV DIRECTIVE MARKER FAIL:", src.count(DRV_DIRECTIVE_OLD)); return False
        src = src.replace(DRV_DIRECTIVE_OLD, DRV_DIRECTIVE_NEW, 1)
        changed = True
    if "OWNER_MODE_HOLD" not in src:
        if src.count(DRV_GATES_OLD) != 1:
            print("DRV GATES MARKER FAIL:", src.count(DRV_GATES_OLD)); return False
        src = src.replace(DRV_GATES_OLD, DRV_GATES_NEW, 1)
        changed = True
    if 'not os.path.exists("/home/opc/w2t25_owner_mode"))' not in src:
        if src.count(DRV_PAUSED_OLD) != 1:
            print("DRV PAUSED MARKER FAIL:", src.count(DRV_PAUSED_OLD)); return False
        src = src.replace(DRV_PAUSED_OLD, DRV_PAUSED_NEW, 1)
        changed = True
    with io.open(DRV, "w", encoding="utf-8") as f:
        f.write(src)
    print("driver patched (changed=%s) ->" % changed, len(src), "bytes")
    return True


def main():
    if not patch_monitor():
        return 1
    if not patch_driver():
        return 1
    for f in (MON, DRV):
        r = subprocess.run([sys.executable, "-m", "py_compile", f], capture_output=True, text=True)
        print("py_compile", f, "rc=", r.returncode, r.stderr[:300])
        if r.returncode != 0:
            return 1
    r = subprocess.run(["sudo", "-n", "systemctl", "restart", "w2t25-monitor.service"], capture_output=True, text=True)
    print("monitor restart rc=", r.returncode, r.stderr[:200])
    time.sleep(3)
    # driver restart (routine, [w] pattern)
    subprocess.run("pkill -f '[w]2t25_server_drive.py'", shell=True)
    time.sleep(2)
    subprocess.run("setsid nohup python3 /home/opc/w2t25_server_drive.py >> /home/opc/w2t25_server_drive.out 2>&1 &", shell=True)
    time.sleep(4)
    # AES-P0-CONTAINMENT-1113: token via env, never via URL
    os.environ["W2T25_MONITOR_TOKEN"] = TOKEN
    checks = [
        ("healthz", 'curl -s -m 6 http://127.0.0.1:8765/healthz'),
        ("relay-harmless-gate", 'curl -s -m 15 -H "X-Access-Key: $W2T25_MONITOR_TOKEN" -X POST -H "Content-Type: application/json" -d \'{"approved":true}\' "http://127.0.0.1:8765/api/projects/3/gates/999999" | head -c 300'),
        ("relay-forbidden-path", 'curl -s -m 8 -H "X-Access-Key: $W2T25_MONITOR_TOKEN" -X POST -d "{}" "http://127.0.0.1:8765/api/projects/3/plan/delete" -o /dev/null -w "%{http_code}"'),
        ("owner-mode-on", 'curl -s -m 8 -H "X-Access-Key: $W2T25_MONITOR_TOKEN" -X POST -H "Content-Type: application/json" -d \'{"on":true}\' "http://127.0.0.1:8765/api/owner-mode"; ls -la /home/opc/w2t25_owner_mode 2>/dev/null | head -1'),
        ("owner-mode-get", 'curl -s -m 8 -H "X-Access-Key: $W2T25_MONITOR_TOKEN" "http://127.0.0.1:8765/api/owner-mode"'),
        ("owner-mode-off", 'curl -s -m 8 -H "X-Access-Key: $W2T25_MONITOR_TOKEN" -X POST -H "Content-Type: application/json" -d \'{"on":false}\' "http://127.0.0.1:8765/api/owner-mode"; ls /home/opc/w2t25_owner_mode 2>&1 | head -1'),
        ("page-has-owner", 'curl -s -m 8 -H "X-Access-Key: $W2T25_MONITOR_TOKEN" "http://127.0.0.1:8765/" | grep -c "لوحة المالك"'),
        ("driver-alive", 'sleep 2; pgrep -af "[w]2t25_server_drive.py" || echo DRIVER-DEAD'),
        ("driver-log", 'sleep 3; tail -n 2 /home/opc/w2t25_drive/latest.log 2>/dev/null | head -c 400'),
    ]
    for name, cmd in checks:
        r = subprocess.run(["bash", "-c", cmd], capture_output=True, text=True)
        print("[check]", name, "=>", (r.stdout or r.stderr).strip()[:320])
    print("V3-DEPLOY-DONE")
    return 0


if __name__ == "__main__":
    sys.exit(main())
