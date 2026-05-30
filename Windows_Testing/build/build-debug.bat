@echo off
REM Build console debug executable (shows uvicorn import/startup errors).
cd /d "%~dp0.."
powershell -NoProfile -ExecutionPolicy Bypass -File "build\build.ps1" -Debug
exit /b %ERRORLEVEL%
