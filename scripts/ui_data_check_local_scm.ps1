$backend = Start-Job -ScriptBlock {
    Set-Location 'D:\Project\devops\260105'
    & 'D:\Project\devops\260105\backend\venv\Scripts\python.exe' -m uvicorn backend.main:app --host 127.0.0.1 --port 7000
}

$frontend = Start-Job -ScriptBlock {
    Set-Location 'D:\Project\devops\260105\frontend'
    & npm.cmd run dev -- --host 127.0.0.1 --port 5173
}

try {
    $ok = $false
    for ($i = 0; $i -lt 30; $i++) {
        Start-Sleep -Seconds 2
        try {
            $backendResp = Invoke-WebRequest -UseBasicParsing http://127.0.0.1:7000/api/scm/list -TimeoutSec 3
            $frontendResp = Invoke-WebRequest -UseBasicParsing http://127.0.0.1:5173 -TimeoutSec 3
            if ($backendResp.StatusCode -eq 200 -and $frontendResp.StatusCode -eq 200) {
                $ok = $true
                break
            }
        } catch {
        }
    }

    if (-not $ok) {
        throw "servers did not become ready"
    }

    Write-Output "---SCM LIST---"
    (Invoke-WebRequest -UseBasicParsing http://127.0.0.1:7000/api/scm/list).Content
    Write-Output "---AUDIT---"
    (Invoke-WebRequest -UseBasicParsing http://127.0.0.1:7000/api/scm/audit/hdpdm01?limit=5).Content
    Write-Output "---HISTORY---"
    (Invoke-WebRequest -UseBasicParsing http://127.0.0.1:7000/api/scm/change-history/hdpdm01?limit=5).Content
    Write-Output "---DETAIL---"
    (Invoke-WebRequest -UseBasicParsing http://127.0.0.1:7000/api/scm/change-history/detail/impact_20260326_135056).Content
} finally {
    Stop-Job -Job $backend, $frontend -ErrorAction SilentlyContinue | Out-Null
    Remove-Job -Job $backend, $frontend -Force -ErrorAction SilentlyContinue | Out-Null
}
