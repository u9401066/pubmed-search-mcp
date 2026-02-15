# =============================================================================
# Result Evaluator - postToolUse Hook for Copilot Coding Agent (PowerShell)
# =============================================================================
# THREE-TIER PARALLEL STRATEGY - postToolUse role:
#   Reads pending_complexity.json (Tier 2), evaluates results, writes state.
#   For Tier 2: even good results get "suggest_supplement" to nudge pipeline.
# See evaluate-results.sh for detailed documentation.
#
# ENCODING: Forces UTF-8 output to prevent mojibake on Windows.
# =============================================================================
$ErrorActionPreference = "Stop"

# Force UTF-8 output encoding
[Console]::OutputEncoding = [System.Text.Encoding]::UTF8
$OutputEncoding = [System.Text.Encoding]::UTF8

try {
    $rawInput = [Console]::In.ReadToEnd()
    if (-not $rawInput -or $rawInput.Trim().Length -eq 0) {
        exit 0
    }

    $inputJson = $rawInput | ConvertFrom-Json -ErrorAction Stop
    $toolName = $inputJson.toolName

    # Only evaluate unified_search results
    if ($toolName -notmatch 'unified_search') {
        exit 0
    }

    $resultType = $inputJson.toolResult.resultType
    $resultText = $inputJson.toolResult.textResultForLlm

    # Parse tool args
    $toolArgs = $null
    if ($inputJson.toolArgs) {
        if ($inputJson.toolArgs -is [string]) {
            $toolArgs = $inputJson.toolArgs | ConvertFrom-Json
        } else {
            $toolArgs = $inputJson.toolArgs
        }
    }

    $query = $toolArgs.query
    $hadPipeline = $toolArgs.pipeline

    $stateDir = ".github/hooks/_state"
    if (-not (Test-Path $stateDir)) {
        New-Item -ItemType Directory -Path $stateDir -Force | Out-Null
    }

    # Read pending complexity flag (Tier 2) - safe parse
    $pendingTier = $null
    $pendingTemplate = "comprehensive"
    $pendingFile = "$stateDir/pending_complexity.json"
    if (Test-Path $pendingFile -ErrorAction SilentlyContinue) {
        try {
            $pendingRaw = Get-Content $pendingFile -Raw -ErrorAction Stop
            if ($pendingRaw -and $pendingRaw.Trim().Length -gt 0) {
                $pending = $pendingRaw | ConvertFrom-Json -ErrorAction Stop
                $pendingTier = $pending.tier
                $pendingTemplate = if ($pending.template) { $pending.template } else { "comprehensive" }
            }
        } catch {
            # Corrupted state file - ignore
        }
        Remove-Item $pendingFile -Force -ErrorAction SilentlyContinue
    }

    # Handle search failure
    if ($resultType -eq 'failure') {
        $eval = @{
            query        = $query
            quality      = "poor"
            result_count = 0
            suggestion   = "Search failed. Try: 1) Simpler query, 2) Different sources, 3) Pipeline mode."
            template     = $pendingTemplate
            nudged       = $false
        }
        $eval | ConvertTo-Json -Compress | Set-Content "$stateDir/last_search_eval.json"
        exit 0
    }

    # Count results from result text
    $resultCount = 0
    if ($resultText) {
        $pmidCount = ([regex]::Matches($resultText, 'PMID:\s*\d+|pmid/\d+')).Count
        $numberedCount = ([regex]::Matches($resultText, '(?m)^\s*\d+\.')).Count
        $titleCount = ([regex]::Matches($resultText, '(?m)^\s*\*\*[A-Z]')).Count
        $resultCount = [Math]::Max([Math]::Max($pmidCount, $numberedCount), $titleCount)
    }

    # Check source diversity
    $sourceCount = 0
    @("pubmed", "openalex", "semantic_scholar", "europe_pmc", "crossref", "core") | ForEach-Object {
        if ($resultText -match $_) {
            $sourceCount++
        }
    }

    # Quality assessment
    $quality = "good"
    $suggestion = ""

    if ($resultCount -lt 3) {
        $quality = "poor"
        $suggestion = "Only $resultCount articles found. "
        if (-not $hadPipeline -or $hadPipeline -eq 'null') {
            $suggestion += "Try pipeline mode: unified_search(pipeline=`"template: comprehensive`"). "
        } else {
            $suggestion += "Try broadening query or removing filters. "
        }
    }

    if ($sourceCount -le 1 -and $resultCount -gt 0) {
        if ($quality -eq "good") { $quality = "acceptable" }
        $suggestion += "Only $sourceCount source(s). Add: sources=`"pubmed,openalex,semantic_scholar`". "
    }

    if ($resultCount -ge 3 -and $resultCount -lt 8 -and -not $hadPipeline) {
        if ($quality -eq "good") { $quality = "acceptable" }
        $suggestion += "Found $resultCount articles. Pipeline mode might find more. "
    }

    # Tier 2 supplement: Even if results decent, suggest pipeline too
    if ($pendingTier -eq "moderate" -and (-not $hadPipeline -or $hadPipeline -eq 'null')) {
        if ($quality -eq "good" -or $quality -eq "acceptable") {
            $quality = "suggest_supplement"
            $suggestion = "Quick search returned $resultCount articles - good start. For comprehensive coverage, also run a pipeline search to catch articles from additional sources and MeSH-expanded queries."
        }
    }

    # Write state file
    if ($quality -ne "good") {
        $eval = @{
            query        = $query
            quality      = $quality
            result_count = $resultCount
            suggestion   = $suggestion
            source_count = $sourceCount
            had_pipeline = if ($hadPipeline) { $hadPipeline } else { "none" }
            template     = $pendingTemplate
            nudged       = $false
        }
        $eval | ConvertTo-Json -Compress | Set-Content "$stateDir/last_search_eval.json" -Encoding UTF8
    } else {
        Remove-Item "$stateDir/last_search_eval.json" -Force -ErrorAction SilentlyContinue
    }

    # Audit log (with tier tracking)
    try {
        $logEntry = @{
            timestamp    = (Get-Date -Format "yyyy-MM-ddTHH:mm:ssZ")
            query        = $query
            quality      = $quality
            result_count = $resultCount
            source_count = $sourceCount
            had_pipeline = if ($hadPipeline) { $hadPipeline } else { "none" }
            tier         = if ($pendingTier) { $pendingTier } else { "none" }
        }
        $logEntry | ConvertTo-Json -Compress | Add-Content "$stateDir/search_audit.jsonl" -Encoding UTF8
    } catch {
        # Audit logging failed - non-critical, continue
    }

    exit 0

} catch {
    # On ANY error, exit silently (postToolUse output is ignored anyway)
    exit 0
}
