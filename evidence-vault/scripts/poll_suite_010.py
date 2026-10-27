#!/usr/bin/env python3
"""AES-010 — poll the trusted suite on Oracle until completion."""
import sys
import time
import paramiko

HOST, USER, KEY = "92.5.14.150", "opc", "/home/z/.ssh_key_010"
R = "/home/opc/aes-reproof-010"
MAX_WAIT = int(sys.argv[1]) if len(sys.argv) > 1 else 540


def poll_once(c):
    cmd = (
        f'if [ -f {R}/pytest-exit.txt ]; then echo DONE; cat {R}/pytest-exit.txt; '
        f'grep -E "SUITE_(START|END)" {R}/suite-runner.out; '
        f'echo "---TAIL40---"; tail -40 {R}/trusted-suite-full.log | grep -vE "^\\." | head -35; '
        f'else echo RUNNING; ps -eo etime,args | grep "python -m pytest" | grep -v grep | head -1; '
        f'wc -l {R}/trusted-suite-full.log; tail -c 300 {R}/trusted-suite-full.log | tr "\\n" " " | cut -c1-280; echo; fi'
    )
    _, o, _ = c.exec_command(cmd, timeout=30)
    o.channel.recv_exit_status()
    return o.read().decode("utf-8", "replace").strip()


def main():
    c = paramiko.SSHClient()
    c.set_missing_host_key_policy(paramiko.AutoAddPolicy())
    c.connect(HOST, username=USER, key_filename=KEY, timeout=15, look_for_keys=False, allow_agent=False)
    t0 = time.time()
    while time.time() - t0 < MAX_WAIT:
        out = poll_once(c)
        print(f"[{(time.time()-t0)/60:.1f}m] {out[:400]}\n")
        if out.startswith("DONE"):
            print(">>> SUITE COMPLETED <<<")
            c.close()
            return 0
        time.sleep(120)
    print(f">>> still running after {MAX_WAIT}s of polling <<<")
    c.close()
    return 1


if __name__ == "__main__":
    sys.exit(main())
