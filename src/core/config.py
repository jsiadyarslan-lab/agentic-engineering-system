"""إعدادات v2 — pydantic-settings (ست تبعيات إنتاجية فقط، لا غير)."""

from __future__ import annotations

from pathlib import Path

from pydantic_settings import BaseSettings

APP_NAME = "agent-hub-v2"
APP_VERSION = "2.0.0a2"  # الأمر الثاني: أول دورة كاملة (mock) — ترقّي مع الأوامر


class Settings(BaseSettings):
    """إعدادات التشغيل — كلها قابلة للتجاوز بمتغيرات البيئة."""

    app_name: str = APP_NAME
    app_version: str = APP_VERSION
    host: str = "127.0.0.1"
    port: int = 8010
    db_path: Path = Path("runtime") / "agent_hub_v2.db"

    model_config = {"env_prefix": "AGenthubV2_", "env_file": ".env"}


settings = Settings()
