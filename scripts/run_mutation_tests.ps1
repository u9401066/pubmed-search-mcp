#!/usr/bin/env pwsh
# Deterministic core-module mutation hard gate

Write-Host "🧬 Running Core Mutation Hard Gate..." -ForegroundColor Cyan
Write-Host ""
Write-Host "This run mutates a curated set of high-signal shared-module behaviors and fails if any survive." -ForegroundColor Gray
Write-Host ""

if (-not (Get-Command uv -ErrorAction SilentlyContinue)) {
    Write-Host "❌ Error: UV not found. Please install UV first." -ForegroundColor Red
    exit 1
}

Write-Host "📋 Scope:" -ForegroundColor Yellow
Write-Host "  Targets: src/pubmed_search/shared/source_contracts.py" -ForegroundColor Gray
Write-Host "           src/pubmed_search/shared/cache_substrate.py" -ForegroundColor Gray
Write-Host "  Tests:   tests/test_source_contracts.py" -ForegroundColor Gray
Write-Host "           tests/test_cache_substrate.py" -ForegroundColor Gray
Write-Host ""

uv run python scripts/run_mutation_gate.py
$mutationExitCode = $LASTEXITCODE

Write-Host ""
Write-Host "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━" -ForegroundColor Cyan
Write-Host "Mutation Gate Summary" -ForegroundColor Cyan
Write-Host "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━" -ForegroundColor Cyan
Write-Host ""

if ($mutationExitCode -eq 0) {
    Write-Host "✅ Core mutation hard gate passed." -ForegroundColor Green
} else {
    Write-Host "❌ Core mutation hard gate failed." -ForegroundColor Red
    Write-Host "   Review the survived or stale mutation cases above." -ForegroundColor Gray
}

exit $mutationExitCode
