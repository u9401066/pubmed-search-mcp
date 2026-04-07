# =============================================================================
# Prompt Analyzer - userPromptSubmitted Hook (PowerShell)
# =============================================================================
# Detects research intent, manages workflow tracker, outputs instructions.
# Output: JSON with "instructions" field for AI context injection.
#
# WORKFLOW INSTRUCTIONS ARE READ FROM THE SHARED POLICY FILE:
#   .github/hooks/copilot-tool-policy.json
#
# ENCODING: Forces UTF-8 output. All strings are ASCII-only.
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
    $policy = Read-JsonFileSafe -Path ".github/hooks/copilot-tool-policy.json"

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
    if ($isResearch -and -not $tracker -and $policy -and $policy.workflowSteps) {
        $topicLen = [Math]::Min(120, $prompt.Length)
        $cleanTopic = ($prompt.Substring(0, $topicLen)) -replace '[^\x20-\x7E]', '?'
        $stepStates = [ordered]@{}
        foreach ($step in $policy.workflowSteps.PSObject.Properties) {
            $stepStates[$step.Name] = "not-started"
        }
        $tracker = @{
            topic      = $cleanTopic
            intent     = $intent
            template   = $template
            created_at = (Get-Date -Format "yyyy-MM-ddTHH:mm:ssZ")
            steps      = $stepStates
        }
        Write-Utf8NoBomFile -Path $trackerFile -Content ($tracker | ConvertTo-Json -Depth 3 -Compress)
    }

    # --- Output Instructions (if tracker active) ---
    if ($tracker -and $policy -and $policy.workflowSteps) {
        $steps = $tracker.steps
        $stepDefs = @()
        foreach ($step in $policy.workflowSteps.PSObject.Properties) {
            $metadata = $step.Value
            $stepDefs += @{
                key = $step.Name
                label = if ($metadata.PSObject.Properties["label"]) { [string]$metadata.label } else { [string]$step.Name }
                tool = if ($metadata.PSObject.Properties["nextInstruction"]) { [string]$metadata.nextInstruction } else { "" }
            }
        }

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
        if ($total -eq 0) { exit 0 }
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
        Append-Utf8NoBomLine -Path "$stateDir/search_audit.jsonl" -Line ($logEntry | ConvertTo-Json -Compress)
    } catch {}

    exit 0
} catch {
    # Fail open - prompt analysis should never block
    exit 0
}
