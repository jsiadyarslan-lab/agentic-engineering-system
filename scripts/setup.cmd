@echo off
REM ============================================================
REM  Agent Hub v2 - Setup wrapper (no PowerShell policy change needed)
REM  Runs scripts\setup.ps1 with -ExecutionPolicy Bypass
REM  Usage:  scripts\setup.cmd   (or double-click)
REM ============================================================

powershell.exe -NoProfile -ExecutionPolicy Bypass -File "%~dp0setup.ps1"
exit /b %ERRORLEVEL%
