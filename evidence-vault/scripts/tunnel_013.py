#!/usr/bin/env python3
"""AES-013 — SSH local port forward to the PUBLIC path: 127.0.0.1:18081 -> host 127.0.0.1:80."""
import select
import socketserver
import paramiko

HOST, USER, KEY = "92.5.14.150", "opc", "/tmp/aes_key"
LOCAL_PORT = 18081
TARGET = ("127.0.0.1", 80)

client = paramiko.SSHClient()
client.set_missing_host_key_policy(paramiko.AutoAddPolicy())
client.connect(HOST, username=USER, key_filename=KEY, timeout=20,
               look_for_keys=False, allow_agent=False)
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


srv = Server(("127.0.0.1", LOCAL_PORT), Handler)
print(f"tunnel ready on 127.0.0.1:{LOCAL_PORT} -> {TARGET}", flush=True)
srv.serve_forever()
