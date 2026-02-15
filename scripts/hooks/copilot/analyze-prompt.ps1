# Prompt Analyzer - userPromptSubmitted Hook (PowerShell)
# ENCODING: Forces UTF-8 output.
$ErrorActionPreference = "Stop"

[Console]::OutputEncoding = [System.Text.Encoding]::UTF8
$OutputEncoding = [System.Text.Encoding]::UTF8

try {
    $rawInput = [Console]::In.ReadToEnd()
    if (-not $rawInput -or $rawInput.Trim().Length -eq 0) {
        exit 0
    }

    $inputJson = $rawInput | ConvertFrom-Json -ErrorAction Stop
    $prompt = $inputJson.prompt
    if (-not $prompt) { exit 0 }

    $stateDir = ".github/hooks/_state"
    if (-not (Test-Path $stateDir)) {
        New-Item -ItemType Directory -Path $stateDir -Force | Out-Null
    }

    $intent = "unknown"
    $complexity = "simple"

    if ($prompt -match '\bvs\.?\b|versus|compared?\s+(to|with)') {
        $intent = "comparison"; $complexity = "complex"
    } elseif ($prompt -match 'systematic|comprehensive|review') {
        $intent = "systematic"; $complexity = "complex"
    } elseif ($prompt -match 'related|citation|PMID|DOI') {
        $intent = "exploration"; $complexity = "moderate"
    } elseif ($prompt -match '\b(gene|BRCA|TP53|drug|compound)\b') {
        $intent = "gene_drug"; $complexity = "moderate"
    } elseif ($prompt -match 'search|find') {
        $intent = "quick_search"; $complexity = "simple"
    }

    try {
        $previewLen = [Math]::Min(200, $prompt.Length)
        $logEntry = @{
            timestamp      = (Get-Date -Format "yyyy-MM-ddTHH:mm:ssZ")
            event          = "prompt_submitted"
            intent         = $intent
            complexity     = $complexity
            prompt_preview = $prompt.Substring(0, $previewLen)
        }
        $logEntry | ConvertTo-Json -Compress | Add-Content "$stateDir/search_audit.jsonl" -Encoding UTF8
    } catch {
        # Audit log write failed - non-critical
    }
    exit 0
} catch {
    # Fail open - prompt analysis should never block
    exit 0
}
