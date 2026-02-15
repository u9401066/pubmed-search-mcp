# Vulture whitelist — false positives and intentionally unused code
# See: https://github.com/jendrikseipp/vulture#whitelisting
#
# Run: uv run vulture src/ vulture_whitelist.py --min-confidence 80
#
# Bare name expressions tell vulture these identifiers are "used" somewhere,
# suppressing false-positive "unused variable" reports.

# ── __aexit__ protocol parameters (required by async context manager protocol) ──
exc_type  # noqa: B018
exc_tb  # noqa: B018

# ── MCP tool parameters (part of public API, used by AI agents) ──
include_details  # noqa: B018
test  # noqa: B018
cron  # noqa: B018
diff_mode  # noqa: B018
notify  # noqa: B018

# ── Script parameters (used by callers but not read in function body) ──
is_chinese  # noqa: B018

# ── Function parameters (API surface, reserved for future use) ──
source_rankings  # noqa: B018
