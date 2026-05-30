@echo off
REM Webable Windows build wrapper.
cd /d "%~dp0.."
powershell -NoProfile -ExecutionPolicy Bypass -File "build\build.ps1" %*
exit /b %ERRORLEVEL%
