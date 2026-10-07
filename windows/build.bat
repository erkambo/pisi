@echo off
rem Build PISI.exe (+ zip, + installer if Inno Setup 6 is installed).
powershell -NoProfile -ExecutionPolicy Bypass -File "%~dp0build.ps1" %*
echo.
pause
