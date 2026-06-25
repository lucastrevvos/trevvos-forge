"""Compute SHA256 checksums for release artefacts and write SHA256SUMS.txt."""
from __future__ import annotations

import hashlib
import sys
from pathlib import Path

_REPO_ROOT = Path(__file__).resolve().parents[1]
_RELEASE_DIR = _REPO_ROOT / "release"
_EXTENSIONS = (".zip", ".tar.gz", ".gz")


def _sha256(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as f:
        for chunk in iter(lambda: f.read(65536), b""):
            h.update(chunk)
    return h.hexdigest()


def main() -> None:
    if not _RELEASE_DIR.exists():
        print(f"release/ directory not found at {_RELEASE_DIR}", file=sys.stderr)
        sys.exit(1)

    artefacts = sorted(
        p for p in _RELEASE_DIR.iterdir()
        if p.is_file() and any(p.name.endswith(ext) for ext in _EXTENSIONS)
    )

    if not artefacts:
        print("No release artefacts found in release/", file=sys.stderr)
        sys.exit(1)

    lines: list[str] = []
    for path in artefacts:
        digest = _sha256(path)
        lines.append(f"{digest}  {path.name}")
        print(f"  {digest}  {path.name}")

    sums_path = _RELEASE_DIR / "SHA256SUMS.txt"
    sums_path.write_text("\n".join(lines) + "\n", encoding="utf-8")
    print(f"\nChecksums written to {sums_path}")


if __name__ == "__main__":
    main()
