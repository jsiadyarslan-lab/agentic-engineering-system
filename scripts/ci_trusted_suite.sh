#!/usr/bin/env bash
# aes03_ci_local.sh — تشغيل المجموعة الموثوقة محليًا (نفس ما يفعله CI)
# الاستخدام: bash aes03_ci_local.sh   (من جذر المستودع، venv مُعد)
# المجموعة: tests/readiness + tests/core + tests/api بمهلة 150s لكل اختبار.
set -e
cd "$(dirname "$0")/../.." # إن نُفذ من scripts/ — وإلا عدّل المسار
PYTHONPATH=src .venv/bin/python -m pytest tests/readiness tests/core tests/api \
  --timeout=150 -q --no-header -p no:cacheprovider "$@"
