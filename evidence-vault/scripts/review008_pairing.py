import os
base = '/home/z/my-project/ui007/docs/evidence/UI007_evidence'
baseline = set(os.listdir(f'{base}/baseline'))
after = set(os.listdir(f'{base}/after'))
shots = set(os.listdir(f'{base}/reproof-008/shots'))
def primary(n): return n[4:] if n.startswith('pop ') else n
bp = {primary(n) for n in baseline}
ap = {primary(n) for n in after}
print(f"baseline files: {len(baseline)}  unique primary names: {len(bp)}")
print(f"after files: {len(after)}  unique primary names: {len(ap)}")
print(f"shots: {len(shots)} -> {sorted(shots)}")
matched = ap & bp
new_after = ap - bp
missing_after = bp - ap
print(f"\nafter with baseline counterpart: {len(matched)}")
print(f"after NEW (no baseline counterpart): {sorted(new_after)}")
print(f"baseline primary names WITHOUT after counterpart: {sorted(missing_after)}")
# pop coverage: do all 8 pop-named baselines have a primary-name after?
pops = [n for n in baseline if n.startswith('pop ')]
print(f"\npop-prefixed baselines: {len(pops)}")
for p in sorted(pops):
    prim = primary(p)
    print(f"  {p!r} -> after counterpart exists: {prim in ap}")
