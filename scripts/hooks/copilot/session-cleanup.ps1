# Session Cleanup - sessionEnd Hook (PowerShell)
# ENCODING: Forces UTF-8 output.
$ErrorActionPreference = "Stop"

[Console]::OutputEncoding = [System.Text.Encoding]::UTF8
$OutputEncoding = [System.Text.Encoding]::UTF8

try {
    $rawInput = [Console]::In.ReadToEnd()
    $reason = "unknown"
    if ($rawInput -and $rawInput.Trim().Length -gt 0) {
        try {
            $inputJson = $rawInput | ConvertFrom-Json -ErrorAction Stop
            $reason = if ($inputJson.reason) { $inputJson.reason } else { "unknown" }
        } catch {
            # Malformed input - continue with defaults
        }
    }

    $stateDir = ".github/hooks/_state"
    if (Test-Path $stateDir) {
        # Log session end
        try {
            $logEntry = @{
                timestamp = (Get-Date -Format "yyyy-MM-ddTHH:mm:ssZ")
                event     = "session_end"
                reason    = $reason
            }
            $logEntry | ConvertTo-Json -Compress | Add-Content "$stateDir/search_audit.jsonl" -Encoding UTF8
        } catch {
            # Audit log write failed - non-critical
        }

        # Clean up state (keep audit log)
        Remove-Item "$stateDir/last_search_eval.json" -Force -ErrorAction SilentlyContinue
        Remove-Item "$stateDir/pending_complexity.json" -Force -ErrorAction SilentlyContinue
    }
    exit 0
} catch {
    # Fail open - cleanup should never block
    exit 0
}
