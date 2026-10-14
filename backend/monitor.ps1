while ($true) {
    $statusRow = docker exec leadpilot-ai-postgres psql -U postgres -d leadpilot -t -c "SELECT status FROM sources WHERE id=72;" 2>$null
    $countRow = docker exec leadpilot-ai-postgres psql -U postgres -d leadpilot -t -c "SELECT count(*) FROM companies WHERE source_id=72;" 2>$null
    $status = ($statusRow -join "").Trim()
    $count = ($countRow -join "").Trim()
    $ts = Get-Date -Format "HH:mm:ss"
    "$ts status=$status companies_saved=$count" | Out-File -Append "C:\Users\KABEER AHMED\OneDrive\Desktop\leadpilot-ai\backend\crawl_progress.log"
    if ($status -in @("COMPLETED","FAILED")) { "$ts crawl finished: $status" | Out-File -Append "C:\Users\KABEER AHMED\OneDrive\Desktop\leadpilot-ai\backend\crawl_progress.log"; break }
    Start-Sleep -Seconds 120
}
