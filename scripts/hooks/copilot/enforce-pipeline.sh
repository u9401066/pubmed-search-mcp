#!/bin/bash
# =============================================================================
# Pipeline Enforcer - preToolUse Hook for Copilot Coding Agent
# =============================================================================
#
# Policy goals:
#   1. Keep complexity-based pipeline enforcement for unified_search
#   2. Apply explicit downstream guards to other research MCP tools
#   3. Use one shared tool policy so coverage does not drift from the MCP surface
#
# ENCODING: All stdout output is ASCII-only to prevent mojibake on Windows.
# =============================================================================
set -e

if ! command -v jq >/dev/null 2>&1; then
    exit 0
fi

INPUT=$(cat)
TOOL_NAME=$(echo "$INPUT" | jq -r '.toolName // empty' 2>/dev/null) || exit 0
TOOL_ARGS=$(echo "$INPUT" | jq -r '.toolArgs // empty' 2>/dev/null) || true

STATE_DIR=".github/hooks/_state"
POLICY_FILE=".github/hooks/copilot-tool-policy.json"

get_complexity_score() {
    local query="$1"
    local score=0

    if echo "$query" | grep -qiE '\bvs\.?\b|versus|compared?\s+(to|with)|better\s+than|superior|inferior|non-?inferior'; then
        score=$((score + 3))
    fi
    if echo "$query" | grep -qiE '\b(patient|population|intervention|comparison|outcome)\b'; then
        score=$((score + 2))
    fi
    if echo "$query" | grep -qiE '\b(efficacy|safety|mortality|morbidity|adverse)\b'; then
        score=$((score + 1))
    fi
    if echo "$query" | grep -qiE '\b(systematic|comprehensive|meta-?analysis|review|all\s+studies)\b'; then
        score=$((score + 2))
    fi
    local word_count
    word_count=$(echo "$query" | wc -w)
    if [ "$word_count" -gt 6 ]; then
        score=$((score + 1))
    fi
    if echo "$query" | grep -qE '\b(AND|OR|NOT)\b'; then
        score=$((score + 1))
    fi
    if echo "$query" | grep -qE '\[MeSH\]|\[Mesh\]|\[tiab\]|\[Title/Abstract\]'; then
        score=$((score + 1))
    fi

    echo "$score"
}

recommend_template() {
    local query="$1"

    if echo "$query" | grep -qiE '\bvs\.?\b|versus|compared?\s+(to|with)'; then
        echo "pico"
        return
    fi
    if echo "$query" | grep -qiE 'systematic|comprehensive|meta-?analysis|review'; then
        echo "comprehensive"
        return
    fi
    if echo "$query" | grep -qiE '\b(gene|BRCA|TP53|EGFR|PubChem|compound|drug)\b'; then
        echo "gene_drug"
        return
    fi

    echo "comprehensive"
}

template_example() {
    local template="$1"
    local query="$2"
    local clean_query="${query:-<research topic>}"

    case "$template" in
        gene_drug)
            printf 'template: gene_drug\nparams:\n  term: %s' "$clean_query"
            ;;
        pico)
            printf 'template: pico\nparams:\n  P: <population>\n  I: <intervention>\n  C: <comparison>\n  O: <outcome>'
            ;;
        *)
            printf 'template: comprehensive\nparams:\n  query: %s' "$clean_query"
            ;;
    esac
}

policy_has_tool() {
    [ -f "$POLICY_FILE" ] || return 1
    jq -e --arg tool "$1" '[.toolGroups[]? | .[]?] | index($tool) != null' "$POLICY_FILE" >/dev/null 2>&1
}

tool_in_rule() {
    [ -f "$POLICY_FILE" ] || return 1
    jq -e --arg tool "$1" --arg rule "$2" '.rules[$rule] // [] | index($tool) != null' "$POLICY_FILE" >/dev/null 2>&1
}

tracker_has_evidence() {
    local tracker_file="$STATE_DIR/workflow_tracker.json"
    [ -f "$tracker_file" ] || return 1
    jq -e '.steps.initial_search == "completed" or .steps.pipeline_search == "completed" or .steps.deep_exploration == "completed" or .steps.result_evaluation == "completed"' "$tracker_file" >/dev/null 2>&1
}

has_explicit_context() {
    local args="$1"
    [ -n "$args" ] || return 1
    echo "$args" | jq -e '
        . != null and (
            (.query? // "" | tostring | gsub("^\\s+|\\s+$"; "") | length) > 0 or
            (.pipeline? // "" | tostring | gsub("^\\s+|\\s+$"; "") | length) > 0 or
            (.pmid? // "" | tostring | gsub("^\\s+|\\s+$"; "") | length) > 0 or
            (.pmcid? // "" | tostring | gsub("^\\s+|\\s+$"; "") | length) > 0 or
            (.doi? // "" | tostring | gsub("^\\s+|\\s+$"; "") | length) > 0 or
            (.identifier? // "" | tostring | gsub("^\\s+|\\s+$"; "") | length) > 0 or
            (.term? // "" | tostring | gsub("^\\s+|\\s+$"; "") | length) > 0 or
            (.gene_id? // "" | tostring | gsub("^\\s+|\\s+$"; "") | length) > 0 or
            (.cid? // "" | tostring | gsub("^\\s+|\\s+$"; "") | length) > 0 or
            (.mesh_term? // "" | tostring | gsub("^\\s+|\\s+$"; "") | length) > 0 or
            (.code? // "" | tostring | gsub("^\\s+|\\s+$"; "") | length) > 0 or
            (.name? // "" | tostring | gsub("^\\s+|\\s+$"; "") | length) > 0 or
            (.source? // "" | tostring | gsub("^\\s+|\\s+$"; "") | length) > 0 or
            (.sources? // "" | tostring | gsub("^\\s+|\\s+$"; "") | length) > 0 or
            ((.pmids? // []) | if type == "array" then length else (tostring | length) end) > 0
        )
    ' >/dev/null 2>&1
}

read_eval_file() {
    if [ -f "$STATE_DIR/last_research_eval.json" ]; then
        echo "$STATE_DIR/last_research_eval.json"
        return
    fi
    if [ -f "$STATE_DIR/last_search_eval.json" ]; then
        echo "$STATE_DIR/last_search_eval.json"
        return
    fi
    echo ""
}

QUERY=$(echo "$TOOL_ARGS" | jq -r '.query // empty' 2>/dev/null) || true
PIPELINE=$(echo "$TOOL_ARGS" | jq -r '.pipeline // empty' 2>/dev/null) || true

if echo "$TOOL_NAME" | grep -qiE '^unified_search$'; then
    if [ -n "$PIPELINE" ] && [ "$PIPELINE" != "null" ]; then
        rm -f "$STATE_DIR/last_search_eval.json" 2>/dev/null
        rm -f "$STATE_DIR/last_research_eval.json" 2>/dev/null
        rm -f "$STATE_DIR/pending_complexity.json" 2>/dev/null
        exit 0
    fi

    SCORE=0
    if [ -n "$QUERY" ]; then
        SCORE=$(get_complexity_score "$QUERY")
    fi

    TEMPLATE=$(recommend_template "$QUERY")
    TEMPLATE_EXAMPLE=$(template_example "$TEMPLATE" "$QUERY")

    if [ "$SCORE" -ge 5 ]; then
        REASON="[PIPELINE REQUIRED] Highly structured query detected.

Your query (complexity: ${SCORE}/10) looks like a structured research request.

Pipeline mode provides:
  - Parallel multi-source searching
  - MeSH / semantic expansion
  - DAG-based orchestration
  - Structured result ranking

Recommended pipeline template:
  ${TEMPLATE_EXAMPLE}

Retry with:
  unified_search(query=\"\", pipeline=\"<yaml above>\")

Available templates: pico, comprehensive, exploration, gene_drug
Or load a saved pipeline: pipeline=\"saved:<name>\""

        jq -n --arg reason "$REASON" '{permissionDecision: "deny", permissionDecisionReason: $reason}'
        exit 0
    fi

    if [ "$SCORE" -ge 3 ]; then
        mkdir -p "$STATE_DIR"
        jq -n \
            --arg query "$QUERY" \
            --argjson score "$SCORE" \
            --arg template "$TEMPLATE" \
            '{query: $query, score: $score, template: $template, tier: "moderate"}' \
            > "$STATE_DIR/pending_complexity.json" 2>/dev/null || true
        exit 0
    fi

    exit 0
fi

if policy_has_tool "$TOOL_NAME" && tool_in_rule "$TOOL_NAME" "requiresEvidenceOrIdentifiers" && [ -f "$STATE_DIR/workflow_tracker.json" ]; then
    if ! has_explicit_context "$TOOL_ARGS" && ! tracker_has_evidence; then
        REASON="[WORKFLOW REQUIRED] Tool \"${TOOL_NAME}\" is a downstream research step.

Use it after you already have evidence context, or provide explicit identifiers.

Before calling this tool, do one of the following:
  1. Run unified_search(query=\"...\")
  2. Run unified_search(query=\"\", pipeline=\"template: comprehensive\\nparams:\\n  query: <topic>\")
  3. Provide explicit identifiers such as pmid / pmids / pmcid / doi / gene_id / cid / name

This guard applies only to Copilot runtime hooks, not to all MCP clients."

        jq -n --arg reason "$REASON" '{permissionDecision: "deny", permissionDecisionReason: $reason}'
        exit 0
    fi
fi

EVAL_FILE=$(read_eval_file)
if [ -n "$EVAL_FILE" ]; then
    EVAL=$(cat "$EVAL_FILE" 2>/dev/null) || exit 0
    QUALITY=$(echo "$EVAL" | jq -r '.quality // "unknown"' 2>/dev/null) || exit 0
    case "$QUALITY" in
        poor|insufficient|suggest_supplement|acceptable)
            ;;
        *)
            exit 0
            ;;
    esac

    ALREADY_NUDGED=$(echo "$EVAL" | jq -r '.nudged // false' 2>/dev/null) || ALREADY_NUDGED="false"
    if [ "$ALREADY_NUDGED" = "true" ]; then
        exit 0
    fi

    if policy_has_tool "$TOOL_NAME" && tool_in_rule "$TOOL_NAME" "feedbackRemediation"; then
        rm -f "$STATE_DIR/last_search_eval.json" 2>/dev/null
        rm -f "$STATE_DIR/last_research_eval.json" 2>/dev/null
        exit 0
    fi

    if jq '.nudged = true' "$EVAL_FILE" > "$EVAL_FILE.tmp" 2>/dev/null; then
        mv "$EVAL_FILE.tmp" "$EVAL_FILE" 2>/dev/null
    else
        rm -f "$EVAL_FILE.tmp" 2>/dev/null
    fi

    if [ "$QUALITY" = "suggest_supplement" ]; then
        EVAL_TEMPLATE=$(echo "$EVAL" | jq -r '.template // "comprehensive"' 2>/dev/null) || EVAL_TEMPLATE="comprehensive"
        PREV_QUERY=$(echo "$EVAL" | jq -r '.query // empty' 2>/dev/null) || PREV_QUERY=""
        RESULT_COUNT=$(echo "$EVAL" | jq -r '.result_count // 0' 2>/dev/null) || RESULT_COUNT="0"
        TEMPLATE_EXAMPLE=$(template_example "$EVAL_TEMPLATE" "$PREV_QUERY")
        REASON="[TIP] Previous quick search returned ${RESULT_COUNT} results for \"${PREV_QUERY}\".

For broader coverage, also run a pipeline search:
  ${TEMPLATE_EXAMPLE}

Retry with:
  unified_search(query=\"\", pipeline=\"<yaml above>\")

Pipeline adds multi-source search, semantic expansion, and structured ranking."
    else
        CONTEXT_LABEL=$(echo "$EVAL" | jq -r '.query // .tool_name // "the previous research step"' 2>/dev/null) || CONTEXT_LABEL="the previous research step"
        SUGGESTION=$(echo "$EVAL" | jq -r '.suggestion // empty' 2>/dev/null) || SUGGESTION=""
        REASON="[WARNING] Previous research step was rated \"${QUALITY}\" for \"${CONTEXT_LABEL}\".

${SUGGESTION}

Recommended follow-up actions:
  1. Refine or re-run search with unified_search / pipeline mode
  2. Expand evidence with related / citing / fulltext tools
  3. Export or synthesize only after evidence quality is sufficient"
    fi

    jq -n --arg reason "$REASON" '{permissionDecision: "deny", permissionDecisionReason: $reason}'
    exit 0
fi

exit 0
