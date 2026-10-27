from PIL import Image
import os
base = '/home/z/my-project/ui007/docs/evidence/UI007_evidence'
pairs = ['welcome-1440','chat-long-ar-1440','factory-1440','settings-general-1440',
         'mobile-chat-390','tablet-chat-768','chat-error-no-provider-1440','project-evidence-1440',
         'chat-1920','runs-1440']
print(f"{'pair':32s} {'base size':12s} {'after size':12s} {'w-match':8s} {'MAD-gray':9s} {'%diff>10':9s} {'base_mean':9s} {'after_mean'}")
for name in pairs:
    bp, ap = f'{base}/baseline/{name}.png', f'{base}/after/{name}.png'
    ib, ia = Image.open(bp), Image.open(ap)
    ib.load(); ia.load()
    wb, hb = ib.size; wa, ha = ia.size
    # expected width from name
    exp = 1440
    if '390' in name: exp = 390
    elif '360' in name: exp = 360
    elif '768' in name: exp = 768
    elif '1920' in name: exp = 1920
    elif '1280' in name: exp = 1280
    # downscale to common size for comparison
    W, H = 360, 400
    gb = ib.convert('L').resize((W, H))
    ga = ia.convert('L').resize((W, H))
    pb, pa = gb.load(), ga.load()
    mad = sum(abs(pb[x,y]-pa[x,y]) for x in range(W) for y in range(H)) / (W*H)
    diff10 = sum(1 for x in range(W) for y in range(H) if abs(pb[x,y]-pa[x,y])>10) / (W*H) * 100
    mb = sum(pb[x,y] for x in range(W) for y in range(H)) / (W*H)
    ma = sum(pa[x,y] for x in range(W) for y in range(H)) / (W*H)
    wmatch = 'OK' if wb == exp and wa == exp else f'MISMATCH exp={exp}'
    print(f"{name:32s} {wb}x{hb:<7d} {wa}x{ha:<7d} {wmatch:8s} {mad:9.2f} {diff10:8.1f}% {mb:9.1f} {ma:9.1f}")
# also: the full-page pair and reproof chat-1440 vs baseline chat-1440
print()
for label, bp, ap in [
    ('pop chat-long-ar-1440-full vs "after chat-long-ar-1440-full"', f'{base}/baseline/pop chat-long-ar-1440-full.png', f'{base}/after/after chat-long-ar-1440-full.png'),
    ('baseline chat-1440 vs reproof-008/shots/chat-1440', f'{base}/baseline/chat-1440.png', f'{base}/reproof-008/shots/chat-1440.png'),
]:
    ib, ia = Image.open(bp), Image.open(ap); ib.load(); ia.load()
    print(f"{label}")
    print(f"   base={ib.size} after={ia.size} modes={ib.mode}/{ia.mode}")
    W, H = 360, 400
    gb = ib.convert('L').resize((W,H)); ga = ia.convert('L').resize((W,H))
    pb, pa = gb.load(), ga.load()
    mad = sum(abs(pb[x,y]-pa[x,y]) for x in range(W) for y in range(H))/(W*H)
    diff10 = sum(1 for x in range(W) for y in range(H) if abs(pb[x,y]-pa[x,y])>10)/(W*H)*100
    print(f"   MAD-gray={mad:.2f}  %diff>10={diff10:.1f}%")
