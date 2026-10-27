#!/usr/bin/env python3
"""AES-AUDIT-001 — footer instrText patch (ROMAN/arabic) + strip empty pgNumType (WPS compat)."""
import re
import shutil
import zipfile
import tempfile
import os

DOCX = "/home/z/my-project/download/AES-AUDIT-001-Comprehensive-Audit-Report.docx"

tmp = tempfile.mkdtemp()
with zipfile.ZipFile(DOCX) as z:
    z.extractall(tmp)

doc_xml_path = os.path.join(tmp, "word", "document.xml")
with open(doc_xml_path, encoding="utf-8") as f:
    doc = f.read()

# 1) map sections -> footer rIds (in order of sectPr appearance)
sect_footers = []  # list of rIds per section (default footers)
for sect in re.finditer(r"<w:sectPr[^>]*>.*?</w:sectPr>", doc, re.S):
    block = sect.group(0)
    rids = re.findall(r'<w:footerReference w:type="default" r:id="(rId\d+)"', block)
    sect_footers.append(rids[0] if rids else None)
print("sections footers rIds:", sect_footers)

rels_path = os.path.join(tmp, "word", "_rels", "document.xml.rels")
with open(rels_path, encoding="utf-8") as f:
    rels = f.read()
rid2file = dict(re.findall(r'Id="(rId\d+)"[^>]*Target="(footer\d+\.xml)"', rels))
print("rid->file:", rid2file)

def patch_footer(fname, fmt):
    p = os.path.join(tmp, "word", fname)
    with open(p, encoding="utf-8") as f:
        x = f.read()
    x2, n = re.subn(
        r"(<w:instrText[^>]*>)([^<]*PAGE[^<]*)(</w:instrText>)",
        lambda m: m.group(1) + f" PAGE \\* {fmt} \\* MERGEFORMAT " + m.group(3),
        x, count=0)
    with open(p, "w", encoding="utf-8") as f:
        f.write(x2)
    print(f"patched {fname} -> {fmt} ({n} instrText)")

# section order: 0=cover(no footer), 1=front matter(ROMAN), 2=body(arabic)
if len(sect_footers) >= 3:
    if sect_footers[1] and sect_footers[1] in rid2file:
        patch_footer(rid2file[sect_footers[1]], "ROMAN")
    if sect_footers[2] and sect_footers[2] in rid2file:
        patch_footer(rid2file[sect_footers[2]], "arabic")

# 2) strip empty pgNumType
doc2, n = re.subn(r"<w:pgNumType/>", "", doc)
with open(doc_xml_path, "w", encoding="utf-8") as f:
    f.write(doc2)
print(f"stripped empty pgNumType: {n}")

# rezip
out = DOCX
new = out + ".new"
with zipfile.ZipFile(new, "w", zipfile.ZIP_DEFLATED) as z:
    for root, _, files in os.walk(tmp):
        for fn in files:
            full = os.path.join(root, fn)
            z.write(full, os.path.relpath(full, tmp))
shutil.move(new, out)
shutil.rmtree(tmp)
print("REPACKED", out, os.path.getsize(out), "bytes")
