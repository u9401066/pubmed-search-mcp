#!/usr/bin/env bash
# Thin wrapper; shared decisions live in hook_runtime.py for shell parity.
set -u

SCRIPT_DIR=$(CDPATH= cd -- "$(dirname -- "$0")" && pwd)
PYTHON_BIN=${PUBMED_HOOK_PYTHON:-}
if [ -z "$PYTHON_BIN" ]; then
    PYTHON_BIN=$(command -v python3 2>/dev/null || command -v python 2>/dev/null || true)
fi
[ -n "$PYTHON_BIN" ] || exit 0
"$PYTHON_BIN" "$SCRIPT_DIR/hook_runtime.py" enforce-pipeline || exit 0
exit 0
