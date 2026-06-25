# Trevvos Forge v0.1.0-alpha.1

> Closed Alpha pre-release. Not for general use.

This is the first binary Alpha release of Trevvos Forge — a local AI engineering CLI that helps developers understand, analyze, review, and test code using local or API-hosted LLMs.

**Release date:** 2026-06-25

---

## Download

| Platform | File | Verify |
|---|---|---|
| Windows x64 | `trevvos-forge-v0.1.0-alpha.1-windows-x64.zip` | `SHA256SUMS.txt` |
| Linux x64 | `trevvos-forge-v0.1.0-alpha.1-linux-x64.tar.gz` | `SHA256SUMS.txt` |

Download from the [GitHub Release](https://github.com/your-org/trevvos-forge/releases/tag/v0.1.0-alpha.1) page.

Verify your download with the included `SHA256SUMS.txt`:

**Linux/macOS:**

```bash
sha256sum -c SHA256SUMS.txt
```

**Windows PowerShell:**

```powershell
Get-FileHash trevvos-forge-v0.1.0-alpha.1-windows-x64.zip -Algorithm SHA256
# Compare with SHA256SUMS.txt
```

---

## What Is Included

- Standalone CLI (`trevvos` / `trevvos.exe`) — no Python required
- Advisory Mode: `analyze`, `explain`, `propose`, `spec`, `review-diff`
- Controlled Testing Mode: `tests inspect`, `tests add`, `tests apply`
- Setup and Doctor: `trevvos setup`, `trevvos doctor`
- Runtime manager: `trevvos runtime status/start/stop`
- Local API and Dashboard: `trevvos api start --open`
- Session Export: `trevvos sessions export`
- Alpha documentation (`README.md`, `ALPHA.md`, `docs/`)

## What Is Not Included

- Ollama or any LLM runtime
- LLM models
- LM Studio or llama.cpp
- API keys or credentials
- Local `.trevvos/` sessions from the build machine
- Cloud sync or remote access

You configure the provider and model separately after installation:

```bash
trevvos setup
trevvos doctor
```

---

## Quick Start

### Windows

```powershell
Expand-Archive -Path trevvos-forge-v0.1.0-alpha.1-windows-x64.zip -DestinationPath trevvos-forge
cd trevvos-forge
.\trevvos.exe --version
.\trevvos.exe setup --provider ollama --model qwen2.5-coder:7b --yes
.\trevvos.exe doctor
.\trevvos.exe api start --open
```

### Linux

```bash
tar -xzf trevvos-forge-v0.1.0-alpha.1-linux-x64.tar.gz
cd trevvos
./trevvos --version
./trevvos setup --provider ollama --model qwen2.5-coder:7b --yes
./trevvos doctor
./trevvos api start --open
```

See [docs/alpha-download-install.md](docs/alpha-download-install.md) for detailed setup guides including LM Studio and OpenAI API.

---

## Recommended Alpha Workflows

### Advisory Mode (Read-Only)

```bash
cd path/to/your/project
trevvos inspect
trevvos analyze main.py
trevvos explain main.py
trevvos propose "improve error handling"
trevvos review-diff
```

Advisory commands do not modify any source files.

### Controlled Testing Mode

```bash
trevvos tests inspect calculator.py
trevvos tests add calculator.py --symbol add
trevvos tests apply --latest --yes
python -m unittest discover -s tests
```

Only test files are modified. The patch is validated in a sandbox before `tests apply` is available.

---

## Supported Providers

| Provider | Status |
|---|---|
| Ollama | Supported |
| LM Studio (openai-compatible) | Supported |
| llama.cpp server (openai-compatible) | Supported |
| OpenAI API (openai-compatible) | Supported |
| OpenRouter (openai-compatible) | Supported |

---

## Supported Platforms

| Platform | Status |
|---|---|
| Windows x64 | Supported |
| Linux x64 glibc | Supported |
| macOS | Not yet — planned |
| Linux ARM64 | Not yet |
| Windows ARM64 | Not yet |
| Alpine/musl Linux | Not yet |

---

## Safety Notes

- Advisory Mode is read-only — no code modifications.
- Controlled Testing only modifies test files after sandbox validation.
- `trevvos apply` (Execution Mode) is experimental and not recommended for this Alpha.
- Local API binds to `127.0.0.1` by default.
- `trevvos setup` does not save API keys to disk.
- Session exports mask secrets in JSON artifacts.

---

## Known Limitations

- Execution Mode (`plan`, `diff`, `apply`, `repair`, `work`) is experimental. Do not use during Alpha unless guided.
- Generated test patches are strongest on small Python files with simple functions.
- Non-Python test generation is limited.
- Dashboard is basic — no auto-refresh, no filtering.
- No cloud sync or remote session access.
- macOS build not included in this release.
- First launch on Windows may be slow due to antivirus scanning.

See [docs/known-limitations.md](docs/known-limitations.md) for the full list.

---

## Reporting Feedback

After any session, export it and attach to your report:

```bash
trevvos sessions export latest
```

Review the export before sharing — it contains source code and LLM prompts. Secrets in JSON artifacts are masked automatically.

Use the [Alpha Feedback issue template](https://github.com/your-org/trevvos-forge/issues/new?template=alpha-feedback.md) or the template at [docs/feedback-template.md](docs/feedback-template.md).
