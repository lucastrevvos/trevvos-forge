#!/usr/bin/env bash
# Build the Trevvos Forge standalone binary for Linux x64.
#
# Produces dist/trevvos/ (onedir) and packages it as a tar.gz under release/.
# Run from the repo root. Requires Python 3.11+ in PATH or an active venv.
#
# Usage:
#   chmod +x packaging/build_linux.sh
#   ./packaging/build_linux.sh

set -euo pipefail

VERSION="0.1.0-alpha.1"
APP_NAME="trevvos"
TAR_NAME="trevvos-forge-v${VERSION}-linux-x64.tar.gz"
TAR_PATH="release/${TAR_NAME}"

echo ""
echo "=== Trevvos Forge Binary Build â€” Linux x64 ==="
echo "Version : ${VERSION}"
echo "Output  : ${TAR_PATH}"
echo ""

# â”€â”€ 1. Install / refresh build deps â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€
echo "--- Installing build dependencies..."
python -m pip install -U pip --quiet
python -m pip install -e . --quiet
python -m pip install pyinstaller --quiet

# â”€â”€ 2. Clean previous outputs â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€
echo "--- Cleaning previous build artefacts..."
rm -rf build dist release
mkdir -p release

# â”€â”€ 3. Build with PyInstaller â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€
echo "--- Running PyInstaller..."
python -m PyInstaller \
  --name "$APP_NAME" \
  --onedir \
  --clean \
  --noconfirm \
  --paths "$PWD" \
  --hidden-import=trevvos_forge \
  --hidden-import=trevvos_forge.cli \
  --collect-submodules=trevvos_forge \
  --collect-data=trevvos_forge \
  --collect-all typer \
  --collect-all rich \
  --copy-metadata trevvos-forge \
  --add-data "trevvos_forge:trevvos_forge" \
  --add-data "trevvos_forge/local_api/static:trevvos_forge/local_api/static" \
  --add-data "README.md:." \
  --add-data "ALPHA.md:." \
  --add-data "docs:docs" \
  packaging/trevvos_entry.py

# â”€â”€ 4. Smoke-test the binary â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€
echo ""
echo "--- Validating binary..."
BIN="dist/${APP_NAME}/${APP_NAME}"

echo "  ${BIN} --version"
"${BIN}" --version

echo "  ${BIN} version"
"${BIN}" version

echo "  ${BIN} --help"
"${BIN}" --help > /tmp/trevvos-help.txt
head -5 /tmp/trevvos-help.txt

echo "  ${BIN} setup --help"
"${BIN}" setup --help > /tmp/trevvos-setup-help.txt
head -3 /tmp/trevvos-setup-help.txt

echo "  ${BIN} doctor --help"
"${BIN}" doctor --help > /tmp/trevvos-doctor-help.txt
head -3 /tmp/trevvos-doctor-help.txt

echo "  ${BIN} api start --help"
"${BIN}" api start --help > /tmp/trevvos-api-help.txt
head -3 /tmp/trevvos-api-help.txt

# â”€â”€ 5. Package as tar.gz â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€
echo ""
echo "--- Creating tar.gz..."
tar -czf "${TAR_PATH}" -C "dist" "${APP_NAME}"

SIZE_MB=$(du -m "${TAR_PATH}" | cut -f1)
echo ""
echo "=== Done ==="
echo "Release : ${TAR_PATH} (~${SIZE_MB} MB)"
echo ""
echo "Usage for testers (Linux):"
echo "  tar -xzf ${TAR_NAME}"
echo "  cd ${APP_NAME}"
echo "  ./${APP_NAME} setup"
echo "  ./${APP_NAME} doctor"
echo "  ./${APP_NAME} api start --open"

