<#
.SYNOPSIS
    LAZARUS CORE - script de construction complet (Windows).
.DESCRIPTION
    Installe les dependances, construit l'interface, execute les tests, gele le moteur Python en
    executable autonome (PyInstaller) puis produit l'installateur NSIS.
.PARAMETER SkipTests
    Ne pas executer les tests automatises.
.PARAMETER SkipEngine
    Ne pas geler le moteur Python (l'application installee exigera alors Python 3.8+).
.PARAMETER DevMode
    Installer seulement les dependances et construire l'interface (pas d'installateur).
.EXAMPLE
    .\scripts\build-all.ps1
    .\scripts\build-all.ps1 -DevMode
#>
param(
    [switch]$SkipTests,
    [switch]$SkipEngine,
    [switch]$DevMode
)

$ErrorActionPreference = 'Stop'
$root = Split-Path $MyInvocation.MyCommand.Path -Parent | Split-Path -Parent

function Section([string]$msg) { Write-Host "`n--- $msg ---" -ForegroundColor Cyan }
function Ok([string]$msg)      { Write-Host "  OK : $msg" -ForegroundColor Green }
function Fail([string]$msg)    { Write-Host "  ECHEC : $msg" -ForegroundColor Red; exit 1 }
function Run([string]$dir, [string]$cmd) {
    Push-Location $dir
    try { Invoke-Expression $cmd; if ($LASTEXITCODE -ne 0) { Fail "$cmd (code $LASTEXITCODE)" } }
    finally { Pop-Location }
}

Section "Prerequis"
if (-not (Get-Command node -ErrorAction SilentlyContinue))   { Fail "Node.js introuvable (https://nodejs.org)" }
if (-not (Get-Command python -ErrorAction SilentlyContinue)) { Fail "Python 3.8+ introuvable (https://python.org)" }
Ok "Node $(node --version) / Python $(python --version)"

Section "Dependances"
Run "$root\app" "npm install --no-audit --no-fund"
Run "$root\app\renderer" "npm install --no-audit --no-fund"
Ok "Dependances installees"

Section "Interface"
Run "$root\app\renderer" "npm run build"
Ok "Interface construite"

if (-not $SkipTests) {
    Section "Tests"
    Run $root "python -m unittest discover -s tests/engine -p 'test_*.py'"
    Run $root "node --test tests/bridge/bridge.test.js"
    Ok "Tous les tests passent"
}

if ($DevMode) { Write-Host "`nMode developpement : termine." -ForegroundColor Green; exit 0 }

if (-not $SkipEngine) {
    Section "Moteur autonome (PyInstaller)"
    Run $root "node scripts/build-engine.js"
    Ok "Moteur gele dans app/engine-bin"
}

Section "Installateur"
$env:CSC_IDENTITY_AUTO_DISCOVERY = 'false'
Run "$root\app" "npx electron-builder --win nsis --publish never"
Ok "Installateur dans app/dist-build"
