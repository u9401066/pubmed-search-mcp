#!/usr/bin/env pwsh
# Comprehensive Testing Script
# Runs all test suites: unit, performance, E2E, security, mutation

param(
    [switch]$Quick,          # Skip slow tests
    [switch]$Security,       # Include security scans
    [switch]$Mutation,       # Include mutation testing (very slow)
    [switch]$Coverage,       # Generate coverage report
    [switch]$Benchmark,      # Run performance benchmarks
    [switch]$All             # Run everything (equivalent to no flags)
)

Write-Host "🧪 Comprehensive Test Suite" -ForegroundColor Cyan
Write-Host "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━" -ForegroundColor Cyan
Write-Host ""

# Default to running basic tests if no flags specified
if (-not ($Quick -or $Security -or $Mutation -or $Coverage -or $Benchmark -or $All)) {
    $Coverage = $true
}

# "All" means everything
if ($All) {
    $Coverage = $true
    $Security = $true
    $Mutation = $true
    $Benchmark = $true
}

$exitCode = 0
$startTime = Get-Date

# ============================================================
# 1. Static Analysis
# ============================================================
Write-Host "📋 1. Static Analysis" -ForegroundColor Yellow
Write-Host ""

# Ruff
Write-Host "  Running Ruff..." -ForegroundColor Gray
uv run ruff check .
if ($LASTEXITCODE -ne 0) {
    Write-Host "  ❌ Ruff found issues" -ForegroundColor Red
    $exitCode = 1
} else {
    Write-Host "  ✅ Ruff passed" -ForegroundColor Green
}

# MyPy
Write-Host "  Running MyPy..." -ForegroundColor Gray
uv run mypy src/
if ($LASTEXITCODE -ne 0) {
    Write-Host "  ⚠️  MyPy found type issues" -ForegroundColor Yellow
} else {
    Write-Host "  ✅ MyPy passed" -ForegroundColor Green
}

Write-Host ""

# ============================================================
# 2. Unit Tests
# ============================================================
Write-Host "📋 2. Unit Tests" -ForegroundColor Yellow
Write-Host ""

if ($Quick) {
    Write-Host "  Running quick tests (skipping integration and slow)..." -ForegroundColor Gray
    uv run pytest -m "not integration and not slow" -v
} elseif ($Coverage) {
    Write-Host "  Running tests with coverage..." -ForegroundColor Gray
    uv run pytest --cov=src --cov-report=html --cov-report=term-missing -v
} else {
    Write-Host "  Running all tests (multi-core)..." -ForegroundColor Gray
    uv run pytest -v
}

if ($LASTEXITCODE -ne 0) {
    Write-Host "  ❌ Tests failed" -ForegroundColor Red
    $exitCode = 1
} else {
    Write-Host "  ✅ Tests passed" -ForegroundColor Green
}

Write-Host ""

# ============================================================
# 3. Performance Tests
# ============================================================
if ($Benchmark -or $All) {
    Write-Host "📋 3. Performance Tests" -ForegroundColor Yellow
    Write-Host ""

    Write-Host "  Running benchmarks (single-core, xdist auto-disabled)..." -ForegroundColor Gray
    uv run pytest tests/test_performance.py -v --benchmark-only -p no:xdist

    if ($LASTEXITCODE -ne 0) {
        Write-Host "  ⚠️  Some benchmarks failed" -ForegroundColor Yellow
    } else {
        Write-Host "  ✅ Benchmarks completed" -ForegroundColor Green
    }

    Write-Host ""
}

# ============================================================
# 4. E2E Tests
# ============================================================
Write-Host "📋 4. End-to-End Tests" -ForegroundColor Yellow
Write-Host ""

Write-Host "  Running E2E workflows (multi-core)..." -ForegroundColor Gray
uv run pytest tests/test_e2e_workflows.py -v

if ($LASTEXITCODE -ne 0) {
    Write-Host "  ❌ E2E tests failed" -ForegroundColor Red
    $exitCode = 1
} else {
    Write-Host "  ✅ E2E tests passed" -ForegroundColor Green
}

Write-Host ""

# ============================================================
# 5. Security Scans
# ============================================================
if ($Security -or $All) {
    Write-Host "📋 5. Security Scans" -ForegroundColor Yellow
    Write-Host ""

    & "$PSScriptRoot\run_security_scan.ps1"

    if ($LASTEXITCODE -ne 0) {
        Write-Host "  ⚠️  Security issues found" -ForegroundColor Yellow
    }

    Write-Host ""
}

# ============================================================
# 6. Mutation Testing
# ============================================================
if ($Mutation -or $All) {
    Write-Host "📋 6. Mutation Testing" -ForegroundColor Yellow
    Write-Host ""
    Write-Host "  ⏰ This will take 10-30 minutes..." -ForegroundColor Gray
    Write-Host ""

    & "$PSScriptRoot\run_mutation_tests.ps1"

    Write-Host ""
}

# ============================================================
# Summary
# ============================================================
$endTime = Get-Date
$duration = $endTime - $startTime

Write-Host "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━" -ForegroundColor Cyan
Write-Host "Test Suite Summary" -ForegroundColor Cyan
Write-Host "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━" -ForegroundColor Cyan
Write-Host ""

Write-Host "Duration: $($duration.ToString('mm\:ss'))" -ForegroundColor Gray
Write-Host ""

if ($Coverage) {
    Write-Host "📊 Coverage Report: htmlcov/index.html" -ForegroundColor Cyan
    Write-Host "   Open with: start htmlcov/index.html" -ForegroundColor Gray
    Write-Host ""
}

if ($Security -or $All) {
    Write-Host "🔒 Security Reports:" -ForegroundColor Cyan
    Write-Host "   - bandit-report.json" -ForegroundColor Gray
    Write-Host "   - safety-report.json" -ForegroundColor Gray
    Write-Host ""
}

if ($Mutation -or $All) {
    Write-Host "🧬 Mutation Report: html/index.html" -ForegroundColor Cyan
    Write-Host "   Open with: start html/index.html" -ForegroundColor Gray
    Write-Host ""
}

if ($exitCode -eq 0) {
    Write-Host "✅ All tests passed!" -ForegroundColor Green
} else {
    Write-Host "❌ Some tests failed. Please review the output above." -ForegroundColor Red
}

Write-Host ""
Write-Host "💡 Usage:" -ForegroundColor Cyan
Write-Host "   Quick tests:      .\scripts\run_all_tests.ps1 -Quick" -ForegroundColor Gray
Write-Host "   With coverage:    .\scripts\run_all_tests.ps1 -Coverage" -ForegroundColor Gray
Write-Host "   With security:    .\scripts\run_all_tests.ps1 -Security" -ForegroundColor Gray
Write-Host "   With benchmarks:  .\scripts\run_all_tests.ps1 -Benchmark" -ForegroundColor Gray
Write-Host "   Everything:       .\scripts\run_all_tests.ps1 -All" -ForegroundColor Gray

exit $exitCode
