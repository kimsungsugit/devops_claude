param(
  [Parameter(Mandatory = $true)][string]$SourceRoot,
  [Parameter(Mandatory = $true)][string]$ReqPaths,
  [string]$Template = "",
  [string]$ReportDir = "reports",
  [switch]$TestMode,
  [switch]$Full,
  [switch]$AiEnable,
  [switch]$Expand,
  [switch]$AiDetailed,
  [int]$RagTopK = 12,
  [string]$BaselineOut = "reports/uds_local/quality_baseline.json",
  [string]$RunOut = "reports/uds_local/quality_run.json",
  [string]$CompareOut = "reports/uds_local/quality_compare.json",
  [switch]$FailOnRegression
)

# ⚠ 예전엔 이 두 줄이 **다른 저장소**(d:\Project\devops\260105)로 하드코딩돼 있었다.
# 이 저장소에서 돌려도 저쪽 코드가 저쪽 인터프리터로 실행돼, 여기서 고친 게이트가
# 결과에 반영되지 않는다 — 실제로 reports/uds_local/quality_baseline*.json 의 산출
# 경로가 전부 D:\Project\devops\260105\reports\... 였다(이 저장소 베이스라인이 아니었다).
# 이제 **이 파일 기준**으로 저장소 루트를 잡는다.
$RepoRoot = (Resolve-Path (Join-Path $PSScriptRoot "..\..")).Path
$py = Join-Path $RepoRoot ".venv\Scripts\python.exe"
$script = Join-Path $RepoRoot "scripts\uds\uds_quality_cycle.py"
if (-not (Test-Path $py)) { throw "인터프리터가 없다: $py  (맨 python 은 mingw 라 bcrypt/ruff 가 없다)" }
if (-not (Test-Path $script)) { throw "러너가 없다: $script" }

$args = @(
  $script,
  "--source-root", $SourceRoot,
  "--req-paths", $ReqPaths,
  "--report-dir", $ReportDir,
  "--rag-top-k", "$RagTopK",
  "--baseline-out", $BaselineOut,
  "--run-out", $RunOut,
  "--compare-out", $CompareOut
)

if ($Template) { $args += @("--template", $Template) }
if ($TestMode) { $args += "--test-mode" }
if ($Full) { $args += "--full" }
if ($AiEnable) { $args += "--ai-enable" }
if ($Expand) { $args += "--expand" }
if ($AiDetailed) { $args += "--ai-detailed" }

& $py @args
if ($LASTEXITCODE -ne 0) {
  throw "UDS quality cycle failed with exit code $LASTEXITCODE"
}

if ($FailOnRegression -and (Test-Path $CompareOut)) {
  $cmp = Get-Content -Raw -Path $CompareOut | ConvertFrom-Json
  if ($cmp.soft_fail -eq $true) {
    $reason = ($cmp.soft_fail_reasons -join ", ")
    throw "UDS quality regression detected: $reason"
  }
}

