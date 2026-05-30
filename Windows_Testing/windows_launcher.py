#!/usr/bin/env python3
"""
Webable Windows desktop entry point.

Starts uvicorn on 127.0.0.1 only, opens the default browser, and shows a small
"running" window with Quit. User data lives in %LOCALAPPDATA%\\Webable.
"""

from __future__ import annotations

import logging
import os
import socket
import sys
import threading
import time
import webbrowser
from pathlib import Path

# Bootstrap before app imports so DATA_ROOT and static paths are correct.
sys.path.insert(0, str(Path(__file__).resolve().parent))

from windows.bootstrap import (  # noqa: E402
    DEFAULT_HOST,
    DEFAULT_PORT,
    apply_frozen_import_patches,
    app_url,
    configure_environment,
    is_frozen,
)

HOST = os.environ.get("WEBABLE_HOST", DEFAULT_HOST)
PORT = int(os.environ.get("WEBABLE_PORT", str(DEFAULT_PORT)))


def _setup_logging(data_dir: Path) -> None:
    log_path = data_dir / "logs" / "webable.log"
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s %(levelname)s %(name)s: %(message)s",
        handlers=[
            logging.FileHandler(log_path, encoding="utf-8"),
            logging.StreamHandler(sys.stdout) if not getattr(sys, "frozen", False) else logging.NullHandler(),
        ],
    )


def _port_available(host: str, port: int) -> bool:
    try:
        with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
            s.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
            s.bind((host, port))
        return True
    except OSError:
        return False


def _find_port(host: str, start: int) -> int:
    for p in range(start, start + 50):
        if _port_available(host, p):
            return p
    raise RuntimeError(f"No free port near {start} on {host}")


def _wait_for_server(url: str, timeout: float = 90.0) -> bool:
    import urllib.error
    import urllib.request

    deadline = time.time() + timeout
    health = url.rstrip("/") + "/health"
    while time.time() < deadline:
        try:
            with urllib.request.urlopen(health, timeout=2) as resp:
                if resp.status == 200:
                    return True
        except (urllib.error.URLError, TimeoutError, OSError):
            time.sleep(0.35)
    return False


def _run_uvicorn(port: int) -> None:
    import uvicorn

    # Import after env/bootstrap so app/db picks up WEBABLE_DATA_DIR.
    from webapp import app  # noqa: WPS433

    config = uvicorn.Config(
        app,
        host=HOST,
        port=port,
        log_level="info",
        access_log=False,
        loop="auto",
    )
    server = uvicorn.Server(config)
    server.run()


def _run_tray_ui(url: str, data_dir: Path) -> None:
    import tkinter as tk
    from tkinter import messagebox

    root = tk.Tk()
    root.title("Webable")
    root.resizable(False, False)
    try:
        icon_path = Path(__file__).resolve().parent / "assets" / "webable.ico"
        if icon_path.is_file():
            root.iconbitmap(str(icon_path))
    except Exception:
        pass

    frame = tk.Frame(root, padx=16, pady=14)
    frame.pack()

    tk.Label(frame, text="Webable is running", font=("Segoe UI", 11, "bold")).pack(anchor="w")
    tk.Label(frame, text="Your data is stored locally.", font=("Segoe UI", 9)).pack(anchor="w", pady=(4, 8))
    tk.Label(frame, text=url, font=("Segoe UI", 9), fg="#4338ca").pack(anchor="w")
    tk.Label(
        frame,
        text=str(data_dir),
        font=("Segoe UI", 8),
        fg="#64748b",
        wraplength=360,
        justify="left",
    ).pack(anchor="w", pady=(6, 12))

    def open_browser() -> None:
        webbrowser.open(url)

    def quit_app() -> None:
        if messagebox.askyesno("Quit Webable", "Stop Webable and close your local session?"):
            root.destroy()
            os._exit(0)

    btn_row = tk.Frame(frame)
    btn_row.pack(anchor="w")
    tk.Button(btn_row, text="Open in browser", command=open_browser, width=14).pack(side="left", padx=(0, 8))
    tk.Button(btn_row, text="Quit", command=quit_app, width=8).pack(side="left")

    root.protocol("WM_DELETE_WINDOW", quit_app)
    root.mainloop()


def main() -> int:
    data_dir = configure_environment(port=PORT)
    apply_frozen_import_patches()
    _setup_logging(data_dir)
    log = logging.getLogger("webable.launcher")

    port = PORT
    if not _port_available(HOST, port):
        port = _find_port(HOST, port)
        log.warning("Default port busy; using %s", port)

    url = app_url(HOST, port)
    log.info("Starting Webable on %s (frozen=%s, data=%s)", url, is_frozen(), data_dir)

    server_thread = threading.Thread(target=_run_uvicorn, args=(port,), daemon=True, name="uvicorn")
    server_thread.start()

    if not _wait_for_server(url):
        log.error("Server did not become ready in time")
        if is_frozen():
            import tkinter as tk
            from tkinter import messagebox

            root = tk.Tk()
            root.withdraw()
            messagebox.showerror(
                "Webable",
                "Webable could not start.\n\nSee log:\n" + str(data_dir / "logs" / "webable.log"),
            )
            root.destroy()
        return 1

    webbrowser.open(url)
    _run_tray_ui(url, data_dir)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
