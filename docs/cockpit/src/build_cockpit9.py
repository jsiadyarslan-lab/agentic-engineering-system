#!/usr/bin/env python3
"""بناء قمرة AES V9 — التصميم المقبول مطبق على المشروع الحقيقي.
تمريرتان صادقتان: بناء على الأصول ثم قياس الحجم الفعلي للناتج وحقنه في بطاقته الذاتية وإعادة البناء.
اللقطة موسعة: كل جلسة ببياناتها (P4 بثها · P3 سجلها · P1/P2 سلاسل بواباتها) — لا بث مستعار."""
import json, re, pathlib, hashlib, time

ROOT = pathlib.Path('/home/z/my-project')
SRC = ROOT / 'scripts/cockpit9_src'
DARK = ROOT / 'scripts/factory_dark_src'
OUT = ROOT / 'download/AES-COCKPIT-V9.html'
V81 = ROOT / 'download/AES-COCKPIT-V8.1.html'
MONO = ROOT / 'download/AES-FACTORY-MONO.html'


def _lum(hex6):
    r, g, b = int(hex6[1:3], 16), int(hex6[3:5], 16), int(hex6[5:7], 16)
    y = round(0.2126 * r + 0.7152 * g + 0.0722 * b)
    return f'#{y:02X}{y:02X}{y:02X}'


def mono_sanitize(css_text):
    """القانون: أي hex غير رمادي يُحوَّل إلى رمادي الإضاءة المكافئ — وكل rgba غير رمادية كذلك."""
    def hx(m):
        s = m.group(0)
        if len(s) == 7:
            return s if s[1:3] == s[3:5] == s[5:7] else _lum(s)
        if len(s) == 4:
            return s if s[1] == s[2] == s[3] else _lum('#' + ''.join(c * 2 for c in s[1:]))
        return s
    t = re.sub(r'#[0-9a-fA-F]{6}\b|#[0-9a-fA-F]{3}\b', hx, css_text)
    def rg(m):
        r, g, b, a = m.group(1), m.group(2), m.group(3), m.group(4)
        if r == g == b:
            return m.group(0)
        y = round(0.2126 * int(r) + 0.7152 * int(g) + 0.0722 * int(b))
        return f'rgba({y},{y},{y},{a})'
    t = re.sub(r'rgba\(\s*(\d+)\s*,\s*(\d+)\s*,\s*(\d+)\s*,\s*([\d.]+)\s*\)', rg, t)
    return t


def load_snap():
    html = V81.read_text(encoding='utf-8')
    m = re.search(r'window\.__DATA__\s*=\s*(\{.*?\});?\s*</script>', html, re.S)
    assert m, 'no __DATA__ in V8.1'
    full = json.loads(m.group(1))

    def p3agg(ch):
        return {
            'kinds': ch['kinds'], 'gates_total': ch['gates_total'],
            'cycles_n': len(ch['cycles']), 'progress': ch['progress'],
            'verified_at': ch['verified_at'],
            'plan_versions': ch['plan_versions'], 'current_plan_id': ch['current_plan_id'],
        }

    return {
        'meta': full['meta'],
        'projects': full['projects'],
        'p4': {
            'feed': full['p4']['feed'], 'stats': full['p4']['stats'],
            'bookmarks': full['p4']['bookmarks'], 'gate315': full['p4']['gate315'],
            'step1047': full['p4']['step1047'],
        },
        'p3feed': full['p3']['feed'],
        'p3stats': full['p3']['stats'],
        'diff_p4': full['diff_p4'],
        'evidence': {'p4': full['evidence']['p4']},
        'artifacts': {'p4': full['artifacts']['p4'], 'p3': {
            'total': full['artifacts']['p3']['total'],
            'total_bytes': full['artifacts']['p3']['total_bytes'],
        }},
        'plans_cur': full['plans_cur'],
        'chains': {
            'p3': p3agg(full['chains']['p3']),
            'p1': full['chains']['p1'],
            'p2': full['chains']['p2'],
        },
        'noise': {k: {'state': v['state'], 'last_recovery': v['last_recovery']} for k, v in full['noise'].items()},
    }


def build(snap, assets, self_size=0):
    a = json.loads(json.dumps(assets))  # نسخة عمل
    a['files']['v9']['size'] = self_size
    assetsjson = json.dumps(a, ensure_ascii=False, separators=(',', ':')).replace('</', '<\\/')
    snapjson = json.dumps(snap, ensure_ascii=False, separators=(',', ':')).replace('</', '<\\/')

    tpl = (SRC / 'template.html').read_text(encoding='utf-8')
    css = (DARK / 'style.css').read_text(encoding='utf-8')
    agent_css = (SRC / 'design_agent.css').read_text(encoding='utf-8')
    glue = (SRC / 'glue.css').read_text(encoding='utf-8')
    fonts = (DARK / 'fonts_embed.css').read_text(encoding='utf-8')
    js = (SRC / 'app.js').read_text(encoding='utf-8')

    shell = (tpl
             .replace('/*__FONTS__*/', fonts)
             .replace('/*__CSS__*/', mono_sanitize(css))
             .replace('/*__AGENT_CSS__*/', agent_css + '\n' + glue)
             .replace('/*__JS__*/', js))
    for tok in ('/*__FONTS__*/', '/*__CSS__*/', '/*__AGENT_CSS__*/', '/*__JS__*/'):
        assert tok not in shell, f'shell token left: {tok}'
    out = shell.replace('"__SNAP__"', snapjson).replace('"__ASSETS__"', assetsjson)
    for tok in ('"__SNAP__"', '"__ASSETS__"'):
        assert tok not in out, f'data token left: {tok}'
    return out


def main():
    snap = load_snap()
    assets = json.loads((SRC / 'assets.json').read_text(encoding='utf-8'))

    # الملف السابق الأحادي: حجمه وبصمته الحقيقيان من القرص، ووضعه «ext» (لا نسخة داخله)
    if 'mono' in assets['files']:
        assets['files']['mono']['size'] = MONO.stat().st_size
        assets['files']['mono']['sha16'] = hashlib.sha256(MONO.read_bytes()).hexdigest()[:16]
        assets['files']['mono']['mode'] = 'ext'
        assets['files']['mono']['mtime'] = time.strftime('%Y-%m-%d %H:%M', time.localtime(MONO.stat().st_mtime))

    # الملف الذاتي V9 — يُضاف إلى مجموعة المصنع
    if 'v9' not in assets['files']:
        assets['files']['v9'] = {
            'id': 'v9', 'g': 'factory', 'name': 'AES-COCKPIT-V9.html', 'kind': 'html',
            'size': 0, 'sha16': '', 'mtime': time.strftime('%Y-%m-%d %H:%M'),
            'path': 'download/AES-COCKPIT-V9.html', 'mode': 'self',
        }
        order = assets['order']['factory']
        assets['order']['factory'] = ['mono', 'v9'] + [x for x in order if x not in ('mono', 'v9')]

    S = 0
    p = None
    for i in range(6):
        p = build(snap, assets, self_size=S)
        OUT.write_text(p, encoding='utf-8')
        actual = OUT.stat().st_size
        print(f'pass {i+1}: injected={S} actual={actual}')
        if actual == S:
            break
        S = actual
    final_sha = hashlib.sha256(OUT.read_bytes()).hexdigest()[:16]
    print(f'OK -> {OUT}  ({OUT.stat().st_size/1024:.1f} KB) · sha16(القرص)={final_sha}')
    print('البصمة داخل الملف لا تُطبع عمداً (تناقض مرجعي ذاتي) — تُحسب من القرص')
    m = re.search(r'window\.__DATA__ = (\{.*?\});</script>', p, re.S)
    d = json.loads(m.group(1))
    print('sha16 snap:', d['meta']['data_sha256_16'], '| p3feed:', len(d['p3feed']),
          '| chains p1/p2:', len(d['chains']['p1']), '/', len(d['chains']['p2']),
          '| ملفات الأصول:', len(json.loads(re.search(r"window\.__ASSETS__ = (\{.*?\});</script>", p, re.S).group(1))['files']))


if __name__ == '__main__':
    main()
