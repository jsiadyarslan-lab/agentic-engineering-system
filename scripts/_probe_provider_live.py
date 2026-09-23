"""مسبار حي مباشر للمزود المُهيَّأ (013.5 §B) — قياس لا تخمين.

يقرأ التهيئة الحية ثم يكلّم نقطة NVIDIA مباشرة برسالة قصيرة جدًا،
ويقيس الزمن الفعلي والرد الخام. الغرض: تحديد هل الفشل «مهلة مزود
بطيء» أم «نموذج غير موجود» — لأن كليهما يصبح MODEL_TIMEOUT في
الطبقة الأعلى، والفرق جوهري في التقرير.
"""

from __future__ import annotations

import json
import sys
import time
import urllib.error
import urllib.request
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from persistence.database import build_engine, make_session_factory  # noqa
from providers_registry import registry  # noqa: E402
from secrets_store import store  # noqa: E402

sessions = make_session_factory(
    build_engine(ROOT / "runtime" / "agent_hub_v2.db"))
mappings = registry.get_mappings(sessions)
print("live mappings:", json.dumps(mappings, ensure_ascii=False)[:600])

with sessions() as s:
    from sqlalchemy import inspect as sa_inspect
    from sqlalchemy import select
    import providers_registry.models as prm
    names = [n for n in dir(prm) if n[0].isupper()]
    print("registry models:", names)
    for name in names:
        cls = getattr(prm, name)
        if not hasattr(cls, "__tablename__"):
            continue
        print(" table:", cls.__tablename__)
        for row in s.scalars(select(cls)).all():
            data = {c.name: getattr(row, c.name)
                    for c in sa_inspect(cls).columns}
            for k, v in list(data.items()):
                if k.lower().endswith(("key", "secret", "token")) and v:
                    data[k] = f"<{len(str(v))} chars>"
                if isinstance(v, str) and len(v) > 140:
                    data[k] = v[:140] + "…"
            print("   ", data)

key = store.get_key("provider::nvidia") or store.get_key("nvidia") or ""
print("key found:", bool(key), "len:", len(key))

url = "https://integrate.api.nvidia.com/v1/chat/completions"
body = json.dumps({
    "model": "deepseek-ai/deepseek-v4.1-flash",
    "messages": [{"role": "user", "content": "قل كلمة: تم"}],
    "max_tokens": 8,
    "stream": False,
}).encode()

for attempt in range(1, 3):
    request = urllib.request.Request(
        url, data=body,
        headers={"Authorization": f"Bearer {key}",
                 "Content-Type": "application/json",
                 "Accept": "application/json"},
    )
    started = time.monotonic()
    try:
        with urllib.request.urlopen(request, timeout=90) as response:
            payload = response.read().decode("utf-8", "replace")
        elapsed = time.monotonic() - started
        print(f"attempt {attempt}: HTTP {response.status} in {elapsed:.1f}s")
        print("  body:", payload[:600])
    except urllib.error.HTTPError as error:
        elapsed = time.monotonic() - started
        detail = error.read().decode("utf-8", "replace")[:500]
        print(f"attempt {attempt}: HTTP {error.code} in {elapsed:.1f}s "
              f"-> {detail}")
    except Exception as error:  # noqa: BLE001
        elapsed = time.monotonic() - started
        print(f"attempt {attempt}: {type(error).__name__} in {elapsed:.1f}s "
              f"-> {error}")
