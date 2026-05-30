# Webable — Windows desktop build

This folder packages Webable for Windows without Docker. **All build scripts live in `build/`.**

## Why `Webable.exe` failed but `python windows_launcher.py` worked

The frozen build ran uvicorn in a **background thread** using `server.run()` → `asyncio.run()`. On **Windows + PyInstaller**, that pattern often **exits silently** in non-main threads (no port bound, log only shows *"Server did not become ready in time"*).

**Fix applied:** `windows_launcher.py` now uses:

- `asyncio.WindowsSelectorEventLoopPolicy()` on Windows  
- Explicit `loop.run_until_complete(server.serve())` in the uvicorn thread  
- Full **traceback logging** to `%LOCALAPPDATA%\Webable\logs\webable.log`  
- Step-by-step **import smoke tests** in `windows/import_app.py`

## Build commands (Windows PowerShell)

```powershell
cd Windows_Testing
Set-ExecutionPolicy -Scope Process Bypass

# 1) DEBUG — console window + tracebacks (run this first to verify fix)
.\build\build-debug.bat
dist\Webable-Debug\Webable-Debug.exe

# 2) Release (no console)
.\build\build.bat

# 3) Release + Inno Setup installer
.\build\build-installer.bat
```

### Without batch files (same commands)

```powershell
.\build\build.ps1 -Debug
.\build\build.ps1
.\build\build.ps1 -Installer
```

### Manual PyInstaller only

```powershell
python -m venv .venv-win
.\.venv-win\Scripts\pip install -r requirements-windows.txt
.\.venv-win\Scripts\python assets\generate_icon.py
.\.venv-win\Scripts\python -m PyInstaller --noconfirm --clean webable-debug.spec
```

## Verify bundled resources

After build:

```powershell
.\.venv-win\Scripts\python scripts\verify_bundle.py
```

Checks `app/templates`, `app/static`, `VERSION` inside `dist/Webable` or `dist/Webable-Debug`.

Also see log lines from `verify_bundle_resources()` in `webable.log`:

- `bundle resource app/templates: OK`
- `bundle resource app/static: OK`

## Log location

```
%LOCALAPPDATA%\Webable\logs\webable.log
```

Debug build also prints to the **console window**.

## Sync app code from parent repo

```bash
bash scripts/sync-from-upstream.sh
```

Then rebuild on Windows.

## Spec files

| File | Output | Console |
|------|--------|---------|
| `webable-debug.spec` | `dist/Webable-Debug/Webable-Debug.exe` | **Yes** |
| `webable.spec` | `dist/Webable/Webable.exe` | No |

Removed invalid hidden import: `sqlalchemy.sql.defaultcomparator` (SQLAlchemy 2.x).

Added: `collect_submodules('app.services')`, uvicorn/starlette/anyio hooks, `hook-freeze.py`.

## Code signing

Sign after build to reduce SmartScreen warnings:

```powershell
signtool sign /fd SHA256 /tr http://timestamp.digicert.com /td SHA256 /a dist\Webable\Webable.exe
signtool sign /fd SHA256 /tr http://timestamp.digicert.com /td SHA256 /a dist\installer\Webable-Setup-1.0.0.exe
```

Requires an Authenticode certificate from a public CA (EV preferred for new publishers).
