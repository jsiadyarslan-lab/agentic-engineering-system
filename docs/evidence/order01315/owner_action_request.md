# طلب تدخل المالك — ORDER013.15 (خيار أ على جهاز Windows)

> **التدخل الواحد المطلوب بدقة (لمسار WSL2 على جهاز Windows):**
> تفعيل الافتراضية العتادية من إعدادات BIOS/UEFI، ثم إعادة تشغيل الجهاز.
> لا يمكن للمنفّذ تنفيذه عن بُعد، ولا يُدَّعى تنفيذه — والمنفّذ لا يملك
> أي وصول إلى مضيف Windows من جلسته إطلاقًا (الدليل القاطع:
> `executor_host_truth.json` — نواة Linux/حاوية docker، لا wsl.exe،
> لا /mnt/c).

## 1. لماذا هذا التدخل تحديدًا

ORDER013.14 أثبت على جهاز المالك (Windows 10 / AMD64):

- `wsl_available()` → `WSL2_NO_DISTRO` بسبب:
  `WSL2 is unable to start since virtualisation is not enabled`
- خدمة Windows Time غير بدأت (0x80070426) → `CLOCK_EVIDENCE_UNTRUSTED` هناك.

الافتراضية العتادية (Intel VT-x / AMD-V) شرط نواة WSL2؛ تعطيلها
على مستوى firmware لا يمكن تغييره من PowerShell أو Python — وهذا
نص الأمر نفسه (§4.3) وموقفنا منه ثابت.

## 2. الخطوات الدقيقة على جهاز المالك

1. أعد التشغيل وادخل إعدادات BIOS/UEFI (عادة Del / F2 / F12 عند الإقلاع).
2. ابحث باسم الشركة: Intel → «Intel Virtualization Technology (VT-x)»؛
   AMD → «SVM Mode». قد يكون تحت Advanced / CPU Configuration.
3. فعّلها (Enabled)، احفظ، واترك الجهاز يقلع إلى Windows.
4. بعد الإقلاع، في PowerShell (مسؤول):
   `systeminfo` — في قسم Hyper-V Requirements يجب أن يظهر:
   «Virtualization Enabled In Firmware: Yes».
5. إن كانت ميزتا Windows لا تزالان معطلتين، فعّلهما (مسؤول):
   `dism.exe /online /enable-feature /featurename:Microsoft-Windows-Subsystem-Linux /all /norestart`
   `dism.exe /online /enable-feature /featurename:VirtualMachinePlatform /all /norestart`
   ثم أعد التشغيل يدويًا (لا إعادة تشغيل تلقائية عن بعد).
6. `wsl --update` ثم `wsl --set-default-version 2` ثم
   `wsl --install -d Ubuntu` (أو توزيعة متاحة: `wsl --list --online`).
7. داخل Ubuntu: `python3 --version` (المطلوب 3.10+) وأنشئ venv —
   لا تعديل بيئة النظام عالميًا.
8. شغّل العامل من جذر المستودع:
   `python scripts/execution_worker.py --port 8900 --token <سر-مشترك>`
   ثم سجّله من الواجهة: الإعدادات ← بيئات التنفيذ ← إضافة بيئة
   (backend: REMOTE_WORKER، endpoint، token) ← تحقق.

## 3. ما يجب فحصه بعد التفعيل (على المالك أو بأمر لاحق)

- `wsl --status` و`wsl --version` — الافتراضية لم تعد عائقًا.
- داخل WSL: cgroups v2 (`stat -f /sys/fs/cgroup`)، و`unshare -Ur true`
  (namespaces)، وSeccomp من `/proc/self/status` — لا استنتاج من اسم
  التوزيعة (نص §4.5).
- ساعة Windows: `w32tm /query /status` — إن ظلت الخدمة متوقفة فهذه
  حالة `CLOCK_EVIDENCE_UNTRUSTED` مستقلة على ذلك المضيف حتى مع نجاح
  العامل.
- اختبارا D2/D3 الحيّان الجديدان (بعد هذا الأمر) سيعملان تلقائيًا
  دون SKIP على أي Linux بركيزة متاحة — بما فيه WSL2 عند تفعيلها.

## 4. ما الذي أُنجز فعلًا بدون هذا التدخل (نتيجة هذا الأمر)

على **مضيف جلسة المنفّذ الحالي** (ركيزة Linux حقيقية — حاوية، namespaces+
seccomp+rlimits، قياس لا اسم توزيعة): عامل حي في وضع substrate،
مسبار عزل BLOCKED مع قناة تحكم متاحة خارج العزل، تسجيل REMOTE_WORKER
وتحقق READY عبر مسار المنتج، مطابقة API/واجهة، اختبارا D2/D3 دون
SKIP (نجاحا حيث فشلا كـtripwire عند خط الأساس)، وساعة مثبتة عند
الالتقاط بإجماع 5 سلطات NTP مستقلة (‏≤2ms تشتتًا). التفاصيل:
`docs/ORDER01315_REPORT.md`.
