@echo off
REM ============================================================
REM  Agent Hub v2 - Run wrapper (no PowerShell policy change needed)
REM  Runs scripts\run.ps1 with -ExecutionPolicy Bypass
REM  Usage:  scripts\run.cmd   (or double-click)
REM  Stop the server with:  Ctrl+C
REM ============================================================

powershell.exe -NoProfile -ExecutionPolicy Bypass -File "%~dp0run.ps1"
exit /b %ERRORLEVEL%
