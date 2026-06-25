# Release v0.1.0-alpha.1

**Status:** Closed Alpha pre-release  
**Release date:** 2026-06-25  
**Tag:** `v0.1.0-alpha.1`

---

## Assets

| File | Platform | Size (approx.) |
|---|---|---|
| `trevvos-forge-v0.1.0-alpha.1-windows-x64.zip` | Windows x64 | ~60–80 MB |
| `trevvos-forge-v0.1.0-alpha.1-linux-x64.tar.gz` | Linux x64 glibc | ~50–70 MB |
| `SHA256SUMS.txt` | All | — |

Download from the GitHub Release page.

---

## Supported Platforms

| Platform | Status | Notes |
|---|---|---|
| Windows x64 | Supported | Tested on Windows 10/11 |
| Linux x64 glibc | Supported | Tested on Ubuntu 22.04 |
| macOS | Not yet | Planned for a future release |
| Linux ARM64 | Not yet | — |
| Windows ARM64 | Not yet | — |
| Alpine / musl Linux | Not yet | glibc required |

---

## Verifying the Download

Verify the checksum before running the binary.

**Linux/macOS:**

```bash
sha256sum -c SHA256SUMS.txt
```

**Windows PowerShell:**

```powershell
$expected = (Get-Content SHA256SUMS.txt | Where-Object { $_ -match "windows-x64.zip" }).Split(" ")[0]
$actual   = (Get-FileHash trevvos-forge-v0.1.0-alpha.1-windows-x64.zip -Algorithm SHA256).Hash.ToLower()
if ($expected -eq $actual) { Write-Host "OK" } else { Write-Host "MISMATCH" }
```

---

## Installation

### Windows

```powershell
# 1. Extract
Expand-Archive -Path trevvos-forge-v0.1.0-alpha.1-windows-x64.zip -DestinationPath trevvos-forge
cd trevvos-forge

# 2. Verify
.\trevvos.exe --version

# 3. Set up (from your project root)
cd C:\path\to\your\project
C:\path\to\trevvos-forge\trevvos.exe setup
```

Or add the extracted folder to your PATH.

### Linux

```bash
# 1. Extract
tar -xzf trevvos-forge-v0.1.0-alpha.1-linux-x64.tar.gz
cd trevvos

# 2. Make executable (should already be set)
chmod +x trevvos

# 3. Verify
./trevvos --version

# 4. Optionally move to PATH
sudo mv trevvos /usr/local/bin/trevvos-forge/
```

See [alpha-download-install.md](alpha-download-install.md) for the full practical guide.

---

## First Commands

Run from the root of a project you want to test with:

```bash
# 1. Configure provider and model
trevvos setup

# 2. Verify connectivity
trevvos doctor

# 3. Inspect the project
trevvos inspect

# 4. Analyze a file
trevvos analyze main.py

# 5. Open dashboard
trevvos api start --open
```

---

## Uninstall / Rollback

Trevvos Forge does not install to system directories. To remove it:

1. Delete the extracted folder (`trevvos-forge/` on Windows, `trevvos/` on Linux).
2. Delete `.trevvos/` from any projects you configured (`rm -rf .trevvos`).

No registry entries, system services, or PATH modifications are made by the binary itself (unless you added it to PATH manually).

---

## Known Limitations in This Release

- **Execution Mode is experimental.** Do not use `trevvos plan`, `diff`, `apply`, `repair`, `work` unless guided.
- **macOS not available.** macOS build is planned for a future release.
- **First launch on Windows may be slow** due to antivirus scanning the executable.
- **Test generation is strongest on small Python files.**
- **No cloud sync or remote access.**
- **API key must be in environment variable** — `trevvos setup` does not persist it.

See [known-limitations.md](known-limitations.md) for the full list.

---

## Troubleshooting

**Windows: "Windows protected your PC" (SmartScreen)**  
Click "More info" → "Run anyway". This is expected for unsigned binaries.

**Windows: "DLL not found"**  
Install the [Visual C++ Redistributable x64](https://aka.ms/vs/17/release/vc_redist.x64.exe).

**Linux: "Permission denied"**  
```bash
chmod +x trevvos
```

**`trevvos doctor` fails to connect**  
Ensure your provider is running: `ollama ps` or check LM Studio server status.

**Dashboard assets not loading**  
Keep the entire extracted directory together — do not move just the `trevvos` executable without its `_internal/` directory.

See [troubleshooting.md](troubleshooting.md) for more.

---

## Reporting Feedback

Export your session and attach it to the report:

```bash
trevvos sessions export latest
```

Fill out the feedback template: [feedback-template.md](feedback-template.md)

Or open a GitHub issue using the [Alpha Feedback template](https://github.com/your-org/trevvos-forge/issues/new?template=alpha-feedback.md).

---

## Publishing This Release (Maintainer Notes)

### Using GitHub CLI

From the repo root, after building artifacts:

```bash
gh release create v0.1.0-alpha.1 \
  release/trevvos-forge-v0.1.0-alpha.1-windows-x64.zip \
  release/trevvos-forge-v0.1.0-alpha.1-linux-x64.tar.gz \
  release/SHA256SUMS.txt \
  --title "Trevvos Forge v0.1.0-alpha.1" \
  --notes-file RELEASE_NOTES.md \
  --prerelease
```

To upload additional assets to an existing release:

```bash
gh release upload v0.1.0-alpha.1 release/* --clobber
```

### Using GitHub UI

1. Go to **Releases** → **Draft a new release**.
2. Tag: `v0.1.0-alpha.1` (create new tag).
3. Title: `Trevvos Forge v0.1.0-alpha.1`.
4. Description: paste contents of `RELEASE_NOTES.md`.
5. Check **Set as a pre-release**.
6. Upload assets: Windows ZIP, Linux tar.gz, SHA256SUMS.txt.
7. Click **Publish release**.
