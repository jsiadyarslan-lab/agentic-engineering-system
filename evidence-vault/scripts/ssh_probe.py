#!/usr/bin/env python3
"""Read-only SSH probe for AES-UI-PREMIUM-REDESIGN-006 Phase 1.

Connects to the Oracle host SSH endpoint WITHOUT credentials to learn:
  - server banner / software version
  - host key type + fingerprint (for the record)
  - authentication methods offered for candidate users

No authentication is attempted with any secret. This is a standard
handshake probe only.
"""
import socket
import sys

import paramiko

HOST = "92.5.14.150"
PORT = 22
USERS = ["opc", "root", "ubuntu", "aes"]


def main():
    print(f"probing {HOST}:{PORT} ...")
    sock = socket.create_connection((HOST, PORT), timeout=12)
    transport = paramiko.Transport(sock)
    transport.banner_timeout = 15
    transport.auth_timeout = 15
    try:
        transport.start_client()
    except Exception as e:
        print(f"handshake failed: {type(e).__name__}: {e}")
        sys.exit(2)

    print(f"remote banner : {transport.get_banner()}")
    hk = transport.get_remote_server_key()
    fingerprint = hk.get_fingerprint().hex()
    print(f"host key      : {hk.get_name()}  md5-hex: {fingerprint}")

    for user in USERS:
        try:
            transport.auth_none(user)
            print(f"user {user!r}: auth_none SUCCEEDED (no auth required!?)")
        except paramiko.BadAuthenticationType as e:
            print(f"user {user!r}: allowed auth methods = {e.allowed_types}")
        except paramiko.AuthenticationException as e:
            print(f"user {user!r}: rejected ({e})")
        except Exception as e:
            print(f"user {user!r}: {type(e).__name__}: {e}")

    transport.close()


if __name__ == "__main__":
    main()
