#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
W2-T07 خطوة 4 (تمهيد) — جلب نسخة الاحتياط الإنتاجية للاستخدام المحلي في التحقق البصري.
قراءة فقط على الخادم: SFTP لملف النسخة الأرشيفية /opt/aes-backups/db/nightly-20261027.db
(ليس القاعدة الحية). لا أي كتابة على الإنتاج.
"""
import hashlib
import json
import os

import paramiko

HOST = "92.5.14.150"
USER = "opc"
KEY = "/tmp/oracle_key"
REMOTE = "/opt/aes-backups/db/nightly-20261027.db"
OUT = "/home/z/my-project/download/aes-remediation/W2-T07/nightly-20261027.db"
META = "/home/z/my-project/download/aes-remediation/W2-T07/20261027-db-fetch.json"

os.makedirs(os.path.dirname(OUT), exist_ok=True)

ssh = paramiko.SSHClient()
ssh.set_missing_host_key_policy(paramiko.AutoAddPolicy())
ssh.connect(HOST, username=USER, key_filename=KEY, look_for_keys=False, allow_agent=False, timeout=15)

# الحجم البعيد أولاً
_, o, _ = ssh.exec_command(f"stat -c %s {REMOTE}", timeout=30)
remote_size = int(o.read().decode().strip())

sftp = ssh.open_sftp()
sftp.get(REMOTE, OUT)
sftp.close()
ssh.close()

local_size = os.path.getsize(OUT)
md5 = hashlib.md5(open(OUT, "rb").read()).hexdigest()

# تحقق sqlite سلامة + أعداد
import sqlite3

con = sqlite3.connect(f"file:{OUT}?mode=ro", uri=True)
integrity = con.execute("PRAGMA integrity_check").fetchone()[0]
tables = len(con.execute("SELECT name FROM sqlite_master WHERE type='table'").fetchall())
projects = con.execute("SELECT count(*) FROM projects").fetchone()[0]
conversations = con.execute("SELECT count(*) FROM conversations").fetchone()[0]
messages = con.execute("SELECT count(*) FROM messages").fetchone()[0]
con.close()

result = {
    "task": "W2-T07 step4 prep — fetch production backup DB for local visual verification",
    "mode": "READ-ONLY on server (SFTP read of archive backup file, not live DB)",
    "remote": REMOTE,
    "remote_size": remote_size,
    "local_size": local_size,
    "size_match": local_size == remote_size,
    "md5": md5,
    "integrity": integrity,
    "tables": tables,
    "projects": projects,
    "conversations": conversations,
    "messages": messages,
}
with open(META, "w") as f:
    json.dump(result, f, ensure_ascii=False, indent=2)
print(json.dumps(result, ensure_ascii=False, indent=2))
assert local_size == remote_size and integrity == "ok", "FETCH MISMATCH"
print("FETCH_OK")
