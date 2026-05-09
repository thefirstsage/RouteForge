$ErrorActionPreference = "Stop"

$AppName = "RouteForge"
$ProjectRoot = $PSScriptRoot
$DistRoot = Join-Path $ProjectRoot "dist"
$CurrentApp = Join-Path $DistRoot $AppName
$BackupRoot = Join-Path $ProjectRoot "backups"

function Remove-OlderBackups {
  param(
    [Parameter(Mandatory = $true)]
    [string]$BackupRoot
  )

  if (-not (Test-Path -LiteralPath $BackupRoot)) {
    return
  }

  $resolvedBackupRoot = (Resolve-Path -LiteralPath $BackupRoot).Path
  $backups = Get-ChildItem -LiteralPath $resolvedBackupRoot -Directory |
    Where-Object { $_.Name -like "$AppName-*" } |
    Sort-Object LastWriteTime -Descending

  $backups | Select-Object -Skip 1 | ForEach-Object {
    $backupPath = $_.FullName
    if ($backupPath.StartsWith($resolvedBackupRoot, [System.StringComparison]::OrdinalIgnoreCase)) {
      Remove-Item -LiteralPath $backupPath -Recurse -Force
    }
  }
}

if (Test-Path -LiteralPath $CurrentApp) {
  New-Item -ItemType Directory -Path $BackupRoot -Force | Out-Null
  $timestamp = Get-Date -Format "yyyyMMdd-HHmmss"
  $backupPath = Join-Path $BackupRoot "$AppName-$timestamp"
  Move-Item -LiteralPath $CurrentApp -Destination $backupPath
  Remove-OlderBackups -BackupRoot $BackupRoot
}

$pyinstallerArgs = @(
  "--noconfirm",
  "--clean",
  "--windowed",
  "--name", $AppName,
  "--paths", "src",
  "--add-data", "config\targets.json;config"
)

if (Test-Path -LiteralPath "assets\routeforge.png") {
  $pyinstallerArgs += @("--add-data", "assets\routeforge.png;assets")
}

if (Test-Path -LiteralPath "assets\routeforge.ico") {
  $pyinstallerArgs += @("--icon", "assets\routeforge.ico")
}

$pyinstallerArgs += "src\desktop_app.py"

python -m PyInstaller @pyinstallerArgs

Remove-OlderBackups -BackupRoot $BackupRoot

Write-Host ""
Write-Host "Build complete."
Write-Host "Open dist\$AppName\$AppName.exe"
Write-Host "Backup retention: keeping the newest backup only."
