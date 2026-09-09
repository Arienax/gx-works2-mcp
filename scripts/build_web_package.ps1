param(
    [string]$Python = "",
    [string]$NpmCommand = "npm.cmd",
    [string]$GatewayDirectory = "",
    [switch]$AllowWithoutGateway,
    [switch]$SkipInstall,
    [switch]$ValidateOnly
)

$ErrorActionPreference = "Stop"
Set-StrictMode -Version Latest
$repositoryRoot = [IO.Path]::GetFullPath((Join-Path $PSScriptRoot ".."))
if ([string]::IsNullOrWhiteSpace($Python)) {
    $Python = Join-Path $repositoryRoot ".venv\Scripts\python.exe"
}
if (-not (Test-Path -LiteralPath $Python -PathType Leaf)) {
    throw "Provide -Python with a Python 3.10+ environment containing requirements-web.txt and PyInstaller."
}
& $Python -c "import sys; assert sys.version_info >= (3, 10); import PyInstaller, fastapi, uvicorn, openai, numpy; import pythoncom, pywinauto"
if ($LASTEXITCODE -ne 0) { throw "Web packaging dependencies are missing from the selected environment." }

$resolvedGateway = ""
if (-not [string]::IsNullOrWhiteSpace($GatewayDirectory)) {
    $resolvedGateway = (Resolve-Path -LiteralPath $GatewayDirectory).Path
    if (-not (Test-Path -LiteralPath (Join-Path $resolvedGateway "PlcAi.GxSimulator2Gateway.exe") -PathType Leaf)) {
        throw "GatewayDirectory must contain PlcAi.GxSimulator2Gateway.exe. The packaging script never downloads or starts the gateway."
    }
} elseif (-not $AllowWithoutGateway) {
    throw "Provide -GatewayDirectory for a complete package, or explicitly use -AllowWithoutGateway for a package without simulator support."
}

$requiredResources = @(
    "resources\config.default.json", "resources\pattern_library.json", "resources\plc_models.json",
    "resources\knowledge\fx3u_knowledge.sqlite", "resources\knowledge\fx3u_dense_lsa.npz",
    "resources\knowledge\manifest.json", "resources\knowledge\THIRD_PARTY_NOTICES.md",
    "resources\locales\en.json", "resources\locales\ja.json", "resources\app.ico", "LICENSE",
    "docs\integrations\web.md", "docs\architecture\web-migration-checklist.md", "start-web.cmd", "scripts\start_web.ps1"
)
foreach ($resource in $requiredResources) {
    if (-not (Test-Path -LiteralPath (Join-Path $repositoryRoot $resource) -PathType Leaf)) {
        throw "Missing required release resource: $resource"
    }
}
if (-not (Test-Path -LiteralPath (Join-Path $repositoryRoot "resources\instructions\mitsubishi") -PathType Container)) {
    throw "Missing Mitsubishi instruction resources."
}

Push-Location (Join-Path $repositoryRoot "web")
try {
    if (-not $ValidateOnly) {
        if (-not (Test-Path -LiteralPath "package-lock.json" -PathType Leaf)) {
            throw "Commit the front-end package-lock.json before making a reproducible release."
        }
        if (-not $SkipInstall) {
            & $NpmCommand ci
            if ($LASTEXITCODE -ne 0) { throw "Front-end dependency installation failed." }
        }
        & $NpmCommand run build
        if ($LASTEXITCODE -ne 0) { throw "Front-end build failed." }
    }
    if (-not (Test-Path -LiteralPath "dist\index.html" -PathType Leaf)) {
        throw "Built frontend is missing: web/dist/index.html."
    }
} finally {
    Pop-Location
}
if ($ValidateOnly) {
    Write-Output "Web release resources and selected packaging dependencies are present. No executable was built or started."
    return
}

$previousGateway = [Environment]::GetEnvironmentVariable("GX_WEB_PACKAGE_GATEWAY_DIR", "Process")
$previousWithoutGateway = [Environment]::GetEnvironmentVariable("GX_WEB_PACKAGE_ALLOW_WITHOUT_GATEWAY", "Process")
try {
    $env:GX_WEB_PACKAGE_GATEWAY_DIR = $resolvedGateway
    $env:GX_WEB_PACKAGE_ALLOW_WITHOUT_GATEWAY = $(if ($AllowWithoutGateway) { "1" } else { "0" })
    Push-Location $repositoryRoot
    try {
        & $Python -m PyInstaller --noconfirm web.spec
        if ($LASTEXITCODE -ne 0) { throw "PyInstaller Web package build failed." }
    } finally {
        Pop-Location
    }
} finally {
    [Environment]::SetEnvironmentVariable("GX_WEB_PACKAGE_GATEWAY_DIR", $previousGateway, "Process")
    [Environment]::SetEnvironmentVariable("GX_WEB_PACKAGE_ALLOW_WITHOUT_GATEWAY", $previousWithoutGateway, "Process")
}
Write-Output (Join-Path $repositoryRoot "dist\GXWorks-Agent-Web\GXWorks-Agent-Web.exe")
if ($AllowWithoutGateway -and [string]::IsNullOrWhiteSpace($resolvedGateway)) {
    Write-Warning "This package does not include the Simulator2 gateway; real simulator acceptance has not been performed."
}
