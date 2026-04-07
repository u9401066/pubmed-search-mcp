#!/bin/bash
# =============================================================================
# Prompt Analyzer - userPromptSubmitted Hook
# =============================================================================
# Detects research intent, manages workflow tracker, outputs instructions.
# Output: JSON with "instructions" field for AI context injection.
#
# WORKFLOW INSTRUCTIONS ARE READ FROM THE SHARED POLICY FILE:
#   .github/hooks/copilot-tool-policy.json
# =============================================================================
set -e

# --- Dependency check ---
if ! command -v jq >/dev/null 2>&1; then
    exit 0  # No jq = skip
fi

INPUT=$(cat)
PROMPT=$(echo "$INPUT" | jq -r '.prompt // empty' 2>/dev/null) || exit 0
if [ -z "$PROMPT" ]; then exit 0; fi

STATE_DIR=".github/hooks/_state"
mkdir -p "$STATE_DIR"
TRACKER_FILE="$STATE_DIR/workflow_tracker.json"
POLICY_FILE=".github/hooks/copilot-tool-policy.json"

# --- Intent Detection ---
INTENT="unknown"
COMPLEXITY="simple"
TEMPLATE="comprehensive"

if echo "$PROMPT" | grep -qiE '\bvs\.?\b|versus|compared?\s+(to|with)'; then
    INTENT="comparison"; COMPLEXITY="complex"; TEMPLATE="pico"
elif echo "$PROMPT" | grep -qiE 'systematic|comprehensive|review|meta.?analysis'; then
    INTENT="systematic"; COMPLEXITY="complex"; TEMPLATE="comprehensive"
elif echo "$PROMPT" | grep -qiE 'related|citation|PMID|DOI|explore'; then
    INTENT="exploration"; COMPLEXITY="moderate"; TEMPLATE="exploration"
elif echo "$PROMPT" | grep -qiE '\b(gene|BRCA|TP53|EGFR|drug|compound|PubChem)\b'; then
    INTENT="gene_drug"; COMPLEXITY="moderate"; TEMPLATE="gene_drug"
elif echo "$PROMPT" | grep -qiE 'search|find|paper|article|literature'; then
    INTENT="quick_search"; COMPLEXITY="simple"
fi

# --- Workflow Tracker ---
IS_RESEARCH=false
if [ "$INTENT" != "unknown" ]; then IS_RESEARCH=true; fi

# Create tracker if research detected and no existing tracker
if $IS_RESEARCH && [ ! -f "$TRACKER_FILE" ] && [ -f "$POLICY_FILE" ]; then
    TOPIC=$(echo "$PROMPT" | head -c 120 | tr -cd '[:print:]')
    jq -n \
        --slurpfile policy "$POLICY_FILE" \
        --arg topic "$TOPIC" \
        --arg intent "$INTENT" \
        --arg template "$TEMPLATE" \
        --arg created_at "$(date -u +%Y-%m-%dT%H:%M:%SZ)" \
        '{
            topic: $topic, intent: $intent,
            template: $template, created_at: $created_at,
            steps: (($policy[0].workflowSteps // {}) | to_entries | map({(.key): "not-started"}) | add)
        }' > "$TRACKER_FILE" 2>/dev/null || true
fi

# --- Output Instructions ---
if [ -f "$TRACKER_FILE" ] && [ -f "$POLICY_FILE" ]; then
    TRACKER=$(cat "$TRACKER_FILE" 2>/dev/null)
    if [ -n "$TRACKER" ]; then
        T_TOPIC=$(echo "$TRACKER" | jq -r '.topic // "unknown"')
        T_INTENT=$(echo "$TRACKER" | jq -r '.intent // "unknown"')
        T_TEMPLATE=$(echo "$TRACKER" | jq -r '.template // "comprehensive"')

        COMPLETED=0
        TOTAL=0
        NEXT_FOUND=false
        PROGRESS=""

        STEP_DEFS=$(jq -c '.workflowSteps | to_entries[] | {
            key: .key,
            label: (.value.label // .key),
            nextInstruction: (.value.nextInstruction // "")
        }' "$POLICY_FILE" 2>/dev/null) || STEP_DEFS=""

        while IFS= read -r STEP_DEF; do
            [ -n "$STEP_DEF" ] || continue
            TOTAL=$((TOTAL + 1))
            KEY=$(echo "$STEP_DEF" | jq -r '.key')
            LABEL=$(echo "$STEP_DEF" | jq -r '.label')
            TOOL=$(echo "$STEP_DEF" | jq -r '.nextInstruction')
            STATUS=$(echo "$TRACKER" | jq -r ".steps.${KEY} // \"not-started\"")

            if [ "$STATUS" = "completed" ]; then
                COMPLETED=$((COMPLETED + 1))
                PROGRESS="${PROGRESS}[x] ${LABEL}\n"
            elif ! $NEXT_FOUND; then
                NEXT_FOUND=true
                PROGRESS="${PROGRESS}[ ] ${LABEL}  <-- NEXT: ${TOOL}\n"
            else
                PROGRESS="${PROGRESS}[ ] ${LABEL}\n"
            fi
        done <<< "$STEP_DEFS"

        if [ "$TOTAL" -eq 0 ]; then
            exit 0
        fi

        INSTRUCTIONS="RESEARCH WORKFLOW (${COMPLETED}/${TOTAL} steps done)\n"
        INSTRUCTIONS="${INSTRUCTIONS}Topic: ${T_TOPIC}\n"
        INSTRUCTIONS="${INSTRUCTIONS}Intent: ${T_INTENT} | Template: ${T_TEMPLATE}\n\n"
        INSTRUCTIONS="${INSTRUCTIONS}${PROGRESS}\n"
        INSTRUCTIONS="${INSTRUCTIONS}Follow steps in order for thorough research."
        INSTRUCTIONS="${INSTRUCTIONS} For complex queries, always use pipeline mode (step 4)."
        INSTRUCTIONS="${INSTRUCTIONS} Skip steps only if user explicitly requests quick search."

        printf '%b' "$INSTRUCTIONS" | jq -Rs '{instructions: .}' 2>/dev/null
    fi
fi

# --- Audit Log ---
jq -n \
    --arg timestamp "$(date -u +%Y-%m-%dT%H:%M:%SZ)" \
    --arg event "prompt_submitted" \
    --arg intent "$INTENT" \
    --arg complexity "$COMPLEXITY" \
    '{timestamp: $timestamp, event: $event, intent: $intent, complexity: $complexity}' \
    >> "$STATE_DIR/search_audit.jsonl" 2>/dev/null

exit 0
