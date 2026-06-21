# Trevvos Forge

Trevvos Forge is a local-first AI engineering engine powered by local LLMs.

The goal is to provide a developer tool that can:

- ask technical questions using local models;
- generate code from prompts;
- understand project structure;
- propose safe changes;
- generate diffs before applying modifications.

The project currently uses Ollama as the first local LLM provider.

## Status

Early alpha.

## Local development

Install in editable mode:

```bash
python -m pip install -e .
```

Generate code:

```bash
trevvos generate "create a function that validates an email" --language python
```

Check your local environment:

```bash
trevvos doctor
```

List local Ollama models:

```bash
trevvos models list
```

Pull a model using Ollama:

```bash
trevvos models pull qwen2.5-coder:1.5b
```

Setup your local environment:

```bash
trevvos setup

trevvos setup --model qwen2.5-coder:1.5b
```

Scan a local project:

```bash
trevvos scan

trevvos scan ./my-project --max-files 100
```

Plan a project change:

```bash
trevvos plan "add JWT authentication to this project"

trevvos plan "improve this project structure" --path ./my-project
```

## Prompts

List versioned prompts:

```bash
trevvos prompts list

trevvos prompts show plan_change
```

## Context

Build automatic context for a request:

```bash
trevvos context "add tests for the CLI"

trevvos context "add persistent config" --max-files 5 --max-chars 20000
```

## Plan

Create a project change plan and save it into a local session:

```bash
trevvos plan "add tests for the CLI"
```

## Diff

Generate a diff from the current planned session:

```bash
trevvos diff
```

Use a specific session:

```bash
trevvos diff --session <session-id>
```

The diff command saves:

- `diff_prompt.md`
- `diff_prompt_metadata.json`
- `diff_raw_response.patch`
- `diff.patch`

## Diff validation

Generated diffs are validated before apply.

The validation checks:

- unsafe paths;
- sensitive files;
- ignored directories;
- binary patches;
- deletion attempts;
- existing files modified outside the selected context.
