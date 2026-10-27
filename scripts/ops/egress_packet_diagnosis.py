#!/usr/bin/env python3
# READ-ONLY packet-level diagnosis: WHERE does TCP:80 die?
# (a) SYN never leaves the host -> local firewall (firewalld/nftables OUTPUT)
# (b) SYN leaves, no SYN-ACK returns -> OCI rule wrong (not applied / wrong direction / Stateless w/o return rule)
# Passive capture only, /tmp scratch file removed at the end. Zero state change.
import json, paramiko

HOST, USER, KEY = "92.5.14.150", "opc", "/tmp/oracle_key"
ssh = paramiko.SSHClient()
ssh.set_missing_host_key_policy(paramiko.AutoAddPolicy())
ssh.connect(HOST, username=USER, key_filename=KEY, timeout=20,
            look_for_keys=False, allow_agent=False)

CMDS = [
    # capture SYNs to port 80 while a curl attempt runs
    ("tcpdump_t80", """
sudo -n bash -c '
rm -f /tmp/t80.txt
timeout 9 tcpdump -i any -nn "tcp port 80 and tcp[tcpflags] & (tcp-syn|tcp-ack) != 0" -c 40 2>/dev/null > /tmp/t80.txt &
TPID=$!
sleep 1.5
curl -s -o /dev/null -m 5 -w "curl_rc=%{exitcode} code=%{http_code}\\n" http://93.184.216.34/ 2>&1 || echo "curl_failed"
sleep 3
kill $TPID 2>/dev/null
echo "--- PACKETS (syn/ack to/from port 80) ---"
cat /tmp/t80.txt
rm -f /tmp/t80.txt
'"""),
    # local firewall OUTPUT chain inspection
    ("firewalld_zone",   "sudo -n firewall-cmd --list-all 2>/dev/null | head -20"),
    ("nft_output",       "sudo -n nft list ruleset 2>/dev/null | grep -iE 'chain output|hook output|tcp dport 80|reject|policy drop' | head -15"),
    ("iptables_output",  "sudo -n iptables -S OUTPUT 2>/dev/null | head -12; echo '---'; sudo -n iptables -L OUTPUT -n --line-numbers 2>/dev/null | head -12"),
    # routing sanity for port-80 destinations
    ("route_default",    "ip route show default; ip route get 93.184.216.34 2>/dev/null"),
    # instance metadata: which subnet/vcn (to help owner verify SL location)
    ("oci_metadata",     "curl -s --max-time 3 -H 'Authorization: Bearer Oracle' http://169.254.169.254/opc/v2/instance/ 2>/dev/null | python3 -c \"import sys,json; d=json.load(sys.stdin); print('region=',d.get('regionInfo',{}).get('regionIdentifier','?')); print('subnet=',d.get('subnetCidrBlock','?')); print('vcn=',d.get('vcnCidrBlock','?')); print('nsg?=',d.get('networkInfo',''))\" 2>/dev/null || echo metadata_v2_unreachable"),
    # control: 443 handshake visible (proves capture method works)
    ("tcpdump_t443_ctl", """
sudo -n bash -c '
rm -f /tmp/t443.txt
timeout 6 tcpdump -i any -nn "host 93.184.216.34 and tcp port 443 and tcp[tcpflags] & (tcp-syn|tcp-ack) != 0" -c 8 2>/dev/null > /tmp/t443.txt &
TPID=$!
sleep 1
curl -s -o /dev/null -m 4 https://93.184.216.34/ 2>/dev/null
sleep 2
kill $TPID 2>/dev/null
echo "--- PACKETS 443 control ---"; cat /tmp/t443.txt; rm -f /tmp/t443.txt
'"""),
]
out = {}
for name, cmd in CMDS:
    try:
        _, so, se = ssh.exec_command(cmd, timeout=60)
        out[name] = so.read().decode(errors="replace").strip()[:2500]
        err = se.read().decode(errors="replace").strip()[:200]
    except Exception as e:
        out[name], err = "", str(e)
    print(f"=== {name} ===\n{out[name]}\n{'[err] ' + err if err else ''}")

with open("/home/z/my-project/download/aes-remediation/egress-packet-diagnosis.json", "w") as f:
    json.dump(out, f, ensure_ascii=False, indent=2)
ssh.close()
print("\nSAVED: egress-packet-diagnosis.json")
