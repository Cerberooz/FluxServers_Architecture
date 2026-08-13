<#
.SYNOPSIS
    One-command local start for FluxWeb.

.DESCRIPTION
    Checks Python, creates a virtualenv, installs dependencies, generates a
    .env with freshly generated secrets, applies migrations, and starts the
    development server.

    Safe to re-run: every step is skipped when it is already done.

.EXAMPLE
    .\run.ps1
    .\run.ps1 -Test          # run the test suite instead of the server
    .\run.ps1 -Lint          # run ruff + black --check
    .\run.ps1 -Fresh         # rebuild the virtualenv from scratch
    .\run.ps1 -Port 8000
#>
[CmdletBinding()]
param(
    [switch]$Test,
    [switch]$Lint,
    [switch]$Fresh,
    [int]$Port = 27003
)

$ErrorActionPreference = 'Stop'
Set-Location -Path $PSScriptRoot

$VenvDir    = Join-Path $PSScriptRoot '.venv'
$VenvPython = Join-Path $VenvDir 'Scripts\python.exe'
$EnvFile    = Join-Path $PSScriptRoot '.env'
$StampFile  = Join-Path $VenvDir '.deps-stamp'

function Write-Step  { param($m) Write-Host "`n==> $m" -ForegroundColor Cyan }
function Write-Ok    { param($m) Write-Host "    $m" -ForegroundColor Green }
function Write-Warn2 { param($m) Write-Host "    $m" -ForegroundColor Yellow }
function Write-Err   { param($m) Write-Host "    $m" -ForegroundColor Red }

# Runs a native executable and returns its exit code.
#
# Windows PowerShell 5.1 turns every stderr line into a NativeCommandError
# ErrorRecord when stderr is redirected (2>&1), which under
# $ErrorActionPreference='Stop' kills the script even when the program
# succeeded. Many tools (flask, alembic, pip) write ordinary progress output
# to stderr. So: never redirect stderr, and judge success by the exit code.
function Invoke-Native {
    param(
        [Parameter(Mandatory)][string]$Exe,
        [string[]]$Arguments = @(),
        [switch]$Quiet
    )
    $previous = $ErrorActionPreference
    $ErrorActionPreference = 'Continue'
    try {
        if ($Quiet) {
            & $Exe @Arguments | Out-Null
        } else {
            & $Exe @Arguments
        }
        return $LASTEXITCODE
    } finally {
        $ErrorActionPreference = $previous
    }
}

# --- 1. Locate a real Python -------------------------------------------
Write-Step 'Checking Python'

# The Windows Store stub in WindowsApps is not a usable interpreter; it just
# opens the Store. Skip anything living there.
$python = $null
foreach ($candidate in @('python', 'python3', 'py')) {
    $cmd = Get-Command $candidate -ErrorAction SilentlyContinue
    if (-not $cmd) { continue }
    $source = $cmd.Source
    if ($source -and $source -like '*WindowsApps*') { continue }
    try {
        # No 2>&1 here: Python 3 prints its version to stdout, and redirecting
        # would resurrect the NativeCommandError problem.
        $version = & $source --version
        if ($version -match 'Python (\d+)\.(\d+)') {
            $major = [int]$Matches[1]; $minor = [int]$Matches[2]
            if ($major -eq 3 -and $minor -ge 11) { $python = $source; break }
            Write-Warn2 "Found $version at $source (need 3.11+)"
        }
    } catch { continue }
}

if (-not $python) {
    Write-Err 'No usable Python 3.11+ found.'
    Write-Host ''
    Write-Host '    Install it with either:' -ForegroundColor Yellow
    Write-Host '      winget install Python.Python.3.12'
    Write-Host '      (or download from https://www.python.org/downloads/)'
    Write-Host ''
    Write-Host '    Important: tick "Add python.exe to PATH" in the installer,'
    Write-Host '    then open a NEW terminal and run this script again.'
    exit 1
}
Write-Ok "Using $python ($(& $python --version))"

# --- 2. Virtual environment --------------------------------------------
if ($Fresh -and (Test-Path $VenvDir)) {
    Write-Step 'Removing existing virtualenv (-Fresh)'
    Remove-Item -Recurse -Force $VenvDir
}

if (-not (Test-Path $VenvPython)) {
    Write-Step 'Creating virtualenv (.venv)'
    & $python -m venv $VenvDir
    if ($LASTEXITCODE -ne 0) { Write-Err 'Failed to create the virtualenv.'; exit 1 }
    Write-Ok 'Created .venv'
} else {
    Write-Step 'Virtualenv present'
    Write-Ok '.venv'
}

# --- 3. Dependencies ----------------------------------------------------
$reqFile  = if ($Test -or $Lint) { 'requirements-dev.txt' } else { 'requirements.txt' }
$reqHash  = (Get-FileHash -Path (Join-Path $PSScriptRoot $reqFile) -Algorithm SHA256).Hash
$stamp    = if (Test-Path $StampFile) { Get-Content $StampFile -Raw } else { '' }

if ($stamp.Trim() -ne "$reqFile`:$reqHash") {
    Write-Step "Installing dependencies from $reqFile"
    & $VenvPython -m pip install --upgrade pip --quiet
    & $VenvPython -m pip install -r (Join-Path $PSScriptRoot $reqFile) --quiet
    if ($LASTEXITCODE -ne 0) { Write-Err 'Dependency installation failed.'; exit 1 }
    Set-Content -Path $StampFile -Value "$reqFile`:$reqHash" -Encoding utf8
    Write-Ok 'Dependencies installed'
} else {
    Write-Step 'Dependencies up to date'
    Write-Ok "matches $reqFile"
}

# --- 4. .env with generated secrets ------------------------------------
if (-not (Test-Path $EnvFile)) {
    Write-Step 'Creating .env'

    $secretKey = & $VenvPython -c "import secrets; print(secrets.token_urlsafe(64))"
    $encKey    = & $VenvPython -c "from cryptography.fernet import Fernet; print(Fernet.generate_key().decode())"

    $example = Join-Path $PSScriptRoot '.env.example'
    if (Test-Path $example) {
        $content = Get-Content $example -Raw
        $content = $content -replace '(?m)^SECRET_KEY=.*$',     "SECRET_KEY=$secretKey"
        $content = $content -replace '(?m)^ENCRYPTION_KEY=.*$', "ENCRYPTION_KEY=$encKey"
        $content = $content -replace '(?m)^FLASK_ENV=.*$',      'FLASK_ENV=development'
        Set-Content -Path $EnvFile -Value $content -Encoding utf8
    } else {
        @(
            'FLASK_ENV=development',
            "SECRET_KEY=$secretKey",
            "ENCRYPTION_KEY=$encKey"
        ) | Set-Content -Path $EnvFile -Encoding utf8
    }

    Write-Ok 'Generated .env with fresh SECRET_KEY and ENCRYPTION_KEY'
    Write-Warn2 'Development mode uses a local SQLite database and logs emails to the console.'
    Write-Warn2 'Add PELICAN_* and payment keys to .env when you need those features.'
} else {
    Write-Step 'Checking .env'
    $envText = Get-Content $EnvFile -Raw
    $added   = @()

    # An .env carried over from an older version can be missing keys that the
    # config now requires. Without FLASK_ENV in particular, a local run is
    # validated as PRODUCTION and fails on things development does not need.
    if ($envText -notmatch '(?m)^\s*FLASK_ENV=') {
        $added += 'FLASK_ENV=development'
    }
    if ($envText -notmatch '(?m)^\s*SECRET_KEY=\S') {
        $added += "SECRET_KEY=$(& $VenvPython -c 'import secrets; print(secrets.token_urlsafe(64))')"
    }
    if ($envText -notmatch '(?m)^\s*ENCRYPTION_KEY=\S') {
        $added += "ENCRYPTION_KEY=$(& $VenvPython -c 'from cryptography.fernet import Fernet; print(Fernet.generate_key().decode())')"
    }
    if ($envText -notmatch '(?m)^\s*CRON_SECRET=\S') {
        $added += "CRON_SECRET=$(& $VenvPython -c 'import secrets; print(secrets.token_urlsafe(32))')"
    }

    if ($added.Count -gt 0) {
        Copy-Item $EnvFile "$EnvFile.bak" -Force
        Add-Content -Path $EnvFile -Value ''
        Add-Content -Path $EnvFile -Value '# --- added automatically by run.ps1 ---'
        foreach ($line in $added) { Add-Content -Path $EnvFile -Value $line }
        Write-Ok "Added $($added.Count) missing setting(s); previous file saved as .env.bak"
        foreach ($line in $added) { Write-Ok "  + $($line.Split('=')[0])" }
    } else {
        Write-Ok 'using existing .env'
    }
}

# --- 5. Environment for Flask ------------------------------------------
$env:FLASK_APP = 'app.py'
if (-not (Test-Path (Join-Path $PSScriptRoot 'instance'))) {
    New-Item -ItemType Directory -Path (Join-Path $PSScriptRoot 'instance') | Out-Null
}

# --- 6. Lint / Test shortcuts ------------------------------------------
if ($Lint) {
    Write-Step 'Running ruff'
    & $VenvPython -m ruff check fluxweb tests app.py
    $ruffExit = $LASTEXITCODE
    Write-Step 'Running black --check'
    & $VenvPython -m black --check fluxweb tests app.py
    $blackExit = $LASTEXITCODE
    if ($ruffExit -ne 0 -or $blackExit -ne 0) { exit 1 }
    Write-Ok 'Lint clean'
    exit 0
}

if ($Test) {
    Write-Step 'Running tests'
    & $VenvPython -m pytest
    exit $LASTEXITCODE
}

# --- 7. Database --------------------------------------------------------
Write-Step 'Preparing the database'

$migrationsDir = Join-Path $PSScriptRoot 'migrations'
$versionsDir   = Join-Path $migrationsDir 'versions'
$dbOk          = $true

if (-not (Test-Path $migrationsDir)) {
    Write-Ok 'Initialising migrations'
    if ((Invoke-Native $VenvPython @('-m', 'flask', 'db', 'init') -Quiet) -ne 0) { $dbOk = $false }
}

# Only autogenerate when there is no revision yet. Running `db migrate` on
# every start would drop an empty revision file into migrations/versions each
# time the models had not changed.
$hasRevisions = (Test-Path $versionsDir) -and
                (Get-ChildItem -Path $versionsDir -Filter '*.py' -ErrorAction SilentlyContinue |
                 Where-Object { $_.Name -ne '__init__.py' } | Measure-Object).Count -gt 0

if ($dbOk -and -not $hasRevisions) {
    Write-Ok 'Generating the initial migration'
    if ((Invoke-Native $VenvPython @('-m', 'flask', 'db', 'migrate', '-m', 'initial schema') -Quiet) -ne 0) {
        $dbOk = $false
    }
}

if ($dbOk) {
    if ((Invoke-Native $VenvPython @('-m', 'flask', 'db', 'upgrade') -Quiet) -ne 0) { $dbOk = $false }
}

if (-not $dbOk) {
    Write-Warn2 'Migrations did not complete; creating tables directly instead.'
    Write-Warn2 'This is fine for local development. Use "flask db upgrade" for production.'
    if ((Invoke-Native $VenvPython @('-m', 'flask', 'init-db')) -ne 0) {
        Write-Err 'Could not prepare the database. Run this to see the full error:'
        Write-Host '    .venv\Scripts\python.exe -m flask init-db' -ForegroundColor Yellow
        exit 1
    }
}
Write-Ok 'Database ready'

# --- 8. Run -------------------------------------------------------------
Write-Step "Starting FluxWeb on http://127.0.0.1:$Port"
Write-Host '    Press Ctrl+C to stop.' -ForegroundColor DarkGray
Write-Host ''

$env:PORT = "$Port"
& $VenvPython -m flask run --port $Port --host 127.0.0.1
