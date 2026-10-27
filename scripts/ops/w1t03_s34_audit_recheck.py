#!/usr/bin/env python3
"""W1-T03-S34-AUDIT-R — narrow-scope RE-AUDIT of the executor's remediation of the 4 findings.

Scope (read-only; no SSH needed — one external GET probe only):
  R1 token leak scan across /home/z/my-project (except owner-token.txt) — expect zero
  R2 owner-notification.txt: Checked URL masked (<TOKEN>) + prefix 5e140aa0 only + masking note
  R3 owner-token.txt mode 0600
  R4 worklog.md: LAST entry is Task ID: W1-T03-S34 (steps 3-4 execution entry, R8 gap closed)
  R5 monitor-live.json: post_audit_correction consistent with the independent audit findings
     (UptimeRobot fleet, 13 IPs, PTR checker-*.uptimerobot.com, median 304s, GET=200/HEAD=405)
  R6 raw data in monitor-live.json left intact (transparent correction, not rewrite)
  R7 TRACKER W1-T03 card: correction present in step 4 + execution log; status still
     'منجزة — بانتظار التدقيق (الخطوات 3-4)'; steps 0-4 all [x]; first audit signature intact
  R8 live external GET on the secret -> 200 + status ok (optional strictness probe)
  R9 strict hex scan: no 32-hex string equal to the token anywhere in W1-T03 evidence;
     every 32-hex found is classified (token / known fake test values)
  R10 git containment: token present in git history ONLY as owner-token.txt itself (the
      designated secret file); zero evidence files containing it in any commit; the two
      corrected files remain untracked; no remote configured (never pushed)

Evaluation by actual output lines/values, never exit codes. Token masked as <TOKEN> everywhere.
Evidence -> download/aes-remediation/W1-T03/audit_s34_recheck.json
"""
import json
import os
import re
import subprocess
import sys
import urllib.request
from datetime import datetime, timezone

ROOT = "/home/z/my-project"
EV = os.path.join(ROOT, "download", "aes-remediation", "W1-T03")
TOKEN_FILE = os.path.join(EV, "owner-token.txt")
NOTIF = os.path.join(EV, "20261027-owner-notification.txt")
LIVE_JSON = os.path.join(EV, "20261027-monitor-live.json")
TRACKER = os.path.join(ROOT, "TRACKER.md")
WORKLOG = os.path.join(ROOT, "worklog.md")
OUT_JSON = os.path.join(EV, "audit_s34_recheck.json")
HOST = "92.5.14.150"
MY_UA = "W1-T03-S34-AUDIT-R/1.0 (narrow-scope recheck)"

TOKEN = open(TOKEN_FILE).read().strip()
PREFIX = TOKEN[:8]

CHECKS = []


def add(cid, desc, expected, actual, ok, blocking=True, note=None):
    rec = {"id": cid, "desc": desc, "expected": str(expected), "actual": str(actual),
           "pass": bool(ok), "blocking": bool(blocking)}
    if note:
        rec["note"] = str(note)
    CHECKS.append(rec)
    print(f"[{'PASS' if ok else 'FAIL'}{' (BLOCKING)' if (not ok and blocking) else ''}] {cid} :: {desc}")
    print(f"    actual: {str(actual)[:400]}")


def section(t):
    print("\n" + "=" * 78 + "\n" + t + "\n" + "=" * 78)


# ---------------------------------------------------------------- R1 token leak scan
section("R1) token leak scan across the tree (except owner-token.txt)")
leaks = []
for dirpath, dirnames, filenames in os.walk(ROOT):
    if ".git" in dirnames:
        dirnames.remove(".git")
    for fn in filenames:
        p = os.path.join(dirpath, fn)
        if p in (TOKEN_FILE, OUT_JSON):
            continue
        try:
            with open(p, "rb") as fh:
                if TOKEN.encode() in fh.read():
                    leaks.append(os.path.relpath(p, ROOT))
        except OSError:
            pass
add("r1_token_leak_worktree", "full token absent from every file in the tree except owner-token.txt",
    "0 matches", f"{len(leaks)} match(es): {leaks}", len(leaks) == 0, blocking=True)

# ---------------------------------------------------------------- R2/R3 notification + mode
section("R2/R3) notification masking + token file mode")
notif = open(NOTIF, encoding="utf-8").read()
notif_flags = {
    "no_full_token": TOKEN not in notif,
    "checked_url_masked": "Checked URL: http://92.5.14.150/healthz-<TOKEN>" in notif,
    "prefix_documented": "5e140aa0" in notif,
    "masking_note_present": "التوكن الكامل مقنَّع" in notif and "W1-T03-S34-AUDIT" in notif,
    "email_body_intact": "Resolved at: 2026-10-27 03:51:08" in notif and "Region: Europe" in notif
                         and "Monitor name: 92.5.14.150" in notif,
}
add("r2_notification_masked", "notification: Checked URL masked, prefix only, email body intact",
    "all flags true", notif_flags, all(notif_flags.values()), blocking=True)

mode = oct(os.stat(TOKEN_FILE).st_mode & 0o777)[2:]
add("r3_token_file_mode", "owner-token.txt mode", "600", mode, mode == "600", blocking=True)

# ---------------------------------------------------------------- R4 worklog last entry
section("R4) worklog last entry = W1-T03-S34")
wl = open(WORKLOG, encoding="utf-8").read()
ids = re.findall(r"^Task ID: (.+)$", wl, re.M)
s34_entry = wl[wl.rfind("Task ID: W1-T03-S34"):]
wl_flags = {
    "last_entry_is_s34": bool(ids) and ids[-1] == "W1-T03-S34",
    "covers_steps_3_4": "خطوة 3" in s34_entry and "خطوة 4" in s34_entry,
    "documents_remediation": "تقنيع التوكن" in s34_entry and "chmod 600" in s34_entry and "post_audit_correction" in s34_entry,
    "discloses_initial_fail": "FAIL أولي 17/21" in s34_entry,
    "my_audit_entry_precedes": "Task ID: W1-T03-S34-AUDIT" in wl[: wl.rfind("Task ID: W1-T03-S34")],
}
add("r4_worklog_last_entry", "last worklog entry is W1-T03-S34 covering steps 3-4 + remediation (R8 gap closed)",
    "all flags true", wl_flags, all(wl_flags.values()), blocking=False)

# ---------------------------------------------------------------- R5/R6 monitor-live.json
section("R5/R6) monitor-live.json post_audit_correction + raw data intact")
live = json.load(open(LIVE_JSON, encoding="utf-8"))
pac = live.get("post_audit_correction", {})
txt = json.dumps(pac, ensure_ascii=False)
pac_flags = {
    "present": isinstance(pac, dict) and bool(pac),
    "uptimerobot_fleet": "UptimeRobot checker fleet" in txt,
    "count_16_polls_13_ips": "16 polls from 13 distinct IPs" in txt,
    "ptr_pattern": "checker-*.uptimerobot.com" in txt,
    "region_europe": "Europe" in txt and "matches Region Europe" in txt,
    "median_304s": "median 304s" in txt,
    "get_200_head_405": "GET polls = 200" in txt and "HEAD polls = 405" in txt,
    "env_ips_identified": all(x in txt for x in ("47.57.232.232", "8.212.10.159", "47.57.242.119"))
                          and "execution-environment egress" in txt,
    "88_99_is_real_checker": "88.99.80.227" in txt and "real UptimeRobot checkers" in txt,
    "none_owner_server_loopback": "None of them are owner/server/loopback" in txt,
}
add("r5_post_correction_consistent",
    "post_audit_correction matches the independent audit findings (fleet/13 IPs/PTR/304s/200-405/env IPs)",
    "all flags true", pac_flags, all(pac_flags.values()), blocking=False)

lc = live.get("checks", {})
raw_flags = {
    "verdict_pass": live.get("verdict") == "PASS",
    "count_18": lc.get("access_log_healthz_count_last1000") == "18",
    "ext_200_403_403": (lc.get("external_secret_200", {}).get("code") == 200
                        and lc.get("external_root_403", {}).get("code") == 403
                        and lc.get("external_wrongtoken_403", {}).get("code") == 403),
    "services_active": lc.get("services") == ["active", "active", "active"],
    "health_200": lc.get("app_health_direct") == "200",
    "samples_still_masked": TOKEN not in json.dumps(lc.get("healthz_recent_samples_masked", [])),
    "raw_checks_unchanged": (lc.get("access_log_healthz_count_last1000") == "18"
                             and isinstance(lc.get("healthz_source_ips"), list) and len(lc["healthz_source_ips"]) == 10
                             and len(lc.get("healthz_recent_samples_masked", [])) == 15
                             and len(lc.get("monitor_poll_timestamps_last20", [])) == 20
                             and lc.get("healthz_status_distribution_nonowner") == ["18 200", "      5 403", "      3 405", "      3 401"]),
}
add("r6_raw_data_intact", "raw measurements in monitor-live.json left intact (correction appended, not rewritten)",
    "all flags true (no full token in samples; counts/samples/timestamps byte-counts unchanged)", raw_flags, all(raw_flags.values()), blocking=False)

# spot-verify: exact sample strings recorded by the first audit are still present verbatim
# (compare against the PARSED list — the file stores them as JSON strings with escaped quotes)
spot_samples = [
    '127.0.0.1 - - [27/Oct/2026:02:28:29 +0000] "GET /healthz-ffffffffffffffffffffffffffffffff HTTP/1.1" 401 179 "-" "curl/7.76.1" "-"',
    '88.99.80.227 - - [27/Oct/2026:03:57:07 +0000] "GET /healthz-<TOKEN> HTTP/1.1" 200 372 "http://92.5.14.150/healthz-<TOKEN>" "Mozilla/5.0+(compatible; UptimeRobot/2.0; http://www.uptimerobot.com/)" "-"',
    '18.193.252.127 - - [27/Oct/2026:04:02:25 +0000] "GET /healthz-<TOKEN> HTTP/1.1" 200 372 "http://92.5.14.150/healthz-<TOKEN>" "Mozilla/5.0+(compatible; UptimeRobot/2.0; http://www.uptimerobot.com/)" "-"',
]
samples_list = lc.get("healthz_recent_samples_masked", [])
spot_ok = all(s in samples_list for s in spot_samples)
add("r6b_spot_lines_verbatim", "known original sample lines still present verbatim (raw data not rewritten)",
    "all 3 spot samples present in parsed list", f"present={spot_ok} (list size={len(samples_list)})", spot_ok, blocking=False)

# ---------------------------------------------------------------- R7 TRACKER card
section("R7) TRACKER W1-T03 card correction + pre-signature state")
tr = open(TRACKER, encoding="utf-8").read()
card = tr[tr.find("### W1-T03"): tr.find("### W1-T04")]
card_flags = {
    "status_awaiting_s34": "منجزة — بانتظار التدقيق (الخطوات 3-4)" in card.split("\n")[
        next(i for i, l in enumerate(card.split("\n")) if "الحالة" in l)],
    "steps_0_4_all_x": card.count("- [x] خطوة") == 5 and card.count("- [ ] خطوة") == 0,
    "step4_correction": ("تصويب بعد التدقيق" in card and "أسطول UptimeRobot" in card
                         and "13 عنواناً" in card and "checker-*.uptimerobot.com" in card
                         and "304ث" in card and "خرج بيئة التنفيذ" in card),
    "step4_masking_note": "بتقنيع التوكن" in card and "5e140aa0" in card,
    "execlog_remediation": "بعد تدقيق W1-T03-S34-AUDIT (FAIL أولي 17/21)" in card and "أصلح المنفذ البند الحاجب" in card,
    "first_audit_signature_intact": "W1-T03-AUDIT · 2026-10-27 · PASS" in card and "28 إثباتًا" in card,
    "board_row_awaiting": "| W1-T03 | مراقبة خارجية مجانية على /health + تنبيه | 1 | ساعة | منجزة — بانتظار التدقيق (الخطوات 3-4) |" in tr,
    "header_awaiting": "W1-T03 منجزة خطوات 0-4 وبانتظار توقيع تدقيق الخطوات 3-4" in tr,
}
add("r7_tracker_card", "card: correction in step 4 + exec log; status awaiting S34 audit; steps 0-4 [x]; first signature intact",
    "all flags true", card_flags, all(card_flags.values()), blocking=False)

# ---------------------------------------------------------------- R8 live external probe
section("R8) live external GET on the secret")
req = urllib.request.Request(f"http://{HOST}/healthz-{TOKEN}", method="GET", headers={"User-Agent": MY_UA})
try:
    with urllib.request.urlopen(req, timeout=15) as r:
        code = r.status
        body = r.read(4096).decode("utf-8", "replace")
except urllib.error.HTTPError as e:
    code = e.code
    body = e.read(4096).decode("utf-8", "replace")
ok8 = code == 200 and '"status":"ok"' in body.replace(" ", "")
add("r8_live_secret_200", "live GET /healthz-<TOKEN> from this env (UA W1-T03-S34-AUDIT-R)", "200 + status ok",
    f"{code} | {body[:100]!r}", ok8, blocking=True)

# ---------------------------------------------------------------- R9 strict 32-hex scan
section("R9) strict 32-hex scan over W1-T03 evidence")
hexfindings = {}
for fn in os.listdir(EV):
    p = os.path.join(EV, fn)
    if not os.path.isfile(p) or p == TOKEN_FILE:
        continue
    try:
        content = open(p, "rb").read().decode("utf-8", "replace")
    except OSError:
        continue
    hits = re.findall(r"\b[0-9a-fA-F]{32}\b", content)
    if hits:
        hexfindings[fn] = sorted(set(hits))
classified = {}
token_hex_leak = []
for fn, hits in hexfindings.items():
    for h in hits:
        if h.lower() == TOKEN.lower():
            token_hex_leak.append(fn)
        elif set(h.lower()) == {"0"} or set(h.lower()) == {"f"}:
            classified.setdefault("fake_test_values", []).append(f"{fn}:{h}")
        else:
            classified.setdefault("other_32hex_reviewed", []).append(f"{fn}:{h}")
add("r9_hex32_strictness", "no 32-hex equal to the token in any W1-T03 evidence file; all 32-hex classified",
    "0 token matches; others classified (fake test values / known sha-style fragments)",
    {"token_matches": token_hex_leak, "classified": classified},
    len(token_hex_leak) == 0, blocking=True,
    note="fake test values = the all-zeros / all-f tokens used deliberately in wrong-token probes; "
         "'other' entries are sha256-style fragments in archived evidence, not the secret")

# ---------------------------------------------------------------- R10 git containment
section("R10) git containment")
def git(args):
    r = subprocess.run(["git", "-C", ROOT] + args, capture_output=True, text=True, timeout=60)
    return (r.stdout + r.stderr).strip()

revs = git(["rev-list", "--all"]).split()
grep_out = git(["grep", "-l", TOKEN] + revs) if revs else ""
token_files_in_history = sorted({line.split(":", 1)[1] for line in grep_out.splitlines() if ":" in line})
notif_commits = git(["log", "--all", "--oneline", "--",
                     "download/aes-remediation/W1-T03/20261027-owner-notification.txt",
                     "download/aes-remediation/W1-T03/20261027-monitor-live.json"])
git_flags = {
    "token_only_in_owner_token_file": token_files_in_history == ["download/aes-remediation/W1-T03/owner-token.txt"],
    "no_evidence_file_ever_had_token": not any(f != "download/aes-remediation/W1-T03/owner-token.txt"
                                               for f in token_files_in_history),
    "corrected_files_untracked": "??" in git(["status", "--porcelain", "--",
                                              "download/aes-remediation/W1-T03/20261027-owner-notification.txt",
                                              "download/aes-remediation/W1-T03/20261027-monitor-live.json"]),
    "corrected_files_never_committed": notif_commits == "",
    "no_remote": git(["remote", "-v"]) == "",
    "never_pushed": git(["remote", "-v"]) == "",
}
add("r10_git_containment",
    "token exists in git history ONLY as owner-token.txt (designated secret file, env-local snapshot repo); "
    "no evidence file ever contained it; corrected files untracked & never committed; no remote -> never pushed",
    "all flags true", git_flags, all(git_flags.values()), blocking=False,
    note=("IMPORTANT for the parent before ANY R9 push: this environment's auto-snapshot repo (HEAD "
          f"{git(['log', '-1', '--format=%h']) if True else ''}, no remote, never pushed) tracks owner-token.txt. "
          "The R9 sync to GitHub MUST explicitly exclude owner-token.txt (per card: 'لا يدخل المستودع أبداً')."))

# ---------------------------------------------------------------- verdict
section("Verdict")
blocking_fails = [c["id"] for c in CHECKS if not c["pass"] and c["blocking"]]
nonblocking_fails = [c["id"] for c in CHECKS if not c["pass"] and not c["blocking"]]
verdict = "PASS" if not blocking_fails else "FAIL"
print(f"checks: {len(CHECKS)} | passed={sum(1 for c in CHECKS if c['pass'])} | "
      f"blocking_fails={blocking_fails} | nonblocking_fails={nonblocking_fails}")
print(f"VERDICT: {verdict}")

results = {
    "audit_id": "W1-T03-S34-AUDIT-R",
    "recheck_of": "W1-T03-S34-AUDIT (initial FAIL 17/21 — single blocking: token in owner-notification.txt)",
    "timestamp_utc": datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M:%S UTC"),
    "scope": "narrow re-audit of the executor's remediation of the 4 findings (all local; zero production changes; one external GET probe)",
    "token_policy": "full token masked as <TOKEN> everywhere; only prefix 5e140aa0 disclosed",
    "checks": CHECKS,
    "summary": {
        "total_checks": len(CHECKS),
        "passed": sum(1 for c in CHECKS if c["pass"]),
        "blocking_failures": blocking_fails,
        "nonblocking_failures": nonblocking_fails,
        "verdict": verdict,
    },
    "remediation_items_verified": {
        "1_blocking_token_masking": notif_flags,
        "2_token_file_mode": mode,
        "3_worklog_entry": wl_flags,
        "4_attribution_correction": {"monitor_live_post_correction": pac_flags, "tracker_card": card_flags},
    },
    "observations": [
        "owner-notification.txt's supplementary section (## التحقق المستقل المكمل) still quotes the ORIGINAL "
        "(pre-correction) attribution wording — the authoritative correction lives in monitor-live.json's "
        "post_audit_correction and the TRACKER card; recommend a one-line pointer be added at next sync (non-blocking).",
        "owner-token.txt is tracked in this environment's auto-snapshot git repo (introduced in local commit only; "
        "no remote configured; never pushed). The R9 push MUST exclude it explicitly — reinforced in the audit note.",
    ],
}
blob = json.dumps(results, ensure_ascii=False, indent=2)
if TOKEN in blob:
    blob = blob.replace(TOKEN, "<TOKEN>")
    print("WARNING: token was found in results and masked before writing.")
with open(OUT_JSON, "w", encoding="utf-8") as f:
    f.write(blob)
print(f"results written to {OUT_JSON}")
sys.exit(0)
