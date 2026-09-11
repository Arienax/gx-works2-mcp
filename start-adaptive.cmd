@echo off
setlocal
chcp 65001 >nul
title GXWorks Context Test - adaptive
powershell.exe -NoProfile -STA -ExecutionPolicy Bypass -File "%~dp0scripts\start_context_test.ps1" -Policy adaptive
if errorlevel 1 pause
endlocal
