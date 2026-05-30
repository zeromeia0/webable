# PyInstaller runtime hook — required for frozen multiprocessing on Windows.
import multiprocessing

multiprocessing.freeze_support()
