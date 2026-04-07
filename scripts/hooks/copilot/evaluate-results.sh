#!/bin/bash
# =============================================================================
# Result Evaluator - postToolUse Hook for Copilot Coding Agent
# =============================================================================
# Policy goals:
#   1. Track workflow progress for the full MCP tool surface
#   2. Evaluate quality for result-bearing research tools, not only unified_search
#   3. Write generic research feedback state for the next preToolUse hook
# =============================================================================
set -e

if ! command -v jq >/dev/null 2>&1; then
    exit 0
fi

INPUT=$(cat)
TOOL_NAME=$(echo "$INPUT" | jq -r '.toolName // empty' 2>/dev/null) || exit 0
if [ -z "$TOOL_NAME" ]; then
    exit 0
fi

TOOL_ARGS=$(echo "$INPUT" | jq -r '.toolArgs // empty' 2>/dev/null) || true
QUERY=$(echo "$TOOL_ARGS" | jq -r '.query // empty' 2>/dev/null) || true
HAD_PIPELINE=$(echo "$TOOL_ARGS" | jq -r '.pipeline // empty' 2>/dev/null) || true

STATE_DIR=".github/hooks/_state"
POLICY_FILE=".github/hooks/copilot-tool-policy.json"
mkdir -p "$STATE_DIR"

tool_in_policy_section() {
    [ -f "$POLICY_FILE" ] || return 1
    jq -e --arg tool "$1" --arg section "$2" --arg name "$3" '.[$section][$name] // [] | index($tool) != null' "$POLICY_FILE" >/dev/null 2>&1
}

workflow_step_for_tool() {
    local tool_name="$1"
    local had_pipeline="$2"
    if [ "$tool_name" = "unified_search" ] && [ -n "$had_pipeline" ] && [ "$had_pipeline" != "null" ]; then
        echo "pipeline_search"
        return
    fi
    [ -f "$POLICY_FILE" ] || return
    jq -r --arg tool "$tool_name" '.workflowSteps | to_entries[] | select((.value.tools // []) | index($tool) != null) | .key' "$POLICY_FILE" 2>/dev/null | head -1
}

tool_group_for_tool() {
    [ -f "$POLICY_FILE" ] || return
    jq -r --arg tool "$1" '.toolGroups | to_entries[] | select((.value // []) | index($tool) != null) | .key' "$POLICY_FILE" 2>/dev/null | head -1
}

heuristic_result_count() {
    local text="$1"
    [ -n "$text" ] || { echo 0; return; }

    local pmid_count numbered_count bullet_count doi_count pmcid_count max_count
    pmid_count=$(echo "$text" | grep -oiE 'PMID:\s*[0-9]+|pmid/[0-9]+' | wc -l)
    pmcid_count=$(echo "$text" | grep -oiE 'PMCID:\s*PMC[0-9]+|PMC[0-9]{5,}' | wc -l)
    doi_count=$(echo "$text" | grep -oiE '10\.[0-9]{4,9}/[-._;()/:A-Za-z0-9]+' | wc -l)
    numbered_count=$(echo "$text" | grep -cE '^\s*[0-9]+\.' || true)
    bullet_count=$(echo "$text" | grep -cE '^\s*[-*]\s+' || true)

    max_count=$pmid_count
    [ "$pmcid_count" -gt "$max_count" ] && max_count=$pmcid_count
    [ "$doi_count" -gt "$max_count" ] && max_count=$doi_count
    [ "$numbered_count" -gt "$max_count" ] && max_count=$numbered_count
    [ "$bullet_count" -gt "$max_count" ] && max_count=$bullet_count
    echo "$max_count"
}

source_count() {
    local text="$1"
    local count=0
    [ -n "$text" ] || { echo 0; return; }
    for src in pubmed openalex semantic_scholar europe_pmc crossref core; do
        if echo "$text" | grep -qi "$src"; then
            count=$((count + 1))
        fi
    done
    echo "$count"
}

text_looks_missing() {
    local text="$1"
    [ -n "$text" ] || return 0
    echo "$text" | grep -qiE 'not\s+found|no\s+results|no\s+full\s*text|unavailable|failed|error|empty\s+result|0\s+articles?'
}

evaluation_mode() {
    local tool_name="$1"
    local tool_group="$2"
    if echo "$tool_name" | grep -qiE 'get_fulltext|get_text_mined_terms|get_article_figures'; then
        echo "fulltext"
        return
    fi
    if echo "$tool_name" | grep -qiE 'search_gene|search_compound|search_clinvar|search_biomedical_images|find_related_articles|find_citing_articles|get_article_references|fetch_article_details|build_citation_tree|get_gene_literature|get_compound_literature|get_citation_metrics|get_session_pmids'; then
        echo "search_list"
        return
    fi
    case "$tool_group" in
        search|discovery|citation_network|image_search)
            echo "search_list"
            ;;
        *)
            echo "detail"
            ;;
    esac
}

suggestion_for_mode() {
    local mode="$1"
    local tool_name="$2"
    local had_pipeline="$3"

    case "$mode" in
        fulltext)
            echo "Try another identifier (PMID / PMCID / DOI), enable broader retrieval sources, or fetch article details first."
            ;;
        search_list)
            if [ -z "$had_pipeline" ] || [ "$had_pipeline" = "null" ]; then
                echo "Broaden the query, add more sources, or retry with pipeline mode for structured expansion."
            else
                echo "Broaden the query, relax filters, or expand with related / citing / fulltext tools."
            fi
            ;;
        *)
            if echo "$tool_name" | grep -qiE 'prepare_export|build_research_timeline|analyze_timeline_milestones|compare_timelines'; then
                echo "Gather PMIDs or session context first, then retry the synthesis step."
            elif echo "$tool_name" | grep -qiE 'read_session|get_session_|get_cached_article'; then
                echo "Run a search first or provide explicit session / PMID context before using this session tool."
            else
                echo "Provide explicit identifiers or gather evidence context before retrying this tool."
            fi
            ;;
    esac
}

TRACKER_FILE="$STATE_DIR/workflow_tracker.json"
STEP_FOR_TOOL=$(workflow_step_for_tool "$TOOL_NAME" "$HAD_PIPELINE")
if [ -n "$STEP_FOR_TOOL" ] && [ -f "$TRACKER_FILE" ]; then
    CURRENT_STATUS=$(jq -r ".steps.${STEP_FOR_TOOL} // \"not-started\"" "$TRACKER_FILE" 2>/dev/null)
    if [ "$CURRENT_STATUS" != "completed" ]; then
        jq ".steps.${STEP_FOR_TOOL} = \"completed\"" "$TRACKER_FILE" > "${TRACKER_FILE}.tmp" 2>/dev/null && \
            mv "${TRACKER_FILE}.tmp" "$TRACKER_FILE" 2>/dev/null || true
    fi
fi

if ! tool_in_policy_section "$TOOL_NAME" "rules" "qualityEvaluation"; then
    exit 0
fi

RESULT_TYPE=$(echo "$INPUT" | jq -r '.toolResult.resultType // "unknown"' 2>/dev/null) || RESULT_TYPE="unknown"
RESULT_TEXT=$(echo "$INPUT" | jq -r '.toolResult.textResultForLlm // empty' 2>/dev/null) || true

PENDING_TIER=""
PENDING_TEMPLATE="comprehensive"
if [ -f "$STATE_DIR/pending_complexity.json" ]; then
    PENDING_TIER=$(jq -r '.tier // empty' "$STATE_DIR/pending_complexity.json" 2>/dev/null)
    PENDING_TEMPLATE=$(jq -r '.template // "comprehensive"' "$STATE_DIR/pending_complexity.json" 2>/dev/null)
    rm -f "$STATE_DIR/pending_complexity.json" 2>/dev/null
fi

TOOL_GROUP=$(tool_group_for_tool "$TOOL_NAME")
MODE=$(evaluation_mode "$TOOL_NAME" "$TOOL_GROUP")
RESULT_COUNT=$(heuristic_result_count "$RESULT_TEXT")
SOURCE_COUNT=$(source_count "$RESULT_TEXT")
QUALITY="good"
SUGGESTION=""

if [ "$RESULT_TYPE" = "failure" ]; then
    QUALITY="poor"
    SUGGESTION=$(suggestion_for_mode "$MODE" "$TOOL_NAME" "$HAD_PIPELINE")
else
    case "$MODE" in
        fulltext)
            if text_looks_missing "$RESULT_TEXT"; then
                QUALITY="poor"
            elif [ ${#RESULT_TEXT} -lt 300 ]; then
                QUALITY="insufficient"
            fi
            ;;
        search_list)
            if [ "$RESULT_COUNT" -lt 3 ]; then
                QUALITY="poor"
            elif [ "$RESULT_COUNT" -lt 8 ]; then
                QUALITY="acceptable"
            fi
            if [ "$TOOL_NAME" = "unified_search" ] && [ "$SOURCE_COUNT" -le 1 ] && [ "$RESULT_COUNT" -gt 0 ] && [ "$QUALITY" = "good" ]; then
                QUALITY="acceptable"
            fi
            ;;
        *)
            if text_looks_missing "$RESULT_TEXT"; then
                QUALITY="poor"
            elif [ ${#RESULT_TEXT} -lt 80 ] && [ "$RESULT_COUNT" -eq 0 ]; then
                QUALITY="insufficient"
            fi
            ;;
    esac

    if [ "$QUALITY" != "good" ]; then
        SUGGESTION=$(suggestion_for_mode "$MODE" "$TOOL_NAME" "$HAD_PIPELINE")
    fi
fi

if [ "$TOOL_NAME" = "unified_search" ] && [ "$PENDING_TIER" = "moderate" ] && { [ -z "$HAD_PIPELINE" ] || [ "$HAD_PIPELINE" = "null" ]; } && { [ "$QUALITY" = "good" ] || [ "$QUALITY" = "acceptable" ]; }; then
    QUALITY="suggest_supplement"
    SUGGESTION="Quick search returned ${RESULT_COUNT} results - good start. For comprehensive coverage, also run a pipeline search to include more sources and semantic expansion."
fi

if [ "$QUALITY" != "good" ]; then
    jq -n \
        --arg tool_name "$TOOL_NAME" \
        --arg tool_group "${TOOL_GROUP:-unknown}" \
        --arg evaluation_mode "$MODE" \
        --arg query "$QUERY" \
        --arg quality "$QUALITY" \
        --argjson result_count "$RESULT_COUNT" \
        --argjson source_count "$SOURCE_COUNT" \
        --arg suggestion "$SUGGESTION" \
        --arg had_pipeline "${HAD_PIPELINE:-none}" \
        --arg template "${PENDING_TEMPLATE:-comprehensive}" \
        '{tool_name: $tool_name, tool_group: $tool_group, evaluation_mode: $evaluation_mode, query: $query, quality: $quality, result_count: $result_count, source_count: $source_count, suggestion: $suggestion, had_pipeline: $had_pipeline, template: $template, nudged: false}' \
        > "$STATE_DIR/last_research_eval.json"
    rm -f "$STATE_DIR/last_search_eval.json" 2>/dev/null
else
    rm -f "$STATE_DIR/last_search_eval.json" 2>/dev/null
    rm -f "$STATE_DIR/last_research_eval.json" 2>/dev/null
fi

jq -n \
    --arg timestamp "$(date -u +%Y-%m-%dT%H:%M:%SZ)" \
    --arg tool_name "$TOOL_NAME" \
    --arg tool_group "${TOOL_GROUP:-unknown}" \
    --arg query "$QUERY" \
    --arg quality "$QUALITY" \
    --argjson result_count "$RESULT_COUNT" \
    --argjson source_count "$SOURCE_COUNT" \
    --arg had_pipeline "${HAD_PIPELINE:-none}" \
    --arg tier "${PENDING_TIER:-none}" \
    '{timestamp: $timestamp, tool_name: $tool_name, tool_group: $tool_group, query: $query, quality: $quality, result_count: $result_count, source_count: $source_count, had_pipeline: $had_pipeline, tier: $tier}' \
    >> "$STATE_DIR/search_audit.jsonl" 2>/dev/null

exit 0
