<#
.SYNOPSIS
    LAZARUS CORE – Complete Build Script
.DESCRIPTION
    Builds native C++ module, React renderer, and Electron app.
    Also installs Python AI dependencies if requested.
.PARAMETER Platform
    Target platform: win | mac | all
.PARAMETER NoBuildNative
    Skip the C++ native module compilation step.
.PARAMETER NoBuildAI
    Skip Python AI dependency installation.
.PARAMETER DevMode
    Only install dependencies (skip electron-builder packaging).
.PARAMETER Tests
    Build and run C++ unit tests after native build.
.EXAMPLE
    .\build-all.ps1 -Platform win
    .\build-all.ps1 -Platform win -DevMode
    .\build-all.ps1 -Platform all -Tests
#>
param(
    [ValidateSet('win','mac','all')]
    [string]$Platform = 'win',
    [switch]$NoBuildNative,
    [switch]$NoBuildAI,
    [switch]$DevMode,
    [switch]$Tests
)

$ErrorActionPreference = 'Stop'
$root = Split-Path $MyInvocation.MyCommand.Path -Parent | Split-Path -Parent

function Section([string]$msg) {
    Write-Host "`n---[ $msg ]---" -ForegroundColor Cyan
}

function Ok([string]$msg)   { Write-Host "  OK: $msg"      -ForegroundColor Green }
function Warn([string]$msg) { Write-Host "  WARN: $msg"    -ForegroundColor Yellow }
function Fail([string]$msg) { Write-Host "  FAIL: $msg"    -ForegroundColor Red; exit 1 }

Write-Host "`n╔══════════════════════════════╗" -ForegroundColor Cyan
Write-Host "║   LAZARUS CORE – BUILD v1.0  ║" -ForegroundColor Cyan
Write-Host "╚══════════════════════════════╝" -ForegroundColor Cyan
Write-Host "  Platform : $Platform"
Write-Host "  DevMode  : $DevMode"
Write-Host "  Tests    : $Tests"
Write-Host ""

# ─── Prerequisite checks ─────────────────────────────────────────
Section "Checking prerequisites"

$node = Get-Command node -ErrorAction SilentlyContinue
if (-not $node) { Fail "Node.js not found — install from https://nodejs.org" }
Ok "Node.js $(node --version)"

$npm = Get-Command npm -ErrorAction SilentlyContinue
if (-not $npm) { Fail "npm not found" }
Ok "npm $(npm --version)"

if (-not $NoBuildNative) {
    $gyp = Get-Command node-gyp -ErrorAction SilentlyContinue
    if (-not $gyp) {
        Warn "node-gyp not found, installing globally..."
        npm install -g node-gyp
    }
    Ok "node-gyp available"
}

if (-not $NoBuildAI) {
    $py = Get-Command python -ErrorAction SilentlyContinue
    if (-not $py) { $py = Get-Command python3 -ErrorAction SilentlyContinue }
    if (-not $py) { Warn "Python not found — AI module will be unavailable" }
    else { Ok "Python $($py.Version) at $($py.Source)" }
}

# ─── 1. Install app dependencies ────────────────────────────────
Section "Installing app dependencies"
Set-Location "$root\app"
npm install --legacy-peer-deps
if ($LASTEXITCODE -ne 0) { Fail "npm install failed in app/" }
Ok "App dependencies installed"

# ─── 2. Install renderer dependencies ───────────────────────────
Section "Installing renderer dependencies"
Set-Location "$root\app\renderer"
npm install --legacy-peer-deps
if ($LASTEXITCODE -ne 0) { Fail "npm install failed in app/renderer/" }
Ok "Renderer dependencies installed"

# ─── 3. Build native C++ module ─────────────────────────────────
if (-not $NoBuildNative) {
    Section "Building C++ native module"
    Set-Location "$root\core"

    node-gyp rebuild --verbose 2>&1 | Tee-Object -Variable nativeLog
    $nativeOk = $LASTEXITCODE -eq 0

    if ($nativeOk) {
        $built = "$root\core\build\Release\lazarus_core.node"
        if (Test-Path $built) {
            Copy-Item $built "$root\app\native\lazarus_core.node" -Force
            Ok "Native module built and copied → app/native/lazarus_core.node"
        } else {
            Warn "Build succeeded but .node file not found at expected location"
        }
    } else {
        Warn "Native module build failed — app will run in simulation mode"
        Write-Host "  Build log:" -ForegroundColor Yellow
        $nativeLog | Select-Object -Last 20 | ForEach-Object { Write-Host "    $_" -ForegroundColor DarkYellow }
    }

    # Optionally run C++ tests
    if ($Tests -and $nativeOk) {
        Section "Running C++ unit tests"
        Set-Location "$root\core"
        cmake -B build_tests -DBUILD_TESTS=ON -DCMAKE_BUILD_TYPE=Release .
        cmake --build build_tests --target all -j 4
        ctest --test-dir build_tests --output-on-failure
        if ($LASTEXITCODE -eq 0) { Ok "All C++ tests passed" }
        else { Warn "Some C++ tests failed" }
    }
}

# ─── 4. Install Python AI dependencies ──────────────────────────
if (-not $NoBuildAI) {
    $pyBin = if (Get-Command python -ErrorAction SilentlyContinue) { 'python' } else { 'python3' }
    if (Get-Command $pyBin -ErrorAction SilentlyContinue) {
        Section "Installing Python AI dependencies"
        Set-Location "$root\ai"
        & $pyBin -m pip install -r requirements.txt --quiet
        if ($LASTEXITCODE -eq 0) { Ok "AI dependencies installed" }
        else { Warn "AI dependency installation failed — AI features will be unavailable" }
    }
}

# ─── 5. Build React renderer ────────────────────────────────────
Section "Building React renderer"
Set-Location "$root\app\renderer"
npm run build
if ($LASTEXITCODE -ne 0) { Fail "React renderer build failed" }
Ok "React renderer built → app/renderer/dist/"

# ─── 6. Package Electron app ────────────────────────────────────
if (-not $DevMode) {
    Section "Packaging Electron app for '$Platform'"
    Set-Location "$root\app"

    switch ($Platform) {
        'win' {
            npm run build:win
            if ($LASTEXITCODE -ne 0) { Fail "Electron Windows build failed" }
            Ok "Windows installer built → app/dist/"
        }
        'mac' {
            npm run build:mac
            if ($LASTEXITCODE -ne 0) { Fail "Electron macOS build failed" }
            Ok "macOS DMG built → app/dist/"
        }
        'all' {
            npm run build
            if ($LASTEXITCODE -ne 0) { Fail "Electron full build failed" }
            Ok "All platform builds complete → app/dist/"
        }
    }
} else {
    Ok "DevMode: skipped Electron packaging"
}

# ─── Summary ─────────────────────────────────────────────────────
Set-Location $root
Write-Host "`n╔══════════════════════════════╗" -ForegroundColor Green
Write-Host "║      BUILD COMPLETE ✓        ║" -ForegroundColor Green
Write-Host "╚══════════════════════════════╝" -ForegroundColor Green
Write-Host ""
if (-not $DevMode) {
    Write-Host "  Installer location: $root\app\dist\" -ForegroundColor White
}
Write-Host "  To start in dev mode: cd app && npm run dev" -ForegroundColor White
Write-Host ""
