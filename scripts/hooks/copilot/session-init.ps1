# Session Init - sessionStart Hook (PowerShell)
# ENCODING: Forces UTF-8 output.
$ErrorActionPreference = "Stop"

[Console]::OutputEncoding = [System.Text.Encoding]::UTF8
$OutputEncoding = [System.Text.Encoding]::UTF8

try {
    $rawInput = [Console]::In.ReadToEnd()
    $source = "unknown"
    if ($rawInput -and $rawInput.Trim().Length -gt 0) {
        try {
            $inputJson = $rawInput | ConvertFrom-Json -ErrorAction Stop
            $source = if ($inputJson.source) { $inputJson.source } else { "unknown" }
        } catch {
            # Malformed input - continue with defaults
        }
    }

    $stateDir = ".github/hooks/_state"
    if (-not (Test-Path $stateDir)) {
        New-Item -ItemType Directory -Path $stateDir -Force | Out-Null
    }

    # Clear stale state from previous session
    Remove-Item "$stateDir/last_search_eval.json" -Force -ErrorAction SilentlyContinue
    Remove-Item "$stateDir/pending_complexity.json" -Force -ErrorAction SilentlyContinue

    # Log session start
    try {
        $logEntry = @{
            timestamp = (Get-Date -Format "yyyy-MM-ddTHH:mm:ssZ")
            source    = $source
            event     = "session_start"
        }
        $logEntry | ConvertTo-Json -Compress | Add-Content "$stateDir/search_audit.jsonl" -Encoding UTF8
    } catch {
        # Audit log write failed - non-critical
    }
    exit 0
} catch {
    # Fail open - session init should never block
    exit 0
}
