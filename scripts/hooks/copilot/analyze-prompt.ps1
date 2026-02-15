# =============================================================================
# Prompt Analyzer - userPromptSubmitted Hook (PowerShell)
# =============================================================================
# Detects research intent, manages workflow tracker, outputs instructions.
# Output: JSON with "instructions" field for AI context injection.
#
# WORKFLOW STEPS:
#   1. Query Analysis      -> analyze_search_query / parse_pico
#   2. Strategy Formation  -> generate_search_queries
#   3. Initial Search      -> unified_search (no pipeline)
#   4. Pipeline Search     -> unified_search(pipeline='template: ...')
#   5. Result Evaluation   -> get_citation_metrics / get_session_summary
#   6. Deep Exploration    -> find_related / citing / fulltext / citation_tree
#   7. Export & Synthesis   -> prepare_export / build_research_timeline
#
# ENCODING: Forces UTF-8 output. All strings are ASCII-only.
# =============================================================================
$ErrorActionPreference = "Stop"

[Console]::OutputEncoding = [System.Text.Encoding]::UTF8
$OutputEncoding = [System.Text.Encoding]::UTF8

try {
    $rawInput = [Console]::In.ReadToEnd()
    if (-not $rawInput -or $rawInput.Trim().Length -eq 0) { exit 0 }

    $inputJson = $rawInput | ConvertFrom-Json -ErrorAction Stop
    $prompt = $inputJson.prompt
    if (-not $prompt) { exit 0 }

    $stateDir = ".github/hooks/_state"
    if (-not (Test-Path $stateDir)) {
        New-Item -ItemType Directory -Path $stateDir -Force | Out-Null
    }

    # --- Intent Detection ---
    $intent = "unknown"
    $complexity = "simple"
    $template = "comprehensive"

    if ($prompt -match '\bvs\.?\b|versus|compared?\s+(to|with)') {
        $intent = "comparison"; $complexity = "complex"; $template = "pico"
    } elseif ($prompt -match 'systematic|comprehensive|review|meta.?analysis') {
        $intent = "systematic"; $complexity = "complex"; $template = "comprehensive"
    } elseif ($prompt -match 'related|citation|PMID|DOI|explore') {
        $intent = "exploration"; $complexity = "moderate"; $template = "exploration"
    } elseif ($prompt -match '\b(gene|BRCA|TP53|EGFR|drug|compound|PubChem)\b') {
        $intent = "gene_drug"; $complexity = "moderate"; $template = "gene_drug"
    } elseif ($prompt -match 'search|find|paper|article|literature') {
        $intent = "quick_search"; $complexity = "simple"
    }

    # --- Workflow Tracker ---
    $trackerFile = "$stateDir/workflow_tracker.json"
    $tracker = $null

    if (Test-Path $trackerFile -ErrorAction SilentlyContinue) {
        try {
            $raw = Get-Content $trackerFile -Raw -ErrorAction Stop
            if ($raw -and $raw.Trim().Length -gt 0) {
                $tracker = $raw | ConvertFrom-Json -ErrorAction Stop
            }
        } catch {
            Remove-Item $trackerFile -Force -ErrorAction SilentlyContinue
        }
    }

    # Create tracker for research intents
    $isResearch = $intent -ne "unknown"
    if ($isResearch -and -not $tracker) {
        $topicLen = [Math]::Min(120, $prompt.Length)
        $cleanTopic = ($prompt.Substring(0, $topicLen)) -replace '[^\x20-\x7E]', '?'
        $tracker = @{
            topic      = $cleanTopic
            intent     = $intent
            template   = $template
            created_at = (Get-Date -Format "yyyy-MM-ddTHH:mm:ssZ")
            steps      = @{
                query_analysis     = "not-started"
                strategy_formation = "not-started"
                initial_search     = "not-started"
                pipeline_search    = "not-started"
                result_evaluation  = "not-started"
                deep_exploration   = "not-started"
                export_synthesis   = "not-started"
            }
        }
        $tracker | ConvertTo-Json -Depth 3 -Compress | Set-Content $trackerFile -Encoding UTF8
    }

    # --- Output Instructions (if tracker active) ---
    if ($tracker) {
        $steps = $tracker.steps
        $stepDefs = @(
            @{ key = "query_analysis";     label = "Query Analysis";      tool = "analyze_search_query / parse_pico" }
            @{ key = "strategy_formation"; label = "Strategy Formation";  tool = "generate_search_queries" }
            @{ key = "initial_search";     label = "Initial Search";      tool = "unified_search (no pipeline)" }
            @{ key = "pipeline_search";    label = "Pipeline Search";     tool = "unified_search(pipeline='template: ...')" }
            @{ key = "result_evaluation";  label = "Result Evaluation";   tool = "get_citation_metrics / get_session_summary" }
            @{ key = "deep_exploration";   label = "Deep Exploration";    tool = "find_related / citing / fulltext / citation_tree" }
            @{ key = "export_synthesis";   label = "Export & Synthesis";  tool = "prepare_export / build_research_timeline" }
        )

        $lines = @()
        $completedCount = 0
        $nextFound = $false

        foreach ($def in $stepDefs) {
            $k = $def.key
            $status = $steps.$k
            if (-not $status) { $status = "not-started" }

            if ($status -eq "completed") {
                $completedCount++
                $lines += "[x] $($def.label)"
            } elseif (-not $nextFound) {
                $nextFound = $true
                $lines += "[ ] $($def.label)  <-- NEXT: $($def.tool)"
            } else {
                $lines += "[ ] $($def.label)"
            }
        }

        $total = $stepDefs.Count
        $tpl = if ($tracker.template) { $tracker.template } else { "comprehensive" }

        $instructions = "RESEARCH WORKFLOW ($completedCount/$total steps done)`n"
        $instructions += "Topic: $($tracker.topic)`n"
        $instructions += "Intent: $($tracker.intent) | Template: $tpl`n`n"
        $instructions += ($lines -join "`n")
        $instructions += "`n`nFollow steps in order for thorough research."
        $instructions += " For complex queries, always use pipeline mode (step 4)."
        $instructions += " Skip steps only if user explicitly requests quick search."

        $output = @{ instructions = $instructions }
        $output | ConvertTo-Json -Compress
    }

    # --- Audit Log ---
    try {
        $logEntry = @{
            timestamp  = (Get-Date -Format "yyyy-MM-ddTHH:mm:ssZ")
            event      = "prompt_submitted"
            intent     = $intent
            complexity = $complexity
        }
        $logEntry | ConvertTo-Json -Compress | Add-Content "$stateDir/search_audit.jsonl" -Encoding UTF8
    } catch {}

    exit 0
} catch {
    # Fail open - prompt analysis should never block
    exit 0
}
