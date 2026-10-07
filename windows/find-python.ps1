# Dot-sourced by install.ps1 / build.ps1. Defines Find-Python, which returns the
# full path of a real Python 3.10+ (never the Microsoft Store stub), installing
# Python 3.12 for the current user via winget if none is found.

function Test-PythonExe([string]$exe) {
    # probes write to stderr on failure; under PS 5.1 + 'Stop' that would throw
    $ErrorActionPreference = 'Continue'
    if (-not $exe -or -not (Test-Path $exe)) { return $false }
    if ($exe -like '*\WindowsApps\*') { return $false }       # Store "install me" stub
    & $exe -c "import sys; sys.exit(0 if sys.version_info >= (3, 10) else 1)" 2>$null
    return ($LASTEXITCODE -eq 0)
}

function Get-PythonCandidates {
    # probes write to stderr on failure; under PS 5.1 + 'Stop' that would throw
    $ErrorActionPreference = 'Continue'
    $c = @()
    if (Get-Command py -ErrorAction SilentlyContinue) {
        foreach ($v in '-3.13', '-3.12', '-3.11', '-3.10', '-3') {
            $p = & py $v -c "import sys; print(sys.executable)" 2>$null
            if ($LASTEXITCODE -eq 0 -and $p) { $c += $p.Trim() }
        }
    }
    foreach ($name in 'python', 'python3') {
        $cmd = Get-Command $name -ErrorAction SilentlyContinue
        if ($cmd) { $c += $cmd.Source }
    }
    foreach ($v in '313', '312', '311', '310') {
        $c += "$env:LOCALAPPDATA\Programs\Python\Python$v\python.exe"
        $c += "$env:ProgramFiles\Python$v\python.exe"
    }
    return $c
}

function Find-Python {
    # probes write to stderr on failure; under PS 5.1 + 'Stop' that would throw
    $ErrorActionPreference = 'Continue'
    foreach ($p in Get-PythonCandidates) {
        if (Test-PythonExe $p) { return $p }
    }
    Write-Host "    No Python 3.10+ found. Installing Python 3.12 (just for you, no admin)..."
    if (-not (Get-Command winget -ErrorAction SilentlyContinue)) {
        throw "winget is not available. Install Python 3.12 from https://www.python.org/downloads/ (tick 'Add python.exe to PATH') and run this again."
    }
    winget install --id Python.Python.3.12 -e --scope user --silent `
        --accept-package-agreements --accept-source-agreements | Out-Host
    foreach ($p in Get-PythonCandidates) {
        if (Test-PythonExe $p) { return $p }
    }
    throw "Python was installed but could not be found. Close this window, open a new one and run the installer again."
}
