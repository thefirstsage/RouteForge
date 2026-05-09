$ErrorActionPreference = 'Stop'

Set-Location -LiteralPath $PSScriptRoot

$appExe = Join-Path $PSScriptRoot 'dist\RouteForge\RouteForge.exe'
$runningApp = Get-CimInstance Win32_Process -ErrorAction SilentlyContinue |
    Where-Object { $_.ExecutablePath -and ($_.ExecutablePath -ieq $appExe) } |
    Select-Object -First 1
if ($runningApp) {
    throw "Close RouteForge before rebuilding."
}

if (-not (Test-Path -LiteralPath '.\.venv\Scripts\python.exe')) {
    throw "Build environment is not installed yet. Run the rebuild command once from this folder."
}

if (-not (Test-Path -LiteralPath '.\.venv\Lib\site-packages\PySide6') -or
    -not (Test-Path -LiteralPath '.\.venv\Lib\site-packages\requests') -or
    -not (Test-Path -LiteralPath '.\.venv\Scripts\pyinstaller.exe')) {
    throw "Build packages are missing. Run the rebuild command once from this folder."
}

$env:PATH = (Resolve-Path -LiteralPath '.\.venv\Scripts').Path + ';' + $env:PATH
$env:TEMP = Join-Path $PSScriptRoot 'build-temp-active'
$env:TMP = $env:TEMP
if (-not (Test-Path -LiteralPath $env:TEMP)) {
    New-Item -ItemType Directory -Path $env:TEMP -Force | Out-Null
}

powershell -ExecutionPolicy Bypass -File .\build_windows.ps1
if ($LASTEXITCODE -ne 0) {
    throw "Build failed with exit code $LASTEXITCODE."
}

foreach ($path in @('build', 'build-temp-active')) {
    if (Test-Path -LiteralPath $path) {
        try { [System.IO.Directory]::Delete((Resolve-Path -LiteralPath $path), $true) } catch {}
    }
}

Write-Host 'Codex rebuild complete.' -ForegroundColor Green
