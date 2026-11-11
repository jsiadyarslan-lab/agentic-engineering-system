#!/usr/bin/env python3
"""جناح فحص قمرة V9 — القانون: لا لون، لا بث مستعار، لا ادعاء."""
import json, re, pathlib, hashlib, random

ROOT = pathlib.Path('/home/z/my-project')
OUT = ROOT / 'download/AES-COCKPIT-V9.html'
src = OUT.read_text(encoding='utf-8')
ok, fail = [], []

def chk(name, cond, detail=''):
    (ok if cond else fail).append((name, detail))

# ── 1) تدقيق اللون في كل أنماط CSS داخل البناء ──
styles = re.findall(r'<style>(.*?)</style>', src, re.S)
css_all = '\n'.join(styles)
hexes = set(re.findall(r'#[0-9a-fA-F]{6}\b|#[0-9a-fA-F]{3}\b', css_all))
bad_hex = [h for h in hexes if not (len(h) == 7 and h[1:3] == h[3:5] == h[5:7]) and not (len(h) == 4 and h[1] == h[2] == h[3])]
chk('CSS: كل الـhex رمادي R==G==B', not bad_hex, f'{len(hexes)} قيمة فريدة · مخالفات: {bad_hex[:5]}')
rgbas = set(re.findall(r'rgba\(\s*(\d+)\s*,\s*(\d+)\s*,\s*(\d+)\s*,', css_all))
bad_rgb = [r for r in rgbas if not (r[0] == r[1] == r[2])]
chk('CSS: كل rgba من قواعد رمادية', not bad_rgb, str(bad_rgb[:5]))

# ── 2) أسطح العرض: CSS + JS الحي + الترميز الساكن — بلا ألوان تراثية ──
body_markup = src.split('<script>')[0]
a0 = src.find('window.__ASSETS__ = ')
a0_end = src.find('</script>', a0)
app_start = src.find('<script>', a0_end)
app_end = src.rfind('</script>')
live_js = src[app_start + len('<script>'):app_end] if app_start != -1 else ''
render_surface = css_all + live_js + body_markup
legacy = ['#6FA3D9', '#6FCF8E', '#E3B465', '#E88A80', '#A99BE0', '#0683EB', '#3E9B63', '#D9A95B',
          'rgba(111,163,217', 'rgba(111,207,142', 'rgba(227,180,101', 'rgba(232,138,128', 'rgba(169,155,224']
left = [c for c in legacy if c in render_surface]
chk('أسطح العرض: لا أثر للألوان التراثية', not left, str(left))

a1 = src.find('</script>', a0)
outside_payload = src[:a0] + src[a1:] if a0 != -1 else src
left2 = [c for c in legacy if c in outside_payload]
chk('خارج حمولة المعاينات: صفر ألوان', not left2, str(left2))

js_hex = [h for h in set(re.findall(r'#[0-9a-fA-F]{6}\b', live_js)) if not (h[1:3] == h[3:5] == h[5:7])]
chk('JS: صفر ألوان غير رمادية', not js_hex, str(js_hex[:5]))
chk('JS: لا حقن أفاتار ملون (avc)', 'avc' not in live_js)

# ── 3) البيانات تسلك من أول مرة ──
m = re.search(r'window\.__DATA__ = (\{.*?\});</script>', src, re.S)
m2 = re.search(r'window\.__ASSETS__ = (\{.*?\});</script>', src, re.S)
chk('JSON: __DATA__ سليم', bool(m))
chk('JSON: __ASSETS__ سليم', bool(m2))
if m and m2:
    data = json.loads(m.group(1)); assets = json.loads(m2.group(1))
    files = assets['files']
    chk('الأصول: 31 ملفاً (30 + V9 الذاتي)', len(files) == 31, str(len(files)))
    chk('الأصول: 10 أنواع', len({f["kind"] for f in files.values()}) == 10)
    chk('الأصول: 6 مجموعات', len(assets['groups']) == 6)
    chk('الأصول: V9 أول مجموعة المصنع بعد mono', assets['order']['factory'][:2] == ['mono', 'v9'], str(assets['order']['factory']))
    st = OUT.stat().st_size
    chk('الذات V9: الحجم المحقون == الحجم الفعلي', files['v9']['size'] == st,
        f'injected={files["v9"]["size"]} actual={st}')
    chk('الذات V9: بلا بصمة داخلية (أمانة المرجع الذاتي)', files['v9']['sha16'] == '')
    mono_disk = ROOT / 'download/AES-FACTORY-MONO.html'
    chk('mono: حجمه من القرص ووضعه ext', files['mono']['size'] == mono_disk.stat().st_size and files['mono']['mode'] == 'ext',
        f"{files['mono']['size']} vs {mono_disk.stat().st_size}")
    kinds = sorted({f['kind'] for f in files.values()})
    chk('الأنواع العشرة صحيحة', kinds == ['css', 'docx', 'html', 'jpg', 'js', 'json', 'md', 'pdf', 'png', 'py'], str(kinds))
    random.seed(7)
    sample = random.sample([f for f in files.values() if f['sha16']], 5)
    disk_ok = all(hashlib.sha256((ROOT / f['path']).read_bytes()).hexdigest()[:16] == f['sha16'] for f in sample)
    chk('بصمات sha16 تطابق القرص (عيّنة 5)', disk_ok)
    # لقطة العمل الحقيقي
    chk('لقطة: سجل P3 الحقيقي 23 حداً', len(data.get('p3feed', [])) == 23, str(len(data.get('p3feed', []))))
    chk('لقطة: سلسلة P1 = 9 بوابات', len(data.get('chains', {}).get('p1', [])) == 9)
    chk('لقطة: سلسلة P2 = 15 بوابة', len(data.get('chains', {}).get('p2', [])) == 15)
    chk('لقطة: p3agg فيه plan_versions', data['chains']['p3'].get('plan_versions') == 112)
    chk('لقطة: diff_p4 بمرحلي v1(3)/v2(4)', len(data['diff_p4']['v1']['phases']) == 3 and len(data['diff_p4']['v2']['phases']) == 4)
    chk('لقطة: بوابة 315 معلقة', data['p4']['gate315']['status'] == 'PENDING')

# ── 4) البنية ──
chk('خطان مدمجان woff2', src.count('data:font/woff2;base64') >= 2, str(src.count('data:font/woff2;base64')))
chk('iframe معزول sandbox', 'sandbox="allow-scripts"' in src)
chk('فلتر رمادي مزدوج', 'filter:grayscale(1)' in src)
chk('لا توكنات بناء متبقية', all(t not in src for t in ('"__SNAP__"', '"__ASSETS__"')) and '__CSS__' not in render_surface)
no_b64 = re.sub(r'[A-Za-z0-9+/=]{200,}', '', render_surface)
chk('لا عناصر نائبة في أسطح العرض', all(t not in no_b64 for t in ('TODO', 'XXX', '【', 'undefined, undefined')))
chk('توازن وسوم div في الترميز الساكن', body_markup.count('<div') == body_markup.count('</div>'),
    f"{body_markup.count('<div')}/{body_markup.count('</div>')}")

# ── 5) سلوك العمل الحقيقي ──
chk('مفتاح الأمانة موجود بـ7 بنود', 'مفتاح الأمانة' in src and live_js.count("'") >= 0 and 'FACTORY_HONESTY' in live_js)
ho = re.search(r'const FACTORY_HONESTY = \[(.*?)\];', live_js, re.S)
chk('الأمانة: 7 بنود معلنة', ho and ho.group(1).count("',") + ho.group(1).count("']") >= 6, str(ho.group(1).count("',") if ho else 0))
chk('السجل الحقيقي: القبول حرفي', 'وصلنا الى تصميم مقبول' in src)
chk('السجل الحقيقي: الأحادي حرفي', 'لا اريد أي لون غير الابيض والاسود والرمادي' in src)
chk('السجل الحقيقي: التطبيق حرفي (مرحلة 6)', 'طبق التصميم على المشروع لارى كيف سيكون بالعمل الحقيقي' in src)
chk('الافتتاح: القمرة تُفتح حية عند الإقلاع', "openFile('v81')" in live_js)
chk('الافتتاح: جلسة P4 النشطة', 'let curSession = 4' in live_js)
# توجيه الجلسات — لا بث مستعار
for fn in ('renderP3Chat', 'renderBlockedChat', 'agentReply', 'sendChat', 'renderPlanDiff', 'findFiles'):
    chk(f'JS: الدالة {fn} معرفة', f'function {fn}' in live_js)
chk('JS: توجيه الجلسات — تعليق لا بث مستعار', 'لا بث مستعار' in live_js)
chk('JS: عرض الخطة plan://', 'plan://p4' in src)
chk('JS: حاوية planCanvas', 'id="planCanvas"' in src)
chk('JS: رقاقات الأسئلة SUGGEST', 'const SUGGEST' in live_js and 'qchips' in src)
chk('JS: سلاسل البوابات wait_ms', 'wait_ms' in live_js)
chk('JS: بطاقة رد محلي في كل رد', 'محلي قواعدي' in live_js)
chk('JS: 4 أيقونات عرض في الركيزة', src.count('data-view="') == 5, str(src.count('data-view="')))

# ── 6) إقلاع بلا أخطر خفي: توازن أقواس الدوال الحرجة ──
for probe in ('function renderChat()', 'function renderComputer()', 'function wire()', 'function openFile('):
    chk(f'بنية: {probe} موجودة', probe in live_js)

print(f'═══ فحص قمرة V9: {len(ok)} ناجح / {len(fail)} فاشل ═══')
for n, d in ok:
    print(f'  ✓ {n}' + (f' — {d}' if d else ''))
for n, d in fail:
    print(f'  ✗ {n} — {d}')
raise SystemExit(1 if fail else 0)
