# Trevvos Forge

**Local AI engineering CLI for code analysis, review, specifications, and controlled test generation.**

Trevvos Forge helps developers inspect and reason about existing codebases from the terminal while keeping code changes explicit and auditable. It supports local models through Ollama and OpenAI-compatible providers such as LM Studio, llama.cpp, and hosted APIs.

> **Status:** Alpha. Advisory Mode and Controlled Testing Mode are the recommended workflows. Execution Mode remains experimental.

## Why Forge exists

AI coding tools are useful, but handing an entire repository to an autonomous loop is not always the right trade-off. Forge is built around a more controlled workflow:

```text
inspect -> analyze -> propose -> review -> validate -> apply explicitly
```

The default experience is read-only. When Forge generates tests, it validates them in a sandbox before anything is applied to the working tree.

## Highlights

- Project and source-code inspection from the CLI.
- File, symbol, and execution-flow explanations.
- Technical proposals before implementation.
- Handoff specifications for external coding agents.
- Local Git diff review.
- Controlled unit-test generation with sandbox validation.
- Session artifacts for auditability and debugging.
- Local read-only dashboard and session export.
- Ollama and OpenAI-compatible providers.
- English and Brazilian Portuguese reports.

## Quick start

### Download an Alpha binary

Current prerelease: **v0.1.0-alpha.1**

Available release assets:

- `trevvos-forge-windows-x64.zip`
- `trevvos-forge-linux-x64.zip`
- `SHA256SUMS.txt`

See the [GitHub Releases](../../releases) page and the [Alpha installation guide](docs/alpha-download-install.md).

### Install from source

Requirements:

- Python 3.11+
- Git
- Ollama or another OpenAI-compatible model endpoint

```bash
git clone https://github.com/lucastrevvos/trevvos-forge.git
cd trevvos-forge
python -m venv .venv
source .venv/bin/activate
python -m pip install -e .
trevvos --help
```

On Windows PowerShell:

```powershell
python -m venv .venv
.\.venv\Scripts\Activate.ps1
python -m pip install -e .
trevvos --help
```

## Core workflows

### Advisory Mode — recommended

Read-only commands for understanding and planning:

```bash
trevvos setup
trevvos doctor
trevvos inspect
trevvos analyze src/
trevvos explain src/main.py --flow
trevvos propose "improve error handling"
trevvos spec "add a new provider" --target codex
trevvos review-diff
```

### Controlled Testing Mode

Forge can generate a unit-test patch, validate it in a sandbox, and keep application explicit:

```bash
trevvos tests inspect calculator.py
trevvos tests add calculator.py --symbol add
trevvos tests apply --latest --yes
```

The important boundary is deliberate:

1. `tests inspect` reads coverage information.
2. `tests add` generates and validates a test patch in a sandbox.
3. `tests apply` applies only the already-validated patch.

### Execution Mode — experimental

Planning, patch generation, repair, apply, and commit workflows exist but are still experimental:

```bash
trevvos plan "add sqrt to the calculator CLI"
trevvos diff
trevvos test --sandbox
trevvos apply
```

Review generated diffs before applying them.

## Providers

### Ollama

```bash
trevvos setup --provider ollama --model qwen2.5-coder:7b --yes
trevvos doctor
```

Forge does not download models automatically.

### OpenAI-compatible endpoints

```bash
trevvos setup \
  --provider openai-compatible \
  --base-url http://localhost:1234/v1 \
  --model qwen3-coder \
  --yes
```

For providers that require a key, prefer the environment:

```bash
export TREVVOS_FORGE_API_KEY="..."
```

Forge does not save API keys to project configuration by default.

## Safety model

Forge is intentionally conservative around code modification:

- Advisory commands are read-only.
- Controlled Testing Mode only targets test files.
- Generated test patches are sandboxed before application.
- Applying code changes requires an explicit command.
- The local API binds to `127.0.0.1` by default.
- Session exports mask known secrets, but exports should still be reviewed before sharing.
- Prompts, model responses, validation results, and other evidence are retained locally for auditability.

Read more in [docs/safety-model.md](docs/safety-model.md).

## Documentation

Start here:

- [Alpha overview](ALPHA.md)
- [Quick start](docs/alpha-quickstart.md)
- [Providers](docs/providers.md)
- [Advisory Mode](docs/advisory-mode.md)
- [Controlled Testing Mode](docs/controlled-testing-mode.md)
- [Safety model](docs/safety-model.md)
- [Known limitations](docs/known-limitations.md)
- [Troubleshooting](docs/troubleshooting.md)

## Current status

Stable enough for Alpha testing:

- Advisory Mode
- Controlled Testing Mode
- Setup and diagnostics
- Local dashboard
- Session export

Experimental:

- Execution Mode

Not yet implemented:

- Managed llama.cpp runtime
- Cloud session sync
- PyPI distribution

## Contributing

Issues, reproducible bug reports, documentation improvements, tests, and focused pull requests are welcome.

Please read [CONTRIBUTING.md](CONTRIBUTING.md) before opening a pull request.

## License

Licensed under the [Apache License 2.0](LICENSE).
