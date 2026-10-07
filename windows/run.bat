@echo off
rem Start PISI without a console window (after install.bat has run once).
start "" "%~dp0..\.venv\Scripts\pythonw.exe" "%~dp0..\pisi.pyw" %*
