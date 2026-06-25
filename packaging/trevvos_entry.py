from __future__ import annotations

import multiprocessing
import sys
from pathlib import Path


def _ensure_bundle_import_path() -> None:
    bundle_root = Path(getattr(sys, "_MEIPASS", Path(__file__).resolve().parent))

    candidates = [
        bundle_root,
        bundle_root / "_internal",
        Path(__file__).resolve().parent,
    ]

    for candidate in candidates:
        value = str(candidate)
        if value not in sys.path:
            sys.path.insert(0, value)


def main() -> None:
    multiprocessing.freeze_support()
    _ensure_bundle_import_path()

    from trevvos_forge.cli import main as cli_main

    cli_main()


if __name__ == "__main__":
    main()
