#!/usr/bin/env python3
"""القبول الحي للأمر 013.5 — §A/§B/§O/§P: المزود النشط الحقيقي وحده يُختبر.

لماذا هذا الملف موجود
=====================
سكربت القبول السابق (``scripts/order0134_acceptance.py``) ثبّت المزود
``zai_internal`` والنموذج ``glm-4.6`` داخل نصّه (السطران 116-117:
``mapping.provider = "zai_internal"`` / ``mapping.model = "glm-4.6"``)،
ثم ربط كل الأدوار بهما قبل تشغيل السيناريو. فكانت نتيجته الخضراء
**لا تُثبت شيئًا عن زمن تشغيل المالك** الذي هو مزود ``nvidia`` بنموذج
يُختار من الواجهة ويُحفظ في القاعدة.

قاعدة §O (وهي روح هذا الملف):
    **النموذج/المزود النشط المعلن في التهيئة الحية هو ما يجب اختباره**
    — لا نموذج يُثبَّت في نص السكربت، ولا افتراضي مخترع، ولا ربط أدوار
    يُعاد كتابته ليصير السيناريو مريحًا. إن تعذّر قراءة التهيئة الحية
    فالنتيجة الصحيحة هي **الرفض الصريح** (خروج بلا صفر) لا التشغيل
    بنموذج مُصطنع. و``--provider``/``--model`` موجودان كتجاوز صريح
    للتشخيص فقط، ويُعلَن في الأدلة أن النتيجة حينها **لا تثبت** زمن
    التشغيل الحي (``live_config_tested: false``).

قياس الحقيقة لا صناعة النجاح (§B + §P)
=======================================
السيناريو هو §P حرفيًا: صحة الخادم ← محادثة عادية جديدة بسؤال بحث
حقيقي ← مشروع بهدف OSINT الحرفي ← أمر توليد خطة ← استطلاع اللقطة
القانونية حتى يخرج المشروع من ``PLANNING`` أو تنتهي المهلة.

الحكم النهائي (منصوص في ``VERDICT_RULE`` أدناه):

- **FAIL**: بقي المشروع ``PLANNING`` حتى نهاية المهلة بلا إنهاء مفهوم،
  أو بقيت جلسة ``GENERATING`` حية بلا سقف بعد المهلة، أو خرج المشروع
  من ``PLANNING`` بفشل **صامت غير مصنّف**، أو ادّعى الويب مصادر بلا
  رابط حقيقي واحد.
- **PASS**: خرج المشروع من ``PLANNING`` إلى حالة نهائية **صادقة**:
  إما خطة مدوّنة، وإما فشل **مصنّف صريح** (‎MODEL_TIMEOUT /
  PROVIDER_UNAVAILABLE / … ) مع ``last_error`` معلن — فالفشل المصنّف
  إنجاز للنزاهة لا عيب يُخفى، والمطلوب من هذا التمرين **الصدق** لا
  اللون الأخضر.

كل قيمة في الأدلة تأتي من رد HTTP أو صف قاعدة — وإن غابت تُسجَّل
``null`` مع سببها في ``unavailable``. لا قيمة تُخترع، ولا انتظار صامت.

القراءة الحية للتهيئة (§A) — مسار الكود الفعلي:
    1. المفضّل: ``GET /api/models/config`` على الخادم الجاري
       (المعالج ``get_models_config`` في ``src/api/models_config.py``
       → ``registry.get_mappings`` في
       ``src/providers_registry/registry.py`` → جدول
       ``role_provider_mappings``).
    2. الاحتياط إن كان الخادم غير متاح: قراءة الجدول نفسه مباشرة
       من ``runtime/agent_hub_v2.db`` (المصدر الدائم المعلن في وثيقة
       ``src/router/role_config.py``) بوضع قراءة-فقط.
    السكربت يقول أي مصدر استخدم بالحرف في اللافتة وفي الأدلة.
    (الإحالة بالرمز لا برقم السطر: ``src/`` يتغيّر تحت هذا السكربت.)

الأدلة: ``runtime/evidence/order0135-acceptance-<طابع زمني>.json``

أمثلة تشغيل::

    .venv\\Scripts\\python.exe scripts\\order0135_acceptance.py
    .venv\\Scripts\\python.exe scripts\\order0135_acceptance.py \\
        --base-url http://127.0.0.1:8010 --planning-timeout 900
    .venv\\Scripts\\python.exe scripts\\order0135_acceptance.py --help
"""

from __future__ import annotations

import argparse
import json
import re
import subprocess
import sys
import time
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
for _extra in (REPO / "scripts", REPO / "src"):
    if str(_extra) not in sys.path:
        sys.path.insert(0, str(_extra))

import _accept_http as http_  # noqa: E402  (وحدة الأدوات المجاورة)

# ------------------------------------------------------------------ #
# الثوابت الحرفية للسيناريو (§P) — رسالة ونصّ الهدف حصرًا.
# لا مزود ولا نموذج مكتوب هنا عن قصد: قاعدة §O.
# ------------------------------------------------------------------ #

#: السؤال الحرفي في المحادثة العادية (§P.b) — «أحدث» تُفعّل بحث الويب
#: عبر كاشف النية الحتمي (src/research/chat_research.py:26-32).
CHAT_QUESTION = "ما هي أحدث نماذج كلاود؟"

#: هدف المشروع الحرفي (§P.c).
PROJECT_OBJECTIVE = ("بناء منصة osint متقدمة جدا وفق احدث التقنيات "
                     "والتكنولوجيا")

#: أدوار المقارنة: المحادثة (chat) والتخطيط (thinker) — §A.
CHAT_ROLE = "chat"
PLANNING_ROLE = "thinker"

#: أحداث ميزانية الويب التي يجب تتبعها حرفيًا (§P.b).
RESEARCH_KINDS = (
    "research.started",
    "research.results",
    "research.used",
    "research.unavailable",
    "research.fetched",
    "research.fetch_failed",
)

#: مصادر قراءة التهيئة الحية — لا يقبل السكربت غيرهما بلا تجاوز صريح.
SOURCE_HTTP = "http:GET /api/models/config"
SOURCE_HTTP_DETAIL = (
    "src/api/models_config.py get_models_config() → "
    "src/providers_registry/registry.py get_mappings() → "
    "جدول role_provider_mappings في runtime/agent_hub_v2.db"
)
SOURCE_DB = "db:role_provider_mappings"
SOURCE_DB_DETAIL = (
    "قراءة مباشرة (read-only) لجدول role_provider_mappings في "
    "runtime/agent_hub_v2.db — المصدر الدائم المعلن في وثيقة "
    "src/router/role_config.py"
)
SOURCE_OVERRIDE = "cli-override"
LIVE_SOURCES = (SOURCE_HTTP, SOURCE_DB)

#: بدائل احتياطية لمفردات الحالة مصدرها src (تُستخدم فقط إن تعذّر
#: الاستيراد، ويُعلن ذلك في الأدلة — لا تخمين صامت).
_FALLBACK_TERMINAL_SESSION_STATES = (
    "COMPLETED", "FAILED", "INTERRUPTED", "CANCELLED",
)
_FALLBACK_ERROR_CLASSES = (
    "MODEL_TIMEOUT", "PROVIDER_QUOTA", "PROVIDER_UNAVAILABLE",
    "PROVIDER_AUTH_ERROR", "MODEL_RESPONSE_INVALID",
    "PROVIDER_NOT_CONFIGURED", "PLANNING_INTERRUPTED", "PLANNING_ERROR",
)

#: ألوان الحكم في الطرفية — بلا ادعاء: PASS/FAIL فقط.
VERDICT_RULE = """قاعدة الحكم (013.5 §P) — الصدق لا اللون الأخضر:

  PASS  ⟺  (1) المشروع خرج من PLANNING داخل المهلة، و
           (2) جلسة التخطيط بلغت حالة نهائية معلنة، و
           (3) أحد أمرين صادقين:
               (أ) نجاح موثّق: خطة دُوّنت (plan_id/PLAN_CREATED) والمشروع
                   AWAITING_OWNER_APPROVAL (أو DRAFT بخطة مدوّنة)، أو
               (ب) فشل مصنَّف صريح: error_class من PLANNING_ERROR_CLASSES
                   مع last_error معلن، والمشروع DRAFT/FAILED.
  FAIL  ⟸  بقاء المشروع PLANNING حتى نهاية المهلة بلا إنهاء مفهوم («تخطيط
           لا ينتهي بذكاء»)، أو جلسة GENERATING حية بلا سقف بعد المهلة،
           أو خروج من PLANNING بفشل صامت غير مصنَّف، أو ادعاء ويب بنتائج
           بلا مصدر (رابط http/https حقيقي) واحد، أو اختلاف المزود/النموذج
           الفعلي عن التهيئة الحية (§O)."""

#: تجاوز صريح لا يُقبل إلا كزوجين، ويُعلَن أثره على صدق النتيجة.
OVERRIDE_WARNING = (
    "⚠️  وضع التجاوز اليدوي مُفعَّل: النتيجة لا تثبت زمن التشغيل الحي "
    "للمالك (§O) — الأثبات يسجّل live_config_tested=false"
)


class Refusal(RuntimeError):
    """رفض صريح للتشغيل — بلا تجاوز صامت ولا نتيجة مصطنعة."""


# ------------------------------------------------------------------ #
# بنية الأدلة — كل خطوة مغلّفة بطابعها وردّها
# ------------------------------------------------------------------ #

class Evidence:
    """حاوية الأدلة: lines of truth — كل إدخال يحمل زمنه ومصدره."""

    def __init__(self) -> None:
        self.data: dict = {
            "command": "013.5",
            "sections": ["§A", "§B", "§O", "§P"],
            "script": "scripts/order0135_acceptance.py",
            "helper": "scripts/_accept_http.py",
            "started_at": http_.utc_now(),
            "finished_at": None,
            "steps": [],
            "checks": [],
            "unavailable": [],
            "notes": [],
        }

    def step(self, step_id: str, label: str, envelope: dict | None = None,
             *, request: dict | None = None, extra: dict | None = None) -> dict:
        """تسجيل خطوة HTTP كاملة: الطلب والرد والحالة والزمن."""
        entry = {
            "id": step_id,
            "label": label,
            "at": (envelope or {}).get("at") or http_.utc_now(),
            "method": (envelope or {}).get("method", ""),
            "url": (envelope or {}).get("url", ""),
            "request": request,
            "ok": (envelope or {}).get("ok"),
            "status": (envelope or {}).get("status"),
            "duration_ms": (envelope or {}).get("duration_ms"),
            "error": (envelope or {}).get("error"),
            "extra": {**(envelope or {}).get("extra", {}), **(extra or {})},
        }
        self.data["steps"].append(entry)
        return entry

    def check(self, name: str, ok: bool, note: str = "", *,
              level: str = "critical") -> bool:
        """تسجيل فحص — level: critical (يُسقط الحكم) | truthful | info."""
        self.data["checks"].append({
            "name": name, "ok": bool(ok), "level": level,
            "note": note, "at": http_.utc_now(),
        })
        mark = "✅" if ok else ("❌" if level != "info" else "•")
        print(f"  {mark} [{level}] {name}" + (f" — {note}" if note else ""),
              flush=True)
        return bool(ok)

    def unavailable(self, field: str, reason: str) -> None:
        """حقل غير متاح — يُسجَّل null مع سببه (لا قيمة مخترعة)."""
        self.data["unavailable"].append({"field": field, "reason": reason})

    def note(self, text: str) -> None:
        self.data["notes"].append({"at": http_.utc_now(), "text": text})


# ------------------------------------------------------------------ #
# هوية المستودع والقاعدة
# ------------------------------------------------------------------ #

def git_head() -> dict:
    """صحة الرأس القصير للمستودع — من git، مع بديل قراءة ملفات .git."""
    try:
        sha = subprocess.run(
            ["git", "rev-parse", "--short", "HEAD"], cwd=REPO,
            capture_output=True, text=True, timeout=15, check=False,
        )
        branch = subprocess.run(
            ["git", "rev-parse", "--abbrev-ref", "HEAD"], cwd=REPO,
            capture_output=True, text=True, timeout=15, check=False,
        )
        dirty = subprocess.run(
            ["git", "status", "--porcelain"], cwd=REPO,
            capture_output=True, text=True, timeout=15, check=False,
        )
        if sha.returncode == 0 and sha.stdout.strip():
            porcelain = dirty.stdout.strip().splitlines() \
                if dirty.returncode == 0 else []
            return {
                "head_sha": sha.stdout.strip(),
                "branch": branch.stdout.strip() if branch.returncode == 0 else None,
                "dirty": bool(porcelain),
                "dirty_files": len(porcelain),
                "source": "git rev-parse",
            }
    except (OSError, subprocess.SubprocessError):
        pass
    # بديل صادق: قراءة .git مباشرة (لا ادعاء نجاح git)
    try:
        git_dir = REPO / ".git"
        head_text = (git_dir / "HEAD").read_text(encoding="utf-8").strip()
        if head_text.startswith("ref:"):
            ref = head_text.split(":", 1)[1].strip()
            sha = (git_dir / ref).read_text(encoding="utf-8").strip()[:7]
        else:
            sha = head_text[:7]
        return {"head_sha": sha, "branch": None, "dirty": None,
                "dirty_files": None, "source": "قراءة .git مباشرة"}
    except OSError:
        return {"head_sha": None, "branch": None, "dirty": None,
                "dirty_files": None, "source": "غير متاح"}


def resolve_db_path(cli_db: str | None, evidence: Evidence) -> tuple[Path, str]:
    """مسار قاعدة التشغيل — من src/core/config.py، أو تجاوز صريح."""
    if cli_db:
        evidence.note(f"مسار القاعدة من --db الصريح: {cli_db}")
        return Path(cli_db).expanduser().resolve(), "--db (تجاوز صريح)"
    try:
        from core.config import settings as aes_settings  # noqa: PLC0415

        raw = Path(aes_settings.db_path)
        path = raw if raw.is_absolute() else REPO / raw
        if path.is_file():
            return path.resolve(), \
            "src/core/config.py Settings.db_path (settings.db_path)"
        evidence.unavailable(
            "db_path(settings)",
            f"settings.db_path = {raw} لم يوجد على القرص",
        )
    except Exception as error:  # noqa: BLE001 — البديل المعلن أدناه
        evidence.unavailable(
            "db_path(settings)",
            f"تعذّر استيراد core.config: {type(error).__name__}: {error}",
        )
    fallback = REPO / "runtime" / "agent_hub_v2.db"
    return fallback.resolve(), "بديل معلن: <repo>/runtime/agent_hub_v2.db"


# ------------------------------------------------------------------ #
# §O — حارس «لا نموذج مُثبَّت في النص»
# ------------------------------------------------------------------ #

#: أنماط الإثبات الصريح لنموذج/مزود مكتوب في النص نفسه — وهو جذر عطل
#: 013.4 بالحرف (``mapping.provider = "zai_internal"``).
_LITERAL_ASSIGN = re.compile(
    r"""^\s*
        (?P<key>"?(?:[A-Za-z_][A-Za-z0-9_]*\.)?(?:provider|model)"?)
        \s*[:=]\s*
        (?P<val>["'][^"']+["'])
        \s*,?\s*$""",
    re.IGNORECASE | re.VERBOSE,
)


def audit_own_source(path: Path) -> list[dict]:
    """تفتيش ذاتي: لا سطر في هذا السكربت يثبّت مزودًا/نموذجًا بنصّ حرفي."""
    offenders: list[dict] = []
    try:
        lines = path.read_text(encoding="utf-8").splitlines()
    except OSError as error:
        return [{"line": None, "text": f"تعذّر تفتيش الملف: {error}"}]
    for number, line in enumerate(lines, 1):
        if _LITERAL_ASSIGN.match(line):
            offenders.append({"line": number, "text": line.strip()[:160]})
    return offenders


def guard_not_hardcoded(config: dict, args, evidence: Evidence) -> None:
    """يرفض التشغيل بنموذج مُثبَّت في النص أو بتهيئة غير حية (§O)."""
    offenders = audit_own_source(Path(__file__))
    evidence.data["self_audit"] = {
        "checked_file": str(Path(__file__).relative_to(REPO)),
        "literal_provider_or_model_assignments": offenders,
    }
    if offenders:
        for offender in offenders:
            print(f"  ❌ سطر {offender['line']}: {offender['text']}",
                  flush=True)
        raise Refusal(
            "هذا السكربت يثبّت مزودًا/نموذجًا بنصّ حرفي "
            f"({len(offenders)} سطر) — §O يمنع ذلك من الجذر"
        )
    if bool(args.provider) != bool(args.model):
        raise Refusal(
            "--provider و--model يجب أن يأتيا معًا "
            "(زوج صريح) — لا نصف تجاوز"
        )
    if args.provider and args.model:
        if config["source"] != SOURCE_OVERRIDE:
            raise Refusal(
                "تجاوز صريح مع تهيئة حية محسومة — "
                "لا نخلط مصدرين"
            )
        evidence.data["live_config_tested"] = False
        evidence.note(OVERRIDE_WARNING)
        return
    if config["source"] not in LIVE_SOURCES:
        raise Refusal(
            "لم نقرأ تهيئة حية (المصدر: "
            f"{config['source']}) — §O يمنع اختبار نموذج غير معلن"
        )
    if not config.get("provider") or not config.get("model"):
        raise Refusal(
            "التهيئة الحية بلا مزود/نموذج معلن — "
            "لا نخترع افتراضيًا"
        )
    evidence.data["live_config_tested"] = True


# ------------------------------------------------------------------ #
# §A — قراءة التهيئة الحية (المزود/النموذج النشط فعلًا)
# ------------------------------------------------------------------ #

def role_defaults() -> tuple[dict, str]:
    """الافتراضات المعلنة للأدوار — من src حصرًا (لا نص مخترع هنا)."""
    try:
        from router.role_config import (  # noqa: PLC0415
            DEFAULT_MODEL, DEFAULT_PROVIDER, ROLE_KEYS,
        )

        return (
            {key: {"provider": DEFAULT_PROVIDER, "model": DEFAULT_MODEL,
                   "configuration": ""} for key in ROLE_KEYS},
            "src/router/role_config.py (ROLE_KEYS/DEFAULT_PROVIDER/"
            "DEFAULT_MODEL)",
        )
    except Exception as error:  # noqa: BLE001
        return {}, f"غير متاح ({type(error).__name__}: {error})"


def _providers_index_http(payload: dict) -> dict:
    out: dict = {}
    for provider in payload.get("providers") or []:
        configs = provider.get("configurations") or []
        out[provider.get("id")] = {
            "label": provider.get("label"),
            "enabled": provider.get("enabled"),
            "available": provider.get("available"),
            "state": provider.get("state"),
            "reason": provider.get("reason"),
            "requires_key": provider.get("requires_key"),
            "has_key": provider.get("has_key"),
            "base_url": provider.get("base_url"),
            "default_model": provider.get("default_model"),
            "known_models": provider.get("known_models") or [],
            "readiness_status": provider.get("readiness_status"),
            "configurations": [
                {"name": c.get("name"), "base_url": c.get("base_url"),
                 "default_model": c.get("default_model"),
                 "models_count": len(c.get("models") or []),
                 "models": c.get("models") or [],
                 "enabled": c.get("enabled"),
                 "readiness": c.get("readiness")}
                for c in configs
            ],
        }
    return out


def _finalize_config(config: dict, global_defaults: dict) -> dict:
    """إكمال الأدوار الناقصة بالافتراض المعلن + اشتقاق دورَي المقارنة."""
    mappings = config["role_mappings"]
    for role, default in global_defaults.items():
        if role not in mappings:
            mappings[role] = {**default, "source": "افتراض معلن (الدور غائب "
                                                 "عن الجدول)"}
            config["notes"].append(
                f"الدور '{role}' غائب عن role_provider_mappings — "
                "استُخدم الافتراض المعلن من src/router/role_config.py"
            )
    chat = mappings.get(CHAT_ROLE) or {}
    thinker = mappings.get(PLANNING_ROLE) or {}
    config["chat_selection"] = chat
    config["thinker_selection"] = thinker
    config["provider"] = chat.get("provider")
    config["model"] = chat.get("model")
    config["configuration"] = chat.get("configuration") or ""
    config["transport_key"] = http_.transport_key(
        config["provider"] or "", config["configuration"]
    )
    config["roles_differ"] = (
        http_.normalized_provider(chat.get("provider"))
        != http_.normalized_provider(thinker.get("provider"))
        or chat.get("model") != thinker.get("model")
    )
    return config


def resolve_config_http(base_url: str, timeout: float,
                        global_defaults: dict) -> dict | None:
    """المصدر المفضّل: ``GET /api/models/config`` على الخادم الجاري."""
    result = http_.get_json(base_url, "/api/models/config", timeout=timeout)
    if not result["ok"] or not isinstance(result["data"], dict):
        return None
    payload = result["data"]
    roles: dict = {}
    for role in payload.get("roles") or []:
        selection = role.get("selection") or {}
        roles[role.get("key")] = {
            "provider": selection.get("provider"),
            "configuration": selection.get("configuration") or "",
            "model": selection.get("model"),
            "label": role.get("label"),
            "is_default": role.get("is_default"),
            "source": "role_provider_mappings (عبر HTTP)",
        }
    if not roles:
        return None
    config = {
        "source": SOURCE_HTTP,
        "source_detail": SOURCE_HTTP_DETAIL,
        "endpoint": result["url"],
        "read_at": result["at"],
        "role_mappings": roles,
        "provider_blocks": _providers_index_http(payload),
        "declared_defaults": payload.get("defaults"),
        "http_envelope": {
            "status": result["status"], "duration_ms": result["duration_ms"],
        },
        "notes": [],
    }
    return _finalize_config(config, global_defaults)


def resolve_config_db(db_path: Path, global_defaults: dict) -> dict | None:
    """الاحتياط: قراءة الجدول الدائم مباشرة (read-only) بلا خادم."""
    try:
        connection = http_.db_connect_ro(db_path)
    except Exception:  # noqa: BLE001 — يُعلن أعلى المستوى
        return None
    try:
        rows, failure = http_.safe_db(
            connection,
            "select role, provider, configuration, model, updated_at "
            "from role_provider_mappings order by id",
        )
        if failure or not rows:
            return None
        roles: dict = {}
        for row in rows:
            roles[row["role"]] = {
                "provider": row["provider"],
                "configuration": row.get("configuration") or "",
                "model": row["model"],
                "updated_at": row.get("updated_at"),
                "source": "role_provider_mappings (قراءة مباشرة)",
            }
        provider_blocks: dict = {}
        provider_rows, provider_failure = http_.safe_db(
            connection,
            "select p.name, p.display_name, p.enabled, p.auth_type, "
            "p.api_style, c.name as config_name, c.base_url, "
            "c.default_model, c.models, c.enabled as config_enabled, "
            "c.last_readiness_status from providers p left join "
            "provider_configurations c on c.provider_id = p.id "
            "order by p.id, c.id",
        )
        for row in provider_rows:
            entry = provider_blocks.setdefault(row["name"], {
                "label": row.get("display_name"),
                "enabled": bool(row.get("enabled")),
                "requires_key": row.get("auth_type") == "bearer",
                "has_key": None,
                "base_url": row.get("base_url"),
                "default_model": row.get("default_model"),
                "known_models": [],
                "readiness_status": row.get("last_readiness_status"),
                "configurations": [],
            })
            models: list = []
            try:
                models = json.loads(row.get("models") or "[]")
            except ValueError:
                models = []
            entry["known_models"] = list(
                dict.fromkeys(entry["known_models"] + models)
            )
            entry["configurations"].append({
                "name": row.get("config_name"),
                "base_url": row.get("base_url"),
                "default_model": row.get("default_model"),
                "models_count": len(models),
                "models": models,
                "enabled": bool(row.get("config_enabled")),
                "readiness": {
                    "status": row.get("last_readiness_status") or "UNTESTED",
                    "checked_at": None,
                },
            })
        config = {
            "source": SOURCE_DB,
            "source_detail": SOURCE_DB_DETAIL,
            "endpoint": f"sqlite3 (read-only): {db_path}",
            "read_at": http_.utc_now(),
            "role_mappings": roles,
            "provider_blocks": provider_blocks,
            "declared_defaults": None,
            "db_failure": provider_failure,
            "notes": [],
        }
        return _finalize_config(config, global_defaults)
    finally:
        connection.close()


def resolve_config(args, db_path: Path, global_defaults: dict,
                   evidence: Evidence) -> dict | None:
    """قراءة المزود/النموذج النشط: HTTP أولًا ثم القاعدة (ترتيب §A)."""
    if args.provider and args.model:
        return {
            "source": SOURCE_OVERRIDE,
            "source_detail": "أعلام --provider/--model الصريحة (تشخيص فقط)",
            "endpoint": None,
            "read_at": http_.utc_now(),
            "role_mappings": {},
            "provider_blocks": {},
            "declared_defaults": None,
            "override": {"provider": args.provider, "model": args.model},
            "notes": [OVERRIDE_WARNING],
        }
    config = resolve_config_http(args.base_url, min(args.request_timeout, 10.0),
                                 global_defaults)
    if config is not None:
        availability = http_.health(args.base_url, timeout=5.0)
        evidence.step("a0-health-probe", "فحص حياة الخادم (قراءة التهيئة)",
                      availability)
        return config
    probe = http_.health(args.base_url, timeout=5.0)
    evidence.step("a0-health-probe", "فحص حياة الخادم (فشل قراءة التهيئة)",
                  probe)
    evidence.note(
        f"تعذّر GET {http_.join(args.base_url, '/api/models/config')} "
        f"({probe.get('error') or 'لا رد'}) — انتقلنا إلى قراءة القاعدة"
    )
    config = resolve_config_db(db_path, global_defaults)
    if config is not None:
        return config
    return None


def print_banner(args, db_path: Path, db_source: str, head: dict,
                 config: dict) -> None:
    """لافتة §A: الرأس، القاعدة، المزود/النموذج النشط، مصدره، وربط الأدوار."""
    line = "=" * 78
    print(line, flush=True)
    print("القبول الحي للأمر 013.5 — §A/§B/§O/§P", flush=True)
    print(line, flush=True)
    print(f"  رأس المستودع (HEAD)   : {head.get('head_sha')} "
          f"({'فرع ' + str(head.get('branch')) if head.get('branch') else ''}"
          f"{' — شجرة غير نظيفة: ' + str(head.get('dirty_files')) + ' ملف' if head.get('dirty') else ''})"
          f"  [المصدر: {head.get('source')}]", flush=True)
    print(f"  مسار القاعدة          : {db_path}  [المصدر: {db_source}]",
          flush=True)
    print(f"  مصدر التهيئة الحية    : {config['source']}", flush=True)
    print(f"    └ التفصيل           : {config.get('source_detail')}",
          flush=True)
    if config.get("endpoint"):
        print(f"    └ نقطة القراءة      : {config['endpoint']} "
              f"@ {config.get('read_at')}", flush=True)
    if config["source"] == SOURCE_OVERRIDE:
        print(f"  {OVERRIDE_WARNING}", flush=True)
        print(f"  المزود (تجاوز صريح)   : {args.provider}", flush=True)
        print(f"  النموذج (تجاوز صريح)  : {args.model}", flush=True)
    else:
        print(f"  المزود النشط (chat)   : {config.get('provider')}", flush=True)
        print(f"  النموذج النشط (chat)  : {config.get('model')}", flush=True)
        print(f"  التكوين               : "
              f"{config.get('configuration') or '(الأساسي)'} | "
              f"مفتاح النقل: {config.get('transport_key')}", flush=True)
        print(f"  دور التخطيط (thinker) : "
              f"{config['thinker_selection'].get('provider')} / "
              f"{config['thinker_selection'].get('model')}", flush=True)
        if config.get("roles_differ"):
            print("  ⚠️  دورا المحادثة والتخطيط مختلفان — كلٌّ يُفحص "
                  "باختياره (§A)", flush=True)
    print("  ربط الأدوار المحسوم من التهيئة الحية:", flush=True)
    mappings = config.get("role_mappings") or {}
    for role in ("chat", "thinker", "reviewer", "implementer", "verifier",
                 "arbiter"):
        if role in mappings:
            item = mappings[role]
            mark = "★" if role in (CHAT_ROLE, PLANNING_ROLE) else " "
            print(f"    {mark} {role:<11} → {item.get('provider')} / "
                  f"{item.get('model')}"
                  f" | config={item.get('configuration') or '(الأساسي)'}",
                  flush=True)
    for role, item in mappings.items():
        if role not in ("chat", "thinker", "reviewer", "implementer",
                        "verifier", "arbiter"):
            print(f"      {role:<11} → {item.get('provider')} / "
                  f"{item.get('model')}", flush=True)
    print(f"  الخادم المستهدف        : {args.base_url}", flush=True)
    print(f"  مهلة التخطيط           : {args.planning_timeout:.0f}ث "
          f"(استطلاع كل {args.poll_interval:.1f}ث)", flush=True)
    print(line, flush=True)


# ------------------------------------------------------------------ #
# أدوات استخراج صادقة — القيمة مع مسارها في ردّ حقيقي
# ------------------------------------------------------------------ #

def deep_find(obj, names: tuple[str, ...], *, max_depth: int = 9
              ) -> dict[str, dict]:
    """أول قيمة غير فارغة لكل اسم مع مسارها في الرد (تتبّع لا تخمين)."""
    wanted = {name: None for name in names}
    stack: list[tuple[object, str, int]] = [(obj, "$", 0)]
    while stack:
        node, path, depth = stack.pop(0)
        if depth > max_depth:
            continue
        if isinstance(node, dict):
            for key, value in node.items():
                child = f"{path}.{key}"
                if key in wanted and wanted[key] is None \
                        and value not in (None, "", [], {}):
                    wanted[key] = {"value": value, "path": child}
                stack.append((value, child, depth + 1))
        elif isinstance(node, list):
            for index, value in enumerate(node):
                stack.append((value, f"{path}[{index}]", depth + 1))
    return wanted


def field(evidence: Evidence, mapping: dict, name: str, default=None):
    """استخراج حقل من نتيجة deep_find مع تسجيل الغياب بصدق."""
    found = (mapping or {}).get(name)
    if found is None:
        return default
    return found["value"]


def source_of(mapping: dict, name: str) -> str | None:
    found = (mapping or {}).get(name)
    return found["path"] if found else None


def same_provider(left, right) -> bool:
    """مقارنة مزودين مع تجاهل لاحقة التكوين (nvidia::default = nvidia)."""
    return http_.normalized_provider(left) == http_.normalized_provider(right)


def step_at(evidence: Evidence, step_id: str):
    """طابع بدء خطوة مسجّلة (من مغلّف الرد نفسه) أو None."""
    for entry in evidence.data.get("steps") or []:
        if entry.get("id") == step_id:
            return entry.get("at")
    return None


def step_duration(evidence: Evidence, step_id: str):
    """مدة خطوة مسجّلة بالمللي ثانية أو None."""
    for entry in evidence.data.get("steps") or []:
        if entry.get("id") == step_id:
            return entry.get("duration_ms")
    return None


# ------------------------------------------------------------------ #
# §P.a — صحة الخادم
# ------------------------------------------------------------------ #

def step_health(args, evidence: Evidence) -> bool:
    """(أ) فحص حياة الخادم — فشل الاتصال = رفض صريح لا تمثيل."""
    print("\n[أ] فحص حياة الخادم", flush=True)
    result = http_.health(args.base_url, timeout=min(args.request_timeout, 10.0))
    evidence.step("a-health", "GET /health", result)
    if not result["ok"] or not isinstance(result["data"], dict):
        unreachable = bool((result.get("extra") or {}).get("unreachable"))
        message = (
            f"لا خادم يستجيب على {args.base_url} "
            f"({result.get('error') or 'بلا رد'})"
            if unreachable else
            f"الخادم رد بخطأ على {args.base_url}: "
            f"{result.get('error') or result.get('status')}"
        )
        print(f"  ❌ {message}", flush=True)
        evidence.check("a-server-reachable", False, message)
        evidence.data["health"] = {
            "ok": False, "unreachable": unreachable,
            "status": result.get("status"), "error": result.get("error"),
            "url": result.get("url"), "at": result.get("at"),
        }
        return False
    payload = result["data"]
    evidence.data["health"] = {
        "ok": True, "status": result["status"], "at": result["at"],
        "url": result["url"], "app": payload.get("app"),
        "version": payload.get("version"), "phase": payload.get("phase"),
        "raw": payload,
    }
    print(f"  ✅ الخادم حي: {payload.get('app')} "
          f"v{payload.get('version')} ({result.get('status')})", flush=True)
    evidence.check("a-server-reachable", True,
                   f"{payload.get('app')} v{payload.get('version')}")
    return True


# ------------------------------------------------------------------ #
# §P.b — المحادثة العادية والويب الحقيقي
# ------------------------------------------------------------------ #

def _chat_timeline_from_db(db_path: Path, conversation_id: int) -> dict:
    """خط زمن أحداث المحادثة من جدول events الدائم (قراءة فقط)."""
    out: dict = {"source": f"sqlite3(read-only):{db_path}#events",
                 "cycle_id": f"chat-{conversation_id}", "events": [],
                 "kind_counts": {}, "delta_events": 0, "failure": None}
    try:
        connection = http_.db_connect_ro(db_path)
    except Exception as error:  # noqa: BLE001
        out["failure"] = f"{type(error).__name__}: {error}"
        return out
    try:
        rows, failure = http_.safe_db(
            connection,
            "select kind, role, state, payload, duration_ms, created_at "
            "from events where cycle_id = ? order by id",
            (f"chat-{conversation_id}",),
        )
        out["failure"] = failure
        for row in rows:
            out["kind_counts"][row["kind"]] = \
                out["kind_counts"].get(row["kind"], 0) + 1
            if row["kind"] == "message_delta":
                out["delta_events"] += 1
                continue
            if len(out["events"]) < 300:
                payload = {}
                try:
                    payload = json.loads(row.get("payload") or "{}")
                except ValueError:
                    payload = {}
                out["events"].append({
                    "kind": row["kind"], "role": row["role"],
                    "state": row["state"], "duration_ms": row["duration_ms"],
                    "created_at": row["created_at"],
                    "payload": payload,
                })
    finally:
        connection.close()
    return out


def step_chat(args, db_path: Path, config: dict, evidence: Evidence) -> dict:
    """(ب) محادثة عادية جديدة ← /api/chat/stream ← تحليل الويب والمصادر."""
    print("\n[ب] محادثة عادية جديدة + سؤال بحث حقيقي", flush=True)
    print(f"    السؤال: {CHAT_QUESTION}", flush=True)
    request_body = {"message": CHAT_QUESTION, "web": "auto"}
    if config["source"] == SOURCE_OVERRIDE:
        request_body["provider"] = args.provider
        request_body["model"] = args.model
    result = http_.post_sse(
        args.base_url, "/api/chat/stream", request_body,
        timeout=args.chat_timeout,
    )
    stream = result.get("data") or {}
    events = stream.get("events") or []
    evidence.step("b-chat-stream", "POST /api/chat/stream (SSE)", result,
                  request=request_body,
                  extra={"sse_events": len(events),
                         "terminal_kind": stream.get("terminal_kind"),
                         "timed_out": stream.get("timed_out")})

    conversation_id = None
    for event in events:
        if event.get("kind") == "conversation.bind":
            details = event.get("details") or {}
            conversation_id = details.get("conversation_id")
    bind_source = "SSE:conversation.bind.details.conversation_id"
    if conversation_id is None:
        # بديل صادق: أحدث محادثة نمطها chat أُنشئت بعد بدء الطلب (الطابع
        # الزمني للمقارنة من رد HTTP نفسه لا من ساعة محلية مخترعة)
        try:
            connection = http_.db_connect_ro(db_path)
            candidates, db_error = http_.safe_db(
                connection,
                "select id, title, mode, created_at from conversations "
                "order by id desc limit 10",
            )
            connection.close()
            if db_error:
                evidence.unavailable("conversation_id",
                                     f"البديل من القاعدة فشل: {db_error}")
            request_stamp = (result.get("at") or "").replace("T", " ") \
                .replace("Z", "")
            for candidate in candidates:
                created = str(candidate.get("created_at") or "")
                if candidate.get("mode") == "chat" and created >= request_stamp:
                    conversation_id = candidate["id"]
                    break
            if conversation_id is not None:
                bind_source = ("db:conversations (أحدث محادثة chat "
                               "أُنشئت بعد بدء الطلب)")
        except Exception as error:  # noqa: BLE001 — البديل اختياري
            evidence.unavailable("conversation_id",
                                 f"تعذّر البديل من القاعدة: {error}")

    research = {kind: 0 for kind in RESEARCH_KINDS}
    research_payloads: dict[str, list] = {kind: [] for kind in RESEARCH_KINDS}
    completed = None
    chat_error = None
    started_event = None
    last_status = None
    for event in events:
        kind = event.get("kind")
        if kind in research:
            research[kind] += 1
            if len(research_payloads[kind]) < 5:
                research_payloads[kind].append({
                    "at": None,
                    "details": event.get("details") or {},
                    "text": (event.get("text") or "")[:300],
                    "status": event.get("status"),
                })
        elif kind == "message_started" and started_event is None:
            started_event = event
        elif kind == "chat.status":
            last_status = event.get("status")
        elif kind == "message_completed":
            completed = event
        elif kind == "chat.error":
            chat_error = event

    def _details_of(kind: str) -> list[dict]:
        return [item["details"] for item in research_payloads.get(kind, [])]

    result_sources: list = []
    for details in _details_of("research.results"):
        result_sources.extend(details.get("results") or [])
    used_sources: list = []
    for details in _details_of("research.used"):
        used_sources.extend(details.get("sources") or [])
    claimed_entries = len(result_sources) + len(used_sources)
    claimed_raw = [
        (item.get("url") if isinstance(item, dict) else item)
        for item in result_sources + used_sources
    ]
    claimed_distinct = list(dict.fromkeys(
        str(url).strip() for url in claimed_raw if url
    ))
    real_urls = http_.real_source_urls(result_sources + used_sources)
    invalid_urls = [url for url in claimed_distinct
                    if not http_.is_real_url(url)]

    # الرسالة المحفوظة — الحقيقة الدائمة عند غياب الاكتمال في البث
    persisted: dict = {"conversation_id": conversation_id, "messages": [],
                       "source": None, "error": None}
    if conversation_id is not None:
        messages_result = http_.get_json(
            args.base_url, f"/api/conversations/{conversation_id}/messages",
            timeout=args.request_timeout,
        )
        evidence.step("b-chat-messages", "GET /api/conversations/{id}/messages",
                      messages_result)
        if messages_result["ok"] and isinstance(messages_result["data"], dict):
            persisted["messages"] = [
                {"role": m.get("role"),
                 "chars": len(m.get("content") or ""),
                 "content_head": (m.get("content") or "")[:400],
                 "created_at": m.get("created_at")}
                for m in messages_result["data"].get("messages") or []
            ]
            persisted["source"] = "HTTP GET /messages"
    assistant = next((m for m in reversed(persisted["messages"])
                      if m["role"] == "assistant"), None)
    details = (completed or {}).get("details") or {}
    answer_chars = details.get("chars")
    answer_source = "SSE:message_completed.details.chars"
    if answer_chars is None and assistant is not None:
        answer_chars = assistant["chars"]
        answer_source = "db/HTTP:messages (رسالة assistant المحفوظة)"
    if answer_chars is None:
        evidence.unavailable("chat.answer_chars",
                             "لا message_completed ولا رسالة assistant محفوظة")
        answer_source = None

    # ---- (013.6 §11) تصنيف نتيجة البحث — ثلاث حالات لا بوليان ----
    def classify_web_outcome() -> tuple[str, str]:
        """«صفر نتائج» ليس دليل نجاح بحث (013.6 §11).

        الفحص السابق كان ``claimed_entries == 0 or len(real_urls) > 0``
        فينجح **تلقائيًا** حين لا يُرجع البحث شيئًا: أي أن غياب النتائج
        كان يُقرأ كنجاح. المالك رفض هذا حرفيًا. التصنيف الآن صريح:

            WEB_NOT_CALLED                لم يُستدعَ البحث أصلًا
            WEB_CALLED_NO_RESULTS         استُدعي فعلًا ولم يُرجع نتيجة
            WEB_RESULTS_WITH_REAL_SOURCES نتائج بروابط حقيقية
            WEB_RESULTS_WITHOUT_REAL_SOURCES
                                          إدخالات بلا رابط حقيقي (تلفيق)

        الحالة الرابعة أُضيفت فوق الثلاث المطلوبة لأنها تحمل الفحص
        الأصلي الذي لا يجوز فقدانه: «نتيجة بلا مصدر حقيقي = فشل».
        """
        called = any((
            research["research.started"], research["research.results"],
            research["research.used"], research["research.unavailable"],
        ))
        if not called:
            return ("WEB_NOT_CALLED",
                    "لم يظهر أي حدث بحث — الكاشف لم يُفعّل لهذا السؤال")
        if claimed_entries == 0:
            declared = research["research.unavailable"] > 0
            return (
                "WEB_CALLED_NO_RESULTS",
                "استُدعي البحث فعلًا ولم يُرجع أي نتيجة"
                + (" — وأُعلن عدم التوفر بصدق"
                   if declared else " — بلا إعلان صريح"),
            )
        if real_urls:
            return (
                "WEB_RESULTS_WITH_REAL_SOURCES",
                f"{len(real_urls)} رابط حقيقي من "
                f"{len(claimed_distinct)} رابطًا مميزًا",
            )
        return (
            "WEB_RESULTS_WITHOUT_REAL_SOURCES",
            f"{claimed_entries} إدخال مصدر بلا رابط حقيقي واحد",
        )

    web_outcome, web_note = classify_web_outcome()
    # حكم بحث الويب **منفصل** عن حكم خطة المشروع: فشل البحث الصادق
    # في بيئة محجوبة لا يجوز أن يُسقط قبول التخطيط، ولا أن يمرّ أخضر.
    evidence.data["web_search"] = {
        "outcome": web_outcome,
        "note": web_note,
        "verified": web_outcome == "WEB_RESULTS_WITH_REAL_SOURCES",
        "classifications": [
            "WEB_NOT_CALLED", "WEB_CALLED_NO_RESULTS",
            "WEB_RESULTS_WITH_REAL_SOURCES",
            "WEB_RESULTS_WITHOUT_REAL_SOURCES",
        ],
        "behaviour_expected": (
            "نجاح بحث الويب يستلزم نتيجة حقيقية واحدة على الأقل؛ "
            "صفر نتائج يُعلَن فشلًا صادقًا لا نجاحًا"
        ),
    }

    chat_block = {
        "conversation_id": conversation_id,
        "conversation_id_source": bind_source,
        "request": request_body,
        "stream": {
            "status": result.get("status"), "ok": result.get("ok"),
            "terminal_kind": stream.get("terminal_kind"),
            "timed_out": stream.get("timed_out"),
            "events": len(events), "counters": stream.get("counters"),
            "error": result.get("error"),
            "duration_ms": result.get("duration_ms"),
            "unparsed": stream.get("unparsed") or [],
        },
        "research_event_counts": research,
        "research_appeared": {
            kind: research[kind] > 0 for kind in RESEARCH_KINDS
            if kind in ("research.started", "research.results",
                        "research.used", "research.unavailable")
        },
        "research_payloads": research_payloads,
        "research_observed": any(count > 0 for count in research.values()),
        "research_outcome": None,
        "claimed_source_entries": claimed_entries,
        "claimed_distinct_urls": claimed_distinct,
        "invalid_source_urls": invalid_urls[:10],
        "real_source_urls": real_urls,
        "real_source_count": len(real_urls),
        "answer_chars": answer_chars,
        "answer_chars_source": answer_source,
        "answer_head": (assistant or {}).get("content_head"),
        "message_started_provider": (
            (started_event or {}).get("details") or {}
        ).get("provider"),
        "message_started_model": (
            (started_event or {}).get("details") or {}
        ).get("model"),
        "completed": {
            "provider": details.get("provider"),
            "model": details.get("model"),
            "chars": details.get("chars"),
            "duration_ms": details.get("duration_ms"),
            "streamed": details.get("streamed"),
            "tokens": details.get("tokens"),
            "web_used": details.get("web_used"),
        } if completed else None,
        "error": {
            "code": (chat_error or {}).get("code"),
            "text": ((chat_error or {}).get("text") or "")[:300],
            "details": (chat_error or {}).get("details") or {},
        } if chat_error else None,
        "last_status": last_status,
        "persisted_messages": persisted,
        "db_timeline": _chat_timeline_from_db(db_path, conversation_id)
        if conversation_id is not None else None,
    }
    # (013.6 §11) التصنيف الثلاثي يُثبَّت على الكتلة بعد بنائها
    chat_block["web_outcome"] = web_outcome
    chat_block["web_outcome_note"] = web_note
    if research["research.unavailable"]:
        chat_block["research_outcome"] = "WEB_UNAVAILABLE (إعلان صادق)"
    elif research["research.results"] or research["research.used"]:
        chat_block["research_outcome"] = "WEB_USED"
    elif research["research.started"]:
        chat_block["research_outcome"] = "STARTED_WITHOUT_OUTCOME"
    else:
        chat_block["research_outcome"] = "NO_RESEARCH_EVENTS"
    evidence.data["chat"] = chat_block

    # ---- الفحوص ----
    print(f"    أحداث البحث: "
          + ", ".join(f"{k}={v}" for k, v in research.items() if v)
          if any(research.values()) else "    أحداث البحث: لا شيء", flush=True)
    print(f"    نتائج معلنة: {claimed_entries} إدخال | روابط مميزة: "
          f"{len(claimed_distinct)} | حقيقية: {len(real_urls)} | "
          f"غير صالحة: {len(invalid_urls)}", flush=True)
    print(f"    طول الجواب: {answer_chars} ({answer_source})", flush=True)

    evidence.check("b-chat-conversation-created", conversation_id is not None,
                   f"conversation_id={conversation_id} ({bind_source})")
    if completed is not None:
        evidence.check(
            "b-chat-answer-received", bool(answer_chars),
            f"message_completed chars={details.get('chars')} "
            f"streamed={details.get('streamed')}",
        )
    else:
        explicit = bool(chat_error and (chat_error.get("code")))
        evidence.check(
            "b-chat-answer-received", False,
            "لا message_completed — "
            + (f"فشل مصنّف صريح: {chat_error.get('code')}"
               if explicit else "ولا خطأ مصنّف معلن (فشل صامت)"),
            level="truthful" if explicit else "critical",
        )
    # (013.6 §11) الفحص القديم كان ينجح عند صفر نتائج (فراغ مُقنَّع).
    # الآن: لكل تصنيف فحصه الصادق — ولا يمرّ «نتائج بمصادر حقيقية»
    # إلا بوجود رابط حقيقي واحد على الأقل.
    evidence.check("b-web-outcome-classified", True,
                   f"{web_outcome} — {web_note}", level="info")
    if web_outcome == "WEB_RESULTS_WITH_REAL_SOURCES":
        evidence.check("b-web-results-have-real-sources", True, web_note)
    elif web_outcome == "WEB_RESULTS_WITHOUT_REAL_SOURCES":
        evidence.check(
            "b-web-results-have-real-sources", False,
            web_note + " — «نتيجة بلا مصدر حقيقي = فشل»",
            level="truthful",
        )
    elif web_outcome == "WEB_CALLED_NO_RESULTS":
        evidence.check(
            "b-web-call-returned-no-results", True,
            web_note + " — لم يُدَّع نجاح بحث ولا لُفِّقت مصادر",
            level="truthful",
        )
    else:
        evidence.check("b-web-not-called", False, web_note, level="info")
    if chat_block["research_outcome"] == "WEB_UNAVAILABLE":
        evidence.check("b-web-unavailable-declared", True,
                       "WEB_UNAVAILABLE معلنة بالسبب الصادق — لا نتائج ملفقة",
                       level="truthful")
    elif chat_block["research_outcome"] == "NO_RESEARCH_EVENTS":
        evidence.check("b-web-research-triggered", False,
                       "لم يظهر أي حدث بحث — الكاشف لم يُفعّل أو الحادث "
                       "لم يصل", level="info")
    return chat_block


# ------------------------------------------------------------------ #
# §P.c — إنشاء المشروع بالهدف الحرفي
# ------------------------------------------------------------------ #

def step_project(args, config: dict, evidence: Evidence) -> dict | None:
    """(ج) مشروع جديد بهدف OSINT الحرفي — بلا تعديل حرف واحد."""
    print("\n[ج] إنشاء مشروع بالهدف الحرفي", flush=True)
    body = {
        "name": "قبول 013.5 — منصة OSINT",
        "objective": PROJECT_OBJECTIVE,
    }
    result = http_.post_json(args.base_url, "/api/projects", body,
                             timeout=args.request_timeout)
    evidence.step("c-project-create", "POST /api/projects", result,
                  request=body)
    if not result["ok"] or not isinstance(result["data"], dict):
        print(f"  ❌ تعذّر إنشاء المشروع: {result.get('error')}", flush=True)
        evidence.check("c-project-created", False,
                       f"POST /api/projects فشل: {result.get('error')}")
        return None
    project = result["data"]
    objective_echo = project.get("objective")
    exact = objective_echo == PROJECT_OBJECTIVE
    block = {
        "project_id": project.get("id"),
        "name": project.get("name"),
        "objective_requested": PROJECT_OBJECTIVE,
        "objective_stored": objective_echo,
        "objective_exact_match": exact,
        "status_at_create": project.get("status"),
        "created_at": project.get("created_at"),
        "execution_policy": project.get("execution_policy"),
        "created_at_local": result.get("at"),
        "response_status": result.get("status"),
    }
    evidence.data["project"] = block
    print(f"  project_id={block['project_id']} "
          f"status={block['status_at_create']}", flush=True)
    evidence.check("c-project-created", bool(block["project_id"]),
                   f"id={block['project_id']} status={block['status_at_create']}")
    evidence.check("c-objective-stored-literally", exact,
                   "الهدف مخزّن حرفيًا كما طُلب" if exact
                   else f"المخزّن: {objective_echo!r}")
    return block


def step_trigger_planning(args, project_id: int, config: dict,
                          evidence: Evidence) -> dict:
    """(د-١) أمر توليد الخطة — نصدره لا ننتظره (خلفي محدود)."""
    print("\n[د-١] أمر توليد الخطة (POST /plan/generate)", flush=True)
    result = http_.post_json(args.base_url,
                             f"/api/projects/{project_id}/plan/generate",
                             {}, timeout=args.request_timeout)
    evidence.step("d-plan-generate",
                  "POST /api/projects/{id}/plan/generate", result)
    data = result["data"] if isinstance(result["data"], dict) else {}
    session = data.get("session") or {}
    block = {
        "ok": result["ok"], "status": result["status"],
        "error": result.get("error"),
        "started": data.get("started"),
        "reason": data.get("reason"),
        "at": result.get("at"),
        "session": {
            "id": session.get("id"),
            "state": session.get("state"),
            "provider": session.get("provider"),
            "model": session.get("model"),
            "request_id": session.get("request_id"),
            "attempt": session.get("attempt"),
            "started_at": session.get("started_at"),
            "heartbeat_at": session.get("heartbeat_at"),
            "last_meaningful_activity_at":
                session.get("last_meaningful_activity_at"),
            "hard_deadline_at": session.get("hard_deadline_at"),
            "hard_timeout_s": session.get("hard_timeout_s"),
            "lease_expires_at": session.get("lease_expires_at"),
            "error_class": session.get("error_class"),
        },
        "project_status_after": (data.get("project") or {}).get("status"),
        "raw_started": data.get("started"),
    }
    evidence.data["planning_trigger"] = block
    if not result["ok"]:
        print(f"  ❌ الأمر فشل: {result.get('error')}", flush=True)
        evidence.check("d-planning-command-accepted", False,
                       f"POST /plan/generate: {result.get('error')}")
        return block
    print(f"  started={block['started']} "
          f"session_id={block['session'].get('id')} "
          f"state={block['session'].get('state')} "
          f"provider={block['session'].get('provider')} "
          f"model={block['session'].get('model')}", flush=True)
    evidence.check(
        "d-planning-command-accepted",
        bool(data.get("started")) or data.get("reason") == "already_generating",
        f"started={data.get('started')} reason={data.get('reason')} "
        f"session={session.get('id')} request_id={session.get('request_id')}",
    )
    if session:
        provider_ok = same_provider(session.get("provider"),
                                    config["thinker_selection"].get("provider"))
        model_ok = session.get("model") == config["thinker_selection"].get("model")
        evidence.check(
            "d-planning-session-uses-live-config", provider_ok and model_ok,
            f"الجلسة: {session.get('provider')} / {session.get('model')} | "
            f"التهيئة الحية (thinker): "
            f"{config['thinker_selection'].get('provider')} / "
            f"{config['thinker_selection'].get('model')}",
        )
    return block


# ------------------------------------------------------------------ #
# §P.d/§P.f — الاستطلاع والخط الزمني
# ------------------------------------------------------------------ #

def poll_planning(args, project_id: int, terminal_states: tuple,
                  evidence: Evidence) -> dict:
    """(د-٢ + و) استطلاع اللقطة القانونية حتى الخروج من PLANNING أو المهلة."""
    print(f"\n[د-٢] استطلاع اللقطة القانونية (مهلة "
          f"{args.planning_timeout:.0f}ث)", flush=True)
    started = time.monotonic()
    deadline = started + float(args.planning_timeout)
    polls: list[dict] = []
    transitions: list[dict] = []
    heartbeats: list[dict] = []
    last_status = None
    last_session_state = None
    exit_reason = "timeout"
    final_snapshot: dict | None = None

    while True:
        result = http_.get_json(args.base_url,
                                f"/api/projects/{project_id}/runtime",
                                timeout=args.request_timeout)
        now = time.monotonic()
        elapsed = round(now - started, 1)
        if not result["ok"] or not isinstance(result["data"], dict):
            evidence.step("d-runtime-poll-error",
                          "GET /api/projects/{id}/runtime (فشل)",
                          result)
            evidence.check("d-runtime-snapshot-readable", False,
                           f"فشل قراءة اللقطة: {result.get('error')}")
            exit_reason = "snapshot_unreadable"
            break
        snapshot = result["data"]
        planning = snapshot.get("planning") or {}
        detail = planning.get("detail") or {}
        sample = {
            "at": result["at"],
            "elapsed_s": elapsed,
            "status": snapshot.get("status"),
            "stage": snapshot.get("stage"),
            "planning_state": planning.get("state"),
            "planning_active": planning.get("active"),
            "wait_phase": planning.get("wait_phase"),
            "session_id": detail.get("id"),
            "request_id": detail.get("request_id"),
            "provider": detail.get("provider"),
            "model": detail.get("model"),
            "attempt": detail.get("attempt"),
            "silence_s": detail.get("silence_s"),
            "heartbeat_at": detail.get("heartbeat_at"),
            "last_meaningful_activity_at":
                detail.get("last_meaningful_activity_at"),
            "hard_deadline_at": detail.get("hard_deadline_at") or
                detail.get("hard_deadline_derived_at"),
            "lease_expires_at": detail.get("lease_expires_at"),
            "elapsed_session_s": detail.get("elapsed_s"),
            "error_class": detail.get("error_class"),
            "waiting_for": snapshot.get("waiting_for"),
            "blocking_reason": snapshot.get("blocking_reason"),
            "last_error": snapshot.get("last_error"),
            "job": snapshot.get("job"),
            "progress_percent": (snapshot.get("progress") or {}).get("percent"),
            "available_actions": snapshot.get("available_actions"),
        }
        polls.append(sample)
        if sample["heartbeat_at"] or sample["last_meaningful_activity_at"]:
            heartbeats.append({
                "at": result["at"], "elapsed_s": elapsed,
                "heartbeat_at": sample["heartbeat_at"],
                "last_meaningful_activity_at":
                    sample["last_meaningful_activity_at"],
                "silence_s": sample["silence_s"],
                "session_state": sample["planning_state"],
            })
        if sample["status"] != last_status or \
                sample["planning_state"] != last_session_state:
            transitions.append({
                "at": result["at"], "elapsed_s": elapsed,
                "from_status": last_status, "to_status": sample["status"],
                "from_session_state": last_session_state,
                "to_session_state": sample["planning_state"],
                "wait_phase": sample["wait_phase"],
                "error_class": sample["error_class"],
                "last_error": sample["last_error"],
            })
            last_status = sample["status"]
            last_session_state = sample["planning_state"]
        print(f"    t+{elapsed:>6.1f}ث status={sample['status']:<24} "
              f"session={sample['planning_state']} "
              f"phase={sample['wait_phase']} "
              f"silence={sample['silence_s']} "
              f"err={sample['error_class']}", flush=True)

        final_snapshot = snapshot
        session_terminal = sample["planning_state"] in terminal_states
        if sample["status"] != "PLANNING" and session_terminal \
                and not sample["planning_active"]:
            exit_reason = "left_planning_with_terminal_session"
            break
        if now >= deadline:
            exit_reason = ("timeout_still_planning"
                           if sample["status"] == "PLANNING"
                           else "timeout_session_not_terminal")
            break
        time.sleep(max(0.2, float(args.poll_interval)))

    total = round(time.monotonic() - started, 1)
    block = {
        "timeout_s": float(args.planning_timeout),
        "elapsed_s": total,
        "exit_reason": exit_reason,
        "poll_interval_s": float(args.poll_interval),
        "poll_count": len(polls),
        "polls": polls,
        "state_transitions": transitions,
        "heartbeat_timing": heartbeats,
        "final_snapshot": final_snapshot,
    }
    evidence.data["planning_polling"] = block
    print(f"    انتهى الاستطلاع: {exit_reason} بعد {total:.1f}ث "
          f"({len(polls)} استطلاعة)", flush=True)
    evidence.check(
        "d-planning-left-planning-within-timeout",
        exit_reason == "left_planning_with_terminal_session",
        {
            "left_planning_with_terminal_session":
                f"خرج من PLANNING إلى حالة نهائية خلال {total:.1f}ث",
            "timeout_still_planning":
                f"❌ بقي PLANNING حتى نهاية المهلة ({total:.1f}ث) — "
                "«تخطيط لا ينتهي بذكاء»",
            "timeout_session_not_terminal":
                f"❌ انتهت المهلة وجلسة التخطيط ليست نهائية "
                "(GENERATING حية بلا إنهاء مفهوم)",
            "snapshot_unreadable":
                "❌ تعذّرت قراءة اللقطة القانونية",
        }.get(exit_reason, exit_reason),
    )
    return block


def collect_planning_evidence(args, project_id: int, polling: dict,
                              terminal_states: tuple, error_classes: tuple,
                              evidence: Evidence) -> dict:
    """(هـ + و) جمع الأدلة النهائية: اللقطة، الحالة، الأحداث، صفوف الجلسة."""
    print("\n[هـ+و] جمع الأدلة النهائية والخط الزمني", flush=True)
    runtime_result = http_.get_json(args.base_url,
                                    f"/api/projects/{project_id}/runtime",
                                    timeout=args.request_timeout)
    evidence.step("f-runtime-final", "GET /api/projects/{id}/runtime",
                  runtime_result)
    state_result = http_.get_json(args.base_url,
                                  f"/api/projects/{project_id}/state",
                                  timeout=args.request_timeout)
    evidence.step("f-state-final", "GET /api/projects/{id}/state",
                  state_result)
    steps_result = http_.get_json(args.base_url,
                                  f"/api/projects/{project_id}/steps",
                                  timeout=args.request_timeout)
    evidence.step("f-steps-final", "GET /api/projects/{id}/steps",
                  steps_result)
    events_result = http_.get_json(
        args.base_url, f"/api/projects/{project_id}/events?limit=500",
        timeout=args.request_timeout)
    evidence.step("f-events", "GET /api/projects/{id}/events?limit=500",
                  events_result)
    runs_result = http_.get_json(args.base_url, "/api/projects/runs/active",
                                 timeout=args.request_timeout)
    evidence.step("f-runs-active", "GET /api/projects/runs/active",
                  runs_result)

    snapshot = runtime_result["data"] if runtime_result["ok"] else None
    state = state_result["data"] if state_result["ok"] else None
    project_row = state if isinstance(state, dict) else (snapshot or {})
    events = ((events_result.get("data") or {}).get("events")
              if events_result["ok"] else []) or []

    # ---- صفوف جلسة التخطيط من القاعدة (الحقيقة الدائمة) ----
    db_sessions: list[dict] = []
    db_project: dict | None = None
    db_failure = None
    try:
        connection = http_.db_connect_ro(args.db_resolved)
        db_sessions, db_failure = http_.safe_db(
            connection,
            "select * from planning_sessions where project_id = ? "
            "order by id",
            (project_id,),
        )
        project_rows, project_failure = http_.safe_db(
            connection,
            "select id, name, objective, status, created_at, updated_at, "
            "current_plan_id, current_phase_id, current_step_id, "
            "last_error, execution_policy, archived_at from projects "
            "where id = ?",
            (project_id,),
        )
        db_project = project_rows[0] if project_rows else None
        db_failure = db_failure or project_failure
        connection.close()
    except Exception as error:  # noqa: BLE001 — قراءة كمالية معلنة
        db_failure = f"{type(error).__name__}: {error}"
    if db_failure:
        evidence.unavailable("planning_sessions(db)",
                             f"قراءة القاعدة فشلت: {db_failure}")

    latest_session = db_sessions[-1] if db_sessions else None
    session_detail = ((snapshot or {}).get("planning") or {}).get("detail") or {}
    final_status = (snapshot or {}).get("status") or \
        (db_project or {}).get("status")
    session_state = (latest_session or {}).get("state") or \
        session_detail.get("state")
    error_class = (latest_session or {}).get("error_class") or \
        session_detail.get("error_class")
    error_detail = (latest_session or {}).get("error_detail") or \
        session_detail.get("error_detail")
    plan_id = (latest_session or {}).get("plan_id") or \
        session_detail.get("plan_id")
    last_error = (snapshot or {}).get("last_error") or \
        (db_project or {}).get("last_error") or ""

    plan_created_events = [e for e in events
                           if e.get("kind") in ("PLAN_CREATED",
                                                "PLAN_APPROVAL_REQUIRED")]
    failure_events = [e for e in events
                      if e.get("kind") in ("PLANNING_FAILED",
                                           "PLANNING_INTERRUPTED",
                                           "PLANNING_RETRY")]
    provider_calls = [
        {"kind": e.get("kind"), "created_at": e.get("created_at"),
         "duration_ms": (e.get("payload") or {}).get("duration_ms"),
         "provider": (e.get("payload") or {}).get("provider"),
         "model": (e.get("payload") or {}).get("model"),
         "request_id": (e.get("payload") or {}).get("request_id"),
         "session_id": (e.get("payload") or {}).get("session_id"),
         "error_class": (e.get("payload") or {}).get("error_class")}
        for e in events
        if e.get("kind") in ("MODEL_CALL_STARTED", "MODEL_CALL_COMPLETED",
                             "MODEL_CALL_FAILED", "PLAN_GENERATING")
    ]

    # ---- الحقول المطلوبة (§P.هـ) مع مسار كل قيمة ----
    hunt_runtime = deep_find(
        snapshot or {}, ("environment_id", "worker_id", "workspace",
                         "backend", "run_id", "job_id", "stage",
                         "correlation_id"),
    )
    hunt_state = deep_find(
        state or {}, ("environment_id", "workspace", "backend", "run_id",
                      "job_id", "selected", "correlation_id"),
    )
    hunt_events = deep_find(events, ("workspace", "environment_id",
                                     "backend", "run_id", "correlation_id"))
    phases = (state or {}).get("phases") or []
    steps = (steps_result.get("data") or {}).get("steps") \
        if steps_result["ok"] else []
    current_phase_id = (snapshot or {}).get("current_phase_id")
    current_step_id = (snapshot or {}).get("current_step_id")
    current_phase = next((p for p in phases
                          if p.get("id") == current_phase_id), None)
    current_step = next((s for s in steps or []
                         if s.get("id") == current_step_id), None)
    job = (snapshot or {}).get("job") or {}
    active_run = (state or {}).get("active_run") if isinstance(state, dict) \
        else None
    runs_payload = (runs_result.get("data") or {}) if runs_result["ok"] else {}
    environment_block = (state or {}).get("environment") or {} \
        if isinstance(state, dict) else {}
    runtime_state = environment_block.get("runtime_state") or {}

    recorded = {
        "project_id": project_id,
        "conversation_id": evidence.data.get("chat", {}).get("conversation_id"),
        # run_id: لا يُخترع — نأخذه من حقل معلن إن وُجد، وإلا من
        # correlation_id المُبَثّ فعلًا (workflow/runner.py:79-86 هو
        # هوية التشغيل)، وإلا null مع بيان المتاح.
        "run_id": field(evidence, hunt_runtime, "run_id")
        or field(evidence, hunt_state, "run_id")
        or field(evidence, hunt_events, "run_id")
        or field(evidence, hunt_events, "correlation_id")
        or field(evidence, hunt_runtime, "correlation_id"),
        "run_id_sources": {
            "runtime": source_of(hunt_runtime, "run_id"),
            "state": source_of(hunt_state, "run_id"),
            "events.run_id": source_of(hunt_events, "run_id"),
            "events.correlation_id": source_of(hunt_events, "correlation_id"),
            "runs_active": "/api/projects/runs/active.active_run "
                           "(يعيد project_id فقط — لا run_id)",
        },
        "active_run_reference": {
            "runs_active_payload": runs_payload.get("active_run"),
            "state_active_run": active_run,
            "note": "‎/api/projects/runs/active يُصدّر project_id لا معرّف "
                    "تشغيل؛ job_id وcorrelation_id هما الهويات المتاحة",
        },
        "job_id": field(evidence, hunt_runtime, "job_id") or job.get("id"),
        "planning_session_id": (latest_session or {}).get("id") or
            session_detail.get("id"),
        "request_id": (latest_session or {}).get("request_id") or
            session_detail.get("request_id"),
        "provider": (latest_session or {}).get("provider") or
            session_detail.get("provider"),
        "model": (latest_session or {}).get("model") or
            session_detail.get("model"),
        "actual_provider": (latest_session or {}).get("actual_provider"),
        "actual_model": (latest_session or {}).get("actual_model"),
        "environment_id": runtime_state.get("environment_id")
            or field(evidence, hunt_runtime, "environment_id")
            or field(evidence, hunt_state, "environment_id"),
        "environment_id_source": (
            "state.environment.runtime_state.environment_id"
            if runtime_state.get("environment_id") else
            source_of(hunt_runtime, "environment_id")
            or source_of(hunt_state, "environment_id")),
        "backend": (environment_block.get("selected") or {}).get("backend")
            or field(evidence, hunt_runtime, "backend")
            or field(evidence, hunt_state, "backend"),
        "backend_source": (
            "state.environment.selected.backend"
            if (environment_block.get("selected") or {}).get("backend") else
            source_of(hunt_runtime, "backend")
            or source_of(hunt_state, "backend")),
        "workspace": field(evidence, hunt_runtime, "workspace")
            or field(evidence, hunt_state, "workspace")
            or field(evidence, hunt_events, "workspace"),
        "workspace_source": source_of(hunt_runtime, "workspace")
            or source_of(hunt_state, "workspace")
            or source_of(hunt_events, "workspace"),
        "phase": ({
            "id": current_phase.get("id"),
            "title": current_phase.get("title"),
            "status": current_phase.get("status"),
            "plan_id": current_phase.get("plan_id"),
        } if current_phase else None),
        "stage": (snapshot or {}).get("stage"),
        "stage_label": ((snapshot or {}).get("stage_labels") or {}).get(
            (snapshot or {}).get("stage")),
        "step": ({
            "id": current_step.get("id"),
            "objective": current_step.get("objective"),
            "status": current_step.get("status"),
            "phase_id": current_step.get("phase_id"),
        } if current_step else None),
        "status": final_status,
        "last_error": last_error,
        "execution_policy": (project_row or {}).get("execution_policy")
            or (db_project or {}).get("execution_policy"),
        "planning_failure_count": len(failure_events),
        "recorded_at": http_.utc_now(),
        # طوابع زمنية حقيقية من ردود HTTP/صفوف القاعدة — لا ساعة مخترعة
        "timestamps": {
            "chat_stream_started_at": step_at(evidence, "b-chat-stream"),
            "chat_stream_duration_ms": step_duration(evidence, "b-chat-stream"),
            "chat_messages_read_at": step_at(evidence, "b-chat-messages"),
            "project_created_at": (evidence.data.get("project") or {}).get(
                "created_at"),
            "planning_command_at": (evidence.data.get(
                "planning_trigger") or {}).get("at"),
            "planning_session_started_at": (latest_session or {}).get(
                "started_at") or session_detail.get("started_at"),
            "planning_session_finished_at": (latest_session or {}).get(
                "finished_at") or session_detail.get("finished_at"),
            "planning_last_heartbeat_at": (latest_session or {}).get(
                "heartbeat_at") or session_detail.get("heartbeat_at"),
            "planning_last_meaningful_activity_at": (latest_session or {}).get(
                "last_meaningful_activity_at")
                or session_detail.get("last_meaningful_activity_at"),
            "project_updated_at": (project_row or {}).get("updated_at"),
            "first_poll_at": (polling.get("polls") or [{}])[0].get("at"),
            "last_poll_at": (polling.get("polls") or [{}])[-1].get("at"),
            "final_snapshot_read_at": runtime_result.get("at"),
            "evidence_collected_at": http_.utc_now(),
            "source": "طوابع ردود HTTP (envelope.at) وأعمدة القاعدة — "
                      "لا قيمة مركّبة",
        },
        "sources": {
            "snapshot": "/api/projects/{id}/runtime",
            "state": "/api/projects/{id}/state",
            "events": "/api/projects/{id}/events",
            "sessions": f"sqlite3(read-only) {args.db_resolved}"
                        "#planning_sessions",
        },
    }
    for name in ("run_id", "planning_session_id", "request_id",
                 "environment_id", "backend", "workspace", "phase", "step"):
        if recorded.get(name) in (None, "", {}, []):
            recorded[name] = None
            evidence.unavailable(
                f"recorded_fields.{name}",
                "غير متاح في اللقطات/الأحداث/القاعدة لهذا السيناريو "
                "(التخطيط لم ينتقل إلى تنفيذ)",
            )

    timeline = {
        "project_events": [
            {"id": e.get("id"), "kind": e.get("kind"),
             "created_at": e.get("created_at"), "payload": e.get("payload")}
            for e in events
        ],
        "project_event_kind_counts": {},
        "planning_sessions_rows": db_sessions,
        "planning_session_provider_timing": provider_calls,
        "planning_session_heartbeats": [
            {"at": s.get("at"), "elapsed_s": s.get("elapsed_s"),
             "heartbeat_at": s.get("heartbeat_at"),
             "last_meaningful_activity_at": s.get("last_meaningful_activity_at"),
             "silence_s": s.get("silence_s"),
             "session_state": s.get("planning_state")}
            for s in polling.get("polls") or []
        ],
        "state_transitions": polling.get("state_transitions"),
        "plan_created_events": plan_created_events,
        "failure_events": failure_events,
        "db_read_failure": db_failure,
    }
    for event in events:
        kind = event.get("kind") or ""
        timeline["project_event_kind_counts"][kind] = \
            timeline["project_event_kind_counts"].get(kind, 0) + 1
    evidence.data["timeline"] = timeline
    evidence.data["recorded_fields"] = recorded
    evidence.data["planning_final"] = {
        "project_status": final_status,
        "session_state": session_state,
        "session_terminal": session_state in terminal_states,
        "error_class": error_class,
        "error_detail": error_detail,
        "error_class_known": error_class in error_classes
        if error_class else False,
        "plan_id": plan_id,
        "last_error": last_error,
        "plan_created_events": len(plan_created_events),
        "process": {
            "watchdog_states_terminal": terminal_states,
            "known_error_classes": error_classes,
        },
        "db_project_row": db_project,
        "snapshot_planning": (snapshot or {}).get("planning"),
        "waiting_for": (snapshot or {}).get("waiting_for"),
        "progress": (snapshot or {}).get("progress"),
        "available_actions": (snapshot or {}).get("available_actions"),
    }
    print(f"    الحالة النهائية: {final_status} | جلسة: {session_state} "
          f"| error_class={error_class} | plan_id={plan_id}", flush=True)
    print(f"    أحداث المشروع: {len(events)} | جلسات في القاعدة: "
          f"{len(db_sessions)}", flush=True)
    return recorded


# ------------------------------------------------------------------ #
# الحكم النهائي (§P.g)
# ------------------------------------------------------------------ #

def decide_verdict(config: dict, evidence: Evidence) -> dict:
    """تطبيق القاعدة المعلنة على وقائع مسجّلة — بلا تجميل."""
    final = evidence.data.get("planning_final") or {}
    polling = evidence.data.get("planning_polling") or {}
    terminal_states = tuple(final.get("process", {}).get(
        "watchdog_states_terminal") or _FALLBACK_TERMINAL_SESSION_STATES)
    error_classes = tuple(final.get("process", {}).get(
        "known_error_classes") or _FALLBACK_ERROR_CLASSES)

    status = final.get("project_status")
    session_state = final.get("session_state")
    error_class = final.get("error_class")
    error_detail = final.get("error_detail")
    last_error = final.get("last_error") or ""
    plan_id = final.get("plan_id")
    exit_reason = polling.get("exit_reason")

    left_planning = exit_reason == "left_planning_with_terminal_session"
    session_terminal = session_state in terminal_states
    truthful_success = bool(plan_id) and status in (
        "AWAITING_OWNER_APPROVAL", "DRAFT", "READY")
    truthful_failure = (
        bool(error_class) and error_class in error_classes
        and status in ("DRAFT", "FAILED") and bool(last_error)
    )
    silent_failure = left_planning and not (truthful_success or truthful_failure)

    outcome = None
    if not left_planning:
        outcome = {
            "timeout_still_planning": "PLANNING_LINGERED_PAST_TIMEOUT",
            "timeout_session_not_terminal": "SESSION_NEVER_TERMINATED",
            "snapshot_unreadable": "SNAPSHOT_UNREADABLE",
        }.get(exit_reason, "NO_INTELLIGIBLE_TERMINATION")
    elif not session_terminal:
        outcome = "SESSION_NOT_TERMINAL"
    elif truthful_success:
        outcome = "TRUTHFUL_SUCCESS_PLAN_RECORDED"
    elif truthful_failure:
        outcome = "TRUTHFUL_CLASSIFIED_FAILURE"
    elif silent_failure:
        outcome = "SILENT_UNCLASSIFIED_FAILURE"
    else:
        outcome = "UNCLASSIFIED_OUTCOME"

    evidence.check("d-planning-session-terminal", session_terminal,
                   f"حالة الجلسة: {session_state} "
                   f"(النهائية: {list(terminal_states)})")
    evidence.check(
        "d-planning-outcome-truthful",
        outcome in ("TRUTHFUL_SUCCESS_PLAN_RECORDED",
                    "TRUTHFUL_CLASSIFIED_FAILURE"),
        {
            "TRUTHFUL_SUCCESS_PLAN_RECORDED":
                f"خطة مدوّنة (plan_id={plan_id}) والمشروع {status}",
            "TRUTHFUL_CLASSIFIED_FAILURE":
                f"فشل مصنّف صريح [{error_class}] والمشروع {status} مع "
                f"last_error معلن — صدق لا صمت",
            "SILENT_UNCLASSIFIED_FAILURE":
                "❌ خرج من PLANNING بفشل غير مصنّف/بلا last_error — صمت",
            "SESSION_NOT_TERMINAL":
                f"❌ المشروع {status} لكن جلسة التخطيط {session_state}",
        }.get(outcome, f"❌ {outcome}"),
    )
    if truthful_failure:
        evidence.check(
            "p-classified-failure-is-explicit", True,
            f"error_class={error_class} | detail={str(error_detail)[:160]}",
            level="truthful",
        )

    failures = [c for c in evidence.data["checks"]
                if not c["ok"] and c["level"] == "critical"]
    verified_live = evidence.data.get("live_config_tested", False)
    verdict_pass = len(failures) == 0
    return {
        "result": "PASS" if verdict_pass else "FAIL",
        "outcome_code": outcome,
        "planning_left_planning": left_planning,
        "planning_session_terminal": session_terminal,
        "planning_truthful_success": truthful_success,
        "planning_truthful_failure": truthful_failure,
        "planning_silent_failure": silent_failure,
        "critical_failures": [{"name": c["name"], "note": c["note"]}
                              for c in failures],
        "truthful_observations": [
            {"name": c["name"], "note": c["note"]}
            for c in evidence.data["checks"] if c["level"] == "truthful"
            and not c["ok"]
        ],
        "live_config_tested": verified_live,
        "live_provider": config.get("provider"),
        "live_model": config.get("model"),
        "config_source": config.get("source"),
        # (013.6 §11) حكم بحث الويب منفصل عن حكم التخطيط: لا يُسقط
        # التخطيطَ فشلُ بحث صادق، ولا يمرّ بحثٌ بلا نتيجة كنجاح.
        "web_search": evidence.data.get("web_search") or {
            "outcome": "NOT_EXERCISED",
            "verified": False,
        },
        "rule": VERDICT_RULE,
    }


def print_verdict(verdict: dict, evidence: Evidence) -> None:
    """طباعة الحكم النهائي مع القاعدة وسبب كل سقوط."""
    line = "=" * 78
    print("\n" + line, flush=True)
    if verdict["result"] == "PASS":
        print("  الحكم النهائي: PASS ✅", flush=True)
    else:
        print("  الحكم النهائي: FAIL ❌", flush=True)
    print(line, flush=True)
    print(f"  التهيئة المُختبرة فعليًا: {verdict['live_provider']} / "
          f"{verdict['live_model']}  [المصدر: {verdict['config_source']}]",
          flush=True)
    if not verdict["live_config_tested"]:
        print("  ⚠️  النتيجة لا تثبت زمن التشغيل الحي: "
              "live_config_tested=false (§O)", flush=True)
    print(f"  المشروع خرج من PLANNING: {verdict['planning_left_planning']} | "
          f"الجلسة نهائية: {verdict['planning_session_terminal']} | "
          f"النتيجة المصنّفة: {verdict['outcome_code']}", flush=True)
    if verdict["planning_truthful_failure"]:
        print("  ✔ فشل المزود المعلن فشلًا مصنّفًا مع خروج المشروع من "
              "PLANNING هو PASS (§P): المطلوب الصدق لا اللون الأخضر",
              flush=True)
    web = verdict.get("web_search") or {}
    if web:
        mark = "✅" if web.get("verified") else "•"
        print(f"  {mark} بحث الويب (حكم منفصل حسب §11): "
              f"{web.get('outcome')} — {web.get('note', '')}", flush=True)
        if not web.get("verified"):
            print("     نجاح بحث الويب يستلزم نتيجة حقيقية واحدة على "
                  "الأقل؛ صفر نتائج يُعلَن فشلًا لا نجاحًا", flush=True)
    if verdict["critical_failures"]:
        print("  أسباب السقوط:", flush=True)
        for failure in verdict["critical_failures"]:
            print(f"    ❌ {failure['name']} — {failure['note']}", flush=True)
    if verdict["truthful_observations"]:
        print("  ملاحظات نزاهة (إعلان صادق لا سقوط):", flush=True)
        for observation in verdict["truthful_observations"]:
            print(f"    • {observation['name']} — {observation['note']}",
                  flush=True)
    counts: dict = {}
    for check in evidence.data["checks"]:
        key = (check["level"], "نجح" if check["ok"] else "فشل")
        counts[key] = counts.get(key, 0) + 1
    print("  ملخّص الفحوص: " + " | ".join(
        f"{level}/{status}={count}"
        for (level, status), count in sorted(counts.items())), flush=True)
    print("\n" + VERDICT_RULE, flush=True)
    print(line, flush=True)


# ------------------------------------------------------------------ #
# التشغيل
# ------------------------------------------------------------------ #

def load_process_vocabulary(evidence: Evidence) -> tuple[tuple, tuple]:
    """مفردات الحالات والفشل من src (المصدر الواحد) مع بديل معلن."""
    terminal = _FALLBACK_TERMINAL_SESSION_STATES
    classes = _FALLBACK_ERROR_CLASSES
    terminal_source = "بديل داخلي معلن"
    classes_source = "بديل داخلي معلن"
    try:
        from workflow.planning_runtime import (  # noqa: PLC0415
            TERMINAL_SESSION_STATES,
        )

        terminal = tuple(TERMINAL_SESSION_STATES)
        terminal_source = "src/workflow/planning_runtime.py (TERMINAL_SESSION_STATES)"
    except Exception as error:  # noqa: BLE001
        evidence.note(f"TERMINAL_SESSION_STATES غير مُستورد: {error}")
    try:
        from workflow.models import (  # noqa: PLC0415
            PLANNING_ERROR_CLASSES,
        )

        classes = tuple(PLANNING_ERROR_CLASSES)
        classes_source = ("src/workflow/models.py "
                          "(PLANNING_ERROR_CLASSES)")
    except Exception as error:  # noqa: BLE001
        evidence.note(f"PLANNING_ERROR_CLASSES غير مُستورد: {error}")
    evidence.data["process_vocabulary"] = {
        "terminal_session_states": list(terminal),
        "terminal_session_states_source": terminal_source,
        "planning_error_classes": list(classes),
        "planning_error_classes_source": classes_source,
    }
    return terminal, classes


def default_base_url() -> tuple[str, str]:
    """العنوان الافتراضي — من إعدادات التطبيق لا من نص مخترع."""
    try:
        from core.config import settings as aes_settings  # noqa: PLC0415

        return (f"http://{aes_settings.host}:{aes_settings.port}",
                "src/core/config.py:26-27 (settings.host/port)")
    except Exception:  # noqa: BLE001
        return "http://127.0.0.1:8010", "بديل معلن: 127.0.0.1:8010"


def build_parser() -> argparse.ArgumentParser:
    """وسائط التشغيل — الافتراضي دائمًا «اقرأ التهيئة الحية»."""
    parser = argparse.ArgumentParser(
        prog="order0135_acceptance.py",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        description=(
            "القبول الحي للأمر 013.5 (§A/§B/§O/§P): يقرأ المزود والنموذج "
            "النشطين من التهيئة الحية (GET /api/models/config، وإلا "
            "role_provider_mappings في القاعدة) ويختبرهما فعليًا: محادثة "
            "بحث حقيقية، ثم مشروع OSINT مع توليد خطة واستطلاع حتى "
            "الخروج من PLANNING أو انتهاء المهلة."
        ),
        epilog=VERDICT_RULE + "\n\n"
        "أكواد الخروج: 0=نجاح | 1=سقوط القبول | 2=تعذّر قراءة التهيئة "
        "الحيّة | 3=رفض (نموذج مُثبَّت/وسائط ناقصة) | 4=الخادم غير متاح.",
    )
    parser.add_argument(
        "--base-url", default=None,
        help="عنوان الخادم الجاري (الافتراضي من settings.host/port = "
             "http://127.0.0.1:8010).",
    )
    parser.add_argument(
        "--planning-timeout", type=float, default=900.0,
        help="المهلة الصلبة لخروج المشروع من PLANNING بالثواني "
             "(الافتراضي 900). بقاؤه PLANNING بعدها = FAIL.",
    )
    parser.add_argument(
        "--poll-interval", type=float, default=5.0,
        help="فاصل استطلاع اللقطة القانونية بالثواني (الافتراضي 5).",
    )
    parser.add_argument(
        "--chat-timeout", type=float, default=600.0,
        help="مهلة قراءة بث المحادثة SSE بالثواني (الافتراضي 600).",
    )
    parser.add_argument(
        "--request-timeout", type=float, default=30.0,
        help="مهلة نداءات JSON المفردة بالثواني (الافتراضي 30).",
    )
    parser.add_argument(
        "--db", default=None,
        help="مسار قاعدة التشغيل (الافتراضي من Settings.db_path في "
             "src/core/config.py).",
    )
    parser.add_argument(
        "--out-dir", default=None,
        help="مجلد ملف الأدلة (الافتراضي runtime/evidence).",
    )
    parser.add_argument(
        "--provider", default=None,
        help="تجاوز تشخيصي لمزود واحد (يجب أن يقترن بـ--model) — "
             "النتيجة حينها لا تثبت التهيئة الحية (§O).",
    )
    parser.add_argument(
        "--model", default=None,
        help="تجاوز تشخيصي لنموذج واحد (يجب أن يقترن بـ--provider).",
    )
    return parser


def main(argv: list[str] | None = None) -> int:
    """تشغيل السيناريو كاملًا وإرجاع كود الخروج الصادق."""
    for stream in (sys.stdout, sys.stderr):
        try:
            stream.reconfigure(encoding="utf-8", errors="replace")
        except Exception:  # noqa: BLE001 — كونسول لا يقبل UTF-8
            pass
    args = build_parser().parse_args(argv)
    evidence = Evidence()
    global_defaults, defaults_source = role_defaults()
    evidence.data["role_defaults_source"] = defaults_source

    base_url, base_source = default_base_url()
    if not args.base_url:
        args.base_url = base_url
        evidence.data["base_url_source"] = base_source
    else:
        evidence.data["base_url_source"] = "--base-url (صريح)"
    evidence.data["base_url"] = args.base_url

    out_dir = Path(args.out_dir).expanduser().resolve() if args.out_dir \
        else REPO / "runtime" / "evidence"
    stamp = http_.stamp()
    evidence_path = out_dir / f"order0135-acceptance-{stamp}.json"

    def finish(code: int) -> int:
        evidence.data["finished_at"] = http_.utc_now()
        evidence.data["exit_code"] = code
        out_dir.mkdir(parents=True, exist_ok=True)
        evidence_path.write_text(
            json.dumps(evidence.data, ensure_ascii=False, indent=1,
                       default=str),
            encoding="utf-8",
        )
        print(f"\nالأدلة: {evidence_path}", flush=True)
        return code

    try:
        db_path, db_source = resolve_db_path(args.db, evidence)
        args.db_resolved = db_path
        evidence.data["db_path"] = str(db_path)
        evidence.data["db_path_source"] = db_source
        head = git_head()
        evidence.data["repo"] = head

        print(f"═══ القبول الحي 013.5 — تحضير ═══", flush=True)
        print(f"  رأس المستودع: {head.get('head_sha')} | القاعدة: {db_path}",
              flush=True)

        config = resolve_config(args, db_path, global_defaults, evidence)
        if config is None:
            message = (
                "تعذّر قراءة التهيئة الحية: لا استجابة من "
                f"{http_.join(args.base_url, '/api/models/config')} ولا جدول "
                f"role_provider_mappings في {db_path} — و§O يمنع اختبار "
                "نموذج مُخترع"
            )
            print(f"\n  ⛔ {message}", flush=True)
            evidence.check("p-live-config-resolved", False, message)
            evidence.data["config_resolution"] = None
            return finish(2)
        guard_not_hardcoded(config, args, evidence)
        evidence.data["config_resolution"] = config
        evidence.check(
            "p-live-config-resolved",
            config["source"] in LIVE_SOURCES
            or config["source"] == SOURCE_OVERRIDE,
            f"المصدر: {config['source']} | {config.get('provider')} / "
            f"{config.get('model')}",
        )
        print_banner(args, db_path, db_source, head, config)

        if not step_health(args, evidence):
            print("\n  النتيجة: FAIL — لا خادم جارٍ، والصدق يمنع التمثيل "
                  "(لا نتيجة مصطنعة بلا خادم).", flush=True)
            evidence.check("p-verdict", False,
                           "تعذّر الوصول إلى الخادم — لم يُنفَّذ أي سيناريو")
            return finish(4)

        step_chat(args, db_path, config, evidence)
        project = step_project(args, config, evidence)
        if project is None:
            evidence.check("p-verdict", False, "تعذّر إنشاء المشروع")
            return finish(1)
        project_id = project["project_id"]

        terminal_states, error_classes = load_process_vocabulary(evidence)
        step_trigger_planning(args, project_id, config, evidence)
        polling = poll_planning(args, project_id, terminal_states, evidence)
        collect_planning_evidence(args, project_id, polling, terminal_states,
                                  error_classes, evidence)

        # (و) مطابقة المزود/النموذج الفعلي بالتهيئة الحية — روح §O
        recorded = evidence.data.get("recorded_fields") or {}
        if config["source"] == SOURCE_OVERRIDE:
            evidence.check(
                "p-planning-used-live-provider-model", True,
                "تجاوز صريح — المقارنة مع التهيئة الحية غير مطبَّقة "
                "(live_config_tested=false)", level="info",
            )
            expected = {"provider": args.provider, "model": args.model}
        else:
            expected = {
                "provider": config["thinker_selection"].get("provider"),
                "model": config["thinker_selection"].get("model"),
            }
            evidence.check(
                "p-planning-used-live-provider-model",
                same_provider(recorded.get("provider"), expected["provider"])
                and recorded.get("model") == expected["model"],
                f"جلسة التخطيط: {recorded.get('provider')} / "
                f"{recorded.get('model')} | التهيئة الحية: "
                f"{expected['provider']} / {expected['model']}",
            )
            chat_expected = config["chat_selection"]
            chat_block = evidence.data.get("chat") or {}
            chat_seen = chat_block.get("message_started_provider")
            chat_model_seen = chat_block.get("message_started_model")
            if chat_seen is not None:
                evidence.check(
                    "p-chat-used-live-provider-model",
                    same_provider(chat_seen, chat_expected.get("provider"))
                    and chat_model_seen == chat_expected.get("model"),
                    f"المحادثة: {chat_seen} / {chat_model_seen} | "
                    f"التهيئة الحية (chat): {chat_expected.get('provider')} / "
                    f"{chat_expected.get('model')}",
                )
            else:
                evidence.check("p-chat-used-live-provider-model", True,
                               "لا message_started في البث — لا نستطيع "
                               "الجزم (سُجِّل null)", level="info")
                evidence.unavailable("chat.message_started_provider",
                                     "لم يصل حدث message_started في البث")

        verdict = decide_verdict(config, evidence)
        evidence.check("p-verdict", verdict["result"] == "PASS",
                       f"{verdict['result']} — {verdict['outcome_code']}")
        evidence.data["verdict"] = verdict
        print_verdict(verdict, evidence)
        return finish(0 if verdict["result"] == "PASS" else 1)
    except Refusal as refusal:
        evidence.data["refusal"] = str(refusal)
        evidence.check("p-not-hardcoded-config", False, str(refusal))
        print(f"\n  ⛔ رفض التشغيل: {refusal}", flush=True)
        return finish(3)
    except KeyboardInterrupt:
        evidence.data["interrupted"] = True
        print("\n  أُوقف يدويًا.", flush=True)
        return finish(1)


if __name__ == "__main__":
    raise SystemExit(main())
