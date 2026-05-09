param(
  [switch]$Rebuild,
  [switch]$CreateZip
)

$ErrorActionPreference = "Stop"

$ProjectRoot = $PSScriptRoot
$SourceAppName = "RouteForge"
$PackageName = "RouteForge_Package"
$DistributionName = "RouteForge_Distribution"
$SourceApp = Join-Path $ProjectRoot "dist\$SourceAppName"
$PackageRoot = Join-Path $ProjectRoot $PackageName
$PackagedApp = Join-Path $PackageRoot "RouteForge"
$SourceExe = Join-Path $SourceApp "$SourceAppName.exe"
$DistributionRoot = Join-Path $ProjectRoot $DistributionName
$ZipPath = Join-Path $DistributionRoot "RouteForge.zip"

function Assert-PathInsideProject {
  param(
    [Parameter(Mandatory = $true)]
    [string]$PathToCheck
  )

  $projectFullPath = [System.IO.Path]::GetFullPath($ProjectRoot)
  $targetFullPath = [System.IO.Path]::GetFullPath($PathToCheck)
  if (-not $targetFullPath.StartsWith($projectFullPath, [System.StringComparison]::OrdinalIgnoreCase)) {
    throw "Refusing to modify a path outside the project folder: $targetFullPath"
  }
}

if ($Rebuild) {
  $rebuildScript = Join-Path $ProjectRoot "Codex Rebuild Existing Env.ps1"
  if (-not (Test-Path -LiteralPath $rebuildScript)) {
    throw "Missing rebuild script: $rebuildScript"
  }
  & powershell -NoProfile -ExecutionPolicy Bypass -File $rebuildScript
}

if (-not (Test-Path -LiteralPath $SourceExe)) {
  throw "Could not find the built app. Run 'Rebuild and Package RouteForge.cmd' first."
}

Assert-PathInsideProject -PathToCheck $PackageRoot
Assert-PathInsideProject -PathToCheck $DistributionRoot

if (Test-Path -LiteralPath $PackageRoot) {
  Remove-Item -LiteralPath $PackageRoot -Recurse -Force
}

New-Item -ItemType Directory -Path $PackageRoot -Force | Out-Null
Copy-Item -LiteralPath $SourceApp -Destination $PackagedApp -Recurse -Force

$PackagedExe = Join-Path $PackagedApp "RouteForge.exe"

$startCmd = @"
@echo off
cd /d "%~dp0RouteForge"
start "" "RouteForge.exe"
"@
Set-Content -Path (Join-Path $PackageRoot "Start RouteForge.cmd") -Value $startCmd -Encoding ASCII

$readme = @"
RouteForge
==========

Open the app:
1. Double-click Start RouteForge.cmd

Main app file:
RouteForge\RouteForge.exe

What this package is:
This is the clean app package. It is the folder to use, share, or zip for distribution.

What not to move:
Keep the RouteForge folder and Start RouteForge.cmd together.

Updating this package:
From the project folder, run:
Rebuild and Package RouteForge.cmd

That rebuilds the app, refreshes this folder, and keeps the package clean each time.
"@
Set-Content -Path (Join-Path $PackageRoot "README_FIRST.txt") -Value $readme -Encoding UTF8

if (Test-Path -LiteralPath "assets\routeforge.ico") {
  Copy-Item -LiteralPath "assets\routeforge.ico" -Destination (Join-Path $PackageRoot "routeforge.ico") -Force
}

if ($CreateZip) {
  if (Test-Path -LiteralPath $DistributionRoot) {
    Remove-Item -LiteralPath $DistributionRoot -Recurse -Force
  }
  New-Item -ItemType Directory -Path $DistributionRoot -Force | Out-Null
  Compress-Archive -LiteralPath $PackageRoot -DestinationPath $ZipPath -Force
}

Write-Host ""
Write-Host "RouteForge package ready:"
Write-Host $PackageRoot
if ($CreateZip) {
  Write-Host ""
  Write-Host "Distribution zip ready:"
  Write-Host $ZipPath
}
