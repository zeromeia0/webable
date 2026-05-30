# Webable — Windows desktop build

This folder (`Windows_Testing`) is a **fork of the Webable app** packaged for Windows end users. It does not modify the parent repository; sync app code with `scripts/sync-from-upstream.sh` when the main project changes.

## Packaging choice (evaluation)

| Format | Verdict |
|--------|---------|
| **Inno Setup installer (.exe)** | **Recommended** for non-technical users: Start Menu shortcut, uninstaller, per-user install (no admin), familiar flow. |
| **Portable folder / .zip** | Good for IT/testing; users must not delete `_internal` and may lack uninstall metadata. |
| **Single-file PyInstaller (.exe)** | Not recommended: slow startup, large file, more antivirus false positives. |
| **MSIX** | Possible later for Store-style trust; requires signing pipeline and more packaging work. |
| **Electron/Tauri wrapper** | Unnecessary: the app is already a local web UI; bundling Python + uvicorn is simpler. |

**Ship:** `dist/installer/Webable-Setup-x.y.z.exe` (installer) and optionally `dist/Webable-x.y.z-portable-win64.zip`.

## What the Windows build does

- Starts **uvicorn** bound to **`127.0.0.1` only** (default port `17890`).
- Opens the **default browser** to `http://127.0.0.1:17890/`.
- Stores data in **`%LOCALAPPDATA%\Webable`** (SQLite, uploads, logs).
- Shows a small **“Webable is running”** window with **Quit** (no Docker/Git/terminal).
- **AI (Ollama) is disabled** by default in the desktop build.
- **No admin rights** required for install (`PrivilegesRequired=lowest` in Inno Setup).

## Prerequisites (build machine)

Build on **Windows 10/11 x64** (cross-compile from Linux is possible but not documented here).

1. **Python 3.12** (64-bit) — https://www.python.org/downloads/  
   - Check “Add python.exe to PATH”.
2. **Inno Setup 6** (for installer only) — https://jrsoftware.org/isinfo.php  
3. ~2 GB free disk for venv + `dist/`.

## Exact build steps

### 1. Open PowerShell in this folder

```powershell
cd path\to\webable\Windows_Testing
```

### 2. (Optional) Refresh app source from parent repo

On Linux/macOS (or Git Bash on Windows):

```bash
bash scripts/sync-from-upstream.sh
```

### 3. Build application bundle

```powershell
Set-ExecutionPolicy -Scope Process Bypass
.\build\build.ps1
```

Output:

- `dist\Webable\Webable.exe` — run directly (portable onedir layout)
- `dist\Webable-x.y.z-portable-win64.zip` — zipped portable build

### 4. Build installer (recommended)

```powershell
.\build\build.ps1 -Installer
```

Or double-click `build\build-installer.bat`.

Output:

- `dist\installer\Webable-Setup-x.y.z.exe`

### 5. Test on a clean Windows VM

1. Run the installer (no admin prompt expected).
2. Launch **Webable** from Start Menu.
3. Confirm browser opens and you can register/login.
4. Confirm `%LOCALAPPDATA%\Webable\webable_app.db` exists after use.
5. Uninstall from **Settings → Apps**; confirm `%LOCALAPPDATA%\Webable` **remains** (user data preserved by design).

### Dev run without PyInstaller

```powershell
.\build\build.ps1 -DevRun
```

## Code signing (reduce SmartScreen / Defender warnings)

Unsigned Windows apps often show **“Windows protected your PC”** (SmartScreen). Signing does not guarantee zero warnings but is the standard fix.

### What you need

1. **Authenticode code signing certificate**  
   - From a public CA (DigiCert, Sectigo, SSL.com, etc.) — **EV** certs build reputation faster.  
   - Or self-signed (only for internal/testing; SmartScreen will still warn).

2. **Windows SDK** or **SignTool** (`signtool.exe`) from Visual Studio Build Tools.

### Sign the main executable (after PyInstaller)

```powershell
$version = (Get-Content VERSION -TotalCount 1).Trim()
signtool sign /fd SHA256 /tr http://timestamp.digicert.com /td SHA256 /a `
  "dist\Webable\Webable.exe"
```

### Sign the installer (after Inno Setup)

```powershell
signtool sign /fd SHA256 /tr http://timestamp.digicert.com /td SHA256 /a `
  "dist\installer\Webable-Setup-$version.exe"
```

### Optional: sign all DLLs/EXEs in the bundle

Some enterprises require every PE file signed:

```powershell
Get-ChildItem -Path dist\Webable -Recurse -Include *.exe,*.dll | ForEach-Object {
  signtool sign /fd SHA256 /tr http://timestamp.digicert.com /td SHA256 /a $_.FullName
}
```

### SmartScreen reputation

- New certificates need **reputation** (downloads over time) unless using **EV** signing.
- Host the installer on a **HTTPS** site with consistent publisher name matching the cert.
- Avoid: downloading extra runtimes at install time, bundling unknown DLLs, onefile packers, requiring admin without reason.

### What we intentionally avoid

- No Docker, Git, or Ollama downloads during install.
- No listening on `0.0.0.0` / public interfaces.
- No elevated install by default.
- No deletion of user financial data on uninstall.

## File layout (this repo)

```
Windows_Testing/
├── app/                    # synced from parent Webable
├── webapp.py
├── windows_launcher.py     # desktop entry point
├── windows/bootstrap.py    # %LOCALAPPDATA% paths, frozen mode
├── webable.spec            # PyInstaller
├── requirements-windows.txt
├── assets/
│   ├── webable.ico         # generated at build
│   ├── generate_icon.py
│   └── version_info.txt    # PE version metadata
├── build/
│   ├── build.ps1
│   ├── build.bat
│   └── build-installer.bat
├── installer/
│   ├── WebableSetup.iss    # Inno Setup
│   └── welcome.txt
├── scripts/sync-from-upstream.sh
└── README-WINDOWS.md
```

## Troubleshooting builds

| Issue | Fix |
|-------|-----|
| `PyInstaller` missing | `pip install -r requirements-windows.txt` inside `.venv-win` |
| `ISCC.exe` not found | Install Inno Setup 6; reopen PowerShell |
| App window then error | Read `%LOCALAPPDATA%\Webable\logs\webable.log` |
| Port in use | Launcher picks next free port (17890–17899) |
| Matplotlib PDF/charts fail at runtime | Rebuild; hiddenimports in `webable.spec` include `matplotlib.backends.backend_agg` |

## Syncing from the main project

When the parent `webable` repo is updated:

```bash
bash scripts/sync-from-upstream.sh
```

Then rebuild on Windows. Packaging scripts and `windows_launcher.py` stay in `Windows_Testing` only.
