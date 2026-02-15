# =============================================================================
# Pipeline Enforcer - preToolUse Hook for Copilot Coding Agent (PowerShell)
# =============================================================================
#
# THREE-TIER PARALLEL STRATEGY (see enforce-pipeline.sh for full docs):
#   Tier 1 (score 0-2): ALLOW - fast search, no interference
#   Tier 2 (score 3-4): ALLOW - fast results + post-eval pipeline suggestion
#   Tier 3 (score 5+):  DENY  - require pipeline upfront
#
# ENCODING: Forces UTF-8 output to prevent mojibake on Windows.
#           All output strings are ASCII-only for maximum compatibility.
# =============================================================================
$ErrorActionPreference = "Stop"

# Force UTF-8 output encoding (prevents mojibake on Windows)
[Console]::OutputEncoding = [System.Text.Encoding]::UTF8
$OutputEncoding = [System.Text.Encoding]::UTF8

try {
    $rawInput = [Console]::In.ReadToEnd()
    if (-not $rawInput -or $rawInput.Trim().Length -eq 0) {
        exit 0  # No input, allow
    }

    $inputJson = $rawInput | ConvertFrom-Json -ErrorAction Stop
    $toolName = $inputJson.toolName
    $toolArgsRaw = $inputJson.toolArgs

    if (-not $toolName) {
        exit 0  # No tool name, allow
    }

    $stateDir = ".github/hooks/_state"

    # -----------------------------------------------------------------------
    # Helper: Get complexity score (numeric)
    # -----------------------------------------------------------------------
    function Get-ComplexityScore {
        param([string]$Query)
        $score = 0

        if ($Query -match '\bvs\.?\b|versus|compared?\s+(to|with)|better\s+than|superior|inferior|non-?inferior') {
            $score += 3
        }
        if ($Query -match '\b(patient|population|intervention|comparison|outcome)\b') {
            $score += 2
        }
        if ($Query -match '\b(efficacy|safety|mortality|morbidity|adverse)\b') {
            $score += 1
        }
        if ($Query -match '\b(systematic|comprehensive|meta-?analysis|review|all\s+studies)\b') {
            $score += 2
        }
        $wordCount = ($Query -split '\s+').Count
        if ($wordCount -gt 6) {
            $score += 1
        }
        if ($Query -match '\b(AND|OR|NOT)\b') {
            $score += 1
        }
        if ($Query -match '\[MeSH\]|\[Mesh\]|\[tiab\]') {
            $score += 1
        }

        return $score
    }

    # -----------------------------------------------------------------------
    # Helper: Recommend template
    # -----------------------------------------------------------------------
    function Get-RecommendedTemplate {
        param([string]$Query)

        if ($Query -match '\bvs\.?\b|versus|compared?\s+(to|with)') {
            return "pico"
        }
        if ($Query -match 'systematic|comprehensive|meta-?analysis|review') {
            return "comprehensive"
        }
        if ($Query -match '\b(gene|BRCA|TP53|EGFR|PubChem|compound|drug)\b') {
            return "gene_drug"
        }
        return "comprehensive"
    }

    # -----------------------------------------------------------------------
    # Helper: Safe JSON file read
    # -----------------------------------------------------------------------
    function Read-JsonFileSafe {
        param([string]$Path)
        try {
            if (Test-Path $Path -ErrorAction SilentlyContinue) {
                $content = Get-Content $Path -Raw -ErrorAction Stop
                if ($content -and $content.Trim().Length -gt 0) {
                    return ($content | ConvertFrom-Json -ErrorAction Stop)
                }
            }
        } catch {
            # Corrupted JSON file - remove it and continue
            Remove-Item $Path -Force -ErrorAction SilentlyContinue
        }
        return $null
    }

    # -----------------------------------------------------------------------
    # MAIN: Check if tool is unified_search
    # -----------------------------------------------------------------------
    if ($toolName -match 'unified_search') {

        $toolArgs = $null
        if ($toolArgsRaw) {
            try {
                if ($toolArgsRaw -is [string]) {
                    $toolArgs = $toolArgsRaw | ConvertFrom-Json -ErrorAction Stop
                } else {
                    $toolArgs = $toolArgsRaw
                }
            } catch {
                # Malformed toolArgs - allow the search to proceed
                exit 0
            }
        }

        $query = if ($toolArgs) { $toolArgs.query } else { $null }
        $pipeline = if ($toolArgs) { $toolArgs.pipeline } else { $null }

        # Pipeline specified -> ALLOW
        if ($pipeline -and $pipeline -ne 'null') {
            Remove-Item "$stateDir/last_search_eval.json" -Force -ErrorAction SilentlyContinue
            Remove-Item "$stateDir/pending_complexity.json" -Force -ErrorAction SilentlyContinue
            exit 0
        }

        # Score complexity
        $score = 0
        if ($query) {
            $score = Get-ComplexityScore -Query $query
        }

        $template = Get-RecommendedTemplate -Query $query

        # --- Tier 3: High complexity (score >= 5) -> DENY ---
        if ($score -ge 5) {
            $reason = @"
[PIPELINE REQUIRED] Highly structured query detected.

Your query (complexity: $score/10) is clearly a structured search
(PICO comparison / systematic review / multi-entity analysis).

Pipeline mode provides:
  - Parallel multi-source searching (PubMed + OpenAlex + Europe PMC + ...)
  - Automatic PICO decomposition and MeSH expansion
  - DAG-based step orchestration
  - 6-dimensional result ranking

Please use pipeline:
  unified_search(query="$query", pipeline="template: $template\ntopic: $query")

Available templates: pico, comprehensive, exploration, gene_drug
Or load a saved pipeline: pipeline="saved:<name>"
"@

            $output = @{
                permissionDecision       = "deny"
                permissionDecisionReason = $reason
            }
            $output | ConvertTo-Json -Compress
            exit 0
        }

        # --- Tier 2: Moderate (score 3-4) -> ALLOW, flag for post-eval ---
        if ($score -ge 3) {
            if (-not (Test-Path $stateDir)) {
                New-Item -ItemType Directory -Path $stateDir -Force | Out-Null
            }
            $pending = @{
                query    = $query
                score    = $score
                template = $template
                tier     = "moderate"
            }
            try {
                $pending | ConvertTo-Json -Compress | Set-Content "$stateDir/pending_complexity.json" -Encoding UTF8
            } catch {
                # State write failed - still allow the search
            }

            exit 0
        }

        # --- Tier 1: Simple (score 0-2) -> ALLOW ---
        exit 0
    }

    # -----------------------------------------------------------------------
    # Feedback loop: Nudge after search evaluation
    # -----------------------------------------------------------------------
    $evalFile = "$stateDir/last_search_eval.json"
    $eval = Read-JsonFileSafe -Path $evalFile

    if ($eval -and ($eval.quality -eq 'poor' -or $eval.quality -eq 'insufficient' -or $eval.quality -eq 'suggest_supplement')) {

        # Already nudged -> don't repeat
        if ($eval.nudged -eq $true) {
            exit 0
        }

        # Agent is already doing follow-up -> clear state, allow
        if ($toolName -match 'search|related|citing|reference|pipeline|expand') {
            Remove-Item $evalFile -Force -ErrorAction SilentlyContinue
            exit 0
        }

        # Mark as nudged
        try {
            $eval | Add-Member -NotePropertyName 'nudged' -NotePropertyValue $true -Force
            $eval | ConvertTo-Json -Compress | Set-Content $evalFile -Encoding UTF8
        } catch {
            # State write failed - continue with nudge anyway
        }

        if ($eval.quality -eq 'suggest_supplement') {
            # Tier 2 parallel nudge
            $evalTemplate = if ($eval.template) { $eval.template } else { "comprehensive" }
            $reason = @"
[TIP] You have quick results for "$($eval.query)" ($($eval.result_count) articles).

For comprehensive coverage, also run a pipeline search:
  unified_search(query="$($eval.query)", pipeline="template: $evalTemplate\ntopic: $($eval.query)")

Pipeline adds: multi-source parallel search, MeSH expansion, structured ranking.
This supplements (not replaces) your existing results.

Skip if quick results are sufficient.
"@
        } else {
            # Poor/insufficient
            $reason = @"
[WARNING] Previous search returned only $($eval.result_count) results for "$($eval.query)".

$($eval.suggestion)

Consider follow-up actions:
  1. Retry with pipeline: unified_search(pipeline="template: comprehensive")
  2. Expand with related articles: find_related_articles(pmid="<top_result>")
  3. Try broader query or different sources
"@
        }

        $output = @{
            permissionDecision       = "deny"
            permissionDecisionReason = $reason
        }
        $output | ConvertTo-Json -Compress
        exit 0
    }

    # All other tools -> ALLOW
    exit 0

} catch {
    # On ANY error, fail open (allow the tool to proceed)
    # Do NOT output error messages that might contain non-ASCII
    exit 0
}
