#!/bin/bash
# =============================================================================
# Session Init - sessionStart Hook
# =============================================================================
# Log session start and prepare state directory.
# =============================================================================
set -e

# --- Dependency check ---
if ! command -v jq >/dev/null 2>&1; then
    mkdir -p ".github/hooks/_state"
    exit 0
fi

INPUT=$(cat)
SOURCE=$(echo "$INPUT" | jq -r '.source // "new"' 2>/dev/null) || SOURCE="unknown"

STATE_DIR=".github/hooks/_state"
mkdir -p "$STATE_DIR"

# Clear stale state from previous session
rm -f "$STATE_DIR/last_search_eval.json" 2>/dev/null
rm -f "$STATE_DIR/pending_complexity.json" 2>/dev/null

# Log session start
jq -n \
    --arg timestamp "$(date -u +%Y-%m-%dT%H:%M:%SZ)" \
    --arg source "$SOURCE" \
    --arg event "session_start" \
    '{timestamp: $timestamp, source: $source, event: $event}' \
    >> "$STATE_DIR/search_audit.jsonl" 2>/dev/null

exit 0
