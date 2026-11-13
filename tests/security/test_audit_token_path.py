# -*- coding: utf-8 -*-
"""مسار التوكن في سكربت التدقيق — AES-P0-CONTAINMENT-PR-REMEDIATION-1113-R1 (fix 6).

(1) تحليل ثابت لـ scripts/ops/w2t25_audit_check.py: لا تظهر قيمة التوكن في نص
    الأوامر المرسلة، ولا في query string، ولا في argv لأي عملية.
(2) اختبار آلية بالقيمة الوهمية فقط (FAKE…): خادم GET محلي على 127.0.0.1،
    ومقارنة نمط التمرير عبر stdin (-H @-) بنمط التمرير في argv — يثبت أين
    توجد القيمة في الذاكرة وأين يمكن أن تظهر في process arguments.
    لا يُنفَّذ أي POST/PUT/PATCH/DELETE ولا يُلمس أي خدمة حقيقية.
"""
import re
import subprocess
import sys
import threading
import time
from http.server import BaseHTTPRequestHandler, HTTPServer
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]
AUDIT = REPO_ROOT / "scripts" / "ops" / "w2t25_audit_check.py"

# قيمة وهمية بالكامل — ليست توكنًا حقيقيًا ولا تاريخيًا
FAKE = "FAKE" + "AA11" + "BB22" + "CC33" + "DD44"


def _extract_remote_commands(source: str):
    return re.findall(r'run\(ssh,\s*"((?:[^"\\]|\\.)*)"\)', source)


# ------------------------------------------------------------ static checks

def test_audit_script_has_no_literal_secret():
    src = AUDIT.read_text(encoding="utf-8")
    assert not re.search(r"(?m)[A-Za-z0-9_]*(?:TOKEN|PASSWORD|API_KEY|CREDENTIAL)"
                         r"[A-Za-z0-9_]*\s*=\s*[\"'][A-Za-z0-9]{16,}", src)


def test_audit_commands_carry_no_query_string_auth():
    src = AUDIT.read_text(encoding="utf-8")
    for cmd in _extract_remote_commands(src):
        assert "?k=" not in cmd, cmd[:80]
        assert not re.search(r"\bK=[A-Za-z0-9]{16,}", cmd), cmd[:80]


def test_audit_auth_headers_travel_via_stdin_not_argv():
    src = AUDIT.read_text(encoding="utf-8")
    cmds = _extract_remote_commands(src)
    auth_cmds = [c for c in cmds if ("X-Access-Key" in c or "w2t25k" in c)]
    assert auth_cmds, "لم يُعثر على أوامر مصادقة — تحقق من السكربت"
    for cmd in auth_cmds:
        assert "printf" in cmd and "-H @-" in cmd, cmd[:120]
        # القيمة تُجلب داخل مُدمَّج أوامر $(…) في ذاكرة shell البعيد — ليست في نص الأمر
        assert "$(sudo cat /etc/w2t25-monitor/monitor_token)" in cmd, cmd[:120]


def test_audit_script_never_prints_token():
    src = AUDIT.read_text(encoding="utf-8")
    # لا متغير بايثون يحمل التوكن أصلًا — التوكن لا يعبر عملية بايثون
    assert not re.search(r"(?m)^\w*tok\w*\s*=\s*[^=]", src, re.I)
    assert "monitor_token" in src  # يُذكر المسار فقط (تسليم عبر shell البعيد)


# ------------------------------------------------- mechanism test (FAKE value)

class _SlowGET(BaseHTTPRequestHandler):
    received_headers = {}

    def do_GET(self):
        key = self.headers.get("X-Access-Key") or ""
        if key:
            _SlowGET.received_headers.setdefault("seen", set()).add(key)
        time.sleep(1.2)                # يُبقي curl حيًا لأخذ عينة من /proc
        self.send_response(200)
        self.send_header("Content-Length", "2")
        self.end_headers()
        self.wfile.write(b"ok")

    def log_message(self, *a):
        pass


def _sample_cmdlines(sample_window=2.0):
    """يجمع كل سطر أوامر لكل عملية curl خلال نافذة زمنية."""
    import os
    seen, deadline = [], time.time() + sample_window
    while time.time() < deadline:
        for pid in os.listdir("/proc"):
            if not pid.isdigit():
                continue
            try:
                with open("/proc/%s/cmdline" % pid, "rb") as fh:
                    raw = fh.read()
            except OSError:
                continue
            if b"curl" in raw:
                args = raw.decode("utf-8", "replace").replace("\0", " ")
                if args not in seen:
                    seen.append(args)
        time.sleep(0.05)
    return seen


def _run_curl(url: str, argv_style: bool):
    if argv_style:   # النمط القديم المتسرب: الترويسة في argv
        cmd = 'curl -s -m 4 -H "X-Access-Key: $R1_FAKE" "%s"' % url
    else:            # النمط المعتمد: الترويسة عبر stdin
        cmd = ('printf "X-Access-Key: ' + '%s' + '" "$R1_FAKE" | curl -s -m 4 -H @- "%s"'
               % (url,))
    env = {"R1_FAKE": FAKE, "PATH": "/usr/bin:/bin"}
    subprocess.run(["bash", "-c", cmd], env=env, capture_output=True, timeout=10)


def test_fake_token_stays_out_of_process_arguments(tmp_path):
    """النمط المعتمد: القيمة في ذاكرة shell فقط — لا تظهر في argv لأي عملية."""
    srv = HTTPServer(("127.0.0.1", 0), _SlowGET)
    port = srv.server_address[1]
    th = threading.Thread(target=srv.serve_forever, daemon=True)
    th.start()
    try:
        sampler = threading.Thread(target=lambda: setattr(
            _SlowGET, "proc_sample", _sample_cmdlines(2.5)), daemon=True)
        sampler.start()
        _run_curl("http://127.0.0.1:%d/ok" % port, argv_style=False)
        sampler.join(timeout=4)
        cmdlines = getattr(_SlowGET, "proc_sample", [])
        leaked = [c for c in cmdlines if FAKE in c]
        assert not leaked, "التسرب إلى argv: %r" % leaked[:2]
        # الآلية تعمل: الخادم استقبل الترويسة فعلًا عبر stdin
        assert FAKE in _SlowGET.received_headers.get("seen", set())
    finally:
        srv.shutdown()
        srv.server_close()


def test_old_argv_style_would_leak_detection_control(tmp_path):
    """عنصر تحكم: النمط القديم كان يضع القيمة في argv — الاختبار قادر على كشفه."""
    srv = HTTPServer(("127.0.0.1", 0), _SlowGET)
    port = srv.server_address[1]
    th = threading.Thread(target=srv.serve_forever, daemon=True)
    th.start()
    try:
        sampler = threading.Thread(target=lambda: setattr(
            _SlowGET, "proc_sample2", _sample_cmdlines(2.5)), daemon=True)
        sampler.start()
        _run_curl("http://127.0.0.1:%d/ok" % port, argv_style=True)
        sampler.join(timeout=4)
        cmdlines = getattr(_SlowGET, "proc_sample2", [])
        leaked = [c for c in cmdlines if FAKE in c]
        assert leaked, "عنصر التحكم لم يلتقط التسرب المتوقع — الاختبار نفسه بحاجة مراجعة"
    finally:
        srv.shutdown()
        srv.server_close()
