# Build PISI for Windows:  dist\PISI\PISI.exe, dist\PISI-<ver>-windows.zip and,
# if Inno Setup 6 is installed, dist\PISI-Setup-<ver>.exe (what to give friends).
#
#   windows\build.bat              full build (runs the tests first)
#   windows\build.bat -SkipTests
param([switch]$SkipTests)
$ErrorActionPreference = 'Stop'
$Root = Split-Path -Parent $PSScriptRoot
Set-Location $Root
. "$PSScriptRoot\find-python.ps1"

$py = Find-Python
$venv = Join-Path $Root '.venv-build'
$vpy = Join-Path $venv 'Scripts\python.exe'
if (-not (Test-Path $vpy)) {
    Write-Host "==> Creating build environment (.venv-build)..."
    & $py -m venv $venv
}
Write-Host "==> Installing build tools..."
& $vpy -m pip install --disable-pip-version-check -q --upgrade pip
& $vpy -m pip install --disable-pip-version-check -q -r (Join-Path $PSScriptRoot 'requirements-build.txt')
if ($LASTEXITCODE -ne 0) { throw "pip install failed" }

$ver = (& $vpy -c "import companion; print(companion.__version__)").Trim()
Write-Host "==> PISI $ver"

if (-not $SkipTests) {
    Write-Host "==> Running tests..."
    $env:QT_QPA_PLATFORM = 'offscreen'
    & $vpy -m pytest -q
    if ($LASTEXITCODE -ne 0) { throw "tests failed - not building" }
    Remove-Item Env:QT_QPA_PLATFORM
}

# Windows file-properties metadata for PISI.exe
$v4 = ($ver.Split('.') + @('0', '0', '0'))[0..3] -join ', '
@"
VSVersionInfo(
  ffi=FixedFileInfo(filevers=($v4), prodvers=($v4)),
  kids=[StringFileInfo([StringTable('040904B0', [
    StringStruct('CompanyName', 'Erkam Boyacioglu'),
    StringStruct('FileDescription', 'PISI - desktop habit companion'),
    StringStruct('FileVersion', '$ver'),
    StringStruct('ProductName', 'PISI'),
    StringStruct('ProductVersion', '$ver'),
    StringStruct('OriginalFilename', 'PISI.exe')])]),
    VarFileInfo([VarStruct('Translation', [1033, 1200])])]
)
"@ | Set-Content -Encoding UTF8 (Join-Path $PSScriptRoot 'version_info.txt')

Write-Host "==> Freezing with PyInstaller..."
& $vpy -m PyInstaller --noconfirm --clean --distpath (Join-Path $Root 'dist') `
    --workpath (Join-Path $Root 'build') (Join-Path $PSScriptRoot 'pisi.spec')
if ($LASTEXITCODE -ne 0) { throw "PyInstaller failed" }
$exe = Join-Path $Root 'dist\PISI\PISI.exe'

Write-Host "==> Smoke test: PISI.exe --doctor ..."
$tmpData = Join-Path $env:TEMP "pisi-smoke-$PID"
$env:XDG_DATA_HOME = $tmpData          # don't touch your real PISI data
$p = Start-Process -FilePath $exe -ArgumentList '--doctor', '--quiet' -Wait -PassThru
Remove-Item Env:XDG_DATA_HOME
$report = Join-Path $tmpData 'desktop-companion\doctor.txt'
if (Test-Path $report) { Get-Content $report | Write-Host } else { throw "doctor produced no report" }
if ($p.ExitCode -ne 0) { throw "PISI.exe --doctor reported a failure (exit $($p.ExitCode))" }
Remove-Item -Recurse -Force $tmpData -ErrorAction SilentlyContinue

Write-Host "==> Zipping..."
$zip = Join-Path $Root "dist\PISI-$ver-windows.zip"
if (Test-Path $zip) { Remove-Item $zip }
Compress-Archive -Path (Join-Path $Root 'dist\PISI') -DestinationPath $zip

$iscc = @("${env:ProgramFiles(x86)}\Inno Setup 6\ISCC.exe",
          "$env:ProgramFiles\Inno Setup 6\ISCC.exe",
          "$env:LOCALAPPDATA\Programs\Inno Setup 6\ISCC.exe") |
        Where-Object { Test-Path $_ } | Select-Object -First 1
if ($iscc) {
    Write-Host "==> Building installer with Inno Setup..."
    & $iscc /Q "/DAppVersion=$ver" (Join-Path $PSScriptRoot 'installer.iss')
    if ($LASTEXITCODE -ne 0) { throw "Inno Setup failed" }
} else {
    Write-Host "    (Inno Setup 6 not found - skipping PISI-Setup.exe; get it from https://jrsoftware.org/isdl.php)"
}

Write-Host ""
Write-Host "Built:" -ForegroundColor Green
Get-ChildItem (Join-Path $Root 'dist') -File | ForEach-Object { Write-Host "   $($_.FullName)" }
