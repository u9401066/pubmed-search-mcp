# Thin wrapper; shared decisions live in hook_runtime.py for shell parity.
$ErrorActionPreference = "SilentlyContinue"
$rawInput = [Console]::In.ReadToEnd()
$runtime = Join-Path $PSScriptRoot "hook_runtime.py"
$python = if ($env:PUBMED_HOOK_PYTHON) {
    $env:PUBMED_HOOK_PYTHON
} elseif (Get-Command "python" -ErrorAction SilentlyContinue) {
    "python"
} elseif (Get-Command "python3" -ErrorAction SilentlyContinue) {
    "python3"
} else {
    exit 0
}
$rawInput | & $python $runtime "session-init" 2>$null
exit 0
