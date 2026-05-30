# Webable — Windows Testing / Desktop packaging

This directory is a **self-contained Windows packaging fork** of [Webable](../README.md). The parent repository is not modified; application code is copied here and refreshed via `scripts/sync-from-upstream.sh`.

**Full build and signing documentation:** [README-WINDOWS.md](README-WINDOWS.md)

## Quick start (developers on Windows)

```powershell
cd Windows_Testing
.\build\build-installer.bat
```

Deliver to users: `dist\installer\Webable-Setup-*.exe`

## Quick start (test without installer)

```powershell
.\build\build.ps1
.\dist\Webable\Webable.exe
```
