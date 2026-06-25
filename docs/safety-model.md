# Safety Model

Trevvos Forge is local-first and artifact-driven.

The recommended Advisory Mode is designed to help developers without modifying code. Execution Mode can modify code, but only through explicit, reviewable steps.

## Local-First

Forge is designed around local workflows:

- local repository;
- local sessions under `.trevvos/`;
- local model provider support through Ollama;
- local git diff and validation commands.

## Sessions And Artifacts

Forge records work in session directories:

```text
.trevvos/sessions/<session-id>/
```

Artifacts can include:

- prompts;
- raw model responses;
- rendered reports;
- metadata;
- selected files;
- project profiles;
- generated diffs;
- validation results;
- sandbox results;
- review reports;
- retry and repair metadata;
- timeline events.

This makes the tool auditable: you can inspect what was asked, what was returned, and what evidence was used.

## Advisory Safety

Advisory commands:

- do not modify source files;
- do not create patches;
- do not apply patches;
- do not run commits;
- do not claim tests were run without evidence.

Advisory Mode is recommended for daily usage.

## Execution Safety

Execution commands can generate or apply changes, but include guardrails:

- structured model output parsing;
- schema validation;
- patch validation;
- `git apply --check`;
- sandbox tests;
- working-tree tests;
- confirmation before apply;
- repair and retry artifacts;
- warnings for risky structural edits;
- checks for CLI behavior preservation;
- blocked unsafe commands.

`trevvos apply` requires confirmation before modifying the working tree. High-risk warnings can require stronger confirmation.

## Sandbox

Sandbox test mode validates generated diffs without applying them directly to the working tree. This helps catch failures before the developer decides to apply.

```bash
trevvos test --sandbox
```

## Known Limitations

- Local LLM quality depends on the selected model.
- A patch can compile but still be behaviorally wrong.
- Structural edits should be reviewed carefully.
- Tests and code review remain necessary.
- Execution Mode is experimental.

## Practical Guidance

Use Advisory Mode first:

```bash
trevvos inspect
trevvos propose "describe the change"
trevvos spec "describe the change" --target codex
trevvos review-diff
```

Use Execution Mode only when you are prepared to review artifacts and validate the result.


