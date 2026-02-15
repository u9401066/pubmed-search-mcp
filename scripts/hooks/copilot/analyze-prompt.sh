#!/bin/bash
# =============================================================================
# Prompt Analyzer - userPromptSubmitted Hook
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
if $IS_RESEARCH && [ ! -f "$TRACKER_FILE" ]; then
    TOPIC=$(echo "$PROMPT" | head -c 120 | tr -cd '[:print:]')
    jq -n \
        --arg topic "$TOPIC" \
        --arg intent "$INTENT" \
        --arg template "$TEMPLATE" \
        --arg created_at "$(date -u +%Y-%m-%dT%H:%M:%SZ)" \
        '{
            topic: $topic, intent: $intent,
            template: $template, created_at: $created_at,
            steps: {
                query_analysis: "not-started",
                strategy_formation: "not-started",
                initial_search: "not-started",
                pipeline_search: "not-started",
                result_evaluation: "not-started",
                deep_exploration: "not-started",
                export_synthesis: "not-started"
            }
        }' > "$TRACKER_FILE" 2>/dev/null
fi

# --- Output Instructions ---
if [ -f "$TRACKER_FILE" ]; then
    TRACKER=$(cat "$TRACKER_FILE" 2>/dev/null)
    if [ -n "$TRACKER" ]; then
        T_TOPIC=$(echo "$TRACKER" | jq -r '.topic // "unknown"')
        T_INTENT=$(echo "$TRACKER" | jq -r '.intent // "unknown"')
        T_TEMPLATE=$(echo "$TRACKER" | jq -r '.template // "comprehensive"')

        STEP_KEYS=("query_analysis" "strategy_formation" "initial_search" "pipeline_search" "result_evaluation" "deep_exploration" "export_synthesis")
        STEP_LABELS=("Query Analysis" "Strategy Formation" "Initial Search" "Pipeline Search" "Result Evaluation" "Deep Exploration" "Export & Synthesis")
        STEP_TOOLS=(
            "analyze_search_query / parse_pico"
            "generate_search_queries"
            "unified_search (no pipeline)"
            "unified_search(pipeline='template: ...')"
            "get_citation_metrics / get_session_summary"
            "find_related / citing / fulltext / citation_tree"
            "prepare_export / build_research_timeline"
        )

        COMPLETED=0
        TOTAL=7
        NEXT_FOUND=false
        PROGRESS=""

        for I in "${!STEP_KEYS[@]}"; do
            KEY="${STEP_KEYS[$I]}"
            LABEL="${STEP_LABELS[$I]}"
            TOOL="${STEP_TOOLS[$I]}"
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
        done

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
