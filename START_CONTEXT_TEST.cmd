@echo off
setlocal
chcp 65001 >nul
title GXWorks Context Policy Test
:menu
cls
echo GXWorks Agent - Context Policy Test (refresh-c6bc6ef)
echo.
echo 1. Adaptive - optimized, on-demand manual retrieval
echo 2. Legacy   - original prompts and retrieval
echo 3. Minimal  - no optional manuals or control examples
echo 4. Manual   - manual retrieval without control examples
echo 5. Examples - matched control examples without manuals
echo 6. Combined - matched examples and manual retrieval
echo 7. Exit
echo.
echo Each policy uses a separate test workspace. Original workspaces are not selected.
echo Close its server window with Ctrl+C after testing.
choice /c 1234567 /n /m "Select [1-7]: "
set "selection=%errorlevel%"
if "%selection%"=="7" exit /b 0
if "%selection%"=="1" set "policy=adaptive"
if "%selection%"=="2" set "policy=legacy"
if "%selection%"=="3" set "policy=minimal"
if "%selection%"=="4" set "policy=manual"
if "%selection%"=="5" set "policy=examples"
if "%selection%"=="6" set "policy=combined"
if not defined policy exit /b 1
powershell.exe -NoProfile -STA -ExecutionPolicy Bypass -File "%~dp0scripts\start_context_test.ps1" -Policy "%policy%"
if errorlevel 1 pause
endlocal
