#!/bin/bash
# =============================================================================
# Result Evaluator - postToolUse Hook for Copilot Coding Agent
# =============================================================================
#
# THREE-TIER PARALLEL STRATEGY - postToolUse role:
#
#   This hook runs AFTER unified_search completes. It:
#
#   1. Reads pending_complexity.json (written by preToolUse for Tier 2 queries)
#   2. Evaluates result quality (count, sources, depth)
#   3. Writes last_search_eval.json for the NEXT preToolUse to read
#
#   For Tier 2 (moderate complexity, ALLOWED through):
#     - Even if results are decent: suggest pipeline supplement
#     - Quality = "suggest_supplement" -> gentle nudge on next tool call
#     - Agent gets both: quick results NOW + pipeline suggestion for LATER
#
#   For any search with poor results:
#     - Quality = "poor"/"insufficient" -> stronger nudge on next tool call
#
# NOTE: postToolUse output is IGNORED by the agent. We influence behavior
#       only through the state file -> preToolUse deny mechanism.
#
# =============================================================================
set -e

# --- Dependency check ---
if ! command -v jq >/dev/null 2>&1; then
    exit 0  # No jq = graceful skip
fi

INPUT=$(cat)
TOOL_NAME=$(echo "$INPUT" | jq -r '.toolName // empty' 2>/dev/null) || exit 0

# Only evaluate unified_search results
if ! echo "$TOOL_NAME" | grep -qiE 'unified_search'; then
    exit 0
fi

TOOL_ARGS=$(echo "$INPUT" | jq -r '.toolArgs // empty' 2>/dev/null) || true
RESULT_TYPE=$(echo "$INPUT" | jq -r '.toolResult.resultType // "unknown"' 2>/dev/null) || RESULT_TYPE="unknown"
RESULT_TEXT=$(echo "$INPUT" | jq -r '.toolResult.textResultForLlm // empty' 2>/dev/null) || true

# Extract the original query and pipeline
QUERY=$(echo "$TOOL_ARGS" | jq -r '.query // empty' 2>/dev/null) || true
HAD_PIPELINE=$(echo "$TOOL_ARGS" | jq -r '.pipeline // empty' 2>/dev/null) || true

STATE_DIR=".github/hooks/_state"
mkdir -p "$STATE_DIR"

# Read pending complexity flag (Tier 2)
PENDING_TIER=""
PENDING_TEMPLATE=""
if [ -f "$STATE_DIR/pending_complexity.json" ]; then
    PENDING_TIER=$(jq -r '.tier // empty' "$STATE_DIR/pending_complexity.json" 2>/dev/null)
    PENDING_TEMPLATE=$(jq -r '.template // "comprehensive"' "$STATE_DIR/pending_complexity.json" 2>/dev/null)
    # Consume the flag
    rm -f "$STATE_DIR/pending_complexity.json" 2>/dev/null
fi

# If search failed entirely
if [ "$RESULT_TYPE" = "failure" ]; then
    jq -n \
        --arg query "$QUERY" \
        --arg quality "poor" \
        --argjson result_count 0 \
        --arg suggestion "Search failed. Try: 1) Simpler query, 2) Different sources, 3) Pipeline mode for structured searching." \
        --arg template "${PENDING_TEMPLATE:-comprehensive}" \
        '{query: $query, quality: $quality, result_count: $result_count, suggestion: $suggestion, template: $template, nudged: false}' \
        > "$STATE_DIR/last_search_eval.json"

    exit 0
fi

# ---------------------------------------------------------------------------
# Parse result text to evaluate quality
# ---------------------------------------------------------------------------

RESULT_COUNT=0
if [ -n "$RESULT_TEXT" ]; then
    PMID_COUNT=$(echo "$RESULT_TEXT" | grep -oiE 'PMID:\s*[0-9]+|pmid/[0-9]+' | wc -l)
    NUMBERED_COUNT=$(echo "$RESULT_TEXT" | grep -cE '^\s*[0-9]+\.' || true)
    TITLE_COUNT=$(echo "$RESULT_TEXT" | grep -cE '^\s*\*\*[A-Z]' || true)
    RESULT_COUNT=$((PMID_COUNT > NUMBERED_COUNT ? PMID_COUNT : NUMBERED_COUNT))
    RESULT_COUNT=$((RESULT_COUNT > TITLE_COUNT ? RESULT_COUNT : TITLE_COUNT))
fi

# Check for depth score
DEPTH_SCORE=""
if echo "$RESULT_TEXT" | grep -qiE 'search.?depth|depth.?score'; then
    DEPTH_SCORE=$(echo "$RESULT_TEXT" | grep -oiE 'depth[^0-9]*([0-9]+)' | head -1 | grep -oE '[0-9]+')
fi

# Check source diversity
SOURCE_COUNT=0
for src in "pubmed" "openalex" "semantic_scholar" "europe_pmc" "crossref" "core"; do
    if echo "$RESULT_TEXT" | grep -qi "$src"; then
        SOURCE_COUNT=$((SOURCE_COUNT + 1))
    fi
done

# ---------------------------------------------------------------------------
# Quality Assessment
# ---------------------------------------------------------------------------
QUALITY="good"
SUGGESTION=""

# Too few results
if [ "$RESULT_COUNT" -lt 3 ]; then
    QUALITY="poor"
    SUGGESTION="Only ${RESULT_COUNT} articles found. "
    if [ -z "$HAD_PIPELINE" ] || [ "$HAD_PIPELINE" = "null" ]; then
        SUGGESTION="${SUGGESTION}Try using pipeline mode for multi-strategy searching: unified_search(pipeline=\"template: comprehensive\"). "
    else
        SUGGESTION="${SUGGESTION}Try broadening the query, using synonyms, or removing restrictive filters. "
    fi
fi

# Low depth score
if [ -n "$DEPTH_SCORE" ] && [ "$DEPTH_SCORE" -lt 30 ]; then
    if [ "$QUALITY" != "poor" ]; then
        QUALITY="insufficient"
    fi
    SUGGESTION="${SUGGESTION}Search depth is shallow (${DEPTH_SCORE}/100). Consider using semantic expansion: generate_search_queries() first, then search with MeSH terms. "
fi

# Single source only
if [ "$SOURCE_COUNT" -le 1 ] && [ "$RESULT_COUNT" -gt 0 ]; then
    if [ "$QUALITY" = "good" ]; then
        QUALITY="acceptable"
    fi
    SUGGESTION="${SUGGESTION}Results from only ${SOURCE_COUNT} source(s). Add more sources for broader coverage: sources=\"pubmed,openalex,semantic_scholar\". "
fi

# Moderately few results (borderline)
if [ "$RESULT_COUNT" -ge 3 ] && [ "$RESULT_COUNT" -lt 8 ] && [ -z "$HAD_PIPELINE" ]; then
    if [ "$QUALITY" = "good" ]; then
        QUALITY="acceptable"
    fi
    SUGGESTION="${SUGGESTION}Found ${RESULT_COUNT} articles. Pipeline mode might find more via parallel multi-strategy search. "
fi

# ---------------------------------------------------------------------------
# Tier 2 supplement: Even if results are "good", suggest pipeline too
# ---------------------------------------------------------------------------
if [ "$PENDING_TIER" = "moderate" ] && [ -z "$HAD_PIPELINE" ]; then
    # Tier 2 query got through without pipeline → suggest supplementary pipeline
    if [ "$QUALITY" = "good" ] || [ "$QUALITY" = "acceptable" ]; then
        QUALITY="suggest_supplement"
        SUGGESTION="Quick search returned ${RESULT_COUNT} articles — good start. For comprehensive coverage, also run a pipeline search to catch articles from additional sources and MeSH-expanded queries."
    fi
    # If already poor/insufficient, keep the stronger quality level
fi

# ---------------------------------------------------------------------------
# Write state file (only if not "good")
# ---------------------------------------------------------------------------
if [ "$QUALITY" != "good" ]; then
    jq -n \
        --arg query "$QUERY" \
        --arg quality "$QUALITY" \
        --argjson result_count "$RESULT_COUNT" \
        --arg suggestion "$SUGGESTION" \
        --argjson source_count "$SOURCE_COUNT" \
        --arg depth_score "${DEPTH_SCORE:-unknown}" \
        --arg had_pipeline "${HAD_PIPELINE:-none}" \
        --arg template "${PENDING_TEMPLATE:-comprehensive}" \
        '{query: $query, quality: $quality, result_count: $result_count, suggestion: $suggestion, source_count: $source_count, depth_score: $depth_score, had_pipeline: $had_pipeline, template: $template, nudged: false}' \
        > "$STATE_DIR/last_search_eval.json"
else
    # Good results → clear any previous poor state
    rm -f "$STATE_DIR/last_search_eval.json" 2>/dev/null
fi

# Structured logging (append to JSONL)
jq -n \
    --arg timestamp "$(date -u +%Y-%m-%dT%H:%M:%SZ)" \
    --arg query "$QUERY" \
    --arg quality "$QUALITY" \
    --argjson result_count "$RESULT_COUNT" \
    --argjson source_count "$SOURCE_COUNT" \
    --arg had_pipeline "${HAD_PIPELINE:-none}" \
    --arg tier "${PENDING_TIER:-none}" \
    '{timestamp: $timestamp, query: $query, quality: $quality, result_count: $result_count, source_count: $source_count, had_pipeline: $had_pipeline, tier: $tier}' \
    >> "$STATE_DIR/search_audit.jsonl" 2>/dev/null

exit 0
