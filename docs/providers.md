# Provider Configuration

Trevvos Forge supports two provider types: `ollama` and `openai-compatible`.

Configure the active provider with `trevvos setup` or by editing `.trevvos/config.json` directly. Environment variables override config file values.

---

## Ollama

**Runtime:** `ollama`  
**Default base URL:** `http://localhost:11434`  
**Recommended model:** `qwen2.5-coder:7b`

Forge does not download or manage models. Pull your model before using it:

```bash
ollama pull qwen2.5-coder:7b
ollama pull qwen2.5-coder:14b
ollama pull qwen2.5-coder:3b
```

### Setup

```bash
trevvos setup --provider ollama --model qwen2.5-coder:7b --yes
```

This sets `provider: ollama`, `runtime: ollama`, and `base_url: http://localhost:11434` in `.trevvos/config.json`.

### Manual config

```json
{
  "provider": "ollama",
  "runtime": "ollama",
  "base_url": "http://localhost:11434",
  "model": "qwen2.5-coder:7b",
  "language": "en"
}
```

### Verify

```bash
trevvos doctor
trevvos runtime status
```

### Runtime Management

If Ollama is not already running as a system service, Forge can start and stop it:

```bash
trevvos runtime start
trevvos runtime stop
```

These commands require Ollama to be installed and in the system PATH.

---

## OpenAI-Compatible

**Runtime:** `external`  
**Default base URL:** `http://localhost:1234/v1`

The `openai-compatible` provider works with any server that speaks the OpenAI `/chat/completions` API format:

- LM Studio
- llama.cpp server
- Jan.ai
- OpenAI API
- OpenRouter
- vLLM, text-generation-webui (with API extension enabled)
- Any other OpenAI-compatible endpoint

### LM Studio

Start LM Studio, load a model, and start the local server (default port: 1234).

```bash
trevvos setup --provider openai-compatible --base-url http://localhost:1234/v1 --model <model-name> --yes
trevvos doctor
```

Use the model name exactly as shown in LM Studio. Example:

```bash
trevvos setup --provider openai-compatible --base-url http://localhost:1234/v1 --model qwen2.5-coder-7b-instruct --yes
```

### llama.cpp Server

Start llama.cpp server:

```bash
./llama-server -m qwen2.5-coder-7b.Q8_0.gguf --port 8080
```

Then configure Forge:

```bash
trevvos setup --provider openai-compatible --base-url http://localhost:8080/v1 --model qwen2.5-coder-7b --yes
```

### OpenAI API

**Linux/macOS:**

```bash
export TREVVOS_FORGE_API_KEY="sk-..."
trevvos setup --provider openai-compatible --base-url https://api.openai.com/v1 --model gpt-4.1-mini --yes
```

**Windows PowerShell:**

```powershell
$env:TREVVOS_FORGE_API_KEY = "sk-..."
trevvos setup --provider openai-compatible --base-url https://api.openai.com/v1 --model gpt-4.1-mini --yes
```

Forge reads the API key from `TREVVOS_FORGE_API_KEY`. It does not save `api_key` to `.trevvos/config.json`.

### OpenRouter

```bash
export TREVVOS_FORGE_API_KEY="sk-or-..."
trevvos setup --provider openai-compatible --base-url https://openrouter.ai/api/v1 --model qwen/qwen-2.5-coder-32b-instruct --yes
```

### Manual config for openai-compatible

```json
{
  "provider": "openai-compatible",
  "runtime": "external",
  "base_url": "http://localhost:1234/v1",
  "model": "qwen2.5-coder-7b-instruct",
  "language": "en"
}
```

---

## Environment Variables

Environment variables override `.trevvos/config.json`:

| Variable | Description |
|---|---|
| `TREVVOS_FORGE_PROVIDER` | `ollama` or `openai-compatible` |
| `TREVVOS_FORGE_RUNTIME` | `ollama` or `external` |
| `TREVVOS_FORGE_BASE_URL` | Provider base URL |
| `TREVVOS_FORGE_MODEL` | Model name |
| `TREVVOS_FORGE_API_KEY` | API key (openai-compatible only) |
| `TREVVOS_FORGE_TIMEOUT` | Request timeout in seconds (default: 320) |

---

## Diagnosing Provider Issues

```bash
trevvos doctor
trevvos doctor --json
```

The doctor command checks:
- Provider configuration is present
- Model name is set
- HTTP connectivity to the base URL
- (Ollama only) Ollama service status and model availability
- (OpenAI-compatible) `/chat/completions` endpoint reachability

See [troubleshooting.md](troubleshooting.md) for common issues and fixes.

---

## Switching Providers

Re-run `trevvos setup` with different options. Setup merges into the existing config without overwriting unrelated keys:

```bash
trevvos setup --provider openai-compatible --base-url https://api.openai.com/v1 --model gpt-4.1-mini --yes --no-inspect
```

Or switch back to Ollama:

```bash
trevvos setup --provider ollama --model qwen2.5-coder:7b --yes --no-inspect
```

---

## Model Recommendations

| Use Case | Ollama Model | OpenAI-compatible |
|---|---|---|
| Fast, basic | qwen2.5-coder:3b | gpt-4.1-nano |
| Balanced (recommended) | qwen2.5-coder:7b | gpt-4.1-mini |
| High quality | qwen2.5-coder:14b or :32b | gpt-4.1 |

For advisory mode, smaller models are often sufficient. For Controlled Testing Mode and Execution Mode, larger models produce better patches.


