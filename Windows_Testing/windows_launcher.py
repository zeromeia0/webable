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
import traceback
import webbrowser
from pathlib import Path

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

# Shared state between uvicorn thread and main thread.
_SERVER_STATE: dict = {"error": None, "traceback": None, "started": False}


def _is_debug_exe() -> bool:
    if os.environ.get("WEBABLE_DEBUG", "").strip().lower() in ("1", "true", "yes", "on"):
        return True
    try:
        return "debug" in Path(sys.executable).stem.lower()
    except Exception:
        return False


def _setup_logging(data_dir: Path) -> None:
    log_path = data_dir / "logs" / "webable.log"
    handlers: list[logging.Handler] = [
        logging.FileHandler(log_path, encoding="utf-8"),
    ]
    # Console output for dev, debug exe, or when WEBABLE_DEBUG=1
    if (not is_frozen()) or _is_debug_exe():
        handlers.append(logging.StreamHandler(sys.stdout))
    logging.basicConfig(
        level=logging.DEBUG if _is_debug_exe() else logging.INFO,
        format="%(asctime)s %(levelname)s %(name)s: %(message)s",
        handlers=handlers,
        force=True,
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


def _wait_for_server(url: str, timeout: float = 120.0) -> bool:
    import urllib.error
    import urllib.request

    log = logging.getLogger("webable.launcher")
    deadline = time.time() + timeout
    health = url.rstrip("/") + "/health"
    while time.time() < deadline:
        if _SERVER_STATE.get("error") is not None:
            log.error(
                "Uvicorn thread reported error before health check passed:\n%s",
                _SERVER_STATE.get("traceback") or _SERVER_STATE.get("error"),
            )
            return False
        try:
            with urllib.request.urlopen(health, timeout=2) as resp:
                if resp.status == 200:
                    return True
        except (urllib.error.URLError, TimeoutError, OSError):
            if not _SERVER_STATE.get("started") and _SERVER_STATE.get("error"):
                return False
            time.sleep(0.35)
    return False


def _run_uvicorn(port: int) -> None:
    """
    Run uvicorn in this thread with an explicit asyncio loop.

    uvicorn.Server.run() -> asyncio.run() often fails silently in a PyInstaller
    frozen exe on Windows when run from a background thread. Using
    WindowsSelectorEventLoopPolicy + loop.run_until_complete(server.serve())
    is the reliable pattern.
    """
    log = logging.getLogger("webable.uvicorn")
    try:
        import asyncio

        if sys.platform == "win32":
            asyncio.set_event_loop_policy(asyncio.WindowsSelectorEventLoopPolicy())

        log.info("=== uvicorn thread starting on %s:%s ===", HOST, port)

        from windows.import_app import import_smoke_test, load_fastapi_app

        import_smoke_test()
        app = load_fastapi_app()

        import uvicorn

        config = uvicorn.Config(
            app,
            host=HOST,
            port=port,
            log_level="info",
            access_log=False,
            loop="asyncio",
        )
        server = uvicorn.Server(config)

        loop = asyncio.new_event_loop()
        asyncio.set_event_loop(loop)
        _SERVER_STATE["started"] = True
        log.info("event loop created; calling server.serve()")
        try:
            loop.run_until_complete(server.serve())
        finally:
            loop.close()
            log.info("uvicorn loop closed")
    except Exception as exc:
        _SERVER_STATE["error"] = exc
        _SERVER_STATE["traceback"] = traceback.format_exc()
        log.error("Uvicorn thread crashed:\n%s", _SERVER_STATE["traceback"])
        if _is_debug_exe():
            print("FATAL uvicorn thread error:", file=sys.stderr)
            print(_SERVER_STATE["traceback"], file=sys.stderr)
        raise


def _show_fatal(title: str, message: str) -> None:
    try:
        import tkinter as tk
        from tkinter import messagebox

        root = tk.Tk()
        root.withdraw()
        messagebox.showerror(title, message)
        root.destroy()
    except Exception:
        print(message, file=sys.stderr)


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
    log_path_hint = ""
    try:
        data_dir = configure_environment(port=PORT)
        apply_frozen_import_patches()
        _setup_logging(data_dir)
        log_path_hint = str(data_dir / "logs" / "webable.log")
        log = logging.getLogger("webable.launcher")

        port = PORT
        if not _port_available(HOST, port):
            port = _find_port(HOST, port)
            log.warning("Default port busy; using %s", port)

        url = app_url(HOST, port)
        log.info("Starting Webable on %s (frozen=%s, debug=%s)", url, is_frozen(), _is_debug_exe())
        log.info("Log file: %s", log_path_hint)

        server_thread = threading.Thread(
            target=_run_uvicorn,
            args=(port,),
            daemon=True,
            name="uvicorn",
        )
        server_thread.start()

        if not _wait_for_server(url):
            tb = _SERVER_STATE.get("traceback") or ""
            err = _SERVER_STATE.get("error")
            log.error("Server did not become ready in time")
            if err:
                log.error("Last uvicorn error: %s\n%s", err, tb)
            msg = "Webable could not start.\n\nSee log:\n" + log_path_hint
            if tb:
                msg += "\n\nLast error:\n" + tb[:2000]
            _show_fatal("Webable", msg)
            return 1

        webbrowser.open(url)
        _run_tray_ui(url, data_dir)
        return 0
    except Exception:
        tb = traceback.format_exc()
        logging.getLogger("webable.launcher").error("Launcher fatal error:\n%s", tb)
        if _is_debug_exe():
            print(tb, file=sys.stderr)
        _show_fatal("Webable", "Webable crashed.\n\nSee log:\n" + (log_path_hint or "webable.log"))
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
