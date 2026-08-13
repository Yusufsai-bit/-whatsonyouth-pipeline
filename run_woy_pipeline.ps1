# What's On Youth - Weekly social media pipeline
# Scheduled via Windows Task Scheduler (every Sunday 6:00 PM)

# Set BLOTATO_API_KEY as a Windows System Environment Variable, not here.
# Control Panel -> System -> Advanced -> Environment Variables -> System Variables -> New
if (-not $env:BLOTATO_API_KEY) {
    Write-Error "BLOTATO_API_KEY environment variable is not set. Aborting."
    exit 1
}
$logPath = Join-Path $PSScriptRoot "woy_pipeline_log.txt"
$ts      = (Get-Date).ToString("yyyy-MM-dd HH:mm:ss")

Add-Content $logPath ""
Add-Content $logPath "[$ts] ===== WOY Weekly Pipeline START ====="

Set-Location $PSScriptRoot

# Stage 1: Scrape + brand
$out1 = python woy_pipeline.py 2>&1
$out1 | Tee-Object -FilePath $logPath -Append

if ($LASTEXITCODE -ne 0) {
    Add-Content $logPath "[$ts] ABORT: woy_pipeline.py failed - skipping publish."
    exit 1
}

# Stage 2: Upload + schedule to Blotato
$out2 = python woy_publish_api.py 2>&1
$out2 | Tee-Object -FilePath $logPath -Append

$ts2 = (Get-Date).ToString("yyyy-MM-dd HH:mm:ss")
Add-Content $logPath "[$ts2] ===== WOY Weekly Pipeline END ====="
