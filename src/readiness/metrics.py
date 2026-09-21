"""مقاييس المراقبة (الأمر 009 §32) — عدادات حية بلا فخامة كاذبة.

تُغذَّى من مسار الأدوات (كل استدعاء) والمسبارات وpreflight —
قيم فعلية لا تقديرات. لقطة تُقرأ من /api/environment/metrics.
"""

from __future__ import annotations

import threading
import time

_LOCK = threading.Lock()
_METRICS: dict[str, float] = {
    "tool_invocations": 0,
    "tool_successes": 0,
    "tool_failures": 0,
    "retry_count": 0,
    "recovery_count": 0,
    "preflight_blocks": 0,
    "owner_gates": 0,
    "probes_run": 0,
    "probe_failures": 0,
    "sse_events_published": 0,
}
_FAILURES_BY_CLASS: dict[str, int] = {}
_FAILURES_BY_STAGE: dict[str, int] = {}
_TOOL_LATENCIES: list[float] = []
_PROBE_LATENCIES: list[float] = []


def bump(metric: str, by: float = 1) -> None:
    with _LOCK:
        _METRICS[metric] = _METRICS.get(metric, 0) + by
        if metric == "tool_invocations" and _TOOL_LATENCIES:
            pass


def count_tool_call(duration_ms: int, ok: bool, *,
                    failure_class: str = "", failure_stage: str = "",
                    retry: bool = False, recovery: bool = False) -> None:
    """تسجيل استدعاء أداة واحد — نجاحًا أو فشلًا (كل استدعاء حقيقي)."""
    with _LOCK:
        _METRICS["tool_invocations"] += 1
        if retry:
            _METRICS["retry_count"] += 1
        if recovery:
            _METRICS["recovery_count"] += 1
        if ok:
            _METRICS["tool_successes"] += 1
        else:
            _METRICS["tool_failures"] += 1
            if failure_class:
                _FAILURES_BY_CLASS[failure_class] = (
                    _FAILURES_BY_CLASS.get(failure_class, 0) + 1
                )
            if failure_stage:
                _FAILURES_BY_STAGE[failure_stage] = (
                    _FAILURES_BY_STAGE.get(failure_stage, 0) + 1
                )
        _TOOL_LATENCIES.append(duration_ms / 1000.0)
        if len(_TOOL_LATENCIES) > 500:
            del _TOOL_LATENCIES[:-500]


def count_probe(latency_ms: int, ok: bool) -> None:
    with _LOCK:
        _METRICS["probes_run"] += 1
        if not ok:
            _METRICS["probe_failures"] += 1
        _PROBE_LATENCIES.append(latency_ms / 1000.0)
        if len(_PROBE_LATENCIES) > 500:
            del _PROBE_LATENCIES[:-500]


def count_event_published() -> None:
    with _LOCK:
        _METRICS["sse_events_published"] += 1


def count_preflight_block() -> None:
    with _LOCK:
        _METRICS["preflight_blocks"] += 1


def count_owner_gate() -> None:
    with _LOCK:
        _METRICS["owner_gates"] += 1


def _stats(values: list[float]) -> dict:
    if not values:
        return {"count": 0, "p50_ms": 0, "p95_ms": 0, "max_ms": 0}
    ordered = sorted(values)
    return {
        "count": len(ordered),
        "p50_ms": int(ordered[len(ordered) // 2] * 1000),
        "p95_ms": int(ordered[min(len(ordered) - 1,
                                  int(len(ordered) * 0.95))] * 1000),
        "max_ms": int(ordered[-1] * 1000),
    }


def snapshot() -> dict:
    """لقطة المقاييس — للعرض وللمسبار (§32)."""
    with _LOCK:
        metrics = dict(_METRICS)
        by_class = dict(_FAILURES_BY_CLASS)
        by_stage = dict(_FAILURES_BY_STAGE)
        tool_lat = list(_TOOL_LATENCIES)
        probe_lat = list(_PROBE_LATENCIES)
    return {
        "metrics": metrics,
        "failure_by_class": by_class,
        "failure_by_stage": by_stage,
        "tool_latency": _stats(tool_lat),
        "probe_latency": _stats(probe_lat),
        "generated_at": time.strftime("%Y-%m-%dT%H:%M:%SZ",
                                      time.gmtime()),
    }
