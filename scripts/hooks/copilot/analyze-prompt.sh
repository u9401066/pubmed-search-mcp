#!/bin/bash
# =============================================================================
# Prompt Analyzer - userPromptSubmitted Hook
# =============================================================================
# Detect research intent in user prompt and log for analysis.
# NOTE: This hook's output is IGNORED - it's purely for logging/analytics.
# The actual enforcement happens in preToolUse (enforce-pipeline.sh).
# =============================================================================
set -e

# --- Dependency check ---
if ! command -v jq >/dev/null 2>&1; then
    exit 0  # No jq = skip logging
fi

INPUT=$(cat)
PROMPT=$(echo "$INPUT" | jq -r '.prompt // empty' 2>/dev/null) || exit 0

STATE_DIR=".github/hooks/_state"
mkdir -p "$STATE_DIR"

# Detect research intent
INTENT="unknown"
COMPLEXITY="simple"

# PICO / comparison
if echo "$PROMPT" | grep -qiE '\bvs\.?\b|versus|compared?\s+(to|with)|比較|對比|A比B|好嗎'; then
    INTENT="comparison"
    COMPLEXITY="complex"
# Systematic / comprehensive
elif echo "$PROMPT" | grep -qiE 'systematic|comprehensive|所有.*文獻|完整搜尋|系統性|文獻回顧|review'; then
    INTENT="systematic"
    COMPLEXITY="complex"
# Exploration (from a paper)
elif echo "$PROMPT" | grep -qiE 'related|citation|引用|相關.*文章|這篇.*論文|PMID|DOI'; then
    INTENT="exploration"
    COMPLEXITY="moderate"
# Gene/Drug research
elif echo "$PROMPT" | grep -qiE '\b(gene|BRCA|TP53|EGFR|variant|mutation|drug|compound)\b|基因|藥物|變異'; then
    INTENT="gene_drug"
    COMPLEXITY="moderate"
# Quick search
elif echo "$PROMPT" | grep -qiE 'search|find|搜尋|找.*論文|有沒有.*關於'; then
    INTENT="quick_search"
    COMPLEXITY="simple"
fi

# Log prompt analysis
jq -n \
    --arg timestamp "$(date -u +%Y-%m-%dT%H:%M:%SZ)" \
    --arg event "prompt_submitted" \
    --arg intent "$INTENT" \
    --arg complexity "$COMPLEXITY" \
    --arg prompt_preview "$(echo "$PROMPT" | head -c 200)" \
    '{timestamp: $timestamp, event: $event, intent: $intent, complexity: $complexity, prompt_preview: $prompt_preview}' \
    >> "$STATE_DIR/search_audit.jsonl" 2>/dev/null

exit 0
