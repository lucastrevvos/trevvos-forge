# Advisory Mode

Advisory Mode is the recommended mode for the current Trevvos Forge MVP.

It helps you understand and plan software engineering work without changing the repository. Advisory commands do not modify code, do not create patches, and do not apply changes.

Use Advisory Mode when you want a local-first senior/tech lead assistant in the terminal.

### Project root and current directory

Advisory commands use the current working directory as the project root by default.

Run Trevvos Forge from the root of the project you want to inspect, analyze, explain, propose, spec, or review:

```bash
cd path/to/your/project
trevvos inspect
trevvos analyze
```

Relative file paths and `--target` values are resolved from the current working directory unless you pass an absolute path.

### Response language

Advisory reports can be written in English or Brazilian Portuguese.

Set a persistent default in the current project:

```bash
trevvos config set language pt-BR
trevvos config set language en
```

Override the language for a single advisory command with `--language`.

## What Advisory Mode Does

- Inspects project structure.
- Analyzes code quality, risks, tests, and architecture.
- Explains files, symbols, and execution flows.
- Generates technical proposals before implementation.
- Generates implementation handoff prompts for external coding AIs.
- Reviews local git diffs before commit.
- Inspects test coverage by source symbol (no LLM call).
- Saves session artifacts for auditability.

## Commands

### `trevvos inspect`

Scans the repository and writes `.trevvos/project_profile.json`.

```bash
trevvos inspect
trevvos inspect --json
trevvos inspect --refresh
```

### `trevvos analyze`

Produces a technical analysis report.

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

Generates a technical proposal without implementation.

```bash
trevvos propose "melhore a testabilidade da CLI" --target main.py
trevvos propose "criar um Value Object Money" --target src/domain
```

### `trevvos spec`

Generates an AI handoff spec and a copy-paste prompt for another coding AI.

```bash
trevvos spec "adicione sqrt na calculadora e exponha na CLI" --target codex
```

Copy the generated prompt into your preferred coding AI:

```text
.trevvos/sessions/<id>/external_ai_prompt.md
```

### `trevvos review-diff`

Reviews local changes before commit.

```bash
trevvos review-diff
trevvos review-diff --staged
```

### `trevvos tests inspect`

Inspects detected test coverage for a source file by symbol. Does not call the provider.

```bash
trevvos tests inspect calculator.py
trevvos tests inspect calculator.py --symbol divide
trevvos tests inspect --json
```

This is an advisory command — it does not modify code and does not create patches. To generate tests, use Controlled Testing Mode (`trevvos tests add`).

## Example Advisory Workflow

```bash
trevvos inspect
trevvos analyze
trevvos explain main.py --flow
trevvos propose "melhore a testabilidade da CLI" --target main.py
trevvos spec "adicione sqrt na calculadora e exponha na CLI" --target codex
trevvos review-diff
```

## Artifacts

Advisory commands save session artifacts under:

```text
.trevvos/sessions/<session-id>/
```

Typical artifacts include:

- prompt sent to the model;
- raw response;
- rendered report;
- metadata JSON;
- project profile snapshot;
- selected files;
- context used for the prompt.

## Guarantees

Advisory Mode:

- does not modify code;
- creates no patches;
- does not apply patches;
- does not commit changes;
- does not claim tests were run unless evidence is provided.

Developer judgment still matters. Advisory reports are guidance, not proof of correctness.
