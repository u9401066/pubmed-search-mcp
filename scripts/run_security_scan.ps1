#!/usr/bin/env pwsh
# Security Scanning Script
# Runs multiple security tools to identify vulnerabilities

Write-Host "🔒 Running Security Scans..." -ForegroundColor Cyan
Write-Host ""

# Check if UV is available
if (-not (Get-Command uv -ErrorAction SilentlyContinue)) {
    Write-Host "❌ Error: UV not found. Please install UV first." -ForegroundColor Red
    exit 1
}

$exitCode = 0

# ============================================================
# 1. Bandit - Security Issues in Code
# ============================================================
Write-Host "📋 1/3 Running Bandit (code security scan)..." -ForegroundColor Yellow

try {
    uv run bandit -r src/ -c .bandit -f json -o bandit-report.json
    if ($LASTEXITCODE -eq 0) {
        Write-Host "  ✅ Bandit: No critical security issues found" -ForegroundColor Green
    } else {
        Write-Host "  ⚠️  Bandit: Found security issues (see bandit-report.json)" -ForegroundColor Yellow
        $exitCode = 1
    }
} catch {
    Write-Host "  ❌ Bandit scan failed: $_" -ForegroundColor Red
    $exitCode = 1
}

Write-Host ""

# ============================================================
# 2. Safety - Vulnerable Dependencies
# ============================================================
Write-Host "📦 2/3 Running Safety (dependency vulnerability scan)..." -ForegroundColor Yellow

try {
    # Generate requirements from UV
    uv pip compile pyproject.toml -o requirements-check.txt 2>$null
    
    # Run safety check
    uv run safety check --file=requirements-check.txt --json --output safety-report.json
    
    if ($LASTEXITCODE -eq 0) {
        Write-Host "  ✅ Safety: No vulnerable dependencies found" -ForegroundColor Green
    } else {
        Write-Host "  ⚠️  Safety: Found vulnerable dependencies (see safety-report.json)" -ForegroundColor Yellow
        $exitCode = 1
    }
    
    # Clean up temporary file
    Remove-Item requirements-check.txt -ErrorAction SilentlyContinue
} catch {
    Write-Host "  ❌ Safety check failed: $_" -ForegroundColor Red
    $exitCode = 1
}

Write-Host ""

# ============================================================
# 3. Custom Security Checks
# ============================================================
Write-Host "🔍 3/3 Running custom security checks..." -ForegroundColor Yellow

# Check for hardcoded secrets
Write-Host "  Checking for hardcoded secrets..." -ForegroundColor Gray

$secretPatterns = @(
    'password\s*=\s*["\'].*["\']',
    'api[_-]?key\s*=\s*["\'].*["\']',
    'secret\s*=\s*["\'].*["\']',
    'token\s*=\s*["\'].*["\']'
)

$foundSecrets = $false
foreach ($pattern in $secretPatterns) {
    $matches = Select-String -Path "src/**/*.py" -Pattern $pattern -ErrorAction SilentlyContinue
    if ($matches) {
        Write-Host "  ⚠️  Found potential hardcoded secret: $($matches.Pattern)" -ForegroundColor Yellow
        $foundSecrets = $true
    }
}

if (-not $foundSecrets) {
    Write-Host "  ✅ No hardcoded secrets found" -ForegroundColor Green
} else {
    $exitCode = 1
}

# Check for dangerous functions
Write-Host "  Checking for dangerous function calls..." -ForegroundColor Gray

$dangerousFunctions = @(
    'eval\(',
    'exec\(',
    'compile\(',
    '__import__\('
)

$foundDangerous = $false
foreach ($func in $dangerousFunctions) {
    $matches = Select-String -Path "src/**/*.py" -Pattern $func -ErrorAction SilentlyContinue
    if ($matches) {
        Write-Host "  ⚠️  Found dangerous function: $func" -ForegroundColor Yellow
        $foundDangerous = $true
    }
}

if (-not $foundDangerous) {
    Write-Host "  ✅ No dangerous function calls found" -ForegroundColor Green
} else {
    $exitCode = 1
}

Write-Host ""

# ============================================================
# Summary
# ============================================================
Write-Host "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━" -ForegroundColor Cyan
Write-Host "Security Scan Summary" -ForegroundColor Cyan
Write-Host "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━" -ForegroundColor Cyan

if ($exitCode -eq 0) {
    Write-Host "✅ All security checks passed!" -ForegroundColor Green
} else {
    Write-Host "⚠️  Some security issues found. Please review the reports." -ForegroundColor Yellow
}

Write-Host ""
Write-Host "Reports generated:" -ForegroundColor Cyan
Write-Host "  - bandit-report.json" -ForegroundColor Gray
Write-Host "  - safety-report.json" -ForegroundColor Gray

exit $exitCode
