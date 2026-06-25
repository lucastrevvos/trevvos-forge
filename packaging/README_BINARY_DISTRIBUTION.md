# Binary Distribution

Trevvos Forge can be distributed as standalone executables for Windows and Linux — no Python, no Git, no pip required by the end user.

This document describes how to build, test, and publish the standalone binaries.

---

## What Is Included in the Binary

The standalone build includes:

- Trevvos Forge CLI (`trevvos` / `trevvos.exe`)
- All CLI commands and workflows
- Local API and dashboard (`trevvos_forge/local_api/static/`)
- Alpha documentation (`README.md`, `ALPHA.md`, `docs/`)
- Python runtime (embedded by PyInstaller)
- All Python dependencies (requests, typer, rich, etc.)

**Not included:**

- Ollama or any LLM runtime
- LLM models
- llama.cpp
- LM Studio
- API keys or credentials
- `.trevvos/` project data from the build machine
- Development sessions or local history

Runtime and model configuration is done by the end user after installation:

```bash
./trevvos setup
./trevvos doctor
```

---

## Build Format

Builds use PyInstaller `--onedir` (one-folder) mode. The output is a directory (`dist/trevvos/`) containing the executable and all dependencies, packaged into an archive.

`--onefile` is not used in the current release because:
- Easier to validate and debug individual components
- Dashboard static assets are preserved in-tree without extraction overhead
- Startup time is faster (no extraction step)

---

## Building on Windows

Requirements:
- Python 3.11+
- Active virtual environment with Forge installed (or the script installs it)
- PowerShell 5.1+

Run from the repo root:

```powershell
.\packaging\build_windows.ps1
```

Output: `release\trevvos-forge-v0.1.0-alpha.1-windows-x64.zip`

The script:
1. Installs pip, the package, and PyInstaller
2. Cleans `build/`, `dist/`, `release/`
3. Runs PyInstaller with `--onedir` and all required `--add-data` flags
4. Validates the binary with `--version`, `--help`, `setup --help`, `doctor --help`, `api start --help`
5. Packages the output directory as a ZIP

---

## Building on Linux

Requirements:
- Python 3.11+
- bash

Run from the repo root:

```bash
chmod +x packaging/build_linux.sh
./packaging/build_linux.sh
```

Output: `release/trevvos-forge-v0.1.0-alpha.1-linux-x64.tar.gz`

The script behaves the same as the Windows version, producing a `tar.gz` instead of a ZIP.

---

## Generating Checksums

After building, generate SHA256 checksums for the release artefacts:

```bash
python packaging/build_release.py
```

Output: `release/SHA256SUMS.txt`

Format:
```
<sha256>  trevvos-forge-v0.1.0-alpha.1-windows-x64.zip
<sha256>  trevvos-forge-v0.1.0-alpha.1-linux-x64.tar.gz
```

Include `SHA256SUMS.txt` in the GitHub Release assets.

---

## Testing the Binary

### Windows

```powershell
# Validate the built binary (before packaging)
dist\trevvos\trevvos.exe --version
dist\trevvos\trevvos.exe --help
dist\trevvos\trevvos.exe setup --help
dist\trevvos\trevvos.exe doctor --help
dist\trevvos\trevvos.exe api start --help

# Smoke test from extracted ZIP (outside the repo)
cd C:\Temp
Expand-Archive -Path path\to\trevvos-forge-v0.1.0-alpha.1-windows-x64.zip -DestinationPath trevvos-test
cd trevvos-test
.\trevvos.exe setup --provider openai-compatible --base-url http://localhost:1234/v1 --model qwen3-coder --yes --no-doctor
.\trevvos.exe inspect
.\trevvos.exe api start --port 8765 --open
```

### Linux

```bash
# Validate the built binary
dist/trevvos/trevvos --version
dist/trevvos/trevvos --help
dist/trevvos/trevvos setup --help
dist/trevvos/trevvos doctor --help
dist/trevvos/trevvos api start --help

# Smoke test from extracted tar.gz (outside the repo)
mkdir /tmp/trevvos-test && cd /tmp/trevvos-test
tar -xzf /path/to/trevvos-forge-v0.1.0-alpha.1-linux-x64.tar.gz
cd trevvos
./trevvos setup --provider openai-compatible --base-url http://localhost:1234/v1 --model qwen3-coder --yes --no-doctor
./trevvos inspect
./trevvos api start --port 8765
```

---

## Publishing a GitHub Release

1. Build Windows and Linux binaries.
2. Generate checksums.
3. Create a GitHub Release with tag `v0.1.0-alpha.1`.
4. Upload:
   - `release/trevvos-forge-v0.1.0-alpha.1-windows-x64.zip`
   - `release/trevvos-forge-v0.1.0-alpha.1-linux-x64.tar.gz`
   - `release/SHA256SUMS.txt`
5. Mark the release as Pre-release.
6. Share the release URL with Alpha testers.

---

## CI/CD

Builds are automated via GitHub Actions at `.github/workflows/build-binaries.yml`.

Triggers:
- Manual dispatch (`workflow_dispatch`)
- Push of a version tag (`v*`)

Jobs:
- `build-windows`: runs on `windows-latest`
- `build-linux`: runs on `ubuntu-22.04`

Artefacts are uploaded to the workflow run and can be downloaded from the GitHub Actions UI.

---

## Known Limitations

- macOS build not yet implemented (planned for a future marco).
- PyInstaller `--onedir` produces a directory, not a single file. Users must keep the entire directory together.
- Large model files are never bundled — users configure Ollama or an OpenAI-compatible provider separately.
- First launch may be slower on Windows due to antivirus scanning the extracted files.
- If `importlib.metadata` is unavailable in the bundle, the version fallback `0.1.0-alpha.1` is used.

---

## Troubleshooting

**Binary does not start / "DLL not found" on Windows:**  
Install the latest [Visual C++ Redistributable](https://aka.ms/vs/17/release/vc_redist.x64.exe).

**"Operation not permitted" on Linux:**  
Make the binary executable: `chmod +x trevvos`

**Dashboard assets not found:**  
Ensure the entire extracted directory is kept together. The `trevvos_forge/local_api/static/` subdirectory must be present at the same level as the executable (inside `_internal/` in PyInstaller 6.x).

**`trevvos setup` writes `.trevvos/` to the current directory:**  
This is expected. Run `trevvos setup` from the root of the project you want to configure.
