# =============================================================================
# Pipeline Enforcer - preToolUse Hook for Copilot Coding Agent (PowerShell)
# =============================================================================
#
# Policy goals:
#   1. Keep complexity-based pipeline enforcement for unified_search
#   2. Apply explicit downstream guards to other research MCP tools
#   3. Use one shared tool policy so coverage does not drift from the MCP surface
#
# ENCODING: Forces UTF-8 output to prevent mojibake on Windows.
#           All output strings are ASCII-only for maximum compatibility.
# =============================================================================
$ErrorActionPreference = "Stop"

[Console]::OutputEncoding = [System.Text.Encoding]::UTF8
$OutputEncoding = [System.Text.Encoding]::UTF8

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
        Remove-Item $Path -Force -ErrorAction SilentlyContinue
    }
    return $null
}

function Write-Utf8NoBomFile {
    param(
        [string]$Path,
        [string]$Content
    )
    $encoding = New-Object System.Text.UTF8Encoding($false)
    [System.IO.File]::WriteAllText($Path, $Content, $encoding)
}

function Get-PolicyArray {
    param(
        [object]$Policy,
        [string]$Section,
        [string]$Name
    )
    if (-not $Policy) {
        return @()
    }
    $sectionObj = $Policy.PSObject.Properties[$Section]
    if (-not $sectionObj) {
        return @()
    }
    $entry = $sectionObj.Value.PSObject.Properties[$Name]
    if (-not $entry) {
        return @()
    }
    return @($entry.Value)
}

function Test-ToolInPolicySection {
    param(
        [object]$Policy,
        [string]$Section,
        [string]$Name,
        [string]$ToolName
    )
    return (Get-PolicyArray -Policy $Policy -Section $Section -Name $Name) -contains $ToolName
}

function Test-KnownHookTool {
    param(
        [object]$Policy,
        [string]$ToolName
    )
    if (-not $Policy) {
        return $false
    }
    foreach ($group in $Policy.toolGroups.PSObject.Properties) {
        if ((@($group.Value)) -contains $ToolName) {
            return $true
        }
    }
    return $false
}

function Read-WorkflowTrackerSafe {
    param([string]$Path)
    return Read-JsonFileSafe -Path $Path
}

function Test-TrackerHasEvidence {
    param([object]$Tracker)
    if (-not $Tracker -or -not $Tracker.steps) {
        return $false
    }
    foreach ($stepName in @("initial_search", "pipeline_search", "deep_exploration", "result_evaluation")) {
        $stepProp = $Tracker.steps.PSObject.Properties[$stepName]
        if ($stepProp -and $stepProp.Value -eq "completed") {
            return $true
        }
    }
    return $false
}

function Test-HasExplicitContext {
    param([object]$ToolArgs)
    if (-not $ToolArgs) {
        return $false
    }

    foreach ($field in @(
        "query", "pipeline", "pmid", "pmids", "pmcid", "doi", "identifier",
        "term", "gene_id", "cid", "mesh_term", "code", "name", "source", "sources"
    )) {
        $prop = $ToolArgs.PSObject.Properties[$field]
        if (-not $prop) {
            continue
        }

        $value = $prop.Value
        if ($null -eq $value) {
            continue
        }
        if ($value -is [string]) {
            if ($value.Trim().Length -gt 0 -and $value -ne "null") {
                return $true
            }
            continue
        }
        if ($value -is [System.Collections.IEnumerable] -and -not ($value -is [string])) {
            foreach ($item in $value) {
                if ($null -ne $item -and "$item".Trim().Length -gt 0) {
                    return $true
                }
            }
            continue
        }
        return $true
    }

    return $false
}

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

function Get-TemplateExample {
    param(
        [string]$Template,
        [string]$Query
    )
    $cleanQuery = if ($Query) { $Query } else { "<research topic>" }

    switch ($Template) {
        "gene_drug" {
            return "template: gene_drug`nparams:`n  term: $cleanQuery"
        }
        "pico" {
            return "template: pico`nparams:`n  P: <population>`n  I: <intervention>`n  C: <comparison>`n  O: <outcome>"
        }
        default {
            return "template: comprehensive`nparams:`n  query: $cleanQuery"
        }
    }
}

try {
    $rawInput = [Console]::In.ReadToEnd()
    if (-not $rawInput -or $rawInput.Trim().Length -eq 0) {
        exit 0
    }

    $inputJson = $rawInput | ConvertFrom-Json -ErrorAction Stop
    $toolName = [string]$inputJson.toolName
    $toolArgsRaw = $inputJson.toolArgs

    if (-not $toolName) {
        exit 0
    }

    $stateDir = ".github/hooks/_state"
    $policyPath = ".github/hooks/copilot-tool-policy.json"
    $policy = Read-JsonFileSafe -Path $policyPath
    $tracker = Read-WorkflowTrackerSafe -Path "$stateDir/workflow_tracker.json"

    $toolArgs = $null
    if ($toolArgsRaw) {
        try {
            if ($toolArgsRaw -is [string]) {
                $toolArgs = $toolArgsRaw | ConvertFrom-Json -ErrorAction Stop
            } else {
                $toolArgs = $toolArgsRaw
            }
        } catch {
            $toolArgs = $null
        }
    }

    $query = if ($toolArgs -and $toolArgs.PSObject.Properties["query"]) { [string]$toolArgs.query } else { "" }
    $pipeline = if ($toolArgs -and $toolArgs.PSObject.Properties["pipeline"]) { [string]$toolArgs.pipeline } else { "" }
    $knownHookTool = Test-KnownHookTool -Policy $policy -ToolName $toolName

    if ($toolName -match 'unified_search') {
        if ($pipeline -and $pipeline -ne 'null') {
            Remove-Item "$stateDir/last_search_eval.json" -Force -ErrorAction SilentlyContinue
            Remove-Item "$stateDir/last_research_eval.json" -Force -ErrorAction SilentlyContinue
            Remove-Item "$stateDir/pending_complexity.json" -Force -ErrorAction SilentlyContinue
            exit 0
        }

        $score = 0
        if ($query) {
            $score = Get-ComplexityScore -Query $query
        }

        $template = Get-RecommendedTemplate -Query $query
        $templateExample = Get-TemplateExample -Template $template -Query $query

        if ($score -ge 5) {
            $reason = @"
[PIPELINE REQUIRED] Highly structured query detected.

Your query (complexity: $score/10) looks like a structured research request.

Pipeline mode provides:
  - Parallel multi-source searching
  - MeSH / semantic expansion
  - DAG-based orchestration
  - Structured result ranking

Recommended pipeline template:
  $templateExample

Retry with:
  unified_search(query="", pipeline="<yaml above>")

Available templates: pico, comprehensive, exploration, gene_drug
Or load a saved pipeline: pipeline="saved:<name>"
"@

            @{
                permissionDecision = "deny"
                permissionDecisionReason = $reason
            } | ConvertTo-Json -Compress
            exit 0
        }

        if ($score -ge 3) {
            if (-not (Test-Path $stateDir)) {
                New-Item -ItemType Directory -Path $stateDir -Force | Out-Null
            }
            Write-Utf8NoBomFile -Path "$stateDir/pending_complexity.json" -Content (@{
                query = $query
                score = $score
                template = $template
                tier = "moderate"
            } | ConvertTo-Json -Compress)
            exit 0
        }

        exit 0
    }

    if (
        $knownHookTool -and
        $tracker -and
        (Test-ToolInPolicySection -Policy $policy -Section "rules" -Name "requiresEvidenceOrIdentifiers" -ToolName $toolName)
    ) {
        $hasExplicitContext = Test-HasExplicitContext -ToolArgs $toolArgs
        $hasTrackedEvidence = Test-TrackerHasEvidence -Tracker $tracker

        if (-not $hasExplicitContext -and -not $hasTrackedEvidence) {
            $reason = @"
[WORKFLOW REQUIRED] Tool "$toolName" is a downstream research step.

Use it after you already have evidence context, or provide explicit identifiers.

Before calling this tool, do one of the following:
  1. Run unified_search(query="...")
  2. Run unified_search(query="", pipeline="template: comprehensive\nparams:\n  query: <topic>")
  3. Provide explicit identifiers such as pmid / pmids / pmcid / doi / gene_id / cid / name

This guard applies only to Copilot runtime hooks, not to all MCP clients.
"@

            @{
                permissionDecision = "deny"
                permissionDecisionReason = $reason
            } | ConvertTo-Json -Compress
            exit 0
        }
    }

    $evalFile = if (Test-Path "$stateDir/last_research_eval.json") {
        "$stateDir/last_research_eval.json"
    } else {
        "$stateDir/last_search_eval.json"
    }
    $eval = Read-JsonFileSafe -Path $evalFile

    if ($eval -and ($eval.quality -in @("poor", "insufficient", "suggest_supplement", "acceptable"))) {
        if ($eval.nudged -eq $true) {
            exit 0
        }

        $isRemediation = $knownHookTool -and (Test-ToolInPolicySection -Policy $policy -Section "rules" -Name "feedbackRemediation" -ToolName $toolName)
        if ($isRemediation) {
            Remove-Item "$stateDir/last_search_eval.json" -Force -ErrorAction SilentlyContinue
            Remove-Item "$stateDir/last_research_eval.json" -Force -ErrorAction SilentlyContinue
            exit 0
        }

        try {
            $eval | Add-Member -NotePropertyName 'nudged' -NotePropertyValue $true -Force
            Write-Utf8NoBomFile -Path $evalFile -Content ($eval | ConvertTo-Json -Compress)
        } catch {
        }

        if ($eval.quality -eq 'suggest_supplement') {
            $evalTemplate = if ($eval.template) { [string]$eval.template } else { "comprehensive" }
            $templateExample = Get-TemplateExample -Template $evalTemplate -Query ([string]$eval.query)
            $reason = @"
[TIP] Previous quick search returned $($eval.result_count) results for "$($eval.query)".

For broader coverage, also run a pipeline search:
  $templateExample

Retry with:
  unified_search(query="", pipeline="<yaml above>")

Pipeline adds multi-source search, semantic expansion, and structured ranking.
"@
        } else {
            $contextLabel = if ($eval.query) { [string]$eval.query } elseif ($eval.tool_name) { [string]$eval.tool_name } else { "the previous research step" }
            $reason = @"
[WARNING] Previous research step was rated "$($eval.quality)" for "$contextLabel".

$($eval.suggestion)

Recommended follow-up actions:
  1. Refine or re-run search with unified_search / pipeline mode
  2. Expand evidence with related / citing / fulltext tools
  3. Export or synthesize only after evidence quality is sufficient
"@
        }

        @{
            permissionDecision = "deny"
            permissionDecisionReason = $reason
        } | ConvertTo-Json -Compress
        exit 0
    }

    exit 0

} catch {
    exit 0
}
