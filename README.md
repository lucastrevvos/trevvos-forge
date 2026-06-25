# Trevvos Forge

Local AI engineering CLI for code analysis, explanations, proposals, specs, diff review, and controlled test generation.

> **Alpha:** Trevvos Forge is under active development. Advisory Mode and Controlled Testing Mode are the recommended workflows. General code execution/apply workflows are experimental.

---

## What Is Trevvos Forge?

Trevvos Forge is a command-line assistant for software engineering work. It runs locally using your choice of LLM provider â€” Ollama, LM Studio, or any OpenAI-compatible endpoint â€” and helps you understand, plan, review, and generate tests without leaving the terminal.

Its recommended workflow is advisory: inspect a project, analyze code, explain flows, generate proposals and handoff specs, review diffs, and inspect test coverage â€” all without modifying code by default.

Controlled Testing Mode adds sandboxed, auditable test generation: `trevvos tests add` generates a test patch, validates it in a sandbox, and only applies it via the explicit `trevvos tests apply` command.

Forge also includes a local dashboard (`trevvos api start --open`) and session export (`trevvos sessions export`) for visibility and debugging.

## What Forge Does Not Do Yet

- Does not replace a developer or guarantee correct code generation.
- Execution Mode (plan/diff/apply) is experimental â€” not recommended for Alpha testers unless guided.
- Does not download or manage AI models automatically.
- Does not sync sessions to the cloud.
- Managed llama.cpp runtime is not yet implemented.
- Dashboard is local and basic.

---

## Download Alpha

The current Alpha release is available as standalone binaries â€” no Python, Git, or pip required.

| Platform | Download |
|---|---|
| Windows x64 | `trevvos-forge-v0.1.0-alpha.1-windows-x64.zip` |
| Linux x64 | `trevvos-forge-v0.1.0-alpha.1-linux-x64.tar.gz` |

See [docs/alpha-download-install.md](docs/alpha-download-install.md) for installation instructions.

---

## Closed Alpha

Forge is currently in a closed technical Alpha.

See:

- [ALPHA.md](ALPHA.md) â€” Alpha overview and safety notes
- [docs/alpha-download-install.md](docs/alpha-download-install.md) â€” Download and install guide
- [docs/alpha-tester-invite.md](docs/alpha-tester-invite.md) â€” Tester invite (English and Portuguese)
- [docs/alpha-quickstart.md](docs/alpha-quickstart.md) â€” First steps and provider setup
- [docs/alpha-test-plan.md](docs/alpha-test-plan.md) â€” Guided test plan for Alpha testers
- [docs/alpha-success-criteria.md](docs/alpha-success-criteria.md) â€” Success and pause criteria for the Alpha run
- [docs/feedback-template.md](docs/feedback-template.md) â€” Bug report template
- [docs/known-limitations.md](docs/known-limitations.md) â€” Known limitations and experimental commands

---

## Quick Start

```bash
# 1. Set up Forge for this project
trevvos setup

# 2. Verify the environment
trevvos doctor

# 3. Inspect the project
trevvos inspect

# 4. Analyze a file
trevvos analyze main.py

# 5. Open the dashboard
trevvos api start --open
```

See [docs/alpha-quickstart.md](docs/alpha-quickstart.md) for full step-by-step guides for Ollama and OpenAI-compatible providers.

---

## Installation

Clone and install in editable mode:

```bash
git clone https://github.com/lucastrevvos/trevvos-forge.git
cd trevvos-forge
python -m venv .venv
source .venv/bin/activate        # Linux/macOS
python -m pip install -e .
trevvos --help
```

**Windows PowerShell:**

```powershell
python -m venv .venv
.\.venv\Scripts\Activate.ps1
python -m pip install -e .
trevvos --help
```

Requirements:

- Python 3.11+
- Git (for diff/review workflows)
- Ollama or any OpenAI-compatible LLM server

---

## Provider Setup

Trevvos Forge supports two providers: `ollama` (local) and `openai-compatible` (LM Studio, llama.cpp, OpenAI API, OpenRouter, etc.).

See [docs/providers.md](docs/providers.md) for detailed configuration.

### Ollama

```bash
trevvos setup --provider ollama --model qwen2.5-coder:7b --yes
trevvos runtime status
trevvos doctor
```

Forge does not download models. Pull your model first:

```bash
ollama pull qwen2.5-coder:7b
```

### OpenAI-Compatible (LM Studio, llama.cpp)

```bash
trevvos setup --provider openai-compatible --base-url http://localhost:1234/v1 --model qwen3-coder --yes
trevvos doctor
```

### OpenAI API

**Linux/macOS:**

```bash
export TREVVOS_FORGE_API_KEY="sk-..."
trevvos setup --provider openai-compatible --base-url https://api.openai.com/v1 --model gpt-4.1-mini --yes
trevvos doctor
```

**Windows PowerShell:**

```powershell
$env:TREVVOS_FORGE_API_KEY = "sk-..."
trevvos setup --provider openai-compatible --base-url https://api.openai.com/v1 --model gpt-4.1-mini --yes
trevvos doctor
```

API keys are read from the environment variable. Forge does not save `api_key` to `.trevvos/config.json` by default.

---

## Modes

### Advisory Mode â€” Recommended

Advisory Mode is the recommended daily mode. These commands are read-only: they do not modify code, do not generate patches, and do not apply changes.

```bash
trevvos inspect
trevvos analyze main.py
trevvos explain main.py --flow
trevvos propose "improve error handling in the provider layer"
trevvos spec "add support for a new provider" --target codex
trevvos review-diff
```

See [docs/advisory-mode.md](docs/advisory-mode.md).

### Controlled Testing Mode

Controlled Testing Mode generates unit tests in a sandboxed, auditable flow. It only modifies test files, never production source.

```bash
trevvos tests inspect calculator.py
trevvos tests add calculator.py --symbol add
trevvos tests apply --latest --yes
python -m unittest discover -s tests
```

The flow:

1. `tests inspect` â€” shows coverage without calling the provider.
2. `tests add` â€” generates a test patch, runs it in a sandbox, saves artifacts. Does **not** modify the working tree by default.
3. `tests apply` â€” applies the already-validated patch. No LLM call at apply time.

See [docs/controlled-testing-mode.md](docs/controlled-testing-mode.md).

### Execution Mode â€” Experimental

Execution Mode can plan changes, generate diffs, apply patches, and commit. It is experimental and not recommended for Alpha testers unless guided.

```bash
trevvos plan "add sqrt to the calculator CLI"
trevvos diff
trevvos test --sandbox
trevvos apply
```

Review generated diffs carefully before applying. See [docs/execution-mode.md](docs/execution-mode.md).

---

## Commands

| Command                   | Mode               |    Modifies code? | Purpose                                                                  |
| ------------------------- | ------------------ | ----------------: | ------------------------------------------------------------------------ |
| `trevvos setup`           | Setup              |                No | Create or update .trevvos/config.json interactively or non-interactively |
| `trevvos doctor`          | Advisory           |                No | Diagnose provider, runtime, and connectivity                             |
| `trevvos inspect`         | Advisory           |                No | Scan project structure and save a project profile                        |
| `trevvos analyze`         | Advisory           |                No | Analyze code quality, risks, tests, and architecture                     |
| `trevvos explain`         | Advisory           |                No | Explain files, symbols, and execution flows                              |
| `trevvos propose`         | Advisory           |                No | Generate a technical proposal before implementation                      |
| `trevvos spec`            | Advisory           |                No | Generate an implementation handoff prompt for external AI                |
| `trevvos review-diff`     | Advisory           |                No | Review local git diffs before commit                                     |
| `trevvos tests inspect`   | Advisory           |                No | Inspect detected test coverage by source symbol                          |
| `trevvos tests add`       | Controlled Testing | No (sandbox only) | Generate test patch, validate in sandbox, save artifacts                 |
| `trevvos tests apply`     | Controlled Testing |   Yes, tests only | Apply an already-validated test patch                                    |
| `trevvos sessions list`   | Utility            |                No | List local sessions                                                      |
| `trevvos sessions export` | Utility            |                No | Export session as ZIP or JSON with secrets masked                        |
| `trevvos api start`       | Utility            |                No | Start local read-only API server and dashboard                           |
| `trevvos runtime status`  | Utility            |                No | Show runtime status                                                      |
| `trevvos runtime start`   | Utility            |                No | Start managed runtime (Ollama)                                           |
| `trevvos plan`            | Execution          |                No | Plan code changes                                                        |
| `trevvos diff`            | Execution          |                No | Generate and validate a patch                                            |
| `trevvos test`            | Execution          |                No | Run verification commands                                                |
| `trevvos repair`          | Execution          |                No | Generate a repair diff for a failed session                              |
| `trevvos apply`           | Execution          |               Yes | Apply a validated patch after confirmation                               |
| `trevvos commit`          | Execution          |               Yes | Commit related changes                                                   |
| `trevvos work`            | Execution          |     No by default | Run a controlled experimental agent loop up to ready-to-apply            |

---

## Advisory Commands

Run all advisory commands from the root of the project you want to inspect:

```bash
cd path/to/your/project
trevvos inspect
trevvos analyze
```

Use `--language` to set the response language per command, or configure it project-wide:

```bash
trevvos config set language pt-BR
```

Supported: `en`, `pt-BR`.

### `trevvos inspect`

Scans the repository and writes `.trevvos/project_profile.json`.

```bash
trevvos inspect
trevvos inspect --json
trevvos inspect --refresh
```

### `trevvos analyze`

Generates a technical analysis of the project, file, or directory.

```bash
trevvos analyze
trevvos analyze main.py
trevvos analyze src/
```

### `trevvos explain`

Explains code didactically.

```bash
trevvos explain main.py
trevvos explain calculator.py --symbol divide
trevvos explain main.py --flow
```

### `trevvos propose`

Generates a technical proposal without implementing it.

```bash
trevvos propose "create a Money value object"
trevvos propose "improve CLI testability" --target main.py
```

### `trevvos spec`

Generates an AI handoff spec and a copy-paste prompt for another coding AI.

```bash
trevvos spec "add sqrt to the calculator and expose it in the CLI"
trevvos spec "add JWT authentication" --target codex
```

Copy `.trevvos/sessions/<id>/external_ai_prompt.md` into your preferred coding AI.

### `trevvos review-diff`

Reviews local git changes before commit.

```bash
trevvos review-diff
trevvos review-diff --staged
```

---

## Local Dashboard

```bash
trevvos api start --open
```

Or start without opening a browser:

```bash
trevvos api start --port 8765
```

Then open: `http://127.0.0.1:8765/`

The dashboard shows sessions, session metadata, artifacts, prompts, diffs, test results, and timings. The API is read-only and binds to `127.0.0.1` by default.

See [docs/local-api-dashboard.md](docs/local-api-dashboard.md).

---

## Session Export

Export a session for debugging or sharing:

```bash
trevvos sessions export latest
trevvos sessions export latest --format json
trevvos sessions export <session-id>
```

Secrets in JSON artifacts are masked automatically. Review the export before sharing â€” it may contain source code and prompts.

---

## Configuration

Forge stores project configuration in `.trevvos/config.json`. Use `trevvos setup` to generate it, or edit manually.

**Ollama example:**

```json
{
  "provider": "ollama",
  "runtime": "ollama",
  "base_url": "http://localhost:11434",
  "model": "qwen2.5-coder:7b",
  "language": "en",
  "test_commands": ["python -m unittest discover -s tests"]
}
```

**OpenAI-compatible example:**

```json
{
  "provider": "openai-compatible",
  "runtime": "external",
  "base_url": "http://localhost:1234/v1",
  "model": "qwen3-coder",
  "language": "en"
}
```

### Environment Variables

| Variable                 | Purpose                                   |
| ------------------------ | ----------------------------------------- |
| `TREVVOS_FORGE_PROVIDER` | Provider: `ollama` or `openai-compatible` |
| `TREVVOS_FORGE_RUNTIME`  | Runtime: `ollama` or `external`           |
| `TREVVOS_FORGE_BASE_URL` | Provider base URL                         |
| `TREVVOS_FORGE_MODEL`    | Model name                                |
| `TREVVOS_FORGE_API_KEY`  | API key (preferred over saving in config) |
| `TREVVOS_FORGE_TIMEOUT`  | Request timeout in seconds (default: 320) |

Environment variables override `.trevvos/config.json`.

---

## Working Directory

By default, Trevvos Forge uses the current working directory as the project root.

Run commands from the root of the project you want to inspect, analyze, or review:

```bash
cd path/to/your/project
trevvos inspect
trevvos analyze
```

Use a file path or `--target` to focus on a specific file or directory. Relative paths are resolved from the current working directory:

```bash
trevvos analyze src/main.py
trevvos propose "improve testability" --target src/domain
```

---

## Artifacts and Sessions

Forge writes session artifacts under:

```text
.trevvos/sessions/<session-id>/
```

Advisory sessions save reports, prompts, metadata, selected files, context, and project profile snapshots. Controlled Testing sessions add test patches, sandbox results, and apply results. Execution sessions may also save plans, patches, validations, warnings, repair metadata, and commit artifacts.

---

## Safety Model

- Advisory commands are read-only: no code modifications, no patches.
- Controlled Testing Mode only edits test files, never production source.
- Test patches are sandboxed before `tests apply`.
- `tests apply` applies only already-validated patches (no new LLM call).
- `trevvos apply` (Execution) requires confirmation before modifying the working tree.
- Secrets are masked in the local API responses and session exports.
- Local API binds to `127.0.0.1` by default.
- Sessions keep prompts, raw responses, metadata, and evidence for auditability.

See [docs/safety-model.md](docs/safety-model.md).

---

## Experimental: Execution Mode

These commands are under development. Not recommended for external Alpha testers unless guided:

```bash
trevvos plan
trevvos diff
trevvos repair
trevvos apply
trevvos work
```

Review generated diffs carefully before applying. See [docs/execution-mode.md](docs/execution-mode.md).

---

## Troubleshooting

See [docs/troubleshooting.md](docs/troubleshooting.md) for common issues.

Quick checks:

```bash
trevvos doctor
trevvos runtime status
trevvos sessions export latest
```

---

## Alpha Feedback

To share a session for debugging:

```bash
trevvos sessions export latest
```

Include in your report:

- exported ZIP or JSON
- OS and Python version
- provider and model
- command used
- expected vs actual behavior

---

## Language

Advisory reports can be generated in English or Brazilian Portuguese.

Set a persistent default in the current project:

```bash
trevvos config set language pt-BR
trevvos config set language en
```

Override the language for a single command with `--language`. Relative paths and targets still resolve from the current working directory:

```bash
trevvos analyze main.py --language pt-BR
trevvos propose "improve testability" --target src/domain --language pt-BR
```

---

## Current Status

Alpha â€” active development.

Stable for Alpha testing:

- Advisory Mode (all commands)
- Controlled Testing Mode (`tests inspect`, `tests add`, `tests apply`)
- Setup, Doctor, Runtime
- Local Dashboard and Session Export

Experimental:

- Execution Mode (`plan`, `diff`, `apply`, `work`, `repair`, `commit`)

Not yet implemented:

- Managed llama.cpp runtime
- Cloud sync
- PyPI distribution

---

## Roadmap

- Managed llama.cpp Runtime
- Improved dashboard (timeline, prompt viewer)
- Prompt file catalog and customization
- Portuguese docs
- Alpha package and distribution

---

## License

License information has not been added yet.


