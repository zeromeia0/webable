# Webable — Windows_Testing

Windows desktop packaging for Webable (no Docker).

## Quick build (Windows)

```powershell
cd Windows_Testing
.\build\build-debug.bat    # console build — use first to see errors
.\build\build.bat            # release build
.\build\build-installer.bat  # release + installer
```

See **[README-WINDOWS.md](README-WINDOWS.md)** for troubleshooting frozen builds, log paths, and signing.

## Layout

```
Windows_Testing/
├── app/                  # synced from parent webable repo
├── build/                # build.ps1, build.bat, build-debug.bat, build-installer.bat
├── windows_launcher.py   # desktop entry point
├── windows/              # bootstrap, import_app
├── webable.spec          # release PyInstaller spec
├── webable-debug.spec    # console debug spec
├── installer/            # Inno Setup
└── scripts/              # sync-from-upstream.sh, verify_bundle.py
```
