param(
    [string]$OutputRoot = "E:\baidudownload\PLC-AI-Studio-Builds"
)

$ErrorActionPreference = "Stop"

$projectRoot = [IO.Path]::GetFullPath((Split-Path -Parent $PSScriptRoot)).TrimEnd("\")
$outputRootFull = [IO.Path]::GetFullPath($OutputRoot).TrimEnd("\")
$projectPrefix = $projectRoot + "\"

if (
    $outputRootFull.Equals($projectRoot, [StringComparison]::OrdinalIgnoreCase) -or
    $outputRootFull.StartsWith($projectPrefix, [StringComparison]::OrdinalIgnoreCase)
) {
    throw "Build output must be outside the project root: $outputRootFull"
}

$workPath = Join-Path $outputRootFull "work_gxworks2_import"
$distPath = Join-Path $outputRootFull "dist_gxworks2_import"

New-Item -ItemType Directory -Force -Path $workPath, $distPath | Out-Null

Push-Location $projectRoot
try {
    & pyinstaller `
        --noconfirm `
        --clean `
        --workpath $workPath `
        --distpath $distPath `
        (Join-Path $projectRoot "packaging\pyinstaller\desktop.spec")
    if ($LASTEXITCODE -ne 0) {
        throw "PyInstaller failed with exit code: $LASTEXITCODE"
    }
}
finally {
    Pop-Location
}

$executable = Join-Path $distPath "GXWorks2-ST-Ladder-Helper\GXWorks2-ST-Ladder-Helper.exe"
if (-not (Test-Path -LiteralPath $executable -PathType Leaf)) {
    throw "Build completed but executable was not found: $executable"
}

$bundleRoot = Split-Path -Parent $executable

# Build the isolated x86 MX Component bridge directly into the release.  The
# gateway build script rejects output paths inside the repository, and this
# bundle directory has already passed the same outside-workspace guard above.
# Keeping it beside the packaged application also makes
# SimulatorGatewayRuntime.find_executable() work on a clean machine instead of
# accidentally depending on a developer-local copy under LOCALAPPDATA.
$gatewayDirectory = Join-Path $bundleRoot "simulator-gateway"
$gatewayBuildScript = Join-Path $projectRoot "tools\build_simulator_gateway.ps1"
& $gatewayBuildScript -OutputDirectory $gatewayDirectory
if ($LASTEXITCODE -ne 0) {
    throw "Simulator gateway build failed with exit code: $LASTEXITCODE"
}

$requiredRuntimeFiles = @(
    "_internal\pydantic_core\_pydantic_core*.pyd",
    "_internal\jiter\jiter*.pyd",
    "_internal\numpy\_core\_multiarray_umath*.pyd",
    "_internal\knowledge\fx3u_knowledge.sqlite",
    "_internal\knowledge\fx3u_dense_lsa.npz",
    "_internal\knowledge\manifest.json",
    "simulator-gateway\PlcAi.GxSimulator2Gateway.exe"
)
foreach ($relativePattern in $requiredRuntimeFiles) {
    $candidatePattern = Join-Path $bundleRoot $relativePattern
    if (-not (Get-ChildItem -Path $candidatePattern -File -ErrorAction SilentlyContinue)) {
        throw "Build dependency check failed; missing runtime file: $relativePattern"
    }
}

Write-Output $executable
