@echo off
REM Build release + Inno Setup installer.
cd /d "%~dp0.."
powershell -NoProfile -ExecutionPolicy Bypass -File "build\build.ps1" -Installer
exit /b %ERRORLEVEL%
