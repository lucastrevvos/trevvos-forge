# Alpha Download and Install

This guide is for Alpha testers. No Python, Git, or pip required.

---

## Step 1: Download

Go to the GitHub Release page and download the file for your OS:

| OS | File |
|---|---|
| Windows x64 | `trevvos-forge-v0.1.0-alpha.1-windows-x64.zip` |
| Linux x64 | `trevvos-forge-v0.1.0-alpha.1-linux-x64.tar.gz` |

Optionally verify the checksum with `SHA256SUMS.txt` (see [release-v0.1.0-alpha.1.md](release-v0.1.0-alpha.1.md)).

---

## Step 2: Extract

### Windows

```powershell
Expand-Archive -Path trevvos-forge-v0.1.0-alpha.1-windows-x64.zip -DestinationPath trevvos-forge
cd trevvos-forge
.\trevvos.exe --version
```

### Linux

```bash
tar -xzf trevvos-forge-v0.1.0-alpha.1-linux-x64.tar.gz
cd trevvos
./trevvos --version
```

Expected output: `Trevvos Forge 0.1.0-alpha.1`

Keep the entire extracted directory together. The `trevvos` executable requires the `_internal/` subdirectory to be present alongside it.

---

## Step 3: Configure Provider

Navigate to the root of a project you want to test with, then run setup.

### Ollama

Make sure Ollama is running and you have pulled a model:

```bash
ollama pull qwen2.5-coder:7b
```

Then set up Forge:

```bash
cd path/to/your/project
trevvos setup --provider ollama --model qwen2.5-coder:7b --yes
trevvos doctor
```

### LM Studio / OpenAI-compatible

Start LM Studio and enable the local server (default port: 1234).

```bash
cd path/to/your/project
trevvos setup --provider openai-compatible --base-url http://localhost:1234/v1 --model <model-name> --yes
trevvos doctor
```

Use the exact model name as shown in LM Studio.

### OpenAI API

**Linux/macOS:**

```bash
export TREVVOS_FORGE_API_KEY="sk-..."
cd path/to/your/project
trevvos setup --provider openai-compatible --base-url https://api.openai.com/v1 --model gpt-4.1-mini --yes
trevvos doctor
```

**Windows PowerShell:**

```powershell
$env:TREVVOS_FORGE_API_KEY = "sk-..."
cd path\to\your\project
trevvos setup --provider openai-compatible --base-url https://api.openai.com/v1 --model gpt-4.1-mini --yes
trevvos doctor
```

The API key is read from the environment variable. `trevvos setup` does not save it to disk.

---

## Step 4: First Commands

```bash
# Inspect the project
trevvos inspect

# Analyze a file
trevvos analyze main.py

# Open the dashboard
trevvos api start --open
```

---

## Step 5: Open the Dashboard

```bash
trevvos api start --open
```

Or open `http://127.0.0.1:8765/` in a browser after starting the server.

The dashboard shows your sessions, artifacts, prompts, and diffs.

---

## Step 6: Export a Session for Feedback

After running any command:

```bash
trevvos sessions export latest
```

Review the exported file before sharing — it contains source code and LLM prompts. Secrets in JSON artifacts are masked automatically.

Attach the export to your feedback report using the template at [feedback-template.md](feedback-template.md).

---

## Troubleshooting

**Windows: "Windows protected your PC"**  
Click "More info" → "Run anyway".

**Windows: binary opens and closes instantly**  
Run from a PowerShell or Command Prompt window, not by double-clicking.

**Linux: "Permission denied"**  
```bash
chmod +x trevvos
```

**`doctor` fails: cannot connect to provider**  
- Ollama: run `ollama serve` or `trevvos runtime start`
- LM Studio: start the local server in the LM Studio UI
- OpenAI: check `echo $TREVVOS_FORGE_API_KEY` is set

**Dashboard doesn't open**  
Open `http://127.0.0.1:8765/` manually in a browser.

See [troubleshooting.md](troubleshooting.md) for more.
