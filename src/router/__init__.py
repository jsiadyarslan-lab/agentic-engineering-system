"""حزمة router — agent-hub v2.

الأمر الثالث: ثلاث وحدات مستقلة منقولة من v1 (stdlib فقط، إعدادات dict):
rate_limiter (نافذة منزلقة + semaphore) + failover_chain (إعادات ثم تبدّل)
+ cooling_loop (تبريد أسي بميزانية) — ينسّق بينها model_router النحيف.
"""
