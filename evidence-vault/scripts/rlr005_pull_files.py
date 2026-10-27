#!/usr/bin/env python3
"""RLR-005 (resume 5) — pull key files locally via SFTP for exact reading."""
import paramiko

HOST, USER, SSHKEY = "92.5.14.150", "opc", "/tmp/oracle_key"

FILES = [
    ("src/ui/chat-stream.js", "chat-stream.js"),
    ("src/research/chat_research.py", "chat_research.py"),
]
# routes.py is big — pull only relevant lines via sed
ROUTE_CMD = ("sed -n '1090,1310p' /opt/agentic-engineering-system/src/api/routes.py")


def main():
    c = paramiko.SSHClient()
    c.set_missing_host_key_policy(paramiko.AutoAddPolicy())
    c.connect(HOST, username=USER, key_filename=SSHKEY, timeout=25,
              look_for_keys=False, allow_agent=False)
    try:
        sftp = c.open_sftp()
        base = "/opt/agentic-engineering-system/"
        out = "/home/z/my-project/scripts/rlr005_files/"
        try:
            sftp.mkdir(out.rsplit("/", 2)[0] + "/rlr005_files")
        except IOError:
            pass
        for remote, local in FILES:
            sftp.get(base + remote, out + local)
            print("pulled", remote, "->", out + local)
        _, o, e = c.exec_command(ROUTE_CMD, timeout=30)
        o.channel.recv_exit_status()
        with open(out + "routes_1090_1310.py", "w") as f:
            f.write(o.read().decode("utf-8", "replace"))
        print("pulled routes.py lines 1090-1310")
        # integrity check for the '[m' question
        _, o, _ = c.exec_command(
            "grep -c 'messageId\\]' /opt/agentic-engineering-system/src/ui/chat-stream.js; "
            "grep -c 'essageId\\]' /opt/agentic-engineering-system/src/ui/chat-stream.js",
            timeout=30)
        o.channel.recv_exit_status()
        print("counts [messageId] vs eaten:", o.read().decode().strip().replace("\n", " | "))
        sftp.close()
    finally:
        c.close()


if __name__ == "__main__":
    main()
