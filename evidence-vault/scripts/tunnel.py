#!/usr/bin/env python3
"""SSH tunnel: local 127.0.0.1:18010 -> 92.5.14.150's 127.0.0.1:8010 (production app).

Run detached:  setsid nohup python3 tunnel.py >/dev/null 2>&1 &
Kill with:     kill $(cat /tmp/aes-tunnel.pid)
"""
import os
import select
import socket
import socketserver
import sys
import threading

import paramiko

HOST, PORT, USER = "92.5.14.150", 22, "opc"
KEY = "/home/z/.ssh_key_006"
LOCAL_BIND = ("127.0.0.1", 18010)
TARGET = ("127.0.0.1", 8010)
PIDFILE = "/tmp/aes-tunnel.pid"


def main():
    with open(PIDFILE, "w") as f:
        f.write(str(os.getpid()))

    client = paramiko.SSHClient()
    client.set_missing_host_key_policy(paramiko.AutoAddPolicy())
    client.connect(hostname=HOST, port=PORT, username=USER, key_filename=KEY,
                   timeout=15, banner_timeout=15, auth_timeout=15,
                   allow_agent=False, look_for_keys=False)
    transport = client.get_transport()
    transport.set_keepalive(15)

    class Handler(socketserver.BaseRequestHandler):
        def handle(self):
            try:
                chan = transport.open_channel("direct-tcpip", TARGET,
                                              self.request.getpeername())
            except Exception:
                return
            if chan is None:
                return
            while True:
                r, _, _ = select.select([self.request, chan], [], [], 60)
                if not r:
                    break
                if self.request in r:
                    data = self.request.recv(16384)
                    if not data:
                        break
                    chan.sendall(data)
                if chan in r:
                    data = chan.recv(16384)
                    if not data:
                        break
                    self.request.sendall(data)
            chan.close()
            self.request.close()

    class Server(socketserver.ThreadingTCPServer):
        daemon_threads = True
        allow_reuse_address = True

    server = Server(LOCAL_BIND, Handler)
    print(f"tunnel up: {LOCAL_BIND} -> {TARGET} via {USER}@{HOST}", flush=True)
    server.serve_forever()


if __name__ == "__main__":
    main()
