#!/usr/bin/env python3
"""
Execution Tracker CLI for Engineering Agent System Master Plan
Usage:
  python tracker.py status                    # Show overall progress
  python tracker.py status --phase=phase-0    # Show phase detail
  python tracker.py complete 0.1.1            # Mark step complete
  python tracker.py start 0.1.2               # Mark step in progress
  python tracker.py block 0.1.3 "Waiting on PR #42"  # Mark blocked
  python tracker.py report                    # Generate markdown report
"""

import re
import sys
import argparse
from datetime import datetime
from pathlib import Path
from typing import Optional, List, Dict, Any

TRACKER_FILE = Path(__file__).parent / "EXECUTION-TRACKER-v2.1.md"

STATUS_ICONS = {
    'completed': '✅',
    'in_progress': '🔄',
    'pending': '⏳',
    'blocked': '🚫'
}

STATUS_MARKDOWN = {
    'completed': '✅',
    'in_progress': '🔄',
    'pending': '⏳',
    'blocked': '🚫'
}

def load_tracker() -> str:
    with open(TRACKER_FILE, 'r', encoding='utf-8') as f:
        return f.read()

def save_tracker(content: str):
    with open(TRACKER_FILE, 'w', encoding='utf-8') as f:
        f.write(content)

def parse_tracker(content: str) -> Dict[str, Any]:
    """Parse the markdown tracker into structured data"""
    phases = []
    current_phase = None
    immediate_actions = []
    
    lines = content.split('\n')
    in_immediate = False
    in_phase_table = False
    phase_headers = []
    
    # Track if we're in a special section that should not be parsed as phases
    in_north_star = False
    in_definition_of_done = False
    in_metrics = False
    
    for line in lines:
        # Phase headers - matches "## 📋 PHASE 0", "## 📋 A. CONTEXT MANAGEMENT", "## 🚀 IMMEDIATE ACTIONS", etc.
        phase_match = re.match(r'##\s*[📋🚀]?\s*(PHASE\s+\d+|[A-G]\.\s+[A-Z\s]+|IMMEDIATE ACTIONS)', line)
        if phase_match:
            if current_phase:
                phases.append(current_phase)
            phase_name = phase_match.group(1)
            current_phase = {
                'name': phase_name,
                'steps': [],
                'in_table': False
            }
            in_phase_table = False
            in_immediate = ('IMMEDIATE ACTIONS' in phase_name)
            in_north_star = False
            in_definition_of_done = False
            in_metrics = False
            continue
        
        # Special section markers
        if 'NORTH STAR METRICS' in line or '## 🎯 NORTH STAR' in line:
            in_north_star = True
            if current_phase:
                phases.append(current_phase)
            current_phase = None
            continue
        if 'DEFINITION OF DONE' in line or '## 🏁 DEFINITION' in line:
            in_definition_of_done = True
            if current_phase:
                phases.append(current_phase)
            current_phase = None
            continue
        if 'METRICS SUMMARY' in line or '## 📈 METRICS' in line or '## 📊 METRICS' in line:
            in_metrics = True
            if current_phase:
                phases.append(current_phase)
            current_phase = None
            continue
        
        # Immediate actions
        if 'IMMEDIATE ACTIONS' in line:
            in_immediate = True
            continue
        
        # Skip parsing tables in special sections
        if in_north_star or in_definition_of_done or in_metrics:
            continue
        
        # Table rows
        if '|' in line and not line.strip().startswith('|---') and not line.strip().startswith('| Status'):
            # Parse table row
            cells = [c.strip() for c in line.split('|')[1:-1]]
            if len(cells) >= 6 and current_phase:
                status_icon = cells[0]
                step_id = cells[1]
                title = cells[2]
                deps = cells[3].replace('←', '').strip() if cells[3] else ''
                owner = cells[4]
                acceptance = cells[5]
                files = cells[6] if len(cells) > 6 else ''
                
                # Map icon to status
                status_map = {'✅': 'completed', '🔄': 'in_progress', '⏳': 'pending', '🚫': 'blocked'}
                status = status_map.get(status_icon, 'pending')
                
                step = {
                    'id': step_id,
                    'title': title,
                    'status': status,
                    'dependencies': [d.strip() for d in deps.split(',') if d.strip()] if deps else [],
                    'owner': owner,
                    'acceptance': acceptance,
                    'files': files
                }
                current_phase['steps'].append(step)
            elif in_immediate and len(cells) >= 4:
                status_icon = cells[0]
                action_id = cells[1]
                title = cells[2]
                command = cells[3]
                status_map = {'✅': 'completed', '🔄': 'in_progress', '⏳': 'pending', '🚫': 'blocked'}
                status = status_map.get(status_icon, 'pending')
                immediate_actions.append({
                    'id': action_id,
                    'title': title,
                    'command': command,
                    'status': status
                })
    
    if current_phase:
        phases.append(current_phase)
    
    return {
        'phases': phases,
        'immediate_actions': immediate_actions
    }

def update_step_status(step_id: str, status: str, note: Optional[str] = None):
    content = load_tracker()
    
    # Find the step row and update status icon
    status_icons = {
        'completed': '✅',
        'in_progress': '🔄',
        'pending': '⏳',
        'blocked': '🚫'
    }
    
    new_icon = status_icons.get(status, '⏳')
    
    # Find the row with this step_id
    lines = content.split('\n')
    for i, line in enumerate(lines):
        if f'| {step_id} |' in line:
            # Update the status icon (first cell)
            parts = line.split('|')
            if len(parts) > 1:
                parts[1] = f' {new_icon} '
                lines[i] = '|'.join(parts)
                break
    
    # Also update immediate actions
    for i, line in enumerate(lines):
        if f'| {step_id} |' in line and 'IMMEDIATE ACTIONS' in '\n'.join(lines[max(0,i-10):i]):
            parts = line.split('|')
            if len(parts) > 1:
                parts[1] = f' {new_icon} '
                lines[i] = '|'.join(parts)
                break
    
    new_content = '\n'.join(lines)
    
    # Update metrics summary
    new_content = update_metrics(new_content)
    
    save_tracker(new_content)
    print(f"✅ {step_id}: → {status}" + (f" ({note})" if note else ""))

def update_metrics(content: str) -> str:
    """Update the metrics summary table"""
    # Parse current state
    data = parse_tracker(content)
    
    all_steps = []
    for phase in data['phases']:
        all_steps.extend(phase['steps'])
    for action in data['immediate_actions']:
        all_steps.append(action)
    
    completed = sum(1 for s in all_steps if s['status'] == 'completed')
    in_progress = sum(1 for s in all_steps if s['status'] == 'in_progress')
    pending = sum(1 for s in all_steps if s['status'] == 'pending')
    total = len(all_steps)
    overall = round((completed + in_progress * 0.5) / total * 100, 1) if total > 0 else 0
    
    # Update metrics summary table
    lines = content.split('\n')
    in_metrics = False
    new_lines = []
    i = 0
    while i < len(lines):
        line = lines[i]
        if '## 📈 METRICS SUMMARY' in line or '## 📊 METRICS SUMMARY' in line:
            in_metrics = True
            new_lines.append(line)
            # Skip until we find the table end
            i += 1
            while i < len(lines) and ('|' in lines[i] or lines[i].strip() == ''):
                i += 1
            # Insert new metrics table
            new_lines.append('')
            new_lines.append('| Phase | Total Steps | Completed | In Progress | Pending | Progress |')
            new_lines.append('|-------|-------------|-----------|-------------|---------|----------|')
            for phase_data in parse_tracker(content)['phases']:
                phase_steps = phase_data['steps']
                p_completed = sum(1 for s in phase_steps if s['status'] == 'completed')
                p_in_progress = sum(1 for s in phase_steps if s['status'] == 'in_progress')
                p_pending = sum(1 for s in phase_steps if s['status'] == 'pending')
                p_total = len(phase_steps)
                p_progress = round((p_completed + p_in_progress * 0.5) / p_total * 100, 1) if p_total > 0 else 0
                new_lines.append(f"| **{phase_data['name']}** | {p_total} | {p_completed} | {p_in_progress} | {p_pending} | **{p_progress}%** |")
            new_lines.append(f"| **Immediate** | {len(data['immediate_actions'])} | {sum(1 for a in data['immediate_actions'] if a['status'] == 'completed')} | {sum(1 for a in data['immediate_actions'] if a['status'] == 'in_progress')} | {sum(1 for a in data['immediate_actions'] if a['status'] == 'pending')} | **{round((sum(1 for a in data['immediate_actions'] if a['status'] == 'completed') + sum(1 for a in data['immediate_actions'] if a['status'] == 'in_progress') * 0.5) / len(data['immediate_actions']) * 100, 1) if data['immediate_actions'] else 0}% |")
            new_lines.append(f"| **TOTAL** | {total} | {completed} | {in_progress} | {pending} | **{overall}%** |")
            new_lines.append('')
            continue
        if in_metrics and line.startswith('| TOTAL'):
            # Skip old total line
            continue
        new_lines.append(line)
        i += 1
    
    return '\n'.join(new_lines)

def show_status(content: str, phase_filter: Optional[str] = None):
    data = parse_tracker(content)
    
    all_steps = []
    for phase in data['phases']:
        all_steps.extend(phase['steps'])
    for action in data['immediate_actions']:
        all_steps.append(action)
    
    completed = sum(1 for s in all_steps if s['status'] == 'completed')
    in_progress = sum(1 for s in all_steps if s['status'] == 'in_progress')
    pending = sum(1 for s in all_steps if s['status'] == 'pending')
    total = len(all_steps)
    overall = round((completed + in_progress * 0.5) / total * 100, 1) if total > 0 else 0
    
    print(f"\n{'='*80}")
    print(f"📊 ENGINEERING AGENT SYSTEM — EXECUTION TRACKER")
    print(f"{'='*80}")
    print(f"Overall Progress: {overall}%")
    print(f"  ✅ Completed: {completed}")
    print(f"  🔄 In Progress: {in_progress}")
    print(f"  ⏳ Pending: {pending}")
    print(f"  📋 Total Steps: {total}")
    print(f"{'='*80}\n")
    
    phases_to_show = [p for p in data['phases'] if phase_filter is None or phase_filter.lower() in p['name'].lower()]
    
    for phase in phases_to_show:
        p_completed = sum(1 for s in phase['steps'] if s['status'] == 'completed')
        p_in_progress = sum(1 for s in phase['steps'] if s['status'] == 'in_progress')
        p_pending = sum(1 for s in phase['steps'] if s['status'] == 'pending')
        p_total = len(phase['steps'])
        p_progress = round((p_completed + p_in_progress * 0.5) / p_total * 100, 1) if p_total > 0 else 0
        
        status_icon = {'completed': '✅', 'in_progress': '🔄', 'pending': '⏳'}.get(
            'completed' if p_completed == p_total else ('in_progress' if p_in_progress > 0 else 'pending'), '❓')
        
        print(f"{status_icon} {phase['name'].upper()} ({p_progress}%)")
        print(f"   Steps: {p_total} | Weeks: {get_phase_weeks(phase['name'])}")
        
        for step in phase['steps']:
            step_icon = STATUS_MARKDOWN.get(step['status'], '❓')
            deps = f" ← {', '.join(step['dependencies'])}" if step['dependencies'] else ""
            blocked = f" 🚫 {step.get('blocked_reason', '')}" if step.get('blocked_reason') else ""
            print(f"    {step_icon} {step['id']}: {step['title']}{deps}{blocked}")
        print()
    
    # Show immediate actions
    print("🚀 IMMEDIATE ACTIONS")
    for action in data['immediate_actions']:
        icon = STATUS_MARKDOWN.get(action['status'], '❓')
        print(f"  {icon} {action['id']}: {action['title']}")
        print(f"    ```bash\n    {action['command']}\n    ```")

def get_phase_weeks(phase_name: str) -> str:
    weeks_map = {
        'PHASE 0': '1-2',
        'PHASE 1': '3-5',
        'PHASE 2': '6-9',
        'PHASE 3': '10-13',
        'PHASE 4': '14-16',
        'PHASE 5': '17-20',
        'IMMEDIATE ACTIONS': 'This Week'
    }
    for key, val in weeks_map.items():
        if key in phase_name.upper():
            return val
    return '—'

def generate_report(content: str) -> str:
    data = parse_tracker(content)
    lines = [
        "# 📊 Engineering Agent System — Progress Report",
        f"\nGenerated: {datetime.now().strftime('%Y-%m-%d %H:%M')}",
        f"\n## Overall Progress: {calculate_overall_progress(content)}%",
        f"\n---\n"
    ]
    
    for phase in data['phases']:
        p_completed = sum(1 for s in phase['steps'] if s['status'] == 'completed')
        p_in_progress = sum(1 for s in phase['steps'] if s['status'] == 'in_progress')
        p_pending = sum(1 for s in phase['steps'] if s['status'] == 'pending')
        p_total = len(phase['steps'])
        p_progress = round((p_completed + p_in_progress * 0.5) / p_total * 100, 1) if p_total > 0 else 0
        
        status_icon = {'completed': '✅', 'in_progress': '🔄', 'pending': '⏳'}.get(
            'completed' if p_completed == p_total else ('in_progress' if p_in_progress > 0 else 'pending'), '❓')
        
        lines.append(f"\n## {status_icon} {phase['name'].upper()} ({p_progress}%)")
        lines.append(f"Weeks: {get_phase_weeks(phase['name'])} | Steps: {p_total}")
        
        for step in phase['steps']:
            step_icon = STATUS_MARKDOWN.get(step['status'], '❓')
            deps = f" ← {', '.join(step['dependencies'])}" if step['dependencies'] else ""
            blocked = f" 🚫 {step.get('blocked_reason', '')}" if step.get('blocked_reason') else ""
            lines.append(f"  {step_icon} **{step['id']}**: {step['title']}{deps}{blocked}")
    
    # Immediate actions
    lines.append("\n---\n## 🚀 Immediate Actions")
    for action in parse_tracker(content)['immediate_actions']:
        icon = STATUS_MARKDOWN.get(action['status'], '❓')
        lines.append(f"  {icon} **{action['id']}**: {action['title']}")
        lines.append(f"    ```bash\n    {action['command']}\n    ```")
    
    return "\n".join(lines)

def calculate_overall_progress(content: str) -> float:
    data = parse_tracker(content)
    all_steps = []
    for phase in data['phases']:
        all_steps.extend(phase['steps'])
    for action in data['immediate_actions']:
        all_steps.append(action)
    
    completed = sum(1 for s in all_steps if s['status'] == 'completed')
    in_progress = sum(1 for s in all_steps if s['status'] == 'in_progress')
    total = len(all_steps)
    return round((completed + in_progress * 0.5) / total * 100, 1) if total > 0 else 0

def main():
    parser = argparse.ArgumentParser(description="Execution Tracker for Engineering Agent System")
    subparsers = parser.add_subparsers(dest='command', required=True)
    
    # status
    p_status = subparsers.add_parser('status', help='Show progress status')
    p_status.add_argument('--phase', help='Filter by phase name')
    
    # complete
    p_complete = subparsers.add_parser('complete', help='Mark step as completed')
    p_complete.add_argument('step_id', help='Step ID (e.g., 0.1.1)')
    
    # start
    p_start = subparsers.add_parser('start', help='Mark step as in progress')
    p_start.add_argument('step_id', help='Step ID (e.g., 0.1.2)')
    
    # block
    p_block = subparsers.add_parser('block', help='Mark step as blocked')
    p_block.add_argument('step_id', help='Step ID')
    p_block.add_argument('reason', help='Blocking reason')
    
    # report
    p_report = subparsers.add_parser('report', help='Generate markdown report')
    p_report.add_argument('-o', '--output', help='Output file path')
    
    args = parser.parse_args()
    
    content = load_tracker()
    
    if args.command == 'status':
        show_status(content, args.phase)
    
    elif args.command == 'complete':
        update_step_status(args.step_id, 'completed')
    
    elif args.command == 'start':
        update_step_status(args.step_id, 'in_progress')
    
    elif args.command == 'block':
        update_step_status(args.step_id, 'blocked', args.reason)
    
    elif args.command == 'report':
        report = generate_report(content)
        if args.output:
            Path(args.output).write_text(report, encoding='utf-8')
            print(f"Report saved to {args.output}")
        else:
            print(report)

if __name__ == '__main__':
    main()