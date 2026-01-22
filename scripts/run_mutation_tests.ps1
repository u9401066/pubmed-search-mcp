#!/usr/bin/env pwsh
# Mutation Testing Script
# Tests the quality of your tests by introducing bugs

Write-Host "🧬 Running Mutation Testing..." -ForegroundColor Cyan
Write-Host ""
Write-Host "This will take some time as mutmut introduces bugs to test your tests." -ForegroundColor Gray
Write-Host ""

# Check if UV is available
if (-not (Get-Command uv -ErrorAction SilentlyContinue)) {
    Write-Host "❌ Error: UV not found. Please install UV first." -ForegroundColor Red
    exit 1
}

# ============================================================
# Configuration
# ============================================================

$targetPath = "src/pubmed_search"
$testsPath = "tests/"
$mutationLimit = 100  # Limit mutations for faster runs

Write-Host "📋 Configuration:" -ForegroundColor Yellow
Write-Host "  Target: $targetPath" -ForegroundColor Gray
Write-Host "  Tests: $testsPath" -ForegroundColor Gray
Write-Host "  Mutation Limit: $mutationLimit (use --all for full run)" -ForegroundColor Gray
Write-Host ""

# ============================================================
# Step 1: Clean Previous Results
# ============================================================
Write-Host "🧹 Cleaning previous mutation results..." -ForegroundColor Yellow

if (Test-Path ".mutmut-cache") {
    Remove-Item -Recurse -Force .mutmut-cache
    Write-Host "  ✅ Cleaned .mutmut-cache" -ForegroundColor Green
}

# ============================================================
# Step 2: Run Baseline Tests
# ============================================================
Write-Host ""
Write-Host "🧪 Running baseline tests..." -ForegroundColor Yellow

$baselineResult = uv run pytest tests/ -q --tb=no
if ($LASTEXITCODE -ne 0) {
    Write-Host "  ❌ Baseline tests failed. Fix tests before running mutation testing." -ForegroundColor Red
    exit 1
}
Write-Host "  ✅ Baseline tests passed" -ForegroundColor Green

# ============================================================
# Step 3: Run Mutation Testing
# ============================================================
Write-Host ""
Write-Host "🧬 Running mutations (this may take 10-30 minutes)..." -ForegroundColor Yellow
Write-Host ""

try {
    # Run mutmut with limited mutations for faster feedback
    # Remove --use-coverage for full coverage
    uv run mutmut run --paths-to-mutate=$targetPath --tests-dir=$testsPath --CI
    
    $mutmutExitCode = $LASTEXITCODE
    
    Write-Host ""
    Write-Host "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━" -ForegroundColor Cyan
    Write-Host "Mutation Testing Results" -ForegroundColor Cyan
    Write-Host "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━" -ForegroundColor Cyan
    Write-Host ""
    
    # Get mutation summary
    uv run mutmut results
    
    Write-Host ""
    Write-Host "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━" -ForegroundColor Cyan
    
} catch {
    Write-Host "❌ Mutation testing failed: $_" -ForegroundColor Red
    exit 1
}

# ============================================================
# Step 4: Show Surviving Mutants
# ============================================================
Write-Host ""
Write-Host "🔍 Analyzing surviving mutants..." -ForegroundColor Yellow
Write-Host ""

# Get list of survived mutants
$survivedOutput = uv run mutmut show survived 2>&1

if ($survivedOutput) {
    Write-Host "⚠️  Survived Mutants (tests didn't catch these bugs):" -ForegroundColor Yellow
    Write-Host $survivedOutput
    Write-Host ""
    Write-Host "💡 Tip: Add tests to catch these mutations" -ForegroundColor Cyan
} else {
    Write-Host "✅ No survived mutants! Your tests are excellent!" -ForegroundColor Green
}

# ============================================================
# Step 5: Generate HTML Report (Optional)
# ============================================================
Write-Host ""
Write-Host "📊 Generating HTML report..." -ForegroundColor Yellow

try {
    uv run mutmut html
    if (Test-Path "html/index.html") {
        Write-Host "  ✅ HTML report generated: html/index.html" -ForegroundColor Green
        Write-Host ""
        Write-Host "  Open report:" -ForegroundColor Cyan
        Write-Host "    start html/index.html" -ForegroundColor Gray
    }
} catch {
    Write-Host "  ⚠️  Could not generate HTML report" -ForegroundColor Yellow
}

# ============================================================
# Summary
# ============================================================
Write-Host ""
Write-Host "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━" -ForegroundColor Cyan
Write-Host "Summary" -ForegroundColor Cyan
Write-Host "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━" -ForegroundColor Cyan
Write-Host ""
Write-Host "Commands:" -ForegroundColor Yellow
Write-Host "  View results:     uv run mutmut results" -ForegroundColor Gray
Write-Host "  Show survived:    uv run mutmut show survived" -ForegroundColor Gray
Write-Host "  Show specific:    uv run mutmut show <id>" -ForegroundColor Gray
Write-Host "  Apply mutation:   uv run mutmut apply <id>" -ForegroundColor Gray
Write-Host "  Generate HTML:    uv run mutmut html" -ForegroundColor Gray
Write-Host ""

if ($mutmutExitCode -eq 0) {
    Write-Host "✅ Mutation testing completed successfully!" -ForegroundColor Green
    exit 0
} else {
    Write-Host "⚠️  Some mutants survived. Consider improving test coverage." -ForegroundColor Yellow
    exit 0  # Don't fail CI, just warn
}
