"""خدمة البحث (الأمر 010 §24-§26) — مصفوفة مزودين لا علمًا واحدًا.

- list_providers: كل المزودين بحالة مسبارهم (ddg يُبذر تلقائيًا)
- probe_provider: مسبار حقيقي واحد يكتب في القاعدة
- configure: تعديل تكوين مزود (رابط searx / نقطة API + مفتاح)
- search: أول مزود جاهز — والفشل يعاد مفصلًا لكل مزود (§24:
  DDG مهلة ≠ الإنترنت مقطوع؛ WEB_FETCH قد يكون READY والبحث معطلًا)
- aggregate_capability: قراءة قدرة web_search المجمعة للجرد
"""

from __future__ import annotations

import datetime as _dt
import json

from sqlalchemy import select

from research import providers as research_providers
from execution.models import ResearchProvider

_SEED = (
    {"kind": "search_ddg", "name": "DuckDuckGo", "config": {}},
    {"kind": "search_searx", "name": "SearXNG", "config": {}, "enabled": 0},
    {"kind": "search_api", "name": "Search API", "config": {}, "enabled": 0},
)


def _utc_now() -> _dt.datetime:
    return _dt.datetime.now(_dt.timezone.utc)


def _json_loads(raw: str, default):
    try:
        return json.loads(raw or "null") or default
    except ValueError:
        return default


def ensure_seeded(sessions) -> None:
    """بذر المزودين الثلاثة عند أول تشغيل — آمن للتكرار."""
    with sessions() as session:
        existing = {
            row.name for row in session.scalars(
                select(ResearchProvider)
            ).all()
        }
        for spec in _SEED:
            if spec["name"] in existing:
                continue
            session.add(ResearchProvider(
                kind=spec["kind"], name=spec["name"],
                config_json=json.dumps(spec["config"], ensure_ascii=False),
                enabled=spec.get("enabled", 1),
            ))
        session.commit()


def _row_to_dict(row: ResearchProvider) -> dict:
    return {
        "id": row.id, "kind": row.kind, "name": row.name,
        "config": _json_loads(row.config_json, {}),
        "enabled": bool(row.enabled),
        "last_probe_status": row.last_probe_status,
        "failure_reason": row.failure_reason,
        "last_probe_at": row.last_probe_at.isoformat()
        if row.last_probe_at else None,
        "last_probe_detail": _json_loads(row.last_probe_detail, {}),
    }


def build_provider(record: dict):
    """بناء كائن المزود الحقيقي من سجل القاعدة — النوع يحدد الصنف."""
    config = record.get("config") or {}
    key = ""
    if record["kind"] == "search_api":
        from secrets_store import store

        key = store.get_key(f"research::{record['name']}") or ""
    if record["kind"] == "search_ddg":
        return research_providers.DuckDuckGoSearchProvider(
            endpoint=config.get("endpoint")
            or "https://html.duckduckgo.com/html/",
        )
    if record["kind"] == "search_searx":
        return research_providers.SearxJsonSearchProvider(
            base_url=config.get("base_url", ""),
        )
    if record["kind"] == "search_api":
        return research_providers.ApiSearchProvider(
            endpoint=config.get("endpoint", ""),
            key=key,
            style=config.get("style", "generic_results"),
        )
    raise ValueError(f"نوع مزود غير مدعوم: {record['kind']}")


def list_providers(sessions) -> list[dict]:
    ensure_seeded(sessions)
    with sessions() as session:
        rows = session.scalars(
            select(ResearchProvider).order_by(ResearchProvider.id)
        ).all()
        return [_row_to_dict(row) for row in rows]


def probe_provider(sessions, provider_id: int) -> dict:
    """مسبار واحد حقيقي — النتيجة تُكتب وتُعاد (§24)."""
    ensure_seeded(sessions)
    with sessions() as session:
        row = session.get(ResearchProvider, int(provider_id))
        if row is None:
            raise KeyError(f"مزود بحث غير معروف: {provider_id}")
        record = _row_to_dict(row)
    provider = build_provider(record)
    result = research_providers.probe_provider(provider)
    with sessions() as session:
        row = session.get(ResearchProvider, int(provider_id))
        row.last_probe_status = result["status"]
        row.failure_reason = "" if result["status"] == "READY" \
            else result["reason"]
        row.last_probe_at = _utc_now()
        row.last_probe_detail = json.dumps(
            result, ensure_ascii=False, default=str
        )
        row.updated_at = _utc_now()
        session.commit()
    out = result
    out["provider"] = _row_to_dict(row)
    return out


def probe_all(sessions) -> list[dict]:
    ensure_seeded(sessions)
    out = []
    for record in list_providers(sessions):
        if not record["enabled"]:
            out.append({
                "provider_id": record["id"], "name": record["name"],
                "status": "DISABLED", "reason": "معطل بقرار المالك",
            })
            continue
        out.append(probe_provider(sessions, record["id"]))
    return out


def configure_provider(
    sessions, provider_id: int, *, config: dict | None = None,
    enabled: bool | None = None, api_key: str = "",
) -> dict:
    """تعديل تكوين مزود (§28 مسار التوفير) — المفتاح للمخزن لا القاعدة."""
    config = config or {}
    with sessions() as session:
        row = session.get(ResearchProvider, int(provider_id))
        if row is None:
            raise KeyError(f"مزود بحث غير معروف: {provider_id}")
        current = _json_loads(row.config_json, {})
        allowed = {"endpoint", "base_url", "style"}
        for key in allowed:
            if key in config:
                current[key] = str(config[key])[:300]
        row.config_json = json.dumps(current, ensure_ascii=False)
        if enabled is not None:
            row.enabled = 1 if enabled else 0
        if api_key:
            from secrets_store import store

            store.set_key(f"research::{row.name}", api_key)
        row.last_probe_status = "UNKNOWN"  # التكوين تغير — أعد الفحص
        row.updated_at = _utc_now()
        session.commit()
        session.refresh(row)
        return _row_to_dict(row)


def search(sessions, query: str) -> dict:
    """البحث بأول مزود جاهز (§25) — فشل الجميع يعاد مفصلًا لا مجملًا."""
    ensure_seeded(sessions)
    attempts: list[dict] = []
    for record in list_providers(sessions):
        if not record["enabled"]:
            continue
        provider = build_provider(record)
        try:
            results = provider.search(query)
            return {
                "provider": record["name"],
                "provider_kind": record["kind"],
                "results": results,
                "attempts": attempts,
            }
        except Exception as error:  # noqa: BLE001 — جرب التالي بتفصيل
            attempts.append({
                "provider": record["name"],
                "error": f"{type(error).__name__}: {error}"[:200],
            })
    from roles.tool_failures import ToolFailure

    raise ToolFailure(
        "web_search",
        "لا مزود بحث جاهز: " + (
            "؛ ".join(f"{a['provider']}: {a['error']}" for a in attempts)
            or "كل المزودين معطلون"
        ),
        failure_class="DEPENDENCY_FAILURE",
        reason=research_providers.SEARCH_NOT_READY,
        stage="PROVIDER_RESOLUTION",
        retryable=False,
        details={"attempts": attempts, "query": query[:200]},
    )


def aggregate_capability(sessions) -> dict:
    """قراءة قدرة web_search المجمعة (§23-§24) — للجرد وpreflight.

    READY فقط إن كان مزود بحث واحد على الأقل جاهزًا بمسبار صالح —
    والتفصيل لكل مزود يبقى في details فلا إجمال مخل.
    """
    records = list_providers(sessions)
    per_provider: list[dict] = []
    ready_any = False
    for record in records:
        if not record["enabled"]:
            per_provider.append({
                "provider": record["name"], "status": "DISABLED",
            })
            continue
        status = record["last_probe_status"]
        if status == "READY":
            ready_any = True
        per_provider.append({
            "provider": record["name"], "status": status,
            "reason": record["failure_reason"][:150],
        })
    return {
        "status": "READY" if ready_any else "NOT_READY",
        "reason": (
            "مزود بحث جاهز بمسبار حقيقي" if ready_any else
            "كل مزودي البحث غير جاهزين — DDG مهلة/محجوب لا يعني الإنترنت "
            "مقطوعًا؛ جهّز SearXNG أو Search API من الإعدادات ← البحث"
        ),
        "per_provider": per_provider,
        "note": "web_fetch قد يكون READY والبحث معطلًا — قدرات منفصلة",
    }


def refresh_stale(sessions) -> None:
    """إعادة فحص المزودين المعطلين تلقائيًا عند الاستعلام؟ لا —
    الفحص قرار معلن (زر/مهام)؛ هنا مجرد وسم الحالات المنتهية."""
    # الجاهزية في مزودي البحث تُعاد فحصها عند preflight عبر probe_all
    # إن كانت آخر قراءة أقدم من TTL — يبقى القرار معلنًا في preflight.
    return None


__all__ = [
    "aggregate_capability",
    "build_provider",
    "configure_provider",
    "ensure_seeded",
    "list_providers",
    "probe_all",
    "probe_provider",
    "search",
]
