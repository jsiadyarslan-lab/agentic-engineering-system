#!/usr/bin/env python3
"""القبول الحي بالمتصفح (الأمر 010 §34) — Playwright فعلي بلا تجميل.

يثبت بالمتصفح الحقيقي: هوية المحادثة (رسائل → محادثة واحدة)،
التخطيط والاتجاهات (RTL/LTR)، المشروع (نقرة/تحديث — لا صفحة سوداء)،
الإعدادات بتبويباتها، بيئات التنفيذ، مصفوفة الجاهزية، حدود الأخطاء.
اللقطات إلى download/order010-screenshots/.
"""

from __future__ import annotations

import json
import sys
import time
import urllib.request
from pathlib import Path

from playwright.sync_api import sync_playwright

BASE = "http://127.0.0.1:8010"
SHOTS = Path("/home/z/my-project/download/order010-screenshots")
SHOTS.mkdir(parents=True, exist_ok=True)

PASS: list[str] = []
FAIL: list[str] = []


def check(name: str, ok: bool, note: str = ""):
    mark = "PASS" if ok else "FAIL"
    print(f"[{mark}] {name}" + (f" — {note}" if note else ""))
    (PASS if ok else FAIL).append(name)


def shot(page, name: str):
    page.screenshot(path=str(SHOTS / f"{name}.png"), full_page=False)
    print(f"    📸 {name}.png")


def get_json(path: str):
    with urllib.request.urlopen(BASE + path, timeout=30) as r:
        return json.loads(r.read().decode())


def main() -> int:
    with sync_playwright() as p:
        browser = p.chromium.launch()
        page = browser.new_page(viewport={"width": 1440, "height": 900})
        page.goto(BASE, wait_until="domcontentloaded")

        # ================= 1) هوية المحادثة (§1) =================
        # المزود الحي قد يكون محدود المعدر (429) — السلوك الصادق:
        # كل رسالة تنتظر تبريد الموجّه ثم تُختم ببطاقة خطأ مفهومة.
        # الهوية تُثبت بالربط أول حدث + نفس المحادثة في الرسالة الثانية.
        # (إثبات الأربع رسائل الكامل موجود حيًا عبر HTTP في محادثة 11.)
        print("\n== 1) هوية المحادثة: رسائل متتالية → محادثة واحدة ==")

        def send_and_wait(message, timeout_s=360):
            page.fill("#input", message)
            page.keyboard.press("Enter")
            deadline = time.time() + timeout_s
            while time.time() < deadline:
                page.wait_for_timeout(2000)
                state = page.evaluate(
                    "({busy: window.Hub.state.busy, "
                    "convId: window.Hub.state.conversationId, "
                    "errCards: document.querySelectorAll('.human-error').length, "
                    "liveDone: !document.querySelector('.live-msg.streaming')})")
                if not state["busy"]:
                    return state
            return page.evaluate("window.Hub.state")

        state1 = send_and_wait("مرحبا — رسالة أولى لاختبار الهوية")
        conv_id_1 = state1["convId"]
        check("الرسالة 1: ربط الهوية فور الإرسال", conv_id_1 is not None,
              f"conv {conv_id_1}")
        state2 = send_and_wait("رسالة ثانية في نفس المحادثة")
        check("الرسالة 2: نفس المحادثة (لا محادثة جديدة)",
              state2["convId"] == conv_id_1,
              f"{conv_id_1} → {state2['convId']}")
        conv_items = page.locator(".conv-item").count()
        hash_now = page.evaluate("location.hash")
        check("توجيه دائم #/chat/{id}", hash_now == f"#/chat/{conv_id_1}",
              hash_now)
        convs = get_json("/api/conversations")["conversations"]
        target = [c for c in convs if c["conversation_id"] == int(conv_id_1)]
        check("المحادثة في القائمة مرة واحدة", len(target) == 1)
        msgs = get_json(
            f"/api/conversations/{conv_id_1}/messages")["messages"]
        user_count = sum(1 for m in msgs if m["role"] == "user")
        check("الرسالتان داخل المحادثة نفسها", user_count == 2,
              f"{user_count}/2")
        shot(page, "01-conversation-identity")

        # ================= 2) الاتجاهات RTL/LTR (§4) =================
        print("\n== 2) الاتجاهات: عربي RTL / إنجليزي وكود LTR ==")
        dir_checks = page.evaluate("""
        () => {
          const out = {};
          // فقاعة مستخدم عربية → dir=auto يحوّلها RTL
          const userBodies = [...document.querySelectorAll('.bubble.user .bubble-body')];
          out.userDirAuto = userBodies.length > 0 &&
            userBodies.every(b => b.dir === 'auto');
          // العارض الحقيقي: كود وروابط وجداول ltr قسري
          const md = window.MD.render(
            '### عنوان عربي\\n\\nنص عربي مع `code_here` ورابط https://example.com/path\\n\\n' +
            '```python\\nprint("hello")\\n```\\n\\n' +
            '| col_a | col_b |\\n|---|---|\\n| 1 | 2 |\\n\\n> اقتباس عربي'
          );
          const holder = document.createElement('div');
          holder.innerHTML = md;
          document.body.appendChild(holder);
          out.codeLtr = holder.querySelector('.md-pre')?.dir === 'ltr';
          out.inlineCodeLtr = holder.querySelector('.md-code')?.dir === 'ltr';
          out.linkLtr = holder.querySelector('a')?.dir === 'ltr';
          out.tableLtr = holder.querySelector('.md-table-wrap')?.dir === 'ltr';
          out.hasTable = !!holder.querySelector('.md-table');
          out.hasBlockquote = !!holder.querySelector('.md-quote');
          out.hasH3 = !!holder.querySelector('h3');
          holder.remove();
          return out;
        }
        """)
        for key, label in [
            ("userDirAuto", "فقاعات المستخدم dir=auto"),
            ("codeLtr", "كتل الكود LTR"),
            ("inlineCodeLtr", "الكود المضمّن LTR"),
            ("linkLtr", "الروابط LTR"),
            ("tableLtr", "الجداول LTR"),
            ("hasTable", "الجداول مدعومة"),
            ("hasBlockquote", "الاقتباسات مدعومة"),
        ]:
            check(f"RTL/LTR: {label}", bool(dir_checks.get(key)))

        # ================= 3) التخطيط (§3) =================
        print("\n== 3) التخطيط: التدفق بعرض مريح لا ضغط ==")
        layout = page.evaluate("""
        () => {
          const msgs = document.getElementById('messages');
          const style = getComputedStyle(msgs);
          const rect = msgs.getBoundingClientRect();
          const chatScroll = document.getElementById('chat-scroll')
            .getBoundingClientRect();
          return {
            maxWidth: style.maxWidth,
            usesMostWidth: rect.width >= Math.min(chatScroll.width * 0.85, 900),
            centered: Math.abs((rect.left + rect.right)/2 -
              (chatScroll.left + chatScroll.right)/2) < 40,
          };
        }
        """)
        check("التدفق يستعمل المساحة (≥85%)",
              bool(layout["usesMostWidth"]), f"max-width={layout['maxWidth']}")
        check("التدفق متمركز", bool(layout["centered"]))
        shot(page, "02-message-stream-layout")

        # ================= 4) المشروع: نقرة + تحديث (§14) =================
        print("\n== 4) المشروع: النقرة والتحديث يحمّلانه — لا صفحة سوداء ==")
        # أنشئ مشروعًا عبر API الحقيقي
        req = urllib.request.Request(
            BASE + "/api/projects",
            data=json.dumps({
                "name": "منصة تحليل البيانات",
                "objective": "تحليل بيانات مفتوحة وإنتاج تقرير أسبوعي موثق",
            }, ensure_ascii=False).encode(),
            headers={"Content-Type": "application/json"}, method="POST")
        with urllib.request.urlopen(req, timeout=30) as r:
            project = json.loads(r.read().decode())
        page.reload(wait_until="domcontentloaded")
        page.wait_for_timeout(800)
        item = page.locator(f'.pj-item[data-id="{project["id"]}"]')
        check("المشروع في الشريط الجانبي", item.count() == 1)
        item.click()
        page.wait_for_timeout(1500)
        visible = page.evaluate(
            "document.getElementById('project-view').hidden === false && "
            "!!document.querySelector('.pj-head')")
        check("النقرة تفتح المشروع (لا صفحة سوداء)", visible)
        hash_project = page.evaluate("location.hash")
        check("توجيه المشروع #/project/{id}",
              hash_project == f"#/project/{project['id']}", hash_project)
        draft = page.locator(".pj-draft-card").count()
        check("المسودة تعرض بطاقة الهدف والإجراء (لا فراغ)", draft == 1)
        shot(page, "03-project-draft-loads")
        # التحديث يعيد فتح نفس المشروع
        page.reload(wait_until="domcontentloaded")
        page.wait_for_timeout(1500)
        still = page.evaluate(
            "document.getElementById('project-view').hidden === false && "
            "!!document.querySelector('.pj-head')")
        check("بعد التحديث: المشروع يُحمّل من التوجيه", still)
        shot(page, "04-project-after-refresh")
        # عودة ثم رجوع
        page.go_back()
        page.wait_for_timeout(800)
        page.go_forward()
        page.wait_for_timeout(1200)
        back_again = page.evaluate(
            "document.getElementById('project-view').hidden === false")
        check("رجوع/تقدم المتصفح يعيدان المشروع", back_again)

        # ================= 5) الإعدادات بتبويباتها (§8-§10) =================
        print("\n== 5) الإعدادات: ستة أقسام منظمة ==")
        page.keyboard.press("Escape")
        page.click("#settings-open")
        page.wait_for_timeout(700)
        tabs = page.locator(".settings-tab").count()
        check("ستة تبويبات", tabs == 6, f"{tabs}")
        # عام
        gen_rows = page.locator("#tab-general .gen-row").count()
        check("تبويب عام: حالة النظام والبيئة الفعالة", gen_rows >= 3,
              f"{gen_rows} صفوف")
        shot(page, "05-settings-general")
        # المزودون
        page.click('.settings-tab[data-tab="providers"]')
        page.wait_for_timeout(600)
        check("تبويب المزودين يعرض الكيانات",
              page.locator("#providers-body").count() == 1)
        shot(page, "06-settings-providers")
        # الأدوات والقدرات
        page.click('.settings-tab[data-tab="tools"]')
        page.wait_for_timeout(900)
        caps = page.locator(".cap-card").count()
        check("مصفوفة القدرات معروضة", caps >= 15, f"{caps} قدرة")
        research = page.locator(".rp-card").count()
        check("مزودو البحث معروضون", research == 3, f"{research}")
        shot(page, "07-settings-tools-capabilities")

        # ================= 6) بيئات التنفيذ (§28) =================
        print("\n== 6) بيئات التنفيذ: عرض وتحقق حقيقي ==")
        page.click('.settings-tab[data-tab="execution"]')
        page.wait_for_timeout(1000)
        env_cards = page.locator(".env-card").count()
        check("بطاقتا البيئتين (محلية + عامل)", env_cards >= 2,
              f"{env_cards}")
        ready_badges = page.locator(".env-badge.ok").count()
        check("بيئة جاهزة بشارة READY", ready_badges >= 1,
              f"{ready_badges}")
        # زر التحقق الحقيقي على البيئة المحلية
        first_verify = page.locator(".env-verify").first
        first_verify.click()
        page.wait_for_timeout(12000)
        verify_heads = page.locator(".env-verify-head.ok").count()
        check("التحقق الحقيقي يجتاز (إقلاع/تنفيذ/التقاط)",
              verify_heads >= 1)
        shot(page, "08-execution-environments")
        # التنفيذ الاختباري
        test_btn = page.locator(".env-test").first
        test_btn.click()
        page.wait_for_timeout(5000)
        exec_out = page.evaluate(
            "document.querySelectorAll('.env-result pre').length")
        check("تنفيذ اختباري بمخرجات فعلية", exec_out >= 1)
        shot(page, "09-env-test-run")

        # ================= 7) حدود الأخطاء (§32) =================
        print("\n== 7) حدود الأخطاء: مساحة العمل تبقى صالحة ==")
        page.evaluate("setTimeout(() => { throw new Error('اختبار حدود الأخطاء'); }, 0)")
        page.wait_for_timeout(1200)
        boundary_visible = page.evaluate(
            "document.getElementById('error-boundary').hidden === false")
        check("شريط الخطأ يظهر", boundary_visible)
        has_rid = page.evaluate(
            "document.querySelector('.eb-rid')?.textContent.includes('Request ID')")
        check("معرف الطلب ظاهر", bool(has_rid))
        workspace_ok = page.evaluate(
            "!!document.getElementById('input') && !document.getElementById('input').disabled")
        check("مساحة العمل صالحة رغم الخطأ", workspace_ok)
        shot(page, "10-error-boundary")

        browser.close()

    # ================= الملخص =================
    print("\n" + "=" * 62)
    print(f"النتيجة: {len(PASS)} ناجح / {len(FAIL)} فاشل")
    if FAIL:
        print("الفاشل:", ", ".join(FAIL))
    return 1 if FAIL else 0


if __name__ == "__main__":
    sys.exit(main())
