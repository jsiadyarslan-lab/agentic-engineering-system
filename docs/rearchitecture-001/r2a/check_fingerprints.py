#!/usr/bin/env python3
"""R2A §6 — reproducible fingerprint checker (run me to re-verify the package).

Usage:  python3 r2a/check_fingerprints.py
(Any Python 3.8+; no third-party deps. ROOT is the evidence directory one level
above this script.)

Verified design ("exclude self, include counterpart"):
  SHA256SUMS   lines = all content files + MANIFEST.json  (SHA256SUMS itself absent)
  MANIFEST.files    = all content files + SHA256SUMS      (MANIFEST.json itself absent)

Output is deliberately hash-free (booleans and counts only) so the saved run log
(r2a/FINGERPRINT-CHECK.txt) stays byte-identical across fingerprint regenerations.
Exit code 0 = all checks pass, 1 = any failure.
"""
import hashlib, json, os, sys

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)          # docs/rearchitecture-001

def sha256(p):
    h = hashlib.sha256()
    with open(p, 'rb') as f:
        for c in iter(lambda: f.read(1 << 20), b''):
            h.update(c)
    return h.hexdigest()

# --- parse SHA256SUMS ---
sums, bad_lines = {}, []
with open(os.path.join(ROOT, 'SHA256SUMS'), encoding='utf-8') as f:
    for i, line in enumerate(f, 1):
        line = line.rstrip('\n')
        if not line:
            continue
        parts = line.split('  ', 1)
        if len(parts) != 2 or len(parts[0]) != 64:
            bad_lines.append(i)
            continue
        sums[parts[1]] = parts[0]

# --- parse MANIFEST ---
man = json.load(open(os.path.join(ROOT, 'MANIFEST.json'), encoding='utf-8'))
man_files = {e['path']: e['bytes'] for e in man['files']}

# --- structure ---
shared = sorted(set(sums) & set(man_files))
# The two counterpart entries are by-design asymmetries, not defects:
#   MANIFEST.json appears only in SHA256SUMS (MANIFEST excludes itself),
#   SHA256SUMS appears only in MANIFEST.files (SHA256SUMS excludes itself).
sums_only = set(sums) - set(man_files)
man_only = set(man_files) - set(sums)
counterpart_exclusive_ok = sums_only == {'MANIFEST.json'} and man_only == {'SHA256SUMS'}
only_sums = sorted(sums_only - {'MANIFEST.json'})
only_man = sorted(man_only - {'SHA256SUMS'})

# --- content verification ---
hash_mismatch, size_mismatch, missing = [], [], []
for rel in shared:
    p = os.path.join(ROOT, rel)
    if not os.path.isfile(p):
        missing.append(rel)
        continue
    if sha256(p) != sums[rel]:
        hash_mismatch.append(rel)
    if os.path.getsize(p) != man_files[rel]:
        size_mismatch.append(rel)

# --- disk census: no unlisted files anywhere under ROOT ---
disk = []
for r, dirs, fs in os.walk(ROOT):
    dirs.sort()
    for fn in sorted(fs):
        disk.append(os.path.relpath(os.path.join(r, fn), ROOT))
unlisted = sorted(set(disk) - set(sums) - set(man_files))

content_ok = len(shared) - len(hash_mismatch) - len(size_mismatch) - len(missing)
all_pass = (
    not bad_lines and not only_sums and not only_man and not hash_mismatch
    and not size_mismatch and not missing and not unlisted and counterpart_exclusive_ok
    and 'SHA256SUMS' not in sums and 'MANIFEST.json' not in man_files
    and 'MANIFEST.json' in sums and 'SHA256SUMS' in man_files
    and sha256(os.path.join(ROOT, 'MANIFEST.json')) == sums.get('MANIFEST.json')
    and os.path.getsize(os.path.join(ROOT, 'SHA256SUMS')) == man_files.get('SHA256SUMS')
)

out = {
    'checker': 'r2a/check_fingerprints.py (R2A§6 — reproducible, hash-free output)',
    'design': 'each list excludes ITSELF and includes its COUNTERPART',
    'sha256sums_entries': len(sums),
    'sha256sums_malformed_lines': bad_lines,
    'manifest_files_entries': len(man_files),
    'excludes_itself': {'SHA256SUMS_excludes_self': 'SHA256SUMS' not in sums,
                        'MANIFEST_excludes_self': 'MANIFEST.json' not in man_files},
    'counterpart_included': {'SHA256SUMS_includes_MANIFEST': 'MANIFEST.json' in sums,
                             'MANIFEST_includes_SHA256SUMS': 'SHA256SUMS' in man_files},
    'shared_content_files': len(shared),
    'counterpart_exclusive_ok': counterpart_exclusive_ok,
    'counterpart_entries': {'in_SHA256SUMS_only': 'MANIFEST.json', 'in_MANIFEST_only': 'SHA256SUMS'},
    'unexpected_only_in_SHA256SUMS': only_sums,
    'unexpected_only_in_MANIFEST': only_man,
    'content_verification_ok': f'{content_ok}/{len(shared)}',
    'hash_mismatches': hash_mismatch,
    'size_mismatches': size_mismatch,
    'missing_from_disk': missing,
    'manifest_fingerprint_matches_SHA256SUMS_line':
        sha256(os.path.join(ROOT, 'MANIFEST.json')) == sums.get('MANIFEST.json'),
    'sha256sums_size_entry_matches_real_file':
        os.path.getsize(os.path.join(ROOT, 'SHA256SUMS')) == man_files.get('SHA256SUMS'),
    'unlisted_files_on_disk': unlisted,
    'all_checks_pass': all_pass,
}
print(json.dumps(out, ensure_ascii=False, indent=1))
sys.exit(0 if all_pass else 1)
