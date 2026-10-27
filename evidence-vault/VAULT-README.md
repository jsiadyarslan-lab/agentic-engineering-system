# AES Evidence Vault — 2026-10-27

أرشيف أدلة الجلسات السابقة (قبل بدء حوكمة TRK-001) — بذرة نمط W3-T16 (مستودع أرشيف منفصل).
الشجرة هنا شجرة أرشيف صرفة (لا كود إنتاج) — main هو مصدر الكود الحي.

## المستثنى أمنيًا (لا يُدفع أبدًا):
- scripts: كل سكربتات auth_setup_*/auth_cleanup_*/cleanup_*/audit001_auth_* وfix_500_011/diagnose_500_011 (تحوي بيانات اعتماد مؤقتة لجلسات القبول البصري — تقنيتها موثقة في worklog.md)
- download/live-reconciliation-011/fix-500/{fix-log.txt,report-011b-fix-500.md} (يحويان محتوى htpasswd)
- scripts/docx_013/ (24M صور وسيطة — المخرج النهائي AES-013-UI-Redesign-Plan.docx مدفوع على main في docs/ops/)
- scripts/release-005.bundle (تاريخ git مكرر — مدمج في main)
- auth.txt (بيانات مصادقة جلسة التدقيق AES-AUDIT-001 — حُذف)

## المحتوى:
- download/: أدلة 15 جلسة سابقة (لقطات/VLM/شبكة/تقارير)
- scripts/: سكربتات التنفيذ والتدقيق للجلسات (غير المستثناة أعلاه)
