# PyInstaller runtime hook: non-GUI matplotlib backend for PDF/charts.
import os

os.environ.setdefault("MPLBACKEND", "Agg")
