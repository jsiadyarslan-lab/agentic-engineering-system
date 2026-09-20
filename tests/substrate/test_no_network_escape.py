"""إثبات سالب 1: لا هروب شبكي من العزل.

الركيزة تنشئ network namespace بلا واجهات (D-04=A: الشبكة = لا شيء).
البرنامج داخل العزل يحاول الاتصال بمستمع TCP حي على المضيف (خارج
العزل) — يجب أن يفشل الاتصال، ويجب ألا يستقبل المستمع أي شيء.
"""

from __future__ import annotations

import socket

from tests.substrate.conftest import read_stdout, run_in_sandbox  # noqa: F401


def test_no_network_escape(adapter, tmp_path):
    # مستمع حي على المضيف قبل تشغيل العزل
    listener = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    listener.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
    listener.bind(("127.0.0.1", 0))
    listener.listen(1)
    port = listener.getsockname()[1]
    listener.settimeout(8.0)

    code = f'''
import socket, sys
try:
    s = socket.create_connection(("127.0.0.1", {port}), timeout=3)
    s.close()
    print("ESCAPED:connected")
    sys.exit(0)   # هروب — سيئ
except Exception as e:
    print("BLOCKED:", type(e).__name__)
    sys.exit(7)   # مُنع — جيد
'''
    try:
        record, artifacts = run_in_sandbox(
            adapter, tmp_path, code, sandbox_id="neg-net-001"
        )
        stdout = read_stdout(record)

        # 1) الاتصال فشل داخل العزل
        assert record.exit_code == 7, f"داخل العزل: {stdout!r}"
        assert "ESCAPED" not in stdout
        assert "BLOCKED" in stdout

        # 2) المستمع على المضيف لم يستقبل شيئًا قط
        try:
            conn, _ = listener.accept()
            conn.close()
            raised = True
        except socket.timeout:
            raised = False
        assert not raised, "وصل اتصال من داخل العزل إلى المضيف!"
    finally:
        listener.close()
