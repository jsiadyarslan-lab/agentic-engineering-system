# ============================================================ #
#  Agent Hub v2 — سكربت التشغيل (Run)
#  يشغل الخادم المحلي على 127.0.0.1:8010 فقط — لا يستمع إلى
#  الشبكة العامة أبدًا.
#
#  ذاتي الإصلاح:
#  1) إن لم توجد البيئة الافتراضية يستدعي setup.ps1 تلقائيًا.
#  2) إن فشل استيراد التطبيق يحاول إعادة التثبيت مرة واحدة
#     قبل أن يتوقف — بيئة سليمة لا تُحجب بأزمة عابرة.
#
#  يفتح المتصفح تلقائيًا فور جاهزية الخادم.
#  لإيقاف الخادم: Ctrl+C
# ============================================================ #

$ErrorActionPreference = "Stop"
try { [Console]::OutputEncoding = [System.Text.Encoding]::UTF8 } catch { }

# جذر المشروع = المجلد الأب لمجلد scripts
$Root = Split-Path -Parent $PSScriptRoot
Set-Location $Root

$Port       = 8010
$VenvPython = Join-Path $Root ".venv\Scripts\python.exe"

# ---------- 1) البيئة الافتراضية (ذاتي الإصلاح) ----------
if (-not (Test-Path $VenvPython)) {
    Write-Host "[تنبيه] البيئة الافتراضية غير موجودة — التجهيز التلقائي الآن..." -ForegroundColor Yellow
    & (Join-Path $PSScriptRoot "setup.ps1")
    # الحقيقة الأرضية هي وجود python.exe — لا $LASTEXITCODE (قد يكون $null
    # بعد سكربت ناجح بلا exit صريح، وأي نقص لاحق يلتقطه فحص الاستيراد أدناه)
    if (-not (Test-Path $VenvPython)) {
        Write-Host "[خطأ] فشل التجهيز التلقائي — راجع الرسائل أعلاه." -ForegroundColor Red
        exit 1
    }
}

# فرض UTF-8 على كل ما يشغّله هذا السكربت من عمليات بايثون (pip ثم uvicorn)
$env:PYTHONUTF8 = "1"

# ---------- 2) فحص الاستيراد (ذاتي الإصلاح) ----------
# ملاحظة: بلا إعادة توجيه stderr عمدًا — مع ErrorActionPreference=Stop
# يحوّل PS 5.1 أي stderr لخطأ قاتل؛ والنجاح صامت أصلًا (لا مخرجات استيراد).
& $VenvPython -c "import api.routes"
if ($LASTEXITCODE -ne 0) {
    Write-Host "[تنبيه] التطبيق غير مثبت في البيئة — إعادة تثبيت سريعة..." -ForegroundColor Yellow
    & $VenvPython -m pip install --quiet --disable-pip-version-check -e ".[test]"
    & $VenvPython -c "import api.routes"
    if ($LASTEXITCODE -ne 0) {
        Write-Host "[خطأ] التطبيق لا يستورد حتى بعد إعادة التثبيت." -ForegroundColor Red
        Write-Host "الحل: .\scripts\setup.ps1" -ForegroundColor Yellow
        exit 1
    }
}
Write-Host "[1/2] البيئة جاهزة." -ForegroundColor Green

# ---------- 3) ملاحظة الصدق حول العزل ----------
Write-Host ""
Write-Host "ملاحظة: ركيزة العزل الحقيقية (namespaces + seccomp) على Linux/WSL2 فقط." -ForegroundColor DarkYellow
Write-Host "على Windows مباشرة يعمل النظام بالوضع المتوافق المعلن بلا ادعاء عزل." -ForegroundColor DarkYellow
Write-Host ""

# ---------- 4) فتح المتصفح تلقائيًا فور جاهزية الخادم ----------
$BrowserJob = Start-Job -ScriptBlock {
    Param($Port)
    $Deadline = (Get-Date).AddSeconds(40)
    while ((Get-Date) -lt $Deadline) {
        try {
            $Client = New-Object Net.Sockets.TcpClient
            $Client.Connect("127.0.0.1", $Port)
            $Connected = $Client.Connected
            $Client.Close()
            if ($Connected) {
                Start-Process "http://127.0.0.1:$Port"
                break
            }
        } catch {
            Start-Sleep -Milliseconds 400
        }
    }
} -ArgumentList $Port

# ---------- 5) التشغيل ----------
Write-Host "[2/2] تشغيل الخادم المحلي..." -ForegroundColor Cyan
Write-Host "المتصفح سيفتح تلقائيًا على: http://127.0.0.1:$Port" -ForegroundColor Cyan
Write-Host "لإيقاف الخادم اضغط: Ctrl+C" -ForegroundColor DarkGray
Write-Host ""

& $VenvPython -m uvicorn api.routes:app --host 127.0.0.1 --port $Port

# ---------- 6) تنظيف بعد التوقف ----------
Stop-Job $BrowserJob -ErrorAction SilentlyContinue
Remove-Job $BrowserJob -Force -ErrorAction SilentlyContinue
Write-Host ""
Write-Host "توقف الخادم." -ForegroundColor Cyan
