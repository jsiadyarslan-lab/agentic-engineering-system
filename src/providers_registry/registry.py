"""سجل المزودين — CRUD دائم + حل المواصفات + مسبار الجاهزية (007.1).

هذه الوحدة هي طبقة الحقيقة الوحيدة للمزودين:

- ensure_seeded: بذر المزودين المدمجين عند أول تشغيل (nvidia/
  openai_compatible/zai_internal) + ترحيل اختيارات runtime/role_model_config.json
  القديمة — لا يُمس ما عدّله المالك لاحقًا.
- resolve_provider_specs: القاعدة ← مواصفات النقل الحية للموجّه
  (transport key = اسم المزود للتكوين الأساسي، أو «مزود::تكوين»).
- probe_configuration: مسبار HTTP حقيقي بتصنيف صريح (READY/AUTH_FAILED/
  NOT_FOUND/…) وتشخيص منظم كامل (§7) — لا «LIVE» بلا نجاح فعلي (§4).

الأسرار: لا قيمة مفتاح تعبر هذه الوحدة إلى أي سجل أو حدث — مرجع
secret_ref فقط، والقيمة من مخزن الأسرار وقت الاستدعاء (§13).
"""

from __future__ import annotations

import datetime as _dt
import json
import time
import urllib.error
import urllib.request
from typing import Any, Callable
from urllib.parse import urlparse

from sqlalchemy import select

from persistence.models import Event
from router.provider_response import classify_network_error  # RLR-001 §1
from providers_registry.models import (
    API_STYLES,
    AUTH_TYPES,
    ProviderConfiguration,
    ProviderRecord,
    RoleProviderMapping,
)

#: البذر المدمج (007.1 §2) — يُنشأ مرة واحدة عند أول تشغيل فقط.
SEED_PROVIDERS: tuple[dict, ...] = (
    {
        "name": "nvidia",
        "display_name": "NVIDIA NIM",
        "type": "nvidia",
        "auth_type": "bearer",
        "configurations": [{
            "name": "default",
            "base_url": "https://integrate.api.nvidia.com/v1",
            # البادئة nvidia/ إلزامية في هذا العنوان — التشخيص الميكانيكي
            # (2026-09-21): قائمة /models الحية (82 نموذجًا) تحتوي
            # nvidia/nemotron-3-ultra-550b-a55b وليس النسخة بلا بادئة —
            # وهذا مصدر 404 المالك الموثق.
            "default_model": "nvidia/nemotron-3-ultra-550b-a55b",
            "models": [
                "nvidia/nemotron-3-ultra-550b-a55b",
                "nemotron-3-ultra-550b-a55b",
            ],
        }],
    },
    {
        "name": "openai_compatible",
        "display_name": "OpenRouter (متوافق OpenAI)",
        "type": "openai_compatible",
        "auth_type": "bearer",
        "configurations": [{
            "name": "default",
            "base_url": "https://openrouter.ai/api/v1",
            "default_model": "anthropic/claude-haiku-3.5",
            "models": ["anthropic/claude-haiku-3.5"],
        }],
    },
    {
        "name": "zai_internal",
        "display_name": "z.ai داخلي (منشأة الحاوية المعلنة)",
        "type": "zai_internal",
        "auth_type": "config_file",
        "configurations": [{
            "name": "default",
            "base_url": "https://internal-api.z.ai/v1",
            "default_model": "glm-4.6",
            "models": ["glm-4.6"],
            "config_file": "/etc/.z-ai-config",
        }],
    },
)


def _utc_now() -> _dt.datetime:
    return _dt.datetime.now(_dt.timezone.utc)


def _api_sessions():
    """جلسة القاعدة في سياق API — بلا سياق (اختبارات مباشرة) = None."""
    try:
        from api import routes  # noqa: PLC0415 — استيراد كسول يمنع الدوران

        return getattr(routes, "_sessions", None)
    except Exception:  # noqa: BLE001 — لا سياق API = لا قاعدة
        return None


def log_provider_event(sessions, kind: str, payload: dict) -> None:
    """حدث مزود دائم (007.1 §16) — جدول events بدور provider.

    لا أسرار في الحدث أبدًا: الحمولة تمر عبر تنقية صريحة للمفاتيح
    الحساسة المعروفة (api_key/key/secret/token قيمها تُستبدل بمرجع).
    """
    clean = {
        key: ("[REDACTED]" if str(key).lower() in
              ("api_key", "key", "secret", "token", "authorization") and value
              else value)
        for key, value in payload.items()
    }
    try:
        with sessions() as session:
            session.add(Event(
                cycle_id=str(clean.get("provider", "providers"))[:64],
                seq=int(_dt.datetime.now().timestamp() * 1000) % 10**9,
                role="provider",
                kind=kind,
                state=None,
                payload=json.dumps(clean, ensure_ascii=False, default=str),
                duration_ms=int(clean.get("latency_ms", 0) or 0),
            ))
            session.commit()
    except Exception:  # noqa: BLE001 — السجل لا يكسر العملية
        pass


# ------------------------------------------------------------------ #
# البذر والترحيل
# ------------------------------------------------------------------ #

def ensure_seeded(sessions) -> bool:
    """بذر المزودين عند أول تشغيل — آمن للتكرار، لا يمس تعديلات المالك."""
    with sessions() as session:
        count = len(session.scalars(select(ProviderRecord)).all())
        if count:
            _migrate_known_model_names(session)
            session.commit()
            _migrate_role_mappings(sessions)
            return False
        for spec in SEED_PROVIDERS:
            provider = ProviderRecord(
                name=spec["name"],
                display_name=spec["display_name"],
                type=spec["type"],
                enabled=True,
                api_style="openai_compatible",
                auth_type=spec["auth_type"],
            )
            session.add(provider)
            session.flush()
            for cfg in spec["configurations"]:
                session.add(ProviderConfiguration(
                    provider_id=provider.id,
                    name=cfg["name"],
                    base_url=cfg["base_url"],
                    api_style="openai_compatible",
                    enabled=True,
                    default_model=cfg.get("default_model", ""),
                    models=json.dumps(cfg.get("models", []), ensure_ascii=False),
                    config_file=cfg.get("config_file", ""),
                ))
        session.commit()
    _migrate_role_mappings(sessions)
    return True


def _migrate_known_model_names(session) -> None:
    """ترحيل معلن (2026-09-21): تصحيح اسم نموذج NVIDIA الافتراضي.

    الدليل ميكانيكي من قائمة المزود الحية نفسها: النموذج في هذا
    العنوان يُعرف بـ«nvidia/nemotron-3-ultra-550b-a55b» — النسخة بلا
    بادئة كانت ترد 404 (تشخيص الأمر 007.1 §7 الموثق). الترحيل لا
    يمس ما عدّله المالك: فقط الاسم القديم المعروف حرفيًا.
    """
    nvidia = session.scalars(
        select(ProviderRecord).where(ProviderRecord.name == "nvidia")
    ).first()
    if nvidia is None:
        return
    correct = "nvidia/nemotron-3-ultra-550b-a55b"
    legacy = "nemotron-3-ultra-550b-a55b"
    for cfg in session.scalars(
        select(ProviderConfiguration)
        .where(ProviderConfiguration.provider_id == nvidia.id)
    ).all():
        if cfg.default_model == legacy:
            cfg.default_model = correct
            try:
                models = json.loads(cfg.models or "[]")
            except ValueError:
                models = []
            if correct not in models:
                models.append(correct)
            cfg.models = json.dumps(models, ensure_ascii=False)
            cfg.updated_at = _utc_now()
    # ربط الأدوار المبذور بالاسم القديم (قيمة البذر لا اختيار المالك)
    for row in session.scalars(select(RoleProviderMapping)).all():
        if row.provider == "nvidia" and row.model == legacy:
            row.model = correct
            row.updated_at = _utc_now()


def _migrate_role_mappings(sessions) -> None:
    """ترحيل اختيارات الأدوار من ملف JSON القديم إن وُجد — مرة واحدة."""
    from router.role_config import ROLE_KEYS  # noqa: PLC0415 — كسول يمنع الدوران

    defaults = _default_mappings()
    with sessions() as session:
        existing = {
            row.role for row in session.scalars(select(RoleProviderMapping)).all()
        }
        if existing:
            return
        migrated = _read_legacy_json()
        for role in ROLE_KEYS:
            found = migrated.get(role) or defaults.get(role) or {}
            session.add(RoleProviderMapping(
                role=role,
                provider=found.get("provider", "nvidia"),
                configuration=found.get("configuration", ""),
                model=found.get("model", "nemotron-3-ultra-550b-a55b"),
            ))
        session.commit()


def _default_mappings() -> dict[str, dict]:
    from router.role_config import DEFAULT_MODEL, DEFAULT_PROVIDER, ROLE_KEYS

    return {
        role: {"provider": DEFAULT_PROVIDER, "configuration": "",
               "model": DEFAULT_MODEL}
        for role in ROLE_KEYS
    }


def _read_legacy_json() -> dict:
    """قراءة runtime/role_model_config.json القديم إن صلح — وإلا فارغ."""
    from router.role_config import CONFIG_PATH

    try:
        raw = json.loads(CONFIG_PATH.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {}
    if not isinstance(raw, dict):
        return {}
    clean = {}
    for key, value in raw.items():
        if isinstance(value, dict) and value.get("provider") and value.get("model"):
            clean[key] = {
                "provider": str(value["provider"]),
                "configuration": str(value.get("configuration", "")),
                "model": str(value["model"]),
            }
    return clean


# ------------------------------------------------------------------ #
# القراءة — المزودون والتكوينات والربط
# ------------------------------------------------------------------ #

def list_providers(sessions) -> list[dict]:
    """كل المزودين بتكويناتهم وجاهزيتهم — بلا أي أسرار."""
    ensure_seeded(sessions)
    out: list[dict] = []
    with sessions() as session:
        providers = session.scalars(
            select(ProviderRecord).order_by(ProviderRecord.id)
        ).all()
        for provider in providers:
            configs = session.scalars(
                select(ProviderConfiguration)
                .where(ProviderConfiguration.provider_id == provider.id)
                .order_by(ProviderConfiguration.id)
            ).all()
            out.append(_provider_payload(provider, configs))
    return out


def _provider_payload(provider: ProviderRecord, configs: list) -> dict:
    from secrets_store import store as secrets

    return {
        "id": provider.id,
        "name": provider.name,
        "display_name": provider.display_name or provider.name,
        "type": provider.type,
        "enabled": provider.enabled,
        "api_style": provider.api_style,
        "auth_type": provider.auth_type,
        "has_key": bool(secrets.get_key(provider.name))
        if provider.auth_type == "bearer" else None,
        "key_masked": secrets.mask(secrets.get_key(provider.name))
        if provider.auth_type == "bearer" and secrets.get_key(provider.name)
        else None,
        "configurations": [
            _config_payload(cfg, provider, is_primary=(index == 0))
            for index, cfg in enumerate(configs)
        ],
        "configurations_count": len(configs),
        "created_at": provider.created_at.isoformat() if provider.created_at else None,
        "updated_at": provider.updated_at.isoformat() if provider.updated_at else None,
    }


def _config_payload(
    cfg: ProviderConfiguration, provider: ProviderRecord,
    *, is_primary: bool = False,
) -> dict:
    try:
        models = json.loads(cfg.models or "[]")
    except ValueError:
        models = []
    return {
        "id": cfg.id,
        "name": cfg.name,
        "base_url": cfg.base_url,
        "api_style": cfg.api_style,
        "enabled": cfg.enabled,
        "default_model": cfg.default_model,
        "models": models,
        "config_file": cfg.config_file or None,
        "auth_type": provider.auth_type,
        "is_primary": is_primary,
        "readiness": {
            "status": cfg.last_readiness_status or "UNTESTED",
            "checked_at": cfg.last_readiness_check.isoformat()
            if cfg.last_readiness_check else None,
        },
    }


def get_provider(sessions, provider_id: int) -> dict | None:
    ensure_seeded(sessions)
    with sessions() as session:
        provider = session.get(ProviderRecord, int(provider_id))
        if provider is None:
            return None
        configs = session.scalars(
            select(ProviderConfiguration)
            .where(ProviderConfiguration.provider_id == provider.id)
            .order_by(ProviderConfiguration.id)
        ).all()
        return _provider_payload(provider, configs)


def get_configuration(sessions, config_id: int) -> ProviderConfiguration | None:
    with sessions() as session:
        return session.get(ProviderConfiguration, int(config_id))


def get_mappings(sessions) -> dict[str, dict]:
    """ربط الأدوار الحالي — {role: {provider, configuration, model}}."""
    from router.role_config import ROLE_KEYS

    ensure_seeded(sessions)
    out: dict[str, dict] = {}
    with sessions() as session:
        rows = {
            row.role: row for row in session.scalars(select(RoleProviderMapping)).all()
        }
    defaults = _default_mappings()
    for role in ROLE_KEYS:
        row = rows.get(role)
        if row is None:
            out[role] = defaults.get(role, {"provider": "nvidia", "configuration": "",
                                            "model": ""})
        else:
            out[role] = {
                "provider": row.provider,
                "configuration": row.configuration or "",
                "model": row.model,
            }
    return out


def save_mappings(sessions, mappings: dict[str, dict]) -> list[str]:
    """حفظ ربط الأدوار — upsert دائم، يعيد الأدوار المحفوظة."""
    from router.role_config import ROLE_KEYS

    saved: list[str] = []
    with sessions() as session:
        rows = {
            row.role: row for row in session.scalars(select(RoleProviderMapping)).all()
        }
        for role, value in mappings.items():
            if role not in ROLE_KEYS:
                raise KeyError(f"دور غير معروف: {role}")
            row = rows.get(role)
            if row is None:
                row = RoleProviderMapping(role=role)
                session.add(row)
            row.provider = str(value["provider"])
            row.configuration = str(value.get("configuration", "") or "")
            row.model = str(value["model"])
            row.updated_at = _utc_now()
            saved.append(role)
        session.commit()
    log_provider_event(sessions, "ROLE_PROVIDER_CHANGED",
                       {"roles": saved, "mappings": mappings})
    return saved


# ------------------------------------------------------------------ #
# الكتابة — إنشاء/تعديل/حذف المزودين والتكوينات
# ------------------------------------------------------------------ #

_SLUG_RE = __import__("re").compile(r"^[a-z0-9][a-z0-9_-]{1,63}$")


def create_provider(
    sessions, *, name: str, display_name: str = "", type_: str = "custom",
    api_style: str = "openai_compatible", auth_type: str = "bearer",
    enabled: bool = True, base_url: str = "", default_model: str = "",
    models: list[str] | None = None, config_file: str = "",
) -> dict:
    """إنشاء مزود جديد من الواجهة (§3) — القائمة ليست مغلقة أبدًا."""
    if not _SLUG_RE.match(name or ""):
        raise ValueError(
            f"اسم المزود '{name}' غير صالح — أحرف لاتينية صغيرة/أرقام/-/_ فقط"
        )
    if api_style not in API_STYLES:
        raise ValueError(f"نمط API غير مدعوم: {api_style} ({list(API_STYLES)})")
    if auth_type not in AUTH_TYPES:
        raise ValueError(f"نوع مصادقة غير مدعوم: {auth_type} ({list(AUTH_TYPES)})")
    with sessions() as session:
        clash = session.scalars(
            select(ProviderRecord).where(ProviderRecord.name == name)
        ).first()
        if clash is not None:
            raise ValueError(f"مزود بهذا الاسم موجود أصلًا: {name}")
        provider = ProviderRecord(
            name=name, display_name=display_name or name, type=type_,
            enabled=enabled, api_style=api_style, auth_type=auth_type,
        )
        session.add(provider)
        session.flush()
        if base_url:
            session.add(ProviderConfiguration(
                provider_id=provider.id, name="default", base_url=base_url,
                api_style=api_style, enabled=True, default_model=default_model,
                models=json.dumps(models or ([default_model] if default_model else []),
                                  ensure_ascii=False),
                config_file=config_file if auth_type == "config_file" else "",
            ))
        session.commit()
        pid = provider.id
    log_provider_event(sessions, "PROVIDER_CREATED", {"provider": name})
    return get_provider(sessions, pid)


def update_provider(sessions, provider_id: int, **fields) -> dict:
    """تعديل مزود — الحقول القابلة للتغيير فقط، لا اسم slug بعد الإنشاء."""
    allowed = {"display_name", "type", "enabled", "api_style", "auth_type"}
    with sessions() as session:
        provider = session.get(ProviderRecord, int(provider_id))
        if provider is None:
            raise KeyError(f"مزود غير معروف: {provider_id}")
        for key, value in fields.items():
            if key not in allowed:
                raise ValueError(f"حقل غير قابل للتعديل: {key}")
            if key == "api_style" and value not in API_STYLES:
                raise ValueError(f"نمط API غير مدعوم: {value}")
            if key == "auth_type" and value not in AUTH_TYPES:
                raise ValueError(f"نوع مصادقة غير مدعوم: {value}")
            setattr(provider, key, value)
        provider.updated_at = _utc_now()
        session.commit()
    log_provider_event(sessions, "PROVIDER_UPDATED",
                       {"provider_id": provider_id, **{k: v for k, v in fields.items()
                                                       if k in allowed}})
    return get_provider(sessions, provider_id)


def delete_provider(sessions, provider_id: int) -> dict:
    """حذف مزود وتكويناته — ممنوع إن كان مرتبطًا بأي دور (حماية الاستخدام)."""
    mappings = get_mappings(sessions)
    with sessions() as session:
        provider = session.get(ProviderRecord, int(provider_id))
        if provider is None:
            raise KeyError(f"مزود غير معروف: {provider_id}")
        in_use = [
            role for role, m in mappings.items() if m["provider"] == provider.name
        ]
        if in_use:
            raise ValueError(
                f"المزود '{provider.name}' مستخدم حاليًا في الأدوار: {in_use} — "
                "غيّر ربط الأدوار أولًا ثم احذفه"
            )
        name = provider.name
        for cfg in session.scalars(
            select(ProviderConfiguration)
            .where(ProviderConfiguration.provider_id == provider.id)
        ).all():
            session.delete(cfg)
        session.delete(provider)
        session.commit()
    log_provider_event(sessions, "PROVIDER_DELETED", {"provider": name})
    return {"success": True, "deleted": name}


def add_configuration(
    sessions, provider_id: int, *, name: str, base_url: str,
    api_style: str = "openai_compatible", enabled: bool = True,
    default_model: str = "", models: list[str] | None = None,
    config_file: str = "",
) -> dict:
    """إضافة تكوين (Base URL) لمزود (§4) — أكثر من endpoint للمزود الواحد."""
    if not name or not base_url:
        raise ValueError("التكوين يحتاج name وbase_url")
    if api_style not in API_STYLES:
        raise ValueError(f"نمط API غير مدعوم: {api_style}")
    parsed = urlparse(base_url)
    if parsed.scheme not in ("http", "https") or not parsed.netloc:
        raise ValueError(f"Base URL غير صالح: {base_url}")
    with sessions() as session:
        provider = session.get(ProviderRecord, int(provider_id))
        if provider is None:
            raise KeyError(f"مزود غير معروف: {provider_id}")
        clash = session.scalars(
            select(ProviderConfiguration).where(
                ProviderConfiguration.provider_id == provider.id,
                ProviderConfiguration.name == name,
            )
        ).first()
        if clash is not None:
            raise ValueError(f"تكوين بهذا الاسم موجود للمزود: {name}")
        cfg = ProviderConfiguration(
            provider_id=provider.id, name=name, base_url=base_url,
            api_style=api_style, enabled=enabled, default_model=default_model,
            models=json.dumps(models or ([] if not default_model else [default_model]),
                              ensure_ascii=False),
            config_file=config_file,
        )
        session.add(cfg)
        session.commit()
        cid = cfg.id
    log_provider_event(sessions, "PROVIDER_CONFIGURATION_CREATED",
                       {"provider_id": provider_id, "configuration": name})
    return _config_payload(get_configuration(sessions, cid), provider,
                           is_primary=False)


def update_configuration(sessions, config_id: int, **fields) -> dict:
    """تعديل تكوين — base_url/النموذج/التمكين/النماذج (§4 تعديل)."""
    allowed = {"name", "base_url", "api_style", "enabled", "default_model",
               "models", "config_file"}
    with sessions() as session:
        cfg = session.get(ProviderConfiguration, int(config_id))
        if cfg is None:
            raise KeyError(f"تكوين غير معروف: {config_id}")
        for key, value in fields.items():
            if key not in allowed:
                raise ValueError(f"حقل غير قابل للتعديل: {key}")
            if key == "base_url":
                parsed = urlparse(value)
                if parsed.scheme not in ("http", "https") or not parsed.netloc:
                    raise ValueError(f"Base URL غير صالح: {value}")
            if key == "api_style" and value not in API_STYLES:
                raise ValueError(f"نمط API غير مدعوم: {value}")
            if key == "models":
                value = json.dumps(value or [], ensure_ascii=False)
            setattr(cfg, key, value)
        cfg.updated_at = _utc_now()
        session.commit()
    log_provider_event(sessions, "PROVIDER_CONFIGURATION_UPDATED",
                       {"configuration_id": config_id,
                        "fields": sorted(k for k in fields if k in allowed)})
    provider = _provider_of_config(sessions, config_id)
    return _config_payload(get_configuration(sessions, config_id), provider,
                           is_primary=_is_primary(sessions, config_id))


def _is_primary(sessions, config_id: int) -> bool:
    """هل هذا التكوين أول تكوينات مزوده؟ — يحدد مفتاح النقل."""
    with sessions() as session:
        cfg = session.get(ProviderConfiguration, int(config_id))
        first = session.scalars(
            select(ProviderConfiguration)
            .where(ProviderConfiguration.provider_id == cfg.provider_id)
            .order_by(ProviderConfiguration.id)
        ).first()
        return first is not None and first.id == cfg.id


def _provider_of_config(sessions, config_id: int) -> ProviderRecord:
    with sessions() as session:
        cfg = session.get(ProviderConfiguration, int(config_id))
        return session.get(ProviderRecord, cfg.provider_id)


def delete_configuration(sessions, config_id: int) -> dict:
    """حذف تكوين غير مستخدم (§4) — المحمي بالربط يُرفض حذفه."""
    mappings = get_mappings(sessions)
    with sessions() as session:
        cfg = session.get(ProviderConfiguration, int(config_id))
        if cfg is None:
            raise KeyError(f"تكوين غير معروف: {config_id}")
        provider = session.get(ProviderRecord, cfg.provider_id)
        remaining = [
            c for c in session.scalars(
                select(ProviderConfiguration)
                .where(ProviderConfiguration.provider_id == cfg.provider_id)
            ).all() if c.id != cfg.id
        ]
        if not remaining:
            raise ValueError("لا يمكن حذف التكوين الوحيد للمزود — أضف بديلًا أولًا")
        in_use = [
            role for role, m in mappings.items()
            if m["provider"] == provider.name
            and (m["configuration"] or "default") == cfg.name
        ]
        if in_use:
            raise ValueError(
                f"التكوين '{cfg.name}' مستخدم حاليًا في الأدوار: {in_use} — "
                "غيّر ربط الأدوار أولًا"
            )
        name, pname = cfg.name, provider.name
        session.delete(cfg)
        session.commit()
    log_provider_event(sessions, "PROVIDER_CONFIGURATION_DELETED",
                       {"provider": pname, "configuration": name})
    return {"success": True, "deleted": f"{pname}::{name}"}


# ------------------------------------------------------------------ #
# حل المواصفات الحية — القاعدة ← الموجّه
# ------------------------------------------------------------------ #

def transport_key(provider_name: str, configuration: str) -> str:
    """مفتاح النقل: المزود للتكوين الأساسي، «مزود::تكوين» لغيره (§5)."""
    if not configuration or configuration == "default":
        return provider_name
    return f"{provider_name}::{configuration}"


def resolve_provider_specs(sessions) -> dict[str, dict]:
    """مواصفات النقل الحية من القاعدة — كل مزود/تكوين مفعّل قابل للحل.

    لا مزود يمنع غيره (§9): كل تكوين يُحل باستقلال، وفشل مصادقة
    أحدهما يستبعده وحده فقط. البذرة تُضمن قبل الحل.
    """
    from router.live_providers import _resolve_provider_credentials

    ensure_seeded(sessions)
    specs: dict[str, dict] = {}
    with sessions() as session:
        providers = session.scalars(
            select(ProviderRecord).where(ProviderRecord.enabled)
        ).all()
        for provider in providers:
            configs = session.scalars(
                select(ProviderConfiguration)
                .where(ProviderConfiguration.provider_id == provider.id,
                       ProviderConfiguration.enabled)
                .order_by(ProviderConfiguration.id)
            ).all()
            primary_assigned = False
            for cfg in configs:
                # (§6) لا نقل لأنماط بلا محول مسجل — استدعاء أعمى ممنوع؛
                # الدور الذي يختارها يُسمّى صراحة في فحص الجاهزية
                if cfg.api_style != "openai_compatible":
                    continue
                spec: dict[str, Any] = {
                    "base_url": cfg.base_url,
                    "model": cfg.default_model,
                }
                if provider.auth_type == "config_file" and cfg.config_file:
                    spec["config_file"] = cfg.config_file
                elif provider.auth_type == "bearer":
                    spec["secrets_store"] = True
                # أول تكوين قابل للحل يحمل اسم المزود (أساسي) — وما
                # بعده «مزود::تكوين» (§5)
                key = (
                    provider.name if not primary_assigned
                    else transport_key(provider.name, cfg.name)
                )
                found = _resolve_provider_credentials(dict(spec), name=provider.name)
                if found:
                    specs[key] = found
                    primary_assigned = True
    return specs


# ------------------------------------------------------------------ #
# مسبار الجاهزية (§4+§7+§8) — تشخيص منظم لا تخمين
# ------------------------------------------------------------------ #

def _http_fetch_real(url: str, headers: dict, timeout: float, method: str = "GET",
                     body: bytes | None = None):
    """النقل الفعلي — يعيد (status, body_text) أو يرفع خطأ شبكة.

    يقرأ حتى 1MB: قوائم النماذج الكبيرة يجب أن تُحلَّ كاملة — الاقتطاع
    المبكر كان يُفسد json.loads فتُعلن الجاهزية بلا فحص النموذج (درس
    تشخيص NVIDIA الموثق). المقتطفات القصيرة للعرض تُقتطع لاحقًا.
    """
    request = urllib.request.Request(
        url, data=body, headers=headers, method=method
    )
    with urllib.request.urlopen(request, timeout=timeout) as response:
        return int(response.status), response.read()[:1_000_000].decode(
            "utf-8", "replace"
        )


def _classify_http_error(status: int, body: str, model: str) -> tuple[str, str]:
    """تصنيف خطأ HTTP — (الحالة، السبب)."""
    lowered = body.lower()
    if status in (401, 403):
        return "AUTH_FAILED", f"HTTP {status} — المصادقة مرفوضة"
    if status == 404:
        if model and ("model" in lowered and ("not" in lowered or "unknown" in lowered
                                              or "invalid" in lowered)):
            return "MODEL_NOT_FOUND", f"HTTP 404 — النموذج غير موجود: {model}"
        return "NOT_FOUND", "HTTP 404 — المسار/العنوان غير موجود"
    if status == 429:
        return "RATE_LIMITED", "HTTP 429 — حد المعدل/الحصة"
    if status >= 500:
        return "UNKNOWN_ERROR", f"HTTP {status} — خطأ خادم لدى المزود"
    return "UNKNOWN_ERROR", f"HTTP {status} — {body[:120]}"


def probe_configuration(
    sessions, config_id: int, *,
    http_fetch: Callable[..., tuple[int, str]] | None = None,
    timeout: float = 20.0,
) -> dict:
    """مسبار جاهزية حقيقي (§4+§8) — GET /models ثم تحقق النموذج.

    التشخيص منظم بالكامل (§7): القيمة المخزنة، العنوان النهائي،
    الطريقة، نمط API، النموذج، وجود المصادقة (مقنّعة)، حالة الاستجابة
    ومقتطفها — والمشكلة مصنّفة (url/endpoint/model/authentication/
    network/provider_availability/api_style/none). لا «READY» بلا نجاح
    HTTP فعلي، ولا تعديل للعناوين بالتخمين (§21).
    """
    fetch = http_fetch or _http_fetch_real
    cfg = get_configuration(sessions, config_id)
    if cfg is None:
        raise KeyError(f"تكوين غير معروف: {config_id}")
    provider = _provider_of_config(sessions, config_id)
    result = _probe_one(sessions, cfg, provider, fetch=fetch, timeout=timeout)
    with sessions() as session:
        row = session.get(ProviderConfiguration, int(config_id))
        row.last_readiness_status = result["status"]
        row.last_readiness_check = _utc_now()
        row.last_readiness_detail = json.dumps(result, ensure_ascii=False,
                                               default=str)
        session.commit()
    log_provider_event(sessions, "PROVIDER_TEST_COMPLETED", {
        "provider": provider.name, "configuration": cfg.name,
        "status": result["status"], "latency_ms": result["latency_ms"],
        "endpoint": result["endpoint"],
    })
    return result


def _probe_one(sessions, cfg: ProviderConfiguration, provider: ProviderRecord, *,
               fetch, timeout: float) -> dict:
    """مسبار تكوين واحد — بنية النتيجة الموحدة (جاهزية + تشخيص)."""
    from secrets_store import store as secrets

    started = time.monotonic()
    base_url = (cfg.base_url or "").rstrip("/")
    model = cfg.default_model or ""
    diagnosis: dict[str, Any] = {
        "stored_base_url": cfg.base_url,
        "api_style": cfg.api_style,
        "model": model,
        "auth_type": provider.auth_type,
    }

    def finish(status: str, reason: str, *, http_status: int | None = None,
               body: str = "", endpoint: str = "", problem: str = "none",
               extra: dict | None = None) -> dict:
        return {
            "status": status,
            "checked_at": _utc_now().isoformat(),
            "latency_ms": int((time.monotonic() - started) * 1000),
            "http_status": http_status,
            "error_code": status if status != "READY" else None,
            "error_message": None if status == "READY" else reason,
            "endpoint": endpoint or (base_url + "/models"),
            "model": model,
            "reason": reason if status != "READY" else "المسبار نجح — اتصال حقيقي",
            "diagnosis": {
                **diagnosis,
                "final_url": endpoint or (base_url + "/models"),
                "http_method": "GET",
                "auth": "Authorization: Bearer [REDACTED]" if provider.auth_type
                == "bearer" else provider.auth_type,
                "endpoint_path": "/models",
                "response_status": http_status,
                "response_body_excerpt": (body or "")[:200],
                "problem": problem,
                **(extra or {}),
            },
        }

    # 1) فحص التكوين نفسه — لا عنوان/نمط غير مدعوم = INVALID_CONFIGURATION
    parsed = urlparse(base_url)
    if not base_url or parsed.scheme not in ("http", "https") or not parsed.netloc:
        return finish("INVALID_CONFIGURATION", f"Base URL غير صالح: '{base_url}'",
                      problem="url")
    if cfg.api_style not in API_STYLES:
        return finish("UNSUPPORTED", f"نمط API غير مدعوم: {cfg.api_style}",
                      problem="api_style")
    if cfg.api_style != "openai_compatible":
        # (§6) المحول مسؤول عن بناء الطلب — ولا محول مسجل بعد لهذا
        # النمط، فالإعلان الصادق UNSUPPORTED لا استدعاء أعمى
        return finish(
            "UNSUPPORTED",
            f"لا محول مسجل لنمط API '{cfg.api_style}' بعد — المسجّل: "
            "openai_compatible",
            problem="api_style",
        )

    # 2) حل المصادقة — مفتاح مفقود = INVALID_CONFIGURATION (لا اختبار أعمى)
    headers: dict[str, str] = {"Content-Type": "application/json"}
    if provider.auth_type == "bearer":
        key = secrets.get_key(provider.name)
        if not key:
            return finish(
                "INVALID_CONFIGURATION",
                f"لا مفتاح محفوظ للمزود '{provider.name}' — احفظه أولًا",
                problem="authentication",
            )
        headers["Authorization"] = f"Bearer {key}"
    elif provider.auth_type == "config_file":
        resolved = _resolve_config_file_auth(cfg.config_file)
        if resolved is None:
            return finish(
                "INVALID_CONFIGURATION",
                f"ملف مصادقة غير مقروء: {cfg.config_file}",
                problem="authentication",
            )
        key, extra_headers = resolved
        headers.update(extra_headers)
        if key:
            headers["Authorization"] = f"Bearer {key}"

    # 3) المسبار الأول: GET {base_url}/models
    models_url = base_url + "/models"
    diagnosis["final_url"] = models_url
    try:
        status, body = fetch(models_url, headers, timeout, method="GET")
    except urllib.error.HTTPError as error:
        body = error.read()[:500].decode("utf-8", "replace")
        state, reason = _classify_http_error(int(error.code), body, model)
        problem = {
            "AUTH_FAILED": "authentication", "NOT_FOUND": "endpoint",
            "MODEL_NOT_FOUND": "model", "RATE_LIMITED": "provider_availability",
        }.get(state, "provider_availability")
        # 404 على /models لا يعني بالضرورة موت المزود — نتحقق من مسار
        # الاستدعاء الفعلي قبل الحكم (تشخيص لا تخمين §7)
        if state == "NOT_FOUND":
            return _probe_chat_fallback(
                finish, fetch, base_url, headers, model, timeout, started,
                diagnosis, models_url, body,
            )
        return finish(state, reason, http_status=int(error.code), body=body,
                      endpoint=models_url, problem=problem)
    except Exception as error:  # noqa: BLE001 — خطأ شبكة واحد صريح مصنّف
        # (RLR-001 §1) التصنيف الدقيق داخل حالة NETWORK_ERROR القائمة:
        # السبب + error_class مقروء آليًا (رفض اتصال ≠ DNS ≠ مهلة)
        classified = classify_network_error(error, models_url)
        return finish("NETWORK_ERROR",
                      f"[{classified.error_class}] فشل الاتصال: {error}",
                      endpoint=models_url, problem="network",
                      extra={"error_class": classified.error_class})

    # 4) نجاح /models — تحقق النموذج ميكانيكيًا إن أمكن (§12)
    model_ids: list[str] = []
    try:
        parsed_body = json.loads(body)
        model_ids = [
            str(m.get("id", "")) for m in parsed_body.get("data", [])
        ] if isinstance(parsed_body, dict) else []
    except ValueError:
        model_ids = []
    if model and model_ids and model not in model_ids:
        return finish(
            "MODEL_NOT_FOUND",
            f"النموذج '{model}' غير موجود في قائمة المزود "
            f"({len(model_ids)} نموذجًا متاحًا)",
            http_status=status, body=body[:200], endpoint=models_url,
            problem="model",
            extra={"available_models_sample": model_ids[:15]},
        )
    return finish("READY", f"اتصال ناجح — {len(model_ids)} نموذجًا",
                  http_status=status, body=body[:100], endpoint=models_url)


def _probe_chat_fallback(
    finish, fetch, base_url: str, headers: dict, model: str, timeout: float,
    started: float, diagnosis: dict, models_url: str, models_body: str,
) -> dict:
    """/models أعطى 404 — مسبار chat/completions يحدد أين المشكلة فعلًا.

    هذا ليس تعديلًا للعناوين بالتخمين (§21): العنوان المخزن يُستخدم
    كما هو، والهدف تمييز «المسار كله غير موجود» من «/models غير
    موجود لكن الاستدعاء يعمل» — والنتيجة مسجلة كاملة.
    """
    chat_url = base_url + "/chat/completions"
    payload = json.dumps({
        "model": model or "ping", "max_tokens": 1,
        "messages": [{"role": "user", "content": "ping"}],
    }).encode("utf-8")
    try:
        status, body = fetch(chat_url, headers, timeout, method="POST",
                             body=payload)
        return finish(
            "READY",
            "استدعاء chat ناجح (مسار /models غير موجود لدى المزود)",
            http_status=status, body=body[:100], endpoint=chat_url,
            extra={"models_endpoint_status": 404,
                   "models_body_excerpt": models_body[:120]},
        )
    except urllib.error.HTTPError as error:
        body = error.read()[:500].decode("utf-8", "replace")
        state, reason = _classify_http_error(int(error.code), body, model)
        problem = {
            "AUTH_FAILED": "authentication", "NOT_FOUND": "url",
            "MODEL_NOT_FOUND": "model", "RATE_LIMITED": "provider_availability",
        }.get(state, "provider_availability")
        return finish(state, reason, http_status=int(error.code), body=body,
                      endpoint=chat_url, problem=problem,
                      extra={"models_endpoint_status": 404,
                             "models_body_excerpt": models_body[:120]})
    except Exception as error:  # noqa: BLE001
        classified = classify_network_error(error, chat_url)
        return finish("NETWORK_ERROR",
                      f"[{classified.error_class}] فشل الاتصال بمسار الاستدعاء: {error}",
                      endpoint=chat_url, problem="network",
                      extra={"error_class": classified.error_class,
                             "models_endpoint_status": 404})


def _resolve_config_file_auth(config_file: str) -> tuple[str, dict] | None:
    """مصادقة ملف الإعدادات المعلن — نفس منطق المنشأة القائم."""
    try:
        with open(config_file, encoding="utf-8") as handle:
            found = json.load(handle)
    except (OSError, ValueError):
        return None
    headers = {"X-Z-AI-From": "Z"}
    if found.get("token"):
        headers["X-Token"] = str(found["token"])
    return str(found.get("apiKey", "")), headers


def refresh_models(
    sessions, config_id: int, *, http_fetch=None, timeout: float = 20.0
) -> dict:
    """جلب النماذج الحية من التكوين (§12) — discovery اختياري لا شرط."""
    fetch = http_fetch or _http_fetch_real
    cfg = get_configuration(sessions, config_id)
    if cfg is None:
        raise KeyError(f"تكوين غير معروف: {config_id}")
    provider = _provider_of_config(sessions, config_id)
    base_url = (cfg.base_url or "").rstrip("/")
    from secrets_store import store as secrets

    headers = {"Content-Type": "application/json"}
    if provider.auth_type == "bearer":
        # (الأمر 008 §35) قوائم /models عامة لدى مزودين (نفيديا موثقة:
        # 82 نموذجًا بلا مفتاح) — نجرب الجلب الحي دائمًا؛ فإن رُفضت
        # المصادقة (401/403) نعود للنماذج المعلنة برسالة صادقة.
        key = secrets.get_key(provider.name)
        if key:
            headers["Authorization"] = f"Bearer {key}"
    elif provider.auth_type == "config_file":
        resolved = _resolve_config_file_auth(cfg.config_file)
        if resolved is None:
            return {"ok": False, "source": "declared",
                    "model_ids": _cfg_models(cfg),
                    "message": "ملف المصادقة غير مقروء — النماذج المعلنة فقط"}
        key, extra = resolved
        headers.update(extra)
        if key:
            headers["Authorization"] = f"Bearer {key}"
    try:
        status, body = fetch(base_url + "/models", headers, timeout, method="GET")
        parsed = json.loads(body)
        ids = [str(m.get("id", "")) for m in parsed.get("data", [])] \
            if isinstance(parsed, dict) else []
        if not ids:
            return {"ok": False, "source": "declared",
                    "model_ids": _cfg_models(cfg),
                    "message": "استجابة بلا نماذج — النماذج المعلنة فقط"}
        merged = sorted(set(ids) | set(_cfg_models(cfg)))
        update_configuration(sessions, config_id, models=merged)
        log_provider_event(sessions, "MODEL_ADDED", {
            "provider": provider.name, "count": len(merged)})
        return {"ok": True, "source": "live", "model_ids": merged[:200],
                "models_count": len(merged)}
    except Exception as error:  # noqa: BLE001 — فشل الجلب لا يكسر شيئًا
        return {"ok": False, "source": "declared", "model_ids": _cfg_models(cfg),
                "message": f"تعذر الجلب الحي: {error} — النماذج المعلنة فقط"}


def _models_endpoint_public(base_url: str, timeout: float) -> bool:
    """فحص واحد خفيف: هل /models عام هنا؟ (نفيديا: نعم موثقة)."""
    try:
        status, _body = _http_fetch_real(
            base_url + "/models", {"Content-Type": "application/json"},
            timeout, method="GET",
        )
        return status == 200
    except Exception:  # noqa: BLE001
        return False


def _cfg_models(cfg: ProviderConfiguration) -> list[str]:
    try:
        return list(json.loads(cfg.models or "[]"))
    except ValueError:
        return []
