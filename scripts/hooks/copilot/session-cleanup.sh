#!/bin/bash
# Session Cleanup - sessionEnd Hook
set -e

# --- Dependency check ---
if ! command -v jq >/dev/null 2>&1; then
    # Best-effort cleanup without jq
    rm -f ".github/hooks/_state/last_search_eval.json" 2>/dev/null
    rm -f ".github/hooks/_state/pending_complexity.json" 2>/dev/null
    exit 0
fi

INPUT=$(cat)
REASON=$(echo "$INPUT" | jq -r '.reason // "unknown"' 2>/dev/null) || REASON="unknown"
STATE_DIR=".github/hooks/_state"

# Log session end
if [ -d "$STATE_DIR" ]; then
    jq -n \
        --arg timestamp "$(date -u +%Y-%m-%dT%H:%M:%SZ)" \
        --arg event "session_end" \
        --arg reason "$REASON" \
        '{timestamp: $timestamp, event: $event, reason: $reason}' \
        >> "$STATE_DIR/search_audit.jsonl" 2>/dev/null

    # Clean up state (keep audit log)
    rm -f "$STATE_DIR/last_search_eval.json" 2>/dev/null
    rm -f "$STATE_DIR/pending_complexity.json" 2>/dev/null
fi

exit 0
