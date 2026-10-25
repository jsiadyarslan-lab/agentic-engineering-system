"""إعدادات v2 — pydantic-settings (ست تبعيات إنتاجية فقط، لا غير).

الأمر الثالث أضاف ProviderConfig: حدود المزودين المنقولة من v1
(حد المعدل + التبدّل + التبريد) — القيم الافتراضية هي سياسة v1
الموحدة نفسها (retries_on_5xx=2، تبريد 60/300/10 انتظارًا/1800ث).
"""

from __future__ import annotations

from pathlib import Path

from pydantic_settings import BaseSettings

APP_NAME = "Agentic Engineering System"
#: (الأمر 007 §1) الاسم الرسمي تغيّر من «Agent Hub v2» — مسارات الكود
#: (agent-hub-v2/، حزمة src) تبقى كما هي عمدًا: تغيير المسارات بلا
#: ضرورة يكسر الاستيرادات والنصوص البرمجية القائمة.
#: (AES-EXP-04 — تصحيح حقيقة الإصدار) pyproject.toml هو المصدر
#: الوحيد للحقيقة (3.8.0)؛ /health كانت تناقضه بإصدار أقدم. التزام
#: EXP-03 (a909597) ادّعى المحاذاة في رسالته لكنه لم يمس هذا الملف
#: — التصحيح هنا فعلي ومتحقق منه في /health.
APP_VERSION = "4.0.0"


class Settings(BaseSettings):
    """إعدادات التشغيل — كلها قابلة للتجاوز بمتغيرات البيئة."""

    app_name: str = APP_NAME
    app_version: str = APP_VERSION
    host: str = "127.0.0.1"
    port: int = 8010
    db_path: Path = Path("runtime") / "agent_hub_v2.db"

    # (الأمر 010 §6) صبر المحادثة التفاعلية — مستوى التشغيل:
    # خطأ مفهوم بعد ~دقيقة انتظار تبريد لا صمت 42 دقيقة.
    chat_cooling_max_waits: int = 1
    chat_cooling_budget_seconds: int = 90

    model_config = {"env_prefix": "AGenthubV2_", "env_file": ".env", "extra": "ignore"}


class ProviderConfig(BaseSettings):
    """حدود المزودين (الأمر الثالث) — الجسر بين الإعدادات والحزم.

    الحزم الثلاث في src/router/ لا تعرف pydantic ولا هذه الفئة: تستقبل
    dict صرفًا. as_dicts() هو نقطة التحويل الوحيدة (الإعدادات → dicts)
    حتى تبقى الوحدات مستقلة قابلة للاختبار بلا إعدادات.
    """

    # Rate limiter
    default_rpm: int = 40              # نافذة نفيديا المجانية (طلبات/دقيقة)
    default_min_interval: float = 1.5  # أقل فاصل بين طلبين (ثوانٍ)
    default_concurrency: int = 1       # استدعاء متزامن واحد لكل مزود

    # Failover
    failover_max_retries: int = 2      # إعادات داخلية قبل التبدّل (v1: retries_on_5xx)
    failover_backoff_base: float = 2.0  # تراجع أُسّي: base × 2^(n-1) ثانية

    # Cooling
    cooling_base_seconds: int = 60     # أساس التبريد الأسي
    cooling_max_seconds: int = 300     # سقف فترة التبريد
    cooling_max_waits: int = 10        # حد الانتظارات لكل استدعاء
    cooling_budget_seconds: int = 1800  # ميزانية انتظار لكل استدعاء

    model_config = {
        "env_prefix": "AGenthubV2_PROVIDER_",
        "env_file": ".env",
        "extra": "ignore",
    }

    def as_dicts(self) -> dict[str, dict]:
        """التحويل إلى إعدادات الحزم الثلاث (dict صرف — لا pydantic بعدها)."""
        return {
            "rate_limiter": {
                "rpm": self.default_rpm,
                "min_interval": self.default_min_interval,
                "concurrency": self.default_concurrency,
                "tpm": 0,  # سقف الإخراج مفتوح — التنظيم على الطلبات (كما في v1)
                "cooldown": self.cooling_base_seconds,
            },
            "failover": {
                "max_retries": self.failover_max_retries,
                "backoff_base": self.failover_backoff_base,
            },
            "cooling": {
                "cooldown_base": self.cooling_base_seconds,
                "cooldown_max": self.cooling_max_seconds,
                "max_waits": self.cooling_max_waits,
                "budget_seconds": self.cooling_budget_seconds,
            },
        }


class PlanningConfig(BaseSettings):
    """مُهل التخطيط (الأمر 013.6 §10) — فصل صريح بين مهلة **نشاط المزود**
    ومهلة **زمن الجلسة الكلي**، بدل سقف واحد خشن.

    الدافع المقيس حيًّا: النموذج الاستدلالي المُهيَّأ قضى ‏~600ث قبل أول
    رمز إخراج، فاستهلكت جلسة واحدة ‏848ث من أصل 900ث — أي أن السقف
    الواحد كان على وشك أن يحسم MODEL_TIMEOUT على عمل جارٍ صحيح، بينما
    لا يوجد أي تمييز بين «المزود صامت الآن» و«انتهت ميزانية الجلسة».

    الفصل هنا جوهري وليس تجميليًا:

    - ``provider_activity_timeout``: كم ثانية بلا **نشاط مزود حقيقي**
      (قطعة مخرجات أو استدلال مُثبت) قبل اعتبار **المحاولة** ميتة.
      قطعها ليس حكمًا نهائيًا: المحاولة تُوسم فشلًا قابلًا للإعادة
      (‏PROVIDER_ACTIVITY_TIMEOUT) وقد يُعاد تشغيلها إعادةً محدودة.
      كل نشاط حقيقي يصل **يعيد ضبط هذه المهلة** — لكنه أبدًا لا يمدّد
      المهلة الكلية (‏``overall_planning_timeout``).
    - ``overall_planning_timeout``: الميزانية الكلية لزمن الجدار
      **لعمل التخطيط كله عبر كل المحاولات**. قطعها حكم نهائي صادق:
      MODEL_TIMEOUT بلا إعادة، لأن الميزانية استُهلكت فعلًا.
    - ``max_attempts``: سقف المحاولات لعمل تخطيط واحد (‏2 افتراضًا =
      محاولة أولى + إعادة آلية واحدة). لا انتظار بلا سقف أبدًا.

    القيم كلها معلنة في اللقطة والواجهة دائمًا، فلا يُخفي الضبط حقيقة.
    """

    provider_activity_timeout: float = 300.0
    overall_planning_timeout: float = 900.0
    max_attempts: int = 2

    model_config = {
        "env_prefix": "AGenthubV2_PLANNING_",
        "env_file": ".env",
        "extra": "ignore",
    }


class LiveModelConfig(BaseSettings):
    """إعدادات الربط الحي (الأمر السادس المنقح §2) — nvidia افتراضيًا.

    - default_provider: nvidia — مفتاح المالكة من مخزن الأسرار حصرًا
      (لا من متغيرات البيئة أبدًا §0.3).
    - default_model: nemotron-3-ultra-550b-a55b لكل الأدوار (nano
      ممنوع للتحكيم — قرار موثق §2.3).
    - providers_json: مزودات إضافية/مخصصة بصيغة JSON
      {"الاسم": {"base_url":…, "model":…, "rpm":…, "min_interval":…,
                  "timeout":…, "max_tokens":…, "headers": {…},
                  "config_file": "/etc/…"}}.
    """

    default_provider: str = "nvidia"
    default_model: str = "nvidia/nemotron-3-ultra-550b-a55b"
    providers_json: str = ""
    #: (013.5 §B) عقد المخرجات والمهلة — معلنان لا ضمنيان.
    #: النماذج الاستدلالية تستهلك سقف المخرجات داخل reasoning_content
    #: قبل أن تُنتج حرفًا واحدًا؛ سقف ضيّق = رد بلا مخرجات، ومهلة
    #: ضيّقة = MODEL_TIMEOUT على عمل صحيح جارٍ. القيمتان تُقرآن في
    #: مواصفة المزود وتظهران في اللقطة، والمُشغِّل يضبطهما بالبيئة:
    #: AGenthubV2_LIVE_MAX_TOKENS / AGenthubV2_LIVE_TIMEOUT.
    max_tokens: int = 16000
    timeout: float = 600.0

    model_config = {
        "env_prefix": "AGenthubV2_LIVE_",
        "env_file": ".env",
        "extra": "ignore",
    }


settings = Settings()
provider_settings = ProviderConfig()
planning_settings = PlanningConfig()
live_model_settings = LiveModelConfig()
