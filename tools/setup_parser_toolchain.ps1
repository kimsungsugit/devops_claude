param(
  [string]$ProjectRoot = "D:\Project\devops\260105",
  [string]$SourceRoot = "D:\Project\Ados\PDS_64_RD"
)

$ErrorActionPreference = "Stop"

$venvPython = Join-Path $ProjectRoot ".venv\Scripts\python.exe"
if (-not (Test-Path $venvPython)) {
  throw "venv python not found: $venvPython"
}

Write-Host "[1/3] Install parser dependencies"
& $venvPython -m pip install -r (Join-Path $ProjectRoot "requirements-dev.txt")
if ($LASTEXITCODE -ne 0) { throw "pip install failed" }

Write-Host "[2/3] Probe parser toolchain"
$env:SOURCE_ROOT = $SourceRoot
& $venvPython (Join-Path $ProjectRoot "tools\setup_code_parsers.py")
if ($LASTEXITCODE -ne 0) { throw "setup_code_parsers failed" }

Write-Host "[3/3] Show status path"
$statusJson = Join-Path $ProjectRoot "reports\uds\parser_toolchain_status.json"
if (Test-Path $statusJson) {
  Write-Host "STATUS_JSON=$statusJson"
} else {
  throw "status json not found: $statusJson"
}
