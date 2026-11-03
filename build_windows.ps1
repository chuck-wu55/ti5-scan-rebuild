$ErrorActionPreference = "Stop"
$projectDir = Split-Path -Parent $MyInvocation.MyCommand.Path
Set-Location -LiteralPath $projectDir
$skillDir = Join-Path $projectDir "resources\solidworks-automation-skill"
if (-not (Test-Path -LiteralPath (Join-Path $skillDir "SKILL.md"))) {
  throw "Bundled SolidWorks skill is missing: $skillDir"
}
$codexRuntimeDir = Join-Path $projectDir "resources\codex-runtime"
$codexDataArg = @()
if (Test-Path -LiteralPath (Join-Path $codexRuntimeDir "codex.exe")) {
  $codexDataArg = @("--add-data", "$codexRuntimeDir;resources/codex-runtime")
  Write-Host "Bundling Codex runtime from: $codexRuntimeDir"
} else {
  Write-Host "Codex runtime is not bundled; installed desktop app/CLI discovery will be used."
}

$pyInstallerArgs = @(
  "--noconfirm",
  "--clean",
  "--windowed",
  "--name", "Ti5 Scan Rebuild",
  "--hidden-import", "win32com.client",
  "--hidden-import", "win32com.client.dynamic",
  "--hidden-import", "pythoncom",
  "--hidden-import", "pywintypes",
  "--add-data", "$skillDir;resources/solidworks-automation-skill"
) + $codexDataArg + @("main.py")

python -m PyInstaller @pyInstallerArgs

if ($LASTEXITCODE -ne 0) {
  throw "PyInstaller failed with exit code $LASTEXITCODE"
}

$internalDir = Join-Path $projectDir "dist\Ti5 Scan Rebuild\_internal"
$qtDir = Join-Path $internalDir "PySide6"
foreach ($dllName in @("icuuc.dll", "icudt78.dll")) {
  foreach ($candidate in @((Join-Path $internalDir $dllName), (Join-Path $qtDir $dllName))) {
    if (Test-Path -LiteralPath $candidate) {
      Remove-Item -LiteralPath $candidate -Force
    }
  }
}

$releaseDir = Join-Path $projectDir "dist\Ti5 Scan Rebuild"
Copy-Item -LiteralPath (Join-Path $projectDir "README.md") -Destination $releaseDir -Force
Copy-Item -LiteralPath (Join-Path $projectDir "QUICKSTART_CN.txt") -Destination $releaseDir -Force
Copy-Item -LiteralPath (Join-Path $projectDir "USER_GUIDE_CN.txt") -Destination $releaseDir -Force

Write-Host "Build complete: $projectDir\dist\Ti5 Scan Rebuild\"
