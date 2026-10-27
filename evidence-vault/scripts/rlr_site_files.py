#!/usr/bin/env python3
"""RLR-001 — inspect produced news website files (READ-ONLY)."""
import subprocess

print("== step 312 workspace (5 pages filled)")
print(subprocess.run(["bash", "-c",
    "ls -la /opt/aes-vis/runtime/projects/21/steps/312/ 2>/dev/null | head -20"],
    capture_output=True, text=True).stdout)

print("== step 313 workspace (playwright, running)")
print(subprocess.run(["bash", "-c",
    "ls -la /opt/aes-vis/runtime/projects/21/steps/313/ 2>/dev/null | head -15"],
    capture_output=True, text=True).stdout)

print("== index.html head (step 312)")
print(subprocess.run(["bash", "-c",
    "head -c 600 /opt/aes-vis/runtime/projects/21/steps/312/index.html 2>/dev/null || "
    "find /opt/aes-vis/runtime/projects/21/steps/312 -name 'index.html' | head -2"],
    capture_output=True, text=True).stdout)

print("== politics.html title check")
print(subprocess.run(["bash", "-c",
    "grep -oE '<title>[^<]*</title>' /opt/aes-vis/runtime/projects/21/steps/312/*.html 2>/dev/null | head -8"],
    capture_output=True, text=True).stdout)

print("== styles.css tokens (step 312)")
print(subprocess.run(["bash", "-c",
    "head -c 500 /opt/aes-vis/runtime/projects/21/steps/312/styles.css 2>/dev/null"],
    capture_output=True, text=True).stdout)

print("== html lang/dir check")
print(subprocess.run(["bash", "-c",
    "grep -h 'html lang' /opt/aes-vis/runtime/projects/21/steps/312/*.html 2>/dev/null | sort -u | head -5"],
    capture_output=True, text=True).stdout)

print("== project 21 root dir")
print(subprocess.run(["bash", "-c",
    "ls -la /opt/aes-vis/runtime/projects/21/ 2>/dev/null | head -12"],
    capture_output=True, text=True).stdout)
