# =============================================================================
# Result Evaluator - postToolUse Hook for Copilot Coding Agent (PowerShell)
# =============================================================================
# Policy goals:
#   1. Track workflow progress for the full MCP tool surface
#   2. Evaluate quality for result-bearing research tools, not only unified_search
#   3. Write generic research feedback state for the next preToolUse hook
#
# ENCODING: Forces UTF-8 output to prevent mojibake on Windows.
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

function Append-Utf8NoBomLine {
    param(
        [string]$Path,
        [string]$Line
    )
    $encoding = New-Object System.Text.UTF8Encoding($false)
    [System.IO.File]::AppendAllText($Path, $Line + [Environment]::NewLine, $encoding)
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

function Get-WorkflowStepForTool {
    param(
        [object]$Policy,
        [string]$ToolName,
        [string]$HadPipeline
    )
    if ($ToolName -eq "unified_search" -and $HadPipeline -and $HadPipeline -ne "null") {
        return "pipeline_search"
    }
    if (-not $Policy) {
        return $null
    }
    foreach ($step in $Policy.workflowSteps.PSObject.Properties) {
        $tools = if ($step.Value.PSObject.Properties["tools"]) { @($step.Value.tools) } else { @() }
        if ($tools -contains $ToolName) {
            return $step.Name
        }
    }
    return $null
}

function Get-ToolGroupName {
    param(
        [object]$Policy,
        [string]$ToolName
    )
    if (-not $Policy) {
        return ""
    }
    foreach ($group in $Policy.toolGroups.PSObject.Properties) {
        if ((@($group.Value)) -contains $ToolName) {
            return $group.Name
        }
    }
    return ""
}

function Get-HeuristicResultCount {
    param([string]$Text)
    if (-not $Text) {
        return 0
    }

    $patterns = @(
        'PMID:\s*\d+|pmid/\d+',
        'PMCID:\s*PMC\d+|PMC\d{5,}',
        '10\.\d{4,9}/[-._;()/:A-Za-z0-9]+',
        '(?m)^\s*\d+\.',
        '(?m)^\s*[-*]\s+'
    )

    $maxCount = 0
    foreach ($pattern in $patterns) {
        $count = ([regex]::Matches($Text, $pattern)).Count
        if ($count -gt $maxCount) {
            $maxCount = $count
        }
    }
    return $maxCount
}

function Get-SourceCount {
    param([string]$Text)
    if (-not $Text) {
        return 0
    }
    $count = 0
    foreach ($sourceName in @("pubmed", "openalex", "semantic_scholar", "europe_pmc", "crossref", "core")) {
        if ($Text -match $sourceName) {
            $count += 1
        }
    }
    return $count
}

function Test-TextLooksMissing {
    param([string]$Text)
    if (-not $Text) {
        return $true
    }
    return $Text -match 'not\s+found|no\s+results|no\s+full\s*text|unavailable|failed|error|empty\s+result|0\s+articles?'
}

function Get-EvaluationMode {
    param(
        [string]$ToolName,
        [string]$ToolGroup
    )
    if ($ToolName -match 'get_fulltext|get_text_mined_terms|get_article_figures') {
        return "fulltext"
    }
    if ($ToolName -match 'search_gene|search_compound|search_clinvar|search_biomedical_images|find_related_articles|find_citing_articles|get_article_references|fetch_article_details|build_citation_tree|get_gene_literature|get_compound_literature|get_citation_metrics|get_session_pmids') {
        return "search_list"
    }
    if ($ToolGroup -in @("search", "discovery", "citation_network", "image_search")) {
        return "search_list"
    }
    return "detail"
}

function Get-Suggestion {
    param(
        [string]$Mode,
        [string]$ToolName,
        [string]$HasPipeline,
        [int]$ResultCount,
        [int]$SourceCount
    )
    switch ($Mode) {
        "fulltext" {
            return "Try another identifier (PMID / PMCID / DOI), enable broader retrieval sources, or fetch article details first."
        }
        "search_list" {
            if (-not $HasPipeline -or $HasPipeline -eq "null") {
                return "Broaden the query, add more sources, or retry with pipeline mode for structured expansion."
            }
            return "Broaden the query, relax filters, or expand with related / citing / fulltext tools."
        }
        default {
            if ($ToolName -match 'prepare_export|build_research_timeline|analyze_timeline_milestones|compare_timelines') {
                return "Gather PMIDs or session context first, then retry the synthesis step."
            }
            if ($ToolName -match 'read_session|get_session_|get_cached_article') {
                return "Run a search first or provide explicit session / PMID context before using this session tool."
            }
            return "Provide explicit identifiers or gather evidence context before retrying this tool."
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
    if (-not $toolName) { exit 0 }

    $toolArgs = $null
    if ($inputJson.toolArgs) {
        try {
            if ($inputJson.toolArgs -is [string]) {
                $toolArgs = $inputJson.toolArgs | ConvertFrom-Json -ErrorAction Stop
            } else {
                $toolArgs = $inputJson.toolArgs
            }
        } catch {
            $toolArgs = $null
        }
    }

    $query = if ($toolArgs -and $toolArgs.PSObject.Properties["query"]) { [string]$toolArgs.query } else { "" }
    $hadPipeline = if ($toolArgs -and $toolArgs.PSObject.Properties["pipeline"]) { [string]$toolArgs.pipeline } else { "" }

    $stateDir = ".github/hooks/_state"
    if (-not (Test-Path $stateDir)) {
        New-Item -ItemType Directory -Path $stateDir -Force | Out-Null
    }

    $policy = Read-JsonFileSafe -Path ".github/hooks/copilot-tool-policy.json"
    $toolGroup = Get-ToolGroupName -Policy $policy -ToolName $toolName

    $trackerFile = "$stateDir/workflow_tracker.json"
    $stepForTool = Get-WorkflowStepForTool -Policy $policy -ToolName $toolName -HadPipeline $hadPipeline
    if ($stepForTool) {
        try {
            $wfTracker = Read-JsonFileSafe -Path $trackerFile
            if ($wfTracker -and $wfTracker.steps -and $wfTracker.steps.PSObject.Properties[$stepForTool]) {
                if ($wfTracker.steps.$stepForTool -ne "completed") {
                    $wfTracker.steps.$stepForTool = "completed"
                    Write-Utf8NoBomFile -Path $trackerFile -Content ($wfTracker | ConvertTo-Json -Depth 3 -Compress)
                }
            }
        } catch {
        }
    }

    if (-not (Test-ToolInPolicySection -Policy $policy -Section "rules" -Name "qualityEvaluation" -ToolName $toolName)) {
        exit 0
    }

    $resultType = if ($inputJson.toolResult) { [string]$inputJson.toolResult.resultType } else { "unknown" }
    $resultText = if ($inputJson.toolResult) { [string]$inputJson.toolResult.textResultForLlm } else { "" }

    $pendingTier = $null
    $pendingTemplate = "comprehensive"
    $pendingFile = "$stateDir/pending_complexity.json"
    if (Test-Path $pendingFile -ErrorAction SilentlyContinue) {
        $pending = Read-JsonFileSafe -Path $pendingFile
        if ($pending) {
            $pendingTier = $pending.tier
            if ($pending.template) {
                $pendingTemplate = [string]$pending.template
            }
        }
        Remove-Item $pendingFile -Force -ErrorAction SilentlyContinue
    }

    $evaluationMode = Get-EvaluationMode -ToolName $toolName -ToolGroup $toolGroup
    $resultCount = Get-HeuristicResultCount -Text $resultText
    $sourceCount = Get-SourceCount -Text $resultText
    $hasContent = $resultText -and $resultText.Trim().Length -ge 80
    $quality = "good"
    $suggestion = ""

    if ($resultType -eq "failure") {
        $quality = "poor"
        $suggestion = Get-Suggestion -Mode $evaluationMode -ToolName $toolName -HasPipeline $hadPipeline -ResultCount 0 -SourceCount 0
    } else {
        switch ($evaluationMode) {
            "fulltext" {
                if (Test-TextLooksMissing -Text $resultText) {
                    $quality = "poor"
                } elseif ($resultText.Trim().Length -lt 300) {
                    $quality = "insufficient"
                }
                if ($quality -ne "good") {
                    $suggestion = Get-Suggestion -Mode $evaluationMode -ToolName $toolName -HasPipeline $hadPipeline -ResultCount $resultCount -SourceCount $sourceCount
                }
            }
            "search_list" {
                if ($resultCount -lt 3) {
                    $quality = "poor"
                } elseif ($resultCount -lt 8) {
                    $quality = "acceptable"
                }
                if ($toolName -eq "unified_search" -and $sourceCount -le 1 -and $resultCount -gt 0 -and $quality -eq "good") {
                    $quality = "acceptable"
                }
                if ($quality -ne "good") {
                    $suggestion = Get-Suggestion -Mode $evaluationMode -ToolName $toolName -HasPipeline $hadPipeline -ResultCount $resultCount -SourceCount $sourceCount
                }
            }
            default {
                if (Test-TextLooksMissing -Text $resultText) {
                    $quality = "poor"
                } elseif (-not $hasContent -and $resultCount -eq 0) {
                    $quality = "insufficient"
                }
                if ($quality -ne "good") {
                    $suggestion = Get-Suggestion -Mode $evaluationMode -ToolName $toolName -HasPipeline $hadPipeline -ResultCount $resultCount -SourceCount $sourceCount
                }
            }
        }
    }

    if (
        $toolName -eq "unified_search" -and
        $pendingTier -eq "moderate" -and
        (-not $hadPipeline -or $hadPipeline -eq "null") -and
        ($quality -eq "good" -or $quality -eq "acceptable")
    ) {
        $quality = "suggest_supplement"
        $suggestion = "Quick search returned $resultCount results - good start. For comprehensive coverage, also run a pipeline search to include more sources and semantic expansion."
    }

    if ($quality -ne "good") {
        Write-Utf8NoBomFile -Path "$stateDir/last_research_eval.json" -Content (@{
            tool_name = $toolName
            tool_group = if ($toolGroup) { $toolGroup } else { "unknown" }
            evaluation_mode = $evaluationMode
            query = $query
            quality = $quality
            result_count = $resultCount
            source_count = $sourceCount
            suggestion = $suggestion
            had_pipeline = if ($hadPipeline) { $hadPipeline } else { "none" }
            template = $pendingTemplate
            nudged = $false
        } | ConvertTo-Json -Compress)
        Remove-Item "$stateDir/last_search_eval.json" -Force -ErrorAction SilentlyContinue
    } else {
        Remove-Item "$stateDir/last_search_eval.json" -Force -ErrorAction SilentlyContinue
        Remove-Item "$stateDir/last_research_eval.json" -Force -ErrorAction SilentlyContinue
    }

    try {
        Append-Utf8NoBomLine -Path "$stateDir/search_audit.jsonl" -Line (@{
            timestamp = (Get-Date -Format "yyyy-MM-ddTHH:mm:ssZ")
            tool_name = $toolName
            tool_group = if ($toolGroup) { $toolGroup } else { "unknown" }
            query = $query
            quality = $quality
            result_count = $resultCount
            source_count = $sourceCount
            had_pipeline = if ($hadPipeline) { $hadPipeline } else { "none" }
            tier = if ($pendingTier) { $pendingTier } else { "none" }
        } | ConvertTo-Json -Compress)
    } catch {
    }

    exit 0

} catch {
    exit 0
}
