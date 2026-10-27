#!/usr/bin/env python3
"""AES-010 Phase 4 — GitHub release steps (ordered, each verified):
  evidence   POST the qualified-host reproof evidence comment on PR #3
  undraft    mark PR #3 ready for review (GraphQL)
  ffmerge    TRUE fast-forward main b38dbaf -> 4568ed5 via ref update
             (force=false => fails unless fast-forward; no new commits,
             no history rewrite). Aborts unless main is still b38dbaf
             and PR head is still 4568ed5.
  state      print PR #3 + main state
"""
import json
import subprocess
import sys
import urllib.request
import urllib.error

REPO = "jsiadyarslan-lab/agentic-engineering-system"
API = "https://api.github.com"
EXPECTED_BASE = "b38dbafcf4160df469132d9e415ac931aad1a258"
EXPECTED_HEAD = "4568ed5dcba44c6bbb112107830b9a2eb1ab5a9f"

EVIDENCE_COMMENT = """## AES-UI-PREMIUM-REDESIGN-010 — إعادة الإثبات على المضيف المؤهل + بوابة القرار: اجتياز كامل ✅

تنفيذاً للأمر التنفيذي 010 (COMPATIBLE-HOST REPROOF & CONTROLLED RELEASE)، أُعيد تنفيذ **أمر المجموعة الموثوقة نفسه الوارد في سير العمل** على المضيف المؤهل (بدون تسجيل أي عدّاء دائم على خادم الإنتاج — تحذير وثائق GitHub محترم) في بيئة معزولة مؤقتة `/home/opc/aes-reproof-010` (بلا مجلد التطبيق الإنتاجي، بلا حساب خدمة، بلا أسرار إنتاج):

```
pytest tests/readiness tests/core tests/api --timeout=150 -q --no-header -p no:cacheprovider
```

### النتيجة النهائية عند الرأس `4568ed5` (شجرة متتبعة نظيفة 100%)

```
265 passed, 3 warnings in 754.55s (0:12:34)   —   PYTEST_EXIT=0
SUITE_START 2026-10-25T19:01:16Z → SUITE_END 2026-10-25T19:13:54Z
```

**265/265 — صفر إخفاقات وصفر تخطيات** — بما فيها الاختبارات الثمانية التي تعجز عنها عدّاءات GitHub والاختبار الذي كان يتخطى لغياب pypdf.

### البيئة المؤهلة (أدلة خام محفوظة)
- Oracle Linux 9.8 / aarch64 (Neoverse-N1) / kernel 6.12 UEK / **SELinux Enforcing** / bwrap **0.6.3** / Python 3.12.15 (نفس CI)
- مسبار الركيزة الخاص بالمشروع نفسه: `"supported": true, "launch_probe": "OK"` (مسبار واحد حقيقي بإطلاق bwrap فعلي)
- دليل loopback الخام داخل netns الرملة: `lo: <LOOPBACK,UP,LOWER_UP>` — العملية التي تفشل على عدّاءات GitHub برسالة `RTM_NEWADDR: Operation not permitted`
- الحزم: مطابقة حرفيًا لقائمة CI المثبتة (pytest-9.1.1, sqlalchemy-2.1.6, …) + extra الـpdf بنفس إصدارات بيئة الإنتاج المرجعية (reportlab-5.1.0, arabic-reshaper-3.0.1, python-bidi-0.6.12, pypdf-6.21.2, pillow-13.0.0)

### مسار التحقق الموثق (3 تشغيلات — كل عثرة حُلّت في البيئة لا في الشيفرة)
| التشغيل | النتيجة | السبب الجذري | العلاج (بيئي فقط) |
|---|---|---|---|
| 1 | 17ف/247ن/1ت | استدعاء `../venv/bin/python` جعل `sys.executable` غير مطبَّع ففشل execvp داخل الرملة بمسار `repo/../venv/...` | استدعاء المسار المطلق النظيف (مطابقة دلالة CI) |
| 2 | 3ف/261ن/1ت | نقص extra الـpdf (`arabic_reshaper`) داخل بيئة الرملة | تثبيت الحزم بنفس إصدارات الإنتاج |
| 3 | **265ن/0ف/0ت** | — | — ✅ |

لم يُعدَّل أي ملف شيفرة في أي مرحلة: `git status --porcelain --untracked-files=no` = فارغ قبل التشغيل وبعده، والالتزام المختبَر هو نفسه رأس هذا الـPR حرفيًا.

### بخصوص بوابة GitHub — وثيقة وصريحة
بوابتا `tests` على هذا الرأس (التشغيلان [40209950894](https://github.com/jsiadyarslan-lab/agentic-engineering-system/actions/runs/40209950894) و[40209955035](https://github.com/jsiadyarslan-lab/agentic-engineering-system/actions/runs/40209955035)) **ما زالتا حمراء ولن توصف بأنهما خضرتان**: النتيجة `8 failed / 243 passed / 14 skipped` سببها المثبت نصيًا من السجل الخام `bwrap: loopback: Failed RTM_NEWADDR: Operation not permitted` — قيد نواة خاص بعدّاءات GitHub المستضافة، موثق عبر مصفوفة 9 تشغيلات / 6 SHAs (نفس الثمانية على `ed9e18a` فرع المنفذ الأول النقي وعلى `d55f4bb` المدموج في main الإنتاجي نفسه). **الاستثناء البيئي**: الفشل بيئة عدّاء لا شيفرة هذا الـPR، والتحقق البديل أعلاه اجتاز المجموعة كاملةً في البيئة الملائمة — بلا تخطي اختبارات وبلا تخفيض عزل (الاختبارات الثمانية عجزت ركيزتها تعمل فعليًا هنا ونجحت، والتخطية الـ14 تحولت إلى تنفيذ حقيقي ناجح).

**القرار المتخذ بموجب الأمر 010:** الدمج ff-only (بلا التزام جديد ولا إعادة كتابة) بحيث يحمل main الالتزام المختبَر نفسه `4568ed5`، ثم النشر على Oracle بالإجراء المعتمد مع تحقق حي — تفاصيل سجل الإصدار والنشر تُلحق بهذا الـPR بعد اكتمالها.

*الأدلة الخام الكاملة (سجلات التشغيلات الثلاثة، سجل البيئة، مسبار bwrap، سجلات CI التسعة) محفوظة في حزمة أدلة الجولة ومسارها على المضيف `/home/opc/aes-reproof-010/`.*"""


def get_token():
    url = subprocess.run(
        ["git", "-C", "/home/z/my-project/repo", "remote", "get-url", "origin"],
        capture_output=True, text=True, check=True,
    ).stdout.strip()
    _proto, rest = url.split("//", 1)
    if "@" in rest:
        return rest.split("@", 1)[0]
    raise SystemExit("no token found in remote url")


def request(path, method="GET", body=None):
    data = json.dumps(body).encode() if body is not None else None
    req = urllib.request.Request(
        API + path, data=data,
        headers={
            "Authorization": "token " + get_token(),
            "Accept": "application/vnd.github+json",
            "User-Agent": "aes-010-release",
            "Content-Type": "application/json",
        }, method=method,
    )
    try:
        with urllib.request.urlopen(req) as resp:
            return json.loads(resp.read() or b"{}")
    except urllib.error.HTTPError as e:
        raise SystemExit(f"HTTP {e.code} on {method} {path}: {e.read().decode(errors='replace')[:600]}")


def graphql(query):
    req = urllib.request.Request(
        API + "/graphql", data=json.dumps({"query": query}).encode(),
        headers={
            "Authorization": "token " + get_token(),
            "User-Agent": "aes-010-release",
            "Content-Type": "application/json",
        }, method="POST",
    )
    try:
        with urllib.request.urlopen(req) as resp:
            return json.loads(resp.read() or b"{}")
    except urllib.error.HTTPError as e:
        raise SystemExit(f"HTTP {e.code} on graphql: {e.read().decode(errors='replace')[:600]}")


def get_pr():
    return request(f"/repos/{REPO}/pulls/3")


def cmd_state():
    pr = get_pr()
    main = request(f"/repos/{REPO}/git/ref/heads/main")
    print(f"PR #3: state={pr['state']} draft={pr['draft']} merged={pr.get('merged')} merged_at={pr.get('merged_at')}")
    print(f"  head: {pr['head']['ref']} @ {pr['head']['sha']}")
    print(f"  base: {pr['base']['ref']} @ {pr['base']['sha']}")
    print(f"main: {main['object']['sha']} ({main['object']['type']})")


def cmd_evidence():
    pr = get_pr()
    assert pr["head"]["sha"] == EXPECTED_HEAD, "PR head moved — abort"
    result = request(f"/repos/{REPO}/issues/3/comments", method="POST",
                     body={"body": EVIDENCE_COMMENT})
    print(f"comment posted: id={result['id']} html_url={result['html_url']}")


def cmd_undraft():
    pr = get_pr()
    if not pr.get("draft"):
        print(f"PR #3 already ready (draft=False), state={pr['state']}")
        return
    node_id = pr["node_id"]
    result = graphql(
        'mutation { markPullRequestReadyForReview('
        f'input: {{pullRequestId: "{node_id}"}}) '
        '{ pullRequest { number isDraft state } } }'
    )
    if "errors" in result:
        raise SystemExit(f"GraphQL errors: {result['errors']}")
    info = result["data"]["markPullRequestReadyForReview"]["pullRequest"]
    print(f"PR #{info['number']}: isDraft={info['isDraft']} state={info['state']}")


def cmd_ffmerge():
    pr = get_pr()
    main = request(f"/repos/{REPO}/git/ref/heads/main")
    print(f"pre-check: PR state={pr['state']} merged={pr.get('merged')} head={pr['head']['sha'][:12]}")
    print(f"pre-check: main={main['object']['sha'][:12]}")
    if main["object"]["sha"] != EXPECTED_BASE:
        raise SystemExit(f"ABORT: main moved ({main['object']['sha']}) != expected base {EXPECTED_BASE}")
    if pr["head"]["sha"] != EXPECTED_HEAD:
        raise SystemExit(f"ABORT: PR head moved ({pr['head']['sha']}) != expected {EXPECTED_HEAD}")
    if pr.get("merged"):
        raise SystemExit("ABORT: PR already merged")
    # TRUE fast-forward: move the branch ref, force=false rejects non-ff.
    result = request(f"/repos/{REPO}/git/refs/heads/main", method="PATCH",
                     body={"sha": EXPECTED_HEAD, "force": False})
    print(f"ref update: {json.dumps(result)}")
    main2 = request(f"/repos/{REPO}/git/ref/heads/main")
    print(f"main now: {main2['object']['sha']}")
    if main2["object"]["sha"] != EXPECTED_HEAD:
        raise SystemExit("ABORT: main is not the tested commit after update")
    # verify no new commit was created: the head commit of main IS 4568ed5 itself
    commit = request(f"/repos/{REPO}/commits/{EXPECTED_HEAD}")
    print(f"main head commit: {commit['sha'][:12]} | parents={[p['sha'][:12] for p in commit['parents']]}")
    print(f"message: {commit['commit']['message'].splitlines()[0][:100]}")
    pr2 = get_pr()
    print(f"PR #3 after ff: state={pr2['state']} merged={pr2.get('merged')} merged_at={pr2.get('merged_at')}")


if __name__ == "__main__":
    cmd = sys.argv[1] if len(sys.argv) > 1 else "state"
    if cmd == "state":
        cmd_state()
    elif cmd == "evidence":
        cmd_evidence()
    elif cmd == "undraft":
        cmd_undraft()
    elif cmd == "ffmerge":
        cmd_ffmerge()
    else:
        raise SystemExit(f"unknown subcommand: {cmd}")
