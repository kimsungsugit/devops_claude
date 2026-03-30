$r = Invoke-WebRequest -Uri 'http://127.0.0.1:8000/api/local/sts/preview/sts_local_20260310_131752.xlsm?max_rows=50' -TimeoutSec 60 -UseBasicParsing
[System.IO.File]::WriteAllText('d:\Project\devops\260105\sts_preview.json', $r.Content, [System.Text.Encoding]::UTF8)
Write-Host "Done. Length: $($r.Content.Length)"
