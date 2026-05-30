#!/usr/bin/env python3
"""Post-build check: bundled templates/static exist under dist/."""
from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent


def check_tree(base: Path, label: str) -> bool:
    ok = True
    required = [
        "app/templates/home.html",
        "app/static/js/webable-currency.js",
        "app/static/css/webable-fab.css",
        "VERSION",
    ]
    print(f"==> verify {label}: {base}")
    if not base.is_dir():
        print(f"MISSING directory: {base}")
        return False
    internal = base / "_internal"
    search_roots = [internal, base] if internal.is_dir() else [base]
    for rel in required:
        found = any((r / rel).is_file() for r in search_roots)
        status = "OK" if found else "MISSING"
        print(f"  {rel}: {status}")
        ok = ok and found
    return ok


def main() -> int:
    release = ROOT / "dist" / "Webable"
    debug = ROOT / "dist" / "Webable-Debug"
    ok = True
    if release.is_dir():
        ok = check_tree(release, "Webable") and ok
    if debug.is_dir():
        ok = check_tree(debug, "Webable-Debug") and ok
    if not release.is_dir() and not debug.is_dir():
        print("No dist/Webable or dist/Webable-Debug folder found. Run build first.")
        return 1
    if ok:
        print("Bundle verification passed.")
        return 0
    print("Bundle verification FAILED — check webable.spec datas entries.")
    return 1


if __name__ == "__main__":
    raise SystemExit(main())
