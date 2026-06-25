"""PyInstaller entry point for Trevvos Forge."""
import multiprocessing

from trevvos_forge.cli import main

if __name__ == "__main__":
    # Required on Windows when using multiprocessing in a frozen app.
    multiprocessing.freeze_support()
    main()
