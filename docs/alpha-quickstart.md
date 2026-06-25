# Alpha Quickstart

This guide walks you through getting Trevvos Forge running against a real project, from installation to your first advisory and test generation session.

---

## Installing the Standalone Binary (Recommended for Alpha)

Download the standalone binary from the GitHub Release â€” **no Python, Git, or pip required**.

**Windows x64:**

```powershell
# 1. Download trevvos-forge-v0.1.0-alpha.1-windows-x64.zip from the release
# 2. Extract it
Expand-Archive -Path trevvos-forge-v0.1.0-alpha.1-windows-x64.zip -DestinationPath trevvos
cd trevvos
.\trevvos.exe --version
.\trevvos.exe --help
```

**Linux x64:**

```bash
# 1. Download trevvos-forge-v0.1.0-alpha.1-linux-x64.tar.gz from the release
# 2. Extract it
tar -xzf trevvos-forge-v0.1.0-alpha.1-linux-x64.tar.gz
cd trevvos
./trevvos --version
./trevvos --help
```

After extraction, continue with your provider setup below. The `trevvos` (or `trevvos.exe`) binary is the same for all scenarios.

---

## Installing from Source (For Contributors)

If you prefer to install from source (requires Python 3.11+ and Git):

```bash
git clone https://github.com/lucastrevvos/trevvos-forge.git
cd trevvos-forge
python -m venv .venv
source .venv/bin/activate        # Linux/macOS
# .\.venv\Scripts\Activate.ps1  # Windows PowerShell
python -m pip install -e .
trevvos --version
```

---

## Prerequisites

- An LLM server: Ollama (local, recommended) or any OpenAI-compatible endpoint
- Python 3.11+ only required if installing from source

---

## Option A: Quickstart with Ollama

### 1. Install Ollama

Download from [https://ollama.com/download](https://ollama.com/download) and follow the install instructions for your OS.

Start the Ollama service if it's not already running:

```bash
ollama serve
```

Pull a coding model:

```bash
ollama pull qwen2.5-coder:7b
```

Smaller models (`3b`) run faster; larger models (`14b`, `32b`) produce better results. `qwen2.5-coder:7b` is a solid balance for most Alpha testing.

### 2. Install Forge

```bash
git clone https://github.com/lucastrevvos/trevvos-forge.git
cd trevvos-forge
python -m venv .venv
source .venv/bin/activate   # Linux/macOS
# .\.venv\Scripts\Activate.ps1   # Windows PowerShell
python -m pip install -e .
trevvos --version
```

### 3. Set Up a Project

Navigate to a project you want to test with. Forge uses the current working directory as the project root:

```bash
cd path/to/your/project
trevvos setup --provider ollama --model qwen2.5-coder:7b --yes
```

This creates `.trevvos/config.json` and optionally runs `trevvos doctor`.

### 4. Verify the Setup

```bash
trevvos doctor
```

Expected output shows green checks for provider, model, and connectivity. If it fails, see [troubleshooting.md](troubleshooting.md).

### 5. Inspect the Project

```bash
trevvos inspect
```

Forge scans the project tree and writes `.trevvos/project_profile.json`. This profile is included as context in subsequent commands.

### 6. Analyze the Project

```bash
trevvos analyze
```

Runs a full project analysis. To analyze a specific file:

```bash
trevvos analyze main.py
trevvos analyze src/
```

### 7. Try Other Advisory Commands

```bash
trevvos explain main.py
trevvos propose "improve error handling in the CLI layer"
trevvos review-diff
```

Advisory commands do not modify any files.

### 8. Try Controlled Test Generation

```bash
trevvos tests inspect calculator.py
trevvos tests add calculator.py --symbol add
```

When satisfied with the generated patch:

```bash
trevvos tests apply --latest --yes
python -m unittest discover -s tests
```

### 9. Open the Dashboard

```bash
trevvos api start --open
```

---

## Option B: Quickstart with LM Studio

### 1. Install LM Studio

Download from lmstudio.ai, download a GGUF model (e.g. qwen2.5-coder-7b), and start the local server on port 1234.

### 2. Set Up Forge

```bash
cd path/to/your/project
trevvos setup --provider openai-compatible --base-url http://localhost:1234/v1 --model qwen2.5-coder:7b --yes
trevvos doctor
```

If the model name in LM Studio differs, use the name exactly as shown in the LM Studio UI.

---

## Option C: Quickstart with OpenAI API

```bash
export TREVVOS_FORGE_API_KEY="sk-..."   # Linux/macOS
# $env:TREVVOS_FORGE_API_KEY = "sk-..."  # Windows PowerShell

cd path/to/your/project
trevvos setup --provider openai-compatible --base-url https://api.openai.com/v1 --model gpt-4.1-mini --yes
trevvos doctor
```

Forge reads the API key from the environment variable. It does not save `api_key` to `.trevvos/config.json`.

---

## What to Test in Alpha

Recommended scenarios:

1. **Advisory Mode basics**: `analyze`, `explain`, `propose` on a real project file.
2. **Review before commit**: `git add` some changes, then `trevvos review-diff --staged`.
3. **Controlled testing**: `tests inspect`, `tests add`, `tests apply` on a simple Python module.
4. **Session export**: after any session, `trevvos sessions export latest`.
5. **Dashboard**: `trevvos api start --open`, browse sessions and artifacts.

Not recommended for Alpha unless specifically testing these areas:

- Execution Mode (`plan`, `diff`, `apply`) â€” experimental.
- Ollama runtime management (`runtime start/stop`) â€” only for managed Ollama setups.

---

## Reporting Issues

Export a session and include it in your report:

```bash
trevvos sessions export latest
```

Include:
- Exported ZIP or JSON file
- OS and Python version (`python --version`)
- Provider and model
- Command used
- Expected vs actual behavior


