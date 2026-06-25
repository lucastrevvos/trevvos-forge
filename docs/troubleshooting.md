# Troubleshooting

---

## Diagnostics First

Before diving into specific issues, run the built-in diagnostics:

```bash
trevvos doctor
trevvos runtime status
trevvos doctor --json   # structured output for sharing
```

---

## Provider Issues

### `trevvos doctor` fails: "cannot connect to provider"

**Ollama:**

1. Check if Ollama is running:
   ```bash
   ollama ps
   # or
   curl http://localhost:11434/api/tags
   ```
2. If not running, start it:
   ```bash
   ollama serve
   # or
   trevvos runtime start
   ```
3. Verify the model is downloaded:
   ```bash
   ollama list
   ollama pull qwen2.5-coder:7b
   ```

**OpenAI-compatible:**

1. Verify the server is running and accessible:
   ```bash
   curl http://localhost:1234/v1/models
   ```
2. Check the `base_url` in `.trevvos/config.json` matches the server address exactly.

### "model not found" or empty response

Ollama: the model name in config must match exactly what `ollama list` shows.

OpenAI-compatible: the model name must match what the server expects. LM Studio shows the model identifier in the server UI. Check the model name with:

```bash
curl http://localhost:1234/v1/models | python -m json.tool
```

### API key errors with openai-compatible provider

Forge reads the API key from the `TREVVOS_FORGE_API_KEY` environment variable. It does not save the key to `.trevvos/config.json`.

```bash
export TREVVOS_FORGE_API_KEY="sk-..."   # Linux/macOS
$env:TREVVOS_FORGE_API_KEY = "sk-..."  # Windows PowerShell
trevvos doctor
```

### Timeout errors

The default timeout is 320 seconds. For slow local models or long generations, increase it:

```bash
export TREVVOS_FORGE_TIMEOUT=600
trevvos doctor
```

Or add `"timeout": 600` to `.trevvos/config.json`.

---

## Setup Issues

### `trevvos setup` shows error about unknown provider

Supported providers are `ollama` and `openai-compatible`:

```bash
trevvos setup --provider ollama --yes
trevvos setup --provider openai-compatible --yes
```

### Config file not created after `trevvos setup`

Check that you ran setup without `--dry-run`. If using `--dry-run`, the config is previewed but not written.

```bash
trevvos setup --provider ollama --yes   # no --dry-run
cat .trevvos/config.json
```

### `trevvos setup` ran but wrong command is active

If the `trevvos setup` command shows unexpected behavior (e.g., only asks for a model name), reinstall Forge:

```bash
python -m pip install -e . --force-reinstall
trevvos setup --help
```

---

## Controlled Testing Issues

### `trevvos tests add` session ends as `failed`

1. View the session:
   ```bash
   trevvos sessions list
   trevvos sessions show <id>
   ```
2. Check `sandbox_result.json` for the failure reason.
3. Common causes:
   - Generated test has a syntax error (try a larger model or smaller `--symbol` scope)
   - Import error in the generated test (the source file may be missing dependencies)
   - Sandbox timeout (set `TREVVOS_FORGE_TIMEOUT` higher)

### `trevvos tests apply` says "patch already applied"

This is not an error. Forge detected (via `git apply --reverse --check`) that the patch is already in the working tree. No action needed.

### `trevvos tests apply --latest` says "no eligible sessions"

The latest session may be in `failed` or `obsolete` state. Either fix the failed session or generate a new one:

```bash
trevvos sessions list
trevvos tests add <file>
```

### Generated tests fail when run

The sandbox validates the patch, but occasionally tests pass in the sandbox and fail in the real environment due to differences in test discovery or dependencies. Review the generated test file and fix manually if needed:

```bash
cat .trevvos/sessions/<id>/test_patch.diff
```

---

## Dashboard and API Issues

### Dashboard shows no sessions

The dashboard reads from `.trevvos/sessions/`. If no sessions have been created yet, the list will be empty. Run any advisory or controlled testing command first.

### Port already in use

Change the port:

```bash
trevvos api start --port 9000
```

### Dashboard does not open automatically

If `--open` does not open a browser, open it manually:

```
http://127.0.0.1:8765/
```

On headless environments (CI, SSH), `--open` will print the URL but cannot open a browser.

---

## Session Export Issues

### Export skips large files

By default, files over 1 MB are skipped in exports. Use `--include-large-files` to include them:

```bash
trevvos sessions export latest --include-large-files
```

### Export output contains sensitive data

Session exports may contain source code and LLM prompts. Secrets in JSON artifacts are masked automatically, but the raw source files are not masked.

Review exports before sharing. Never share exports from sessions that included secrets in source files.

---

## General Issues

### `trevvos --help` shows an old command structure

Reinstall:

```bash
python -m pip install -e . --force-reinstall
trevvos --help
```

### Python version issues

Forge requires Python 3.11+:

```bash
python --version
# Python 3.11.x or higher required
```

Use `pyenv`, `asdf`, or the system package manager to install a compatible version.

### Rich output garbled in terminal

Disable Rich formatting:

```bash
trevvos analyze --no-progress main.py
NO_COLOR=1 trevvos analyze main.py
```

---

## Getting Help

Export a session and open an issue:

```bash
trevvos sessions export latest
```

Include in your report:
- Exported ZIP or JSON
- OS and Python version
- Provider and model
- Command used
- Expected vs actual behavior

See [alpha-quickstart.md](alpha-quickstart.md) for setup guides.
