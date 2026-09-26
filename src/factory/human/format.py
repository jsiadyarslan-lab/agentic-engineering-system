#!/usr/bin/env python3
"""
Human Interface Formatting
Formatting utilities for human-facing output.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from enum import Enum
from typing import Any, Dict, List, Optional


class Colors:
    """ANSI color codes."""
    RESET = "\033[0m"
    BOLD = "\033[1m"
    DIM = "\033[2m"
    RED = "\033[91m"
    GREEN = "\033[92m"
    YELLOW = "\033[93m"
    BLUE = "\033[94m"
    MAGENTA = "\033[95m"
    CYAN = "\033[96m"
    WHITE = "\033[97m"
    GRAY = "\033[90m"


class Icons:
    """Unicode icons for UI."""
    CHECK = "✅"
    CROSS = "❌"
    WARNING = "⚠️"
    INFO = "ℹ️"
    ROCKET = "🚀"
    GEAR = "⚙️"
    MAGNIFYING = "🔍"
    LIGHTNING = "⚡"
    SHIELD = "🛡️"
    BRAIN = "🧠"
    ROBOT = "🤖"
    FILE = "📄"
    FOLDER = "📁"
    LINK = "🔗"
    KEY = "🔑"
    CLOCK = "⏰"
    CALENDAR = "📅"
    CHECKLIST = "✅"
    WARNING_SIGN = "⚠️"
    ERROR = "❌"
    SUCCESS = "✅"
    WARNING = "⚠️"
    INFO = "ℹ️"
    ROCKET = "🚀"
    GEAR = "⚙️"
    MAGNIFYING = "🔍"
    LIGHTNING = "⚡"
    SHIELD = "🛡️"
    BRAIN = "🧠"
    FILE = "📄"
    FOLDER = "📁"
    LINK = "🔗"
    KEY = "🔑"
    CLOCK = "⏰"
    CALENDAR = "📅"


class Colors:
    """Color formatting utilities."""
    
    @staticmethod
    def colorize(text: str, color: str) -> str:
        return f"{color}{text}{Colors.RESET}"
    
    @staticmethod
    def success(text: str) -> str:
        return f"{Colors.GREEN}{text}{Colors.RESET}"
    
    @staticmethod
    def error(text: str) -> str:
        return f"{Colors.RED}{text}{Colors.RESET}"
    
    @staticmethod
    def warning(text: str) -> str:
        return f"{Colors.YELLOW}{text}{Colors.RESET}"
    
    @staticmethod
    def info(text: str) -> str:
        return f"{Colors.BLUE}{text}{Colors.RESET}"
    
    @staticmethod
    def bold(text: str) -> str:
        return f"{Colors.BOLD}{text}{Colors.RESET}"
    
    @staticmethod
    def dim(text: str) -> str:
        return f"{Colors.DIM}{text}{Colors.RESET}"


def format_mission_status(mission: Dict) -> str:
    """Format mission status for display."""
    state = mission.get("state", "UNKNOWN")
    state_colors = {
        "IDLE": "🔵",
        "LISTENING": "🔵",
        "EXPLORING": "🔵",
        "ANALYZING": "🔵",
        "PLANNING": "🟡",
        "DESIGNING": "🟡",
        "REVIEWING": "🟡",
        "AWAITING_APPROVAL": "🟠",
        "EXECUTING": "🟢",
        "VERIFYING": "🟡",
        "SECURITY_CHECK": "🔵",
        "COMPLETED": "🟢",
        "REVISING": "🟠",
        "BLOCKED": "🔴",
        "ABORTED": "⚫",
        "ESCALATED": "🔴",
    }
    
    icon = {
        "IDLE": "🔵",
        "LISTENING": "🔵",
        "EXPLORING": "🔵",
        "ANALYZING": "🔵",
        "PLANNING": "🟡",
        "DESIGNING": "🟡",
        "REVIEWING": "🟡",
        "AWAITING_APPROVAL": "🟠",
        "EXECUTING": "🟢",
        "VERIFYING": "🟡",
        "SECURITY_CHECK": "🔵",
        "COMPLETED": "🟢",
        "REVISING": "🟠",
        "BLOCKED": "🔴",
        "ABORTED": "⚫",
        "ESCALATED": "🔴",
    }.get(state, "⚪")
    
    progress = ""
    # Add progress indicator based on state
    
    return f"{state_colors.get(state, '⚪')} {state}"


def format_mission_summary(mission: Dict) -> str:
    """Format mission for display."""
    lines = []
    lines.append(f"{'='*60}")
    lines.append(f"📋 Mission: {mission.get('mission_id', 'N/A')[:8]}")
    lines.append(f"State: {format_mission_status(mission.get('state', 'UNKNOWN'))}")
    lines.append(f"Request: {mission.get('user_request', 'N/A')[:80]}...")
    lines.append(f"Created: {mission.get('created_at', 'N/A')}")
    lines.append(f"Progress: {mission.get('progress', 0)}%")
    lines.append(f"Evidence: {mission.get('evidence_count', 0)} items")
    return "\n".join([""] + [f"  {line}" for line in lines])


def format_agent_output(agent: str, output: Any, success: bool = True) -> str:
    """Format agent output for display."""
    status = "✅" if success else "❌"
    agent_icons = {
        "explorer": "🔍",
        "thinker": "🧠",
        "planner": "📋",
        "designer": "🎨",
        "reviewer": "👁️",
        "implementer": "⚙️",
        "verifier": "🔍",
        "security": "🛡️",
    }
    icon = agent_icons.get(agent, "🤖")
    status_icon = "✅" if success else "❌"
    
    if isinstance(output, dict):
        summary = output.get("summary", str(output)[:100])
    else:
        summary = str(output)[:100]
    
    return f"{agent_icons.get(agent, '🤖')} {status_icon} {agent}: {summary}"


def format_plan(plan: Dict) -> str:
    """Format plan for display."""
    lines = ["📋 Plan:"]
    lines.append(f"  Summary: {plan.get('summary', 'N/A')}")
    lines.append(f"  Tasks: {len(plan.get('tasks', []))}")
    
    for i, task in enumerate(plan.get("tasks", [])[:10], 1):
        lines.append(f"  {i}. {task.get('description', 'N/A')}")
    
    if len(plan.get("tasks", [])) > 10:
        lines.append(f"  ... and {len(plan['tasks']) - 10} more tasks")
    
    return "\n".join(lines)


def format_design_spec(design: Dict) -> str:
    """Format design specification for display."""
    lines = ["🎨 Design Specification:"]
    lines.append(f"  Summary: {design.get('summary', 'N/A')}")
    lines.append(f"  Architecture: {design.get('architecture', 'N/A')[:80]}...")
    lines.append(f"  Components: {len(design.get('components', []))}")
    lines.append(f"  Interfaces: {len(design.get('interfaces', []))}")
    return "\n".join(["  " + line for line in lines])


def format_review(review: Dict) -> str:
    """Format review for display."""
    status = "✅ APPROVED" if review.get("approved") else "❌ REJECTED"
    lines = [
        f"👁️ Review: {status}",
        f"  Summary: {review.get('summary', 'N/A')}",
        f"  Issues: {len(review.get('issues', []))}",
        f"  Suggestions: {len(review.get('suggestions', []))}",
    ]
    return "\n".join(["  " + line for line in lines])


def format_verification(verification: Dict) -> str:
    """Format verification result."""
    status = "✅ PASSED" if verification.get("passed") else "❌ FAILED"
    lines = [
        f"🔍 Verification: {status}",
        f"  Tests: {verification.get('tests_passed', 0)}/{verification.get('tests_total', 0)} passed",
        f"  Coverage: {verification.get('coverage', 0):.1f}%",
        f"  Issues: {len(verification.get('issues', []))}",
    ]
    return "\n".join(["  " + line for line in lines])


def format_security_report(report: Dict) -> str:
    """Format security report."""
    lines = ["🛡️ Security Report:"]
    lines.append(f"  Vulnerabilities: {report.get('vulnerabilities_found', 0)}")
    lines.append(f"  Secrets found: {report.get('secrets_found', 0)}")
    lines.append(f"  Dependencies checked: {report.get('dependencies_checked', 0)}")
    return "\n".join(["  " + line for line in lines])


def format_task_list(tasks: List[Dict]) -> str:
    """Format task list for display."""
    if not tasks:
        return "  No tasks"
    
    lines = []
    for i, task in enumerate(tasks, 1):
        status_icon = "✅" if task.get("completed") else "⏳"
        deps = task.get("dependencies", [])
        dep_str = f" (depends on: {', '.join(map(str, deps))})" if deps else ""
        lines.append(f"  {i}. {status_icon} {task.get('description', 'N/A')}{dep_str}")
    
    return "\n".join(["  " + line for line in lines])


def format_evidence_hashes(hashes: List[str]) -> str:
    """Format evidence hashes for display."""
    if not hashes:
        return "  No evidence hashes"
    
    lines = ["🔐 Evidence Hashes:"]
    for i, h in enumerate(hashes[:5], 1):
        lines.append(f"  {i}. {h[:16]}...")
    if len(hashes) > 5:
        lines.append(f"  ... and {len(hashes) - 5} more")
    return "\n".join(["  " + line for line in lines])


def format_error(error: str, context: str = "") -> str:
    """Format error for display."""
    return f"❌ Error{' in ' + context if context else ''}: {error}"


def format_warning(warning: str) -> str:
    """Format warning."""
    return f"⚠️ Warning: {warning}"


def format_info(info: str) -> str:
    """Format info message."""
    return f"ℹ️ {info}"


def format_success(message: str) -> str:
    """Format success message."""
    return f"✅ {message}"


def format_table(headers: List[str], rows: List[List[str]]) -> str:
    """Format data as a table."""
    if not rows:
        return "No data"
    
    # Calculate column widths
    widths = [len(h) for h in headers]
    for row in rows:
        for i, cell in enumerate(row):
            if i < len(widths):
                widths[i] = max(widths[i], len(str(cell)))
    
    # Build table
    lines = []
    # Header
    header = " | ".join(h.ljust(w) for h, w in zip(headers, widths))
    lines.append(" | ".join(h.ljust(w) for h, w in zip(headers, widths)))
    lines.append("-" * len(header))
    
    for row in rows:
        line = " | ".join(str(cell).ljust(w) for cell, w in zip(row, widths))
        lines.append(line)
    
    return "\n".join(lines)


def truncate(text: str, max_len: int = 80, suffix: str = "...") -> str:
    """Truncate text to max length."""
    if len(text) <= max_len:
        return text
    return text[:max_len - len(suffix)] + suffix


def format_duration(seconds: float) -> str:
    """Format duration in human-readable format."""
    if seconds < 1:
        return f"{seconds*1000:.0f}ms"
    elif seconds < 60:
        return f"{seconds:.1f}s"
    elif seconds < 3600:
        return f"{seconds/60:.1f}m"
    else:
        return f"{seconds/3600:.1f}h"


def format_size(bytes_: int) -> str:
    """Format byte size in human-readable format."""
    for unit in ['B', 'KB', 'MB', 'GB', 'TB']:
        if bytes_ < 1024:
            return f"{bytes_:.1f}{unit}"
        bytes_ /= 1024
    return f"{bytes_:.1f}PB"


def format_percentage(value: float, total: float) -> str:
    """Format percentage."""
    if total == 0:
        return "0%"
    return f"{value/total*100:.1f}%"