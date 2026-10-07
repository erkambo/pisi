@echo off
rem Remove PISI's start-at-sign-in entry and Start menu shortcut (and stop it).
rem   uninstall.bat          keeps your habits/data in %APPDATA%\desktop-companion
rem   uninstall.bat --purge  also deletes that data
set "ROOT=%~dp0.."
set "PY=%ROOT%\.venv\Scripts\python.exe"
if not exist "%PY%" (
  echo PISI's .venv was not found - nothing to uninstall here.
  pause
  exit /b 1
)
pushd "%ROOT%"
"%PY%" -m companion --uninstall %1
popd
echo You can now delete this folder (and .venv inside it) whenever you like.
pause
