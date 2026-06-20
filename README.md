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
