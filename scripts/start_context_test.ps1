param(
    [ValidateSet("adaptive", "legacy", "minimal", "manual", "examples", "combined")]
    [string]$Policy = "adaptive",
    [int]$Port = 0,
    [switch]$NoBrowser,
    [switch]$ValidateOnly
)
$ErrorActionPreference = "Stop"
Set-StrictMode -Version Latest
$root = [IO.Path]::GetFullPath((Join-Path $PSScriptRoot ".."))
try {
    if (-not (Test-Path -LiteralPath (Join-Path $root "GXWorks-Agent-Web.exe") -PathType Leaf)) {
        throw "Use the complete extracted Windows test release, not the source checkout."
    }
    $dataRoot = [Environment]::GetFolderPath("LocalApplicationData")
    if ([string]::IsNullOrWhiteSpace($dataRoot)) { throw "LocalApplicationData is unavailable." }
    $workspace = Join-Path $dataRoot ("GXWorks-Agent\ContextPolicyTests\refresh-c6bc6ef\" + $Policy)
    $env:GXWORKS_CONTEXT_POLICY = $Policy
    Write-Host ("CONTEXT TEST: " + $Policy) -ForegroundColor Cyan
    Write-Host ("Base: fix/generation-result-refresh @ c6bc6ef")
    Write-Host ("Isolated workspace: " + $workspace)
    Write-Host "Model calls made from the UI use your configured API and may incur charges."
    Write-Host "Starting this launcher does not call a model, GX, a gateway, or a PLC."
    $arguments = @{ Workspace = $workspace; Port = $Port }
    if ($NoBrowser) { $arguments.NoBrowser = $true }
    if ($ValidateOnly) { $arguments.ValidateOnly = $true }
    & (Join-Path $PSScriptRoot "start_web.ps1") @arguments
    exit $LASTEXITCODE
} catch {
    Write-Host ("Context test launch failed: " + $_.Exception.Message) -ForegroundColor Red
    exit 1
}
