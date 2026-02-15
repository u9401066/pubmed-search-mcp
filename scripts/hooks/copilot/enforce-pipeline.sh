#!/bin/bash
# =============================================================================
# Pipeline Enforcer - preToolUse Hook for Copilot Coding Agent
# =============================================================================
#
# THREE-TIER PARALLEL STRATEGY:
#   Tier 1 (score 0-2): ALLOW - fast search, no interference
#   Tier 2 (score 3-4): ALLOW + flag for post-eval pipeline suggestion
#   Tier 3 (score 5+):  DENY  - require pipeline upfront
#
# STATE FILES: .github/hooks/_state/
#   - pending_complexity.json : preToolUse writes (Tier 2), postToolUse reads
#   - last_search_eval.json   : postToolUse writes, preToolUse reads (nudge)
#
# ENCODING: All stdout output is ASCII-only to prevent mojibake on Windows.
# =============================================================================
set -e

# --- Dependency check ---
if ! command -v jq >/dev/null 2>&1; then
    # No jq available: allow all tools (graceful degradation)
    exit 0
fi

INPUT=$(cat)
TOOL_NAME=$(echo "$INPUT" | jq -r '.toolName // empty' 2>/dev/null) || exit 0
TOOL_ARGS=$(echo "$INPUT" | jq -r '.toolArgs // empty' 2>/dev/null) || true

STATE_DIR=".github/hooks/_state"

# ---------------------------------------------------------------------------
# Helper: Score query complexity (returns numeric score)
# ---------------------------------------------------------------------------
get_complexity_score() {
    local query="$1"
    local score=0

    # Comparison patterns (strongest signal)
    if echo "$query" | grep -qiE '\bvs\.?\b|versus|compared?\s+(to|with)|better\s+than|superior|inferior|non-?inferior'; then
        score=$((score + 3))
    fi

    # PICO-like patterns
    if echo "$query" | grep -qiE '\b(patient|population|intervention|comparison|outcome)\b'; then
        score=$((score + 2))
    fi
    if echo "$query" | grep -qiE '\b(efficacy|safety|mortality|morbidity|adverse)\b'; then
        score=$((score + 1))
    fi

    # Systematic/comprehensive signals
    if echo "$query" | grep -qiE '\b(systematic|comprehensive|meta-?analysis|review|all\s+studies)\b'; then
        score=$((score + 2))
    fi

    # Multiple entities / long query
    local word_count
    word_count=$(echo "$query" | wc -w)
    if [ "$word_count" -gt 6 ]; then
        score=$((score + 1))
    fi

    # Boolean operators suggest structured searching
    if echo "$query" | grep -qE '\b(AND|OR|NOT)\b'; then
        score=$((score + 1))
    fi

    # MeSH-like notation
    if echo "$query" | grep -qE '\[MeSH\]|\[Mesh\]|\[tiab\]|\[Title/Abstract\]'; then
        score=$((score + 1))
    fi

    echo "$score"
}

# ---------------------------------------------------------------------------
# Helper: Determine which pipeline template to recommend
# ---------------------------------------------------------------------------
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

# ---------------------------------------------------------------------------
# Helper: Check if there's pending feedback (poor/supplement suggestion)
# ---------------------------------------------------------------------------
check_feedback_state() {
    local state_file="$STATE_DIR/last_search_eval.json"

    if [ ! -f "$state_file" ]; then
        return 1
    fi

    local quality
    quality=$(jq -r '.quality // "unknown"' "$state_file" 2>/dev/null) || return 1

    case "$quality" in
        poor|insufficient|suggest_supplement)
            return 0
            ;;
        *)
            return 1
            ;;
    esac
}

# ---------------------------------------------------------------------------
# MAIN: Tool name matching
# ---------------------------------------------------------------------------

if echo "$TOOL_NAME" | grep -qiE 'unified_search'; then

    QUERY=$(echo "$TOOL_ARGS" | jq -r '.query // empty' 2>/dev/null) || true
    PIPELINE=$(echo "$TOOL_ARGS" | jq -r '.pipeline // empty' 2>/dev/null) || true

    # Pipeline already specified -> ALLOW
    if [ -n "$PIPELINE" ] && [ "$PIPELINE" != "null" ]; then
        rm -f "$STATE_DIR/last_search_eval.json" 2>/dev/null
        rm -f "$STATE_DIR/pending_complexity.json" 2>/dev/null
        exit 0
    fi

    # Score the query complexity
    SCORE=0
    if [ -n "$QUERY" ]; then
        SCORE=$(get_complexity_score "$QUERY")
    fi

    TEMPLATE=$(recommend_template "$QUERY")

    # --- Tier 3: High complexity (score >= 5) -> DENY, require pipeline ---
    if [ "$SCORE" -ge 5 ]; then
        REASON="[PIPELINE REQUIRED] Highly structured query detected.

Your query (complexity: ${SCORE}/10) is clearly a structured search
(PICO comparison / systematic review / multi-entity analysis).

Pipeline mode provides:
  - Parallel multi-source searching (PubMed + OpenAlex + Europe PMC + ...)
  - Automatic PICO decomposition and MeSH expansion
  - DAG-based step orchestration
  - 6-dimensional result ranking

Please use pipeline:
  unified_search(query=\"${QUERY}\", pipeline=\"template: ${TEMPLATE}\\ntopic: ${QUERY}\")

Available templates: pico, comprehensive, exploration, gene_drug
Or load a saved pipeline: pipeline=\"saved:<name>\""

        jq -n --arg reason "$REASON" \
            '{permissionDecision: "deny", permissionDecisionReason: $reason}'
        exit 0
    fi

    # --- Tier 2: Moderate complexity (score 3-4) -> ALLOW, flag for post-eval ---
    if [ "$SCORE" -ge 3 ]; then
        mkdir -p "$STATE_DIR"
        jq -n \
            --arg query "$QUERY" \
            --argjson score "$SCORE" \
            --arg template "$TEMPLATE" \
            '{query: $query, score: $score, template: $template, tier: "moderate"}' \
            > "$STATE_DIR/pending_complexity.json" 2>/dev/null || true

        # ALLOW - let the quick search through for fast results
        exit 0
    fi

    # --- Tier 1: Simple (score 0-2) -> ALLOW, no interference ---
    exit 0
fi

# ---------------------------------------------------------------------------
# Feedback loop: After search, nudge agent with pipeline suggestion
# ---------------------------------------------------------------------------

if check_feedback_state; then
    EVAL=$(cat "$STATE_DIR/last_search_eval.json" 2>/dev/null) || exit 0
    QUALITY=$(echo "$EVAL" | jq -r '.quality // "unknown"' 2>/dev/null) || exit 0
    SUGGESTION=$(echo "$EVAL" | jq -r '.suggestion // empty' 2>/dev/null) || true
    PREV_QUERY=$(echo "$EVAL" | jq -r '.query // empty' 2>/dev/null) || true
    RESULT_COUNT=$(echo "$EVAL" | jq -r '.result_count // 0' 2>/dev/null) || true
    ALREADY_NUDGED=$(echo "$EVAL" | jq -r '.nudged // false' 2>/dev/null) || true

    # Already nudged once -> don't repeat
    if [ "$ALREADY_NUDGED" = "true" ]; then
        exit 0
    fi

    # Agent is already doing follow-up search -> clear state, allow
    if echo "$TOOL_NAME" | grep -qiE 'search|related|citing|reference|pipeline|expand'; then
        rm -f "$STATE_DIR/last_search_eval.json" 2>/dev/null
        exit 0
    fi

    # Mark as nudged (only nudge once)
    if jq '.nudged = true' "$STATE_DIR/last_search_eval.json" > "$STATE_DIR/last_search_eval.tmp" 2>/dev/null; then
        mv "$STATE_DIR/last_search_eval.tmp" "$STATE_DIR/last_search_eval.json" 2>/dev/null
    else
        rm -f "$STATE_DIR/last_search_eval.tmp" 2>/dev/null
    fi

    # Different messages for different feedback types
    if [ "$QUALITY" = "suggest_supplement" ]; then
        EVAL_TEMPLATE=$(echo "$EVAL" | jq -r '.template // "comprehensive"' 2>/dev/null) || EVAL_TEMPLATE="comprehensive"
        REASON="[TIP] You have quick results for \"${PREV_QUERY}\" (${RESULT_COUNT} articles).

For more comprehensive coverage, also run a pipeline search in parallel:
  unified_search(query=\"${PREV_QUERY}\", pipeline=\"template: ${EVAL_TEMPLATE}\\ntopic: ${PREV_QUERY}\")

Pipeline adds: multi-source parallel search, MeSH expansion, structured ranking.
This supplements (not replaces) your existing results.

Skip this if the quick results are sufficient for your needs."

    else
        REASON="[WARNING] Previous search returned only ${RESULT_COUNT} results for \"${PREV_QUERY}\".

${SUGGESTION}

Consider these follow-up actions:
  1. Retry with pipeline: unified_search(pipeline=\"template: comprehensive\")
  2. Expand with related articles: find_related_articles(pmid=\"<top_result>\")
  3. Try broader query or different sources

You may proceed if you've already addressed this."
    fi

    jq -n --arg reason "$REASON" \
        '{permissionDecision: "deny", permissionDecisionReason: $reason}'
    exit 0
fi

# All other tools -> ALLOW
exit 0
