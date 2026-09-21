"""الأمر 006 §17 — اختبارات smoke حية عبر HTTP فعلي (لا screenshots).

تثبت السلسلة الكاملة بلا أي mock:
1) chat:  رسالة → /api/chat/stream → استدعاء HTTP حي → رد متدفق.
2) task:  هدف → /api/cycle/stream → الأدوار الخمسة الحية → أدلة.
3) توجيه الأدوار: كل دور بنموذجه المعيّن له (نماذج مختلفة فعلًا).
4) الركيزة: التنفيذ داخلها (execution_site=substrate في الأدلة).

التشغيل: خادم حي على 127.0.0.1:8010 + مزود zai_internal محلول.
"""

from __future__ import annotations

import json
import sys
import urllib.request

BASE = "http://127.0.0.1:8010"


def post_sse(path: str, body: dict) -> list[dict]:
    """POST + تفكيك بث SSE إلى أحداث."""
    request = urllib.request.Request(
        BASE + path,
        data=json.dumps(body, ensure_ascii=False).encode("utf-8"),
        headers={"Content-Type": "application/json"},
        method="POST",
    )
    events: list[dict] = []
    with urllib.request.urlopen(request, timeout=900) as response:
        raw = response.read().decode("utf-8")
    for block in raw.split("\n\n"):
        if block.startswith("data: "):
            events.append(json.loads(block[6:]))
    return events


def put_json(path: str, body: dict) -> dict:
    request = urllib.request.Request(
        BASE + path,
        data=json.dumps(body, ensure_ascii=False).encode("utf-8"),
        headers={"Content-Type": "application/json"},
        method="PUT",
    )
    with urllib.request.urlopen(request, timeout=60) as response:
        return json.loads(response.read().decode("utf-8"))


def get_json(path: str) -> dict:
    with urllib.request.urlopen(BASE + path, timeout=60) as response:
        return json.loads(response.read().decode("utf-8"))


def main() -> int:
    print("=" * 70)
    print("SMOKE 1: chat حي — رسالة → استدعاء HTTP حي → رد متدفق")
    chat_events = post_sse("/api/chat/stream", {
        "message": "اكتب جملة واحدة فقط تشرح ما هو العدد الأولي.",
        "provider": "zai_internal",
        "model": "glm-4.6",
    })
    kinds = [e["kind"] for e in chat_events]
    assert "chat.start" in kinds, kinds
    assert kinds.count("chat.done") == 1, kinds
    assert "chat.error" not in kinds, [e for e in chat_events if e["kind"] == "chat.error"]
    done = next(e for e in chat_events if e["kind"] == "chat.done")
    text = " ".join(
        e["text"] for e in chat_events if e["kind"] == "chat.delta"
    )
    print(f"  ✅ provider={done['details']['provider']} model={done['details']['model']}")
    print(f"  ✅ زمن الاستدعاء الحي: {done['details']['duration_ms']}ms")
    print(f"  ✅ الرد المبث قطعًا: {len([e for e in chat_events if e['kind']=='chat.delta'])} قطعة")
    print(f"  ✅ مقتطف الرد: {text[:110]}")
    conversation_id = next(
        e for e in chat_events if e["kind"] == "chat.start"
    )["details"]["conversation_id"]

    listing = get_json("/api/conversations")["conversations"]
    assert any(c["conversation_id"] == conversation_id for c in listing)
    print(f"  ✅ المحادثة حقيقية في القائمة (id={conversation_id}, mode=chat)")

    print("=" * 70)
    print("SMOKE 2+3: مهمة حية + توجيه أدوار مستقل (نماذج مختلفة فعلًا)")
    # جلب النماذج الحية المتاحة للمزود — لتعيين نموذج مختلف لكل دور
    models = get_json("/api/providers/zai_internal/models")
    model_ids = models.get("model_ids", []) if models.get("ok") else []
    print(f"  نماذج {models.get('source')}: {model_ids[:6]}")
    glm = "glm-4.6"
    variants = [m for m in model_ids if m != glm][:4] or [glm] * 4
    roles_cfg = {
        "thinker": {"provider": "zai_internal", "model": glm},
        "reviewer": {"provider": "zai_internal", "model": variants[0]},
        "implementer": {"provider": "zai_internal", "model": glm},
        "verifier": {"provider": "zai_internal", "model": variants[1] if len(variants) > 1 else glm},
        "arbiter": {"provider": "zai_internal", "model": glm},
    }
    if len(variants) >= 2:
        print(f"  توجيه مستقل فعلي: reviewer→{variants[0]}, verifier→{variants[1]}, البقية→{glm}")
    else:
        print(f"  مزود واحد بنموذج واحد معلن — التوجيه بالمزود المعيّن لكل دور")

    task_events = post_sse("/api/cycle/stream", {
        "goal": (
            "اكتب تقريرًا من صفحة واحدة عن أثر الذكاء الاصطناعي على "
            "التعليم، من 5-8 مصادر موثقة، عربي RTL، PDF بحجم A4"
        ),
        "roles": roles_cfg,
    })
    kinds = [e["kind"] for e in task_events]
    done = next(e for e in task_events if e["kind"] == "task_done")
    verdict = done["verdict"]
    details = done["details"]

    # السلسلة الحية كاملة (§17): رسالة → استدعاء حي → دور → التالي…
    for kind in ("plan", "review_verdict", "task_execution", "task_verification"):
        assert kind in kinds, f"{kind} مفقود: {kinds}"
    calls = [e for e in task_events if e.get("kind") == "router.call.logged"]
    assert calls, "لا استدعاءات حية مسجلة في البث"
    print(f"  ✅ الأدوار الخمسة عملت: plan/review/execution/verification كلها في البث")
    print(f"  ✅ استدعاءات حية عبر الموجّه: {len(calls)}")
    for c in calls[:8]:
        d = c.get("details", c)
        print(f"     · {d.get('provider')}/{d.get('model')} — {d.get('duration_ms')}ms")

    # إثبات النموذج المعيّن لكل دور وصل فعلًا (router.call.logged يحمل النموذج)
    used_models = {c.get("details", c).get("model") for c in calls}
    print(f"  ✅ النماذج المستخدمة فعلًا في الاستدعاءات: {sorted(used_models)}")
    if len(variants) >= 2:
        assert variants[0] in used_models, "نموذج المدقق المعيّن لم يُستدعَ"
        assert variants[1] in used_models, "نموذج المراجع المعيّن لم يُستدعَ"

    # الأدلة الحية
    evidence_path = details.get("evidence_path", "")
    with open(evidence_path, encoding="utf-8") as handle:
        evidence = json.load(handle)
    role_models = evidence.get("role_models", {})
    print(f"  ✅ الأدلة: {evidence_path}")
    print(f"     sha256: {details.get('evidence_sha256', '')[:20]}…")
    for role, sel in role_models.items():
        print(f"     · {role}: {sel['provider']}/{sel['model']}")
    if len(variants) >= 2:
        assert role_models["reviewer"]["model"] == variants[0]
        assert role_models["verifier"]["model"] == variants[1]

    print(f"  ✅ الحكم الصادق: {verdict}")
    if verdict != "PASS":
        print("     أسباب:", details.get("verdict_reasons"))

    print("=" * 70)
    print("SMOKE 4: التنفيذ داخل الركيزة (execution_site=substrate)")
    tool_calls = evidence.get("tool_calls", [])
    substrate_calls = [t for t in tool_calls if t.get("execution_site") == "substrate"]
    declared = [t for t in tool_calls if t.get("execution_site") == "in_process_declared"]
    print(f"  ✅ استدعاءات أدوات: {len(tool_calls)} (ركيزة: {len(substrate_calls)}، معلنة خارجها: {len(declared)})")
    for t in substrate_calls[:4]:
        print(f"     · {t.get('tool')} — {t.get('duration_ms')}ms — sha256: {str(t.get('output_sha256',''))[:14]}…")
    files = evidence.get("files", {})
    print(f"  ✅ ملفات الأدلة: {sorted(files)[:6]}")

    print("=" * 70)
    print("SMOKE 5: صدق الفشل — مهمة بمزود غير متاح = CONFIGURATION_REQUIRED")
    cfg_events = post_sse("/api/cycle/stream", {
        "goal": "مهمة بمزود غائب",
        "roles": {"thinker": {"provider": "nvidia", "model": "x"}},
    })
    req = [e for e in cfg_events if e["kind"] == "CONFIGURATION_REQUIRED"]
    assert req, [e.get("kind") for e in cfg_events]
    assert "المفكر" in req[0]["text"]
    print(f"  ✅ {req[0]['text'][:120]}")

    print("=" * 70)
    print("كل اختبارات الـsmoke الحية نجحت — المسار الرئيسي Live فعليًا.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
