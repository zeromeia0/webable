#!/usr/bin/env python3
"""Audit frontend asset parity and template references (source vs Windows mirror)."""

from __future__ import annotations

import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
APP = ROOT / "app"
WIN = ROOT / "Windows_Testing" / "app"
STATIC_REF = re.compile(r"""['"]?/static/([^"'>\s]+)['"]?""")


def list_files(base: Path, sub: str) -> set[str]:
    d = base / sub
    if not d.is_dir():
        return set()
    return {str(p.relative_to(d)).replace("\\", "/") for p in d.rglob("*") if p.is_file()}


def template_static_refs(templates: Path) -> set[str]:
    refs: set[str] = set()
    for tpl in templates.rglob("*.html"):
        text = tpl.read_text(encoding="utf-8", errors="replace")
        refs.update(STATIC_REF.findall(text))
    return refs


def compare_trees() -> list[str]:
    issues: list[str] = []
    for sub in ("static", "templates"):
        src = list_files(APP, sub)
        win = list_files(WIN, sub)
        only_src = sorted(src - win)
        only_win = sorted(win - src)
        if only_src:
            issues.append(f"Only in source app/{sub}: {only_src}")
        if only_win:
            issues.append(f"Only in Windows_Testing/app/{sub}: {only_win}")
    return issues


def missing_asset_refs() -> list[str]:
    issues: list[str] = []
    static_files = list_files(APP, "static")
    refs = template_static_refs(APP / "templates")
    for ref in sorted(refs):
        if ref not in static_files:
            issues.append(f"Template references missing static asset: {ref}")
    return issues


def topbar_currency_coverage() -> list[str]:
    issues: list[str] = []
    templates_dir = APP / "templates"
    for tpl in templates_dir.rglob("*.html"):
        text = tpl.read_text(encoding="utf-8", errors="replace")
        if "partials/app_topbar.html" in text and "webable-currency.js" not in text:
            rel = tpl.relative_to(templates_dir)
            issues.append(f"{rel} includes topbar but not webable-currency.js")
    return issues


def main() -> int:
    issues: list[str] = []
    issues.extend(compare_trees())
    issues.extend(missing_asset_refs())
    issues.extend(topbar_currency_coverage())

    print("== Webable parity audit ==")
    print(f"Source app: {APP}")
    print(f"Windows mirror: {WIN}")
    print(f"Static files: {len(list_files(APP, 'static'))}")
    print(f"Templates: {len(list_files(APP, 'templates'))}")
    print(f"Template /static references: {len(template_static_refs(APP / 'templates'))}")

    if issues:
        print("\nISSUES:")
        for item in issues:
            print(f"  - {item}")
        return 1

    print("\nNo parity issues detected.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
