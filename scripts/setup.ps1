# ============================================================ #
#  Agent Hub v2 — سكربت التجهيز (Setup)
#  ينشئ البيئة الافتراضية ويثبت المشروع من pyproject.toml
#  (ست تبعيات إنتاجية فقط + pytest كتبعية تطوير)
#  يعمل على Windows عبر PowerShell 5.1 أو أحدث
# ============================================================ #

$ErrorActionPreference = "Stop"
try { [Console]::OutputEncoding = [System.Text.Encoding]::UTF8 } catch { }

# فرض UTF-8 على كل ما يشغّله هذا السكربت من عمليات بايثون (pip/pytest)
$env:PYTHONUTF8 = "1"

# جذر المشروع = المجلد الأب لمجلد scripts
$Root = Split-Path -Parent $PSScriptRoot
Set-Location $Root

Write-Host ""
Write-Host "=== Agent Hub v2 — بدء التجهيز ===" -ForegroundColor Cyan

# ---------- 1) التحقق من وجود Python ----------
$PythonExe  = $null
$PythonArgs = @()

if (Get-Command python -ErrorAction SilentlyContinue) {
    $PythonExe = "python"
}
elseif (Get-Command py -ErrorAction SilentlyContinue) {
    $PythonExe  = "py"
    $PythonArgs = @("-3")
}

if (-not $PythonExe) {
    Write-Host "[خطأ] لم يتم العثور على Python. ثبّت Python 3.10 أو أحدث من python.org (علّم Add to PATH) ثم أعد المحاولة." -ForegroundColor Red
    exit 1
}

$VersionOutput = (& $PythonExe @PythonArgs --version 2>&1 | Out-String).Trim()
Write-Host "[1/4] تم العثور على Python: $VersionOutput" -ForegroundColor Green

if ($VersionOutput -notmatch "Python 3\.(\d+)") {
    Write-Host "[خطأ] تعذر قراءة إصدار Python." -ForegroundColor Red
    exit 1
}

$Minor = [int]$Matches[1]
if ($Minor -lt 10) {
    Write-Host "[خطأ] المطلوب Python 3.10 على الأقل (الموصى به: 3.11 أو 3.12)." -ForegroundColor Red
    exit 1
}

# ---------- 2) البيئة الافتراضية ----------
$VenvPython = Join-Path $Root ".venv\Scripts\python.exe"

if (-not (Test-Path $VenvPython)) {
    Write-Host "[2/4] إنشاء البيئة الافتراضية .venv ..." -ForegroundColor Yellow
    & $PythonExe @PythonArgs -m venv .venv
    if ($LASTEXITCODE -ne 0) {
        Write-Host "[خطأ] فشل إنشاء البيئة الافتراضية." -ForegroundColor Red
        exit 1
    }
}
else {
    Write-Host "[2/4] البيئة الافتراضية موجودة بالفعل." -ForegroundColor Green
}

# ---------- 3) تثبيت المشروع (editable) + pytest ----------
Write-Host "[3/4] تثبيت المشروع وتبعياته (أول مرة فقط — يحتاج إنترنت)..." -ForegroundColor Yellow
& $VenvPython -m pip install --disable-pip-version-check -e ".[test]"
if ($LASTEXITCODE -ne 0) {
    Write-Host "[خطأ] فشل تثبيت التبعيات. تأكد من اتصال الإنترنت ثم أعد المحاولة:" -ForegroundColor Red
    Write-Host "  .\scripts\setup.ps1" -ForegroundColor Yellow
    exit 1
}
Write-Host "      تم التثبيت بنجاح." -ForegroundColor Green

# ---------- 4) التحقق من الاستيراد ----------
Write-Host "[4/4] التحقق من جاهزية التطبيق..." -ForegroundColor Yellow
& $VenvPython -c "import api.routes; print('IMPORTS_OK')"
if ($LASTEXITCODE -ne 0) {
    Write-Host "[خطأ] التطبيق لا يستورد بعد — أعد التجهيز أو راجع الرسائل أعلاه." -ForegroundColor Red
    exit 1
}
Write-Host "      التطبيق جاهز." -ForegroundColor Green

# ---------- اكتمال ----------
Write-Host ""
Write-Host "[اكتمل] اكتمل التجهيز بنجاح." -ForegroundColor Green
Write-Host ""
Write-Host "الخطوة التالية — شغّل الخادم بالأمر:" -ForegroundColor Cyan
Write-Host "  .\scripts\run.ps1"
Write-Host "أو بالنقر المزدوج: scripts\run.cmd"
Write-Host "ثم افتح المتصفح على: http://127.0.0.1:8010" -ForegroundColor Cyan
Write-Host ""
Write-Host "ملاحظة الصدق: ركيزة العزل الحقيقية (namespaces + seccomp) تعمل على Linux فقط." -ForegroundColor DarkYellow
Write-Host "على Windows مباشرة يعمل النظام بالوضع المتوافق المعلن (محادثة + دورة + EOE)." -ForegroundColor DarkYellow
Write-Host "للعزل الحقيقي الكامل شغّله من WSL2." -ForegroundColor DarkYellow
Write-Host ""
