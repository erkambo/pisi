# Install PISI from this source folder (for testers / tinkerers).
# Friends who just want the app should use PISI-Setup.exe instead (see README).
#
#   - finds (or installs) Python 3.10+
#   - creates a private virtualenv in .venv and installs PyQt6 + tzdata into it
#   - turns on "start when I sign in" and adds PISI to the Start menu
#   - starts PISI
$ErrorActionPreference = 'Stop'
$Root = Split-Path -Parent $PSScriptRoot
Set-Location $Root
. "$PSScriptRoot\find-python.ps1"

try {
    Write-Host "==> Looking for Python 3.10+..."
    $py = Find-Python
    Write-Host "    using $py"

    $venv = Join-Path $Root '.venv'
    $vpy = Join-Path $venv 'Scripts\python.exe'
    if (-not (Test-Path $vpy)) {
        Write-Host "==> Creating a private environment in .venv ..."
        & $py -m venv $venv
        if ($LASTEXITCODE -ne 0) { throw "could not create the virtual environment" }
    }

    Write-Host "==> Installing PyQt6 + tzdata (first time takes a minute)..."
    & $vpy -m pip install --disable-pip-version-check -q --upgrade pip
    & $vpy -m pip install --disable-pip-version-check -q -r (Join-Path $PSScriptRoot 'requirements.txt')
    if ($LASTEXITCODE -ne 0) { throw "pip install failed (are you online?)" }
    & $vpy -c "import PyQt6.QtWidgets, zoneinfo; zoneinfo.ZoneInfo('Europe/Istanbul')"
    if ($LASTEXITCODE -ne 0) { throw "PyQt6 did not import correctly" }

    Write-Host "==> Start at sign-in + Start menu shortcut..."
    & $vpy -m companion --install

    Write-Host "==> Starting PISI..."
    $pyw = Join-Path $venv 'Scripts\pythonw.exe'
    Start-Process -FilePath $pyw -ArgumentList "`"$Root\pisi.pyw`"" -WorkingDirectory $Root

    Write-Host ""
    Write-Host "Done! The cat should appear in a few seconds." -ForegroundColor Green
    Write-Host "Its paw icon lives in the taskbar's ^ hidden-icons area - drag it onto the taskbar to keep it handy."
    Write-Host "Something off?  Run:  .venv\Scripts\python.exe -m companion --doctor"
} catch {
    Write-Host ""
    Write-Host "Install failed: $_" -ForegroundColor Red
    exit 1
}
