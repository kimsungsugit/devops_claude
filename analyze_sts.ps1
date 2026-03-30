$json = Get-Content 'd:\Project\devops\260105\sts_preview50.json' -Raw -Encoding UTF8
$data = $json | ConvertFrom-Json

# Analyze main test spec sheet
$testSpec = $data.sheets | Where-Object { $_.name -eq '3.SW Integration Test Spec' }
Write-Host "=== Main Test Spec Sheet ==="
Write-Host "Total rows (incl header): $($testSpec.total_rows)"
Write-Host "Total cols: $($testSpec.total_cols)"

# Count unique test cases (rows where Test Case ID is not empty)
$mainRows = $testSpec.rows | Where-Object { $_[1] -ne '' -and $_[1] -ne 'Test Case ID' }
Write-Host "Rows with Test Case ID (visible): $($mainRows.Count)"

# Count empty descriptions
$emptyDesc = $mainRows | Where-Object { $_[8] -eq '' -or $_[8] -eq $null }
Write-Host "Empty descriptions in main rows: $($emptyDesc.Count)"

# Count empty test methods
$emptyMethod = $mainRows | Where-Object { $_[5] -eq '' -or $_[5] -eq $null }
Write-Host "Empty test methods: $($emptyMethod.Count)"

# Count empty expected results
$allDataRows = $testSpec.rows | Select-Object -Skip 1
$emptyExpected = $allDataRows | Where-Object { $_[11] -eq '' -or $_[11] -eq $null }
Write-Host "Rows with empty expected results: $($emptyExpected.Count)"

# Count empty test actions
$emptyAction = $allDataRows | Where-Object { $_[10] -eq '' -or $_[10] -eq $null }
Write-Host "Rows with empty test actions: $($emptyAction.Count)"

# Count empty pre-conditions in main rows
$emptyPrecond = $mainRows | Where-Object { $_[9] -eq '' -or $_[9] -eq $null }
Write-Host "Main rows with empty pre-conditions: $($emptyPrecond.Count)"

# Count empty Safety Related
$emptySafety = $mainRows | Where-Object { $_[3] -eq '' -or $_[3] -eq $null }
Write-Host "Main rows with empty Safety Related: $($emptySafety.Count)"

# Count empty FS_REQ
$emptyFsReq = $mainRows | Where-Object { $_[7] -eq '' -or $_[7] -eq $null }
Write-Host "Main rows with empty FS_REQ: $($emptyFsReq.Count)"

# Count empty SRS
$emptySrs = $mainRows | Where-Object { $_[12] -eq '' -or $_[12] -eq $null }
Write-Host "Main rows with empty SRS: $($emptySrs.Count)"

# List test methods used
$methods = $mainRows | ForEach-Object { $_[5] } | Where-Object { $_ -ne '' } | Sort-Object -Unique
Write-Host "Test methods used: $($methods -join ', ')"

Write-Host ""
Write-Host "=== Traceability Sheet ==="
$trace = $data.sheets | Where-Object { $_.name -eq '5. Traceability(SwRS)' }
Write-Host "Total rows: $($trace.total_rows)"
Write-Host "Total cols: $($trace.total_cols)"

# Get requirement IDs from row 2 (0-indexed)
$reqRow = $trace.rows[2]
$reqIds = @()
for ($i = 4; $i -lt $reqRow.Count; $i++) {
    if ($reqRow[$i] -ne '' -and $reqRow[$i] -ne $null) {
        $reqIds += $reqRow[$i]
    }
}
Write-Host "Requirement IDs visible (first 20 cols): $($reqIds.Count)"
Write-Host "Requirement IDs: $($reqIds -join ', ')"
Write-Host "Total requirement columns (estimated): $($trace.total_cols - 4)"

# Count test cases in traceability
$traceTestCases = $trace.rows | Select-Object -Skip 4 | Where-Object { $_[2] -ne '' -and $_[2] -ne $null }
Write-Host "Test cases in traceability (visible): $($traceTestCases.Count)"
Write-Host "Estimated total test cases: $($trace.total_rows - 4)"

# Check for test cases with Count > 0 but no visible mappings
$unmapped = $traceTestCases | Where-Object {
    $hasMapping = $false
    for ($i = 4; $i -lt $_.Count; $i++) {
        if ($_[$i] -eq 1 -or $_[$i] -eq '1') { $hasMapping = $true; break }
    }
    -not $hasMapping
}
Write-Host "Test cases with no visible requirement mapping (in first 20 cols): $($unmapped.Count)"

# List test case IDs
Write-Host ""
Write-Host "=== All Visible Test Case IDs in Traceability ==="
$traceTestCases | ForEach-Object { Write-Host $_[2] }
