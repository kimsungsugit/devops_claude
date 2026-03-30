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

    & node C:\Users\kss11\AppData\Local\npm-cache\_npx\31e32ef8478fbf80\node_modules\@playwright\cli\playwright-cli.js -s=codex_ui_check open http://127.0.0.1:5173
    Start-Sleep -Seconds 3
    & node C:\Users\kss11\AppData\Local\npm-cache\_npx\31e32ef8478fbf80\node_modules\@playwright\cli\playwright-cli.js -s=codex_ui_check snapshot
    & node C:\Users\kss11\AppData\Local\npm-cache\_npx\31e32ef8478fbf80\node_modules\@playwright\cli\playwright-cli.js -s=codex_ui_check close
} finally {
    Stop-Job -Job $backend, $frontend -ErrorAction SilentlyContinue | Out-Null
    Remove-Job -Job $backend, $frontend -Force -ErrorAction SilentlyContinue | Out-Null
}
