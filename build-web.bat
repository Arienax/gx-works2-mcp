@echo off
setlocal EnableExtensions EnableDelayedExpansion
chcp 65001 >nul 2>&1
cd /d "%~dp0"
title GXWorks Agent - Build Web Source Runtime

set "NO_PAUSE="
set "FRONTEND_ONLY="
for %%A in (%*) do (
    if /I "%%~A"=="--no-pause" set "NO_PAUSE=1"
    if /I "%%~A"=="--frontend-only" set "FRONTEND_ONLY=1"
)

echo ==============================================
echo   GXWorks Agent - Web source build
echo ==============================================

if not defined FRONTEND_ONLY (
    set "WEB_PYTHON=!CD!\.venv\Scripts\python.exe"
    if not exist "!CD!\requirements\web.txt" (
        echo [ERROR] Missing requirements\web.txt.
        goto :fail
    )

    if not exist "!WEB_PYTHON!" (
        echo [1/4] Creating Python Web environment in .venv ...
        set "BOOTSTRAP_PYTHON="
        where py.exe >nul 2>&1
        if not errorlevel 1 set "BOOTSTRAP_PYTHON=py -3"
        if not defined BOOTSTRAP_PYTHON (
            where python.exe >nul 2>&1
            if not errorlevel 1 set "BOOTSTRAP_PYTHON=python"
        )
        if not defined BOOTSTRAP_PYTHON (
            echo [ERROR] Python 3.10+ was not found.
            echo Install Python 3.10 or newer, then run build-web.bat again.
            goto :fail
        )
        !BOOTSTRAP_PYTHON! -c "import sys; raise SystemExit(0 if sys.version_info >= (3,10) else 1)"
        if errorlevel 1 (
            echo [ERROR] Python 3.10+ is required for the Web runtime.
            goto :fail
        )
        !BOOTSTRAP_PYTHON! -m venv "!CD!\.venv"
        if errorlevel 1 (
            echo [ERROR] Failed to create .venv.
            goto :fail
        )
    ) else (
        echo [1/4] Using existing Python Web environment: .venv
    )

    "!WEB_PYTHON!" -c "import sys; raise SystemExit(0 if sys.version_info >= (3,10) else 1)"
    if errorlevel 1 (
        echo [ERROR] Existing .venv uses Python older than 3.10.
        echo Remove .venv and run build-web.bat again, or recreate it with Python 3.10+.
        goto :fail
    )

    echo       Installing/updating Web and MCP runtime dependencies ...
    "!WEB_PYTHON!" -m pip install -r "!CD!\requirements\web.txt"
    if errorlevel 1 (
        echo [ERROR] Failed to install requirements\web.txt into .venv.
        goto :fail
    )

    "!WEB_PYTHON!" -c "import fastapi, uvicorn, openai, numpy, mcp"
    if errorlevel 1 (
        echo [ERROR] Web runtime dependency verification failed.
        goto :fail
    )
) else (
    echo [1/4] Skipping Python setup (--frontend-only).
)

where node.exe >nul 2>&1
if errorlevel 1 (
    echo [ERROR] Node.js was not found in PATH.
    echo Install a current Node.js release, then run build-web.bat again.
    goto :fail
)
where npm.cmd >nul 2>&1
if errorlevel 1 (
    echo [ERROR] npm.cmd was not found in PATH.
    goto :fail
)
if not exist "web\package-lock.json" (
    echo [ERROR] Missing web\package-lock.json.
    goto :fail
)

for /f "delims=" %%V in ('node --version') do set "NODE_VERSION=%%V"
echo [INFO] Node: !NODE_VERSION!
echo.

pushd web

echo [2/4] Installing locked frontend dependencies ...
call npm.cmd ci
if errorlevel 1 goto :build_fail

echo.
echo [3/4] Regenerating TypeScript API types from web\openapi.json ...
call npm.cmd run types
if errorlevel 1 goto :build_fail

echo.
echo [4/4] Type-checking and building the Vite frontend ...
call npm.cmd run build
if errorlevel 1 goto :build_fail

popd
echo.
echo [OK] Frontend build completed: web\dist
if not defined FRONTEND_ONLY echo [OK] Source Web runtime is ready. You can now run start-web.cmd.
if not defined NO_PAUSE pause
endlocal
exit /b 0

:build_fail
set "BUILD_EXIT=!ERRORLEVEL!"
popd
echo.
echo [ERROR] Frontend build failed with exit code !BUILD_EXIT!.
goto :fail_code

:fail
set "BUILD_EXIT=1"

:fail_code
if not defined NO_PAUSE pause
endlocal & exit /b %BUILD_EXIT%
