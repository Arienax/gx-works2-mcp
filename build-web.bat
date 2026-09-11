@echo off
setlocal EnableExtensions
chcp 65001 >nul 2>&1
cd /d "%~dp0"
title GXWorks Agent - Build Web Frontend

set "NO_PAUSE="
if /I "%~1"=="--no-pause" set "NO_PAUSE=1"

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
echo ==============================================
echo   GXWorks Agent - Web frontend build
echo ==============================================
echo [INFO] Node: %NODE_VERSION%
echo.

pushd web

echo [1/3] Installing locked frontend dependencies ...
call npm.cmd ci
if errorlevel 1 goto :build_fail

echo.
echo [2/3] Regenerating TypeScript API types from web\openapi.json ...
call npm.cmd run types
if errorlevel 1 goto :build_fail

echo.
echo [3/3] Type-checking and building the Vite frontend ...
call npm.cmd run build
if errorlevel 1 goto :build_fail

popd
echo.
echo [OK] Frontend build completed: web\dist
if not defined NO_PAUSE pause
endlocal
exit /b 0

:build_fail
set "BUILD_EXIT=%ERRORLEVEL%"
popd
echo.
echo [ERROR] Frontend build failed with exit code %BUILD_EXIT%.
goto :fail_code

:fail
set "BUILD_EXIT=1"

:fail_code
if not defined NO_PAUSE pause
endlocal & exit /b %BUILD_EXIT%
