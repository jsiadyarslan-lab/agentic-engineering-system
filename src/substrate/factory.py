"""Substrate selection — one honest source of truth (AES-EXP-04 §3.3).

Every consumer (probes, backends, service, tools, roles, routes) asks
THIS module whether an isolated substrate exists on this host. The
contract (§3.3) is now explicit:

- if the environment is available and genuinely isolated-executable,
  the matching adapter kind is exposed;
- if the tool exists but a required capability is missing, the report
  names the EXACT missing capability (no generic "unavailable");
- if the environment cannot provide isolation, there is NO readiness
  claim for isolated execution (callers stay fail-closed BLOCKED);
- nothing here caches a stale success as current evidence: the
  selection decision is made per process (one real bwrap launch probe,
  cached for the process lifetime — the per-execute path re-checks the
  cheap invariants and the launch itself remains the final arbiter).

Selection order (oldest evidence first, no generation is deleted):

1. ``local-namespace-substrate`` — the owner-accepted E1 local kernel
   substrate (Linux/x86_64, ctypes namespaces + pivot_root + seccomp).
   Unchanged on the hosts it was proven for.
2. ``local-bwrap-substrate`` — the bubblewrap-backed adapter
   (AES-EXP-04): Linux of any architecture where bubblewrap passes a
   REAL launch probe (proven on Oracle Linux 9.8 / aarch64, where the
   x86_64-only gate of the legacy substrate was an unsupported
   inference, not a capability fact).
3. no adapter — every sandboxed execution stays BLOCKED with the
   truthful reason (never a host-execution fallback).
"""

from __future__ import annotations

import os
import sys

from substrate.local_substrate import LocalImage, SubstrateUnavailable
from substrate.sandbox import SandboxManager

#: Adapter kinds (also the descriptor names of the two adapters).
KIND_LOCAL = "local-namespace-substrate"
KIND_BWRAP = "local-bwrap-substrate"

_SELECTION: dict[str, object] | None = None


def _is_linux() -> bool:
    return sys.platform.startswith("linux")


def _machine() -> str:
    try:
        return os.uname().machine
    except AttributeError:  # pragma: no cover — non-posix
        return "unknown"


def select_substrate(*, force: bool = False) -> dict[str, object]:
    """Decide (once per process) which substrate this host honestly has.

    Returns ``{"kind": KIND_LOCAL|KIND_BWRAP|None, "capabilities": dict,
    "reason": str}`` — ``reason`` is the FULL truthful explanation when
    kind is None (and empty when an adapter is selected).
    """
    global _SELECTION
    if _SELECTION is not None and not force:
        return dict(_SELECTION)

    local_reason = ""
    if not _is_linux():
        local_reason = (
            f"local namespace substrate requires Linux/x86_64 "
            f"(host: {sys.platform}/{_machine()})"
        )
    elif _machine() != "x86_64":
        # غير مبرَّر فرض x86_64 حين يثبت المنفّذ المثبت دعم المعمارية —
        # لكن الركيزة المحلية القديمة تُقيَّد بشهادتها الفعلية (x86_64)
        local_reason = (
            f"local namespace substrate evidence covers Linux/x86_64 "
            f"only (host: {_machine()}) — bubblewrap evaluated instead"
        )
    else:
        from substrate.local_substrate import substrate_capabilities

        caps = substrate_capabilities()
        if caps.get("supported"):
            _SELECTION = {
                "kind": KIND_LOCAL,
                "capabilities": caps,
                "reason": "",
            }
            return dict(_SELECTION)
        local_reason = (
            "local namespace substrate self-check failed: "
            f"{caps.get('supported', False)} — {caps}"
        )

    bwrap_reason = ""
    if _is_linux():
        from substrate.bwrap_substrate import bwrap_capabilities

        caps = bwrap_capabilities()
        if caps.get("supported"):
            _SELECTION = {
                "kind": KIND_BWRAP,
                "capabilities": caps,
                "reason": "",
            }
            return dict(_SELECTION)
        bwrap_reason = str(caps.get("reason") or "bwrap capabilities unproven")
    else:
        bwrap_reason = "bubblewrap requires Linux"

    reason = local_reason + "؛ " + bwrap_reason
    _SELECTION = {"kind": None, "capabilities": {}, "reason": reason}
    return dict(_SELECTION)


def substrate_available() -> bool:
    """هل توجد ركيزة عزل قابلة للعمل على هذا المضيف الآن؟ (§3.3)"""
    return select_substrate()["kind"] is not None


def substrate_failure_reason() -> str:
    """السبب الصادق الكامل عند غياب الركيزة (سلسلة فارغة عند التوفر)."""
    return str(select_substrate().get("reason") or "")


def substrate_capabilities_report() -> dict[str, object]:
    """تقرير القدرات للركيزة المختارة (أو سبب الغياب للحوادث)."""
    selection = select_substrate()
    return {
        "kind": selection.get("kind"),
        "supported": selection.get("kind") is not None,
        "capabilities": selection.get("capabilities") or {},
        "reason": selection.get("reason") or "",
    }


def default_sandbox_images() -> dict[str, LocalImage]:
    """صور الركيزة المختارة ({}`` عندما لا ركيزة — فشل صادق لاحقًا)."""
    kind = select_substrate()["kind"]
    if kind == KIND_LOCAL:
        from substrate.local_substrate import default_local_images

        return default_local_images()
    if kind == KIND_BWRAP:
        from substrate.bwrap_substrate import default_bwrap_images

        return default_bwrap_images()
    return {}


def sandbox_git_image() -> LocalImage:
    """صورة git للركيزة المختارة — SubstrateUnavailable عند الغياب."""
    kind = select_substrate()["kind"]
    if kind == KIND_LOCAL:
        from substrate.local_substrate import local_git_image

        return local_git_image()
    if kind == KIND_BWRAP:
        from substrate.bwrap_substrate import bwrap_git_image

        return bwrap_git_image()
    raise SubstrateUnavailable(substrate_failure_reason())


def make_sandbox_manager(
    *, images: dict[str, LocalImage] | None = None
) -> SandboxManager | None:
    """مدير رمل بالركيزة المختارة — ``None`` عند غياب أي ركيزة.

    ``None`` هو العقد المتفق عليه: كل المستهلكين يبقون fail-closed
    (BLOCKED) مع السبب الصادق من :func:`substrate_failure_reason`.
    """
    kind = select_substrate()["kind"]
    if kind is None:
        return None
    if kind == KIND_LOCAL:
        from substrate.local_substrate import LocalSubstrateAdapter

        adapter = LocalSubstrateAdapter(images=images)
    else:
        from substrate.bwrap_substrate import BubblewrapSubstrateAdapter

        adapter = BubblewrapSubstrateAdapter(images=images)
    manager = SandboxManager(substrate=adapter)
    manager.allow_images(frozenset(adapter.image_names))
    return manager


__all__ = [
    "KIND_BWRAP",
    "KIND_LOCAL",
    "default_sandbox_images",
    "make_sandbox_manager",
    "sandbox_git_image",
    "select_substrate",
    "substrate_available",
    "substrate_capabilities_report",
    "substrate_failure_reason",
]
