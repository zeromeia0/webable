#!/usr/bin/env python3
"""Build-time helper: create assets/webable.ico (requires Pillow)."""
from __future__ import annotations

from pathlib import Path

try:
    from PIL import Image, ImageDraw
except ImportError as exc:
    raise SystemExit("Install Pillow: pip install pillow") from exc

OUT = Path(__file__).resolve().parent / "webable.ico"
SIZE = 256


def main() -> None:
    img = Image.new("RGBA", (SIZE, SIZE), (15, 23, 42, 255))
    draw = ImageDraw.Draw(img)
    # Simple "W" mark in indigo/emerald for finance app branding.
    draw.rounded_rectangle((24, 24, SIZE - 24, SIZE - 24), radius=48, fill=(79, 70, 229, 255))
    draw.rounded_rectangle((56, 72, SIZE - 56, SIZE - 72), radius=24, fill=(16, 185, 129, 255))
    # Simple bar chart motif (no font dependency).
    draw.rectangle((96, 120, 112, 200), fill=(255, 255, 255, 230))
    draw.rectangle((120, 96, 136, 200), fill=(255, 255, 255, 200))
    draw.rectangle((144, 136, 160, 200), fill=(255, 255, 255, 230))
    sizes = [(16, 16), (32, 32), (48, 48), (64, 64), (128, 128), (256, 256)]
    img.save(OUT, format="ICO", sizes=[(s, s) for s in sizes])
    print(f"Wrote {OUT}")


if __name__ == "__main__":
    main()
