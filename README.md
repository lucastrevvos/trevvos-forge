# Trevvos Forge

Local-first AI engineering advisor for developers.

Trevvos Forge acts like a senior engineer or tech lead in your terminal: it inspects a project, analyzes code, explains flows, proposes changes, prepares implementation handoffs for other AIs, and reviews diffs without modifying code by default.

The project uses local LLM providers, with Ollama as the first supported provider.

## What Is Trevvos Forge?

Trevvos Forge is a command-line assistant for software engineering work. Its recommended MVP workflow is advisory: it helps you understand a codebase, evaluate risks, plan changes, and review work while keeping the developer in control.

Forge can also generate and apply patches through Execution Mode, but that path is experimental and should be used carefully.

## Why Forge?

- Local-first by default.
- Designed for terminal workflows.
- Produces session artifacts you can inspect.
- Separates advisory guidance from code-modifying execution.
- Helps preserve developer judgment instead of hiding it.

## Modes

### Advisory Mode Recommended

Advisory Mode is the recommended daily mode. These commands do not modify code, do not generate patches, and do not apply changes.

Use Advisory Mode when you want to:

- understand a project;
- analyze code quality and risks;
- explain a file, symbol, or flow;
- generate a technical proposal;
- prepare a handoff prompt for another coding AI;
- review your own local diff before commit.

### Execution Mode Experimental

Execution Mode can plan changes, generate diffs, run tests, repair failures, apply patches, and commit changes.

Execution Mode is experimental. Review generated diffs carefully before applying. Use it only when you are comfortable inspecting the generated artifacts and validating the result.

## Core Workflow

Recommended advisory loop:

```bash
trevvos inspect
trevvos analyze
trevvos explain main.py --flow
trevvos propose "improve the CLI testability" --target main.py
trevvos spec "add sqrt to the calculator CLI" --target codex
trevvos review-diff
```

## Installation

Install in editable mode during local development:

```bash
python -m pip install -e .
```

## Requirements

- Python 3.11+
- Git for diff/review workflows
- Ollama for local LLM usage
- A local model such as `qwen2.5-coder`

Check the local environment:

```bash
trevvos doctor
```

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

List local Ollama models:

```bash
trevvos models list
```

Pull a model:

```bash
trevvos models pull qwen2.5-coder:7b
```

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

## Quick Start

Inspect a project:

```bash
trevvos inspect
```

Analyze the project:

```bash
trevvos analyze
```

Explain a file:

```bash
trevvos explain main.py
```

Generate a technical proposal:

```bash
trevvos propose "add authentication"
```

Generate a handoff prompt for another coding AI:

```bash
trevvos spec "add JWT authentication" --target codex
```

Review local changes before committing:

```bash
trevvos review-diff
```

## Commands

| Command | Mode | Modifies code? | Purpose |
|---|---|---:|---|
| `trevvos inspect` | Advisory | No | Scan project structure and save a project profile |
| `trevvos analyze` | Advisory | No | Analyze code quality, risks, tests, and architecture |
| `trevvos explain` | Advisory | No | Explain files, symbols, and execution flows |
| `trevvos propose` | Advisory | No | Generate a technical proposal before implementation |
| `trevvos spec` | Advisory | No | Generate an implementation handoff prompt for external AI |
| `trevvos review-diff` | Advisory | No | Review local git diffs before commit |
| `trevvos plan` | Execution | No | Plan code changes |
| `trevvos diff` | Execution | No | Generate and validate a patch |
| `trevvos test` | Execution | No | Run verification commands |
| `trevvos repair` | Execution | No | Generate a repair diff for a failed session |
| `trevvos apply` | Execution | Yes | Apply a validated patch after confirmation |
| `trevvos commit` | Execution | Yes | Commit related changes |
| `trevvos work` | Execution | No by default | Run a controlled experimental agent loop up to ready-to-apply |

## Advisory Commands

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

## Execution Commands Experimental

### `trevvos plan`

Creates a behavior-first change plan.

### `trevvos diff`

Generates a patch for the current planned session and validates it.

### `trevvos test`

Runs verification commands in the working tree or sandbox mode.

### `trevvos repair`

Generates a repair attempt when a valid diff exists and behavior/test/review evidence indicates a repairable issue.

### `trevvos apply`

Applies a validated patch after confirmation.

### `trevvos commit`

Commits related changes with generated commit metadata.

### `trevvos work`

Runs a controlled experimental loop: plan, diff, sandbox test, review, retry, and repair. It stops before apply by default.

## Example Workflows

### Understand A Project

```bash
trevvos inspect
trevvos analyze
trevvos explain main.py --flow
```

### Ask For A Technical Proposal

```bash
trevvos propose "create a Value Object Money" --target src/domain
```

### Generate A Handoff Prompt For Another Coding AI

```bash
trevvos spec "add JWT authentication" --target codex
```

Then copy:

```text
.trevvos/sessions/<id>/external_ai_prompt.md
```

### Review Human Changes

```bash
git diff
trevvos review-diff
```

### Try Execution Mode Experimentally

```bash
trevvos plan "add sqrt to the calculator CLI"
trevvos diff
trevvos test --sandbox
trevvos apply
```

Review generated diffs carefully before applying.

## Artifacts And Sessions

Forge writes session artifacts under:

```text
.trevvos/sessions/<session-id>/
```

Advisory sessions save reports, prompts, metadata, selected files, context, and project profile snapshots. Execution sessions may also save plans, patches, validations, tests, warnings, repair metadata, retry metadata, and commit artifacts.

## Safety Model

- Advisory commands do not modify code.
- Advisory commands do not generate patches.
- Execution Mode validates generated patches before apply.
- Patch application requires confirmation.
- Sandbox test mode can validate generated diffs without modifying the working tree.
- Sessions keep prompts, raw responses, metadata, and evidence for auditability.
- Forge does not replace tests, code review, or developer judgment.

See [docs/safety-model.md](docs/safety-model.md).

## Current Status

Early alpha.

Current limitations:

- Local LLM quality depends on the selected model.
- Advisory Mode is recommended for daily usage.
- Execution Mode is experimental.
- Structural edits generated by LLMs must be reviewed carefully.
- The tool does not replace tests, code review, or developer judgment.

## Roadmap

- Release polish and command help improvements.
- More examples and smoke demos.
- Stronger project intelligence.
- Additional advisory workflows.
- Continued hardening of Execution Mode.

## License

License information has not been added yet.
