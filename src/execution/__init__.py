"""حزمة بيئات التنفيذ (الأمر 010 §16-§21).

backends:  الخلفيات الحقيقية (LOCAL ركيزة محلية / REMOTE_WORKER عامل بعيد)
service:   السجل والتحقق والاختيار والتنفيذ الموحد (المسبار = المنفذ)
api:       نقاط نهاية الإدارة
models:    الجداول الدائمة (عائلة EXECUTION)
"""

from __future__ import annotations

from execution.backends import (
    ExecutionOutcome,
    LocalLinuxBackend,
    RemoteWorkerBackend,
    VerifyResult,
)
from execution.models import EXECUTION_TABLES

__all__ = [
    "EXECUTION_TABLES",
    "ExecutionOutcome",
    "LocalLinuxBackend",
    "RemoteWorkerBackend",
    "VerifyResult",
]
