#!/usr/bin/env python3
"""W1-T02 — تنظيف مستخدم الاختبار: حذف السطر في المكان (لا mv) +
restorecon + ملكية/أذونات + تحقق بايتي (sha256 وعدد الأسطر يعودان لما قبل)."""
import paramiko

HOST, USER, KEY = "92.5.14.150", "opc", "/tmp/oracle_key"
USER_NAME = "w1t02a"

c = paramiko.SSHClient()
c.set_missing_host_key_policy(paramiko.AutoAddPolicy())
c.connect(HOST, username=USER, key_filename=KEY, timeout=20,
          look_for_keys=False, allow_agent=False)


def run(cmd, t=30):
    _, o, e = c.exec_command(cmd, timeout=t)
    rc = o.channel.recv_exit_status()
    out, err = o.read().decode(), e.read().decode()
    print(f"$ {cmd[:110]}\n{out.strip()[:500]}"
          f"{('[stderr] ' + err.strip()[:200]) if err.strip() else ''}\n[rc={rc}]")
    return rc, out, err


run(f"sudo -n awk -F: '{{print $1}}' /etc/nginx/.htpasswd_vis")
# حذف سطر w1t02a في المكان: اكتب ملف مؤقت ثم sudo cp content INTO الملف الأصلي
# (لا mv — يحفظ سياق SELinux httpd_config_t للملف الأصلي)
run(f"sudo -n sh -c \"grep -v '^{USER_NAME}:' /etc/nginx/.htpasswd_vis > /tmp/htpasswd_w1t02.strip && "
    f"cat /tmp/htpasswd_w1t02.strip > /etc/nginx/.htpasswd_vis && rm -f /tmp/htpasswd_w1t02.strip && echo STRIP_OK\"")
run("sudo -n restorecon -v /etc/nginx/.htpasswd_vis")
run("sudo -n chown root:nginx /etc/nginx/.htpasswd_vis && sudo -n chmod 640 /etc/nginx/.htpasswd_vis")
run("sudo -n ls -laZ /etc/nginx/.htpasswd_vis")
run("sudo -n sha256sum /etc/nginx/.htpasswd_vis && sudo -n wc -l /etc/nginx/.htpasswd_vis && sudo -n awk -F: '{print $1}' /etc/nginx/.htpasswd_vis")
c.close()
