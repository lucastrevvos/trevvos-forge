# Execution Mode

Execution Mode is experimental.

It can plan changes, generate patches, run tests, attempt repairs, apply diffs, and commit related changes. Use it carefully and review generated diffs before applying.

Execution commands also use the current working directory as the project root. Run them from the root of the Git repository or project you want to modify.
Execution reports can also honor the current project language setting or a per-command `--language` override when supported.

`trevvos tests add` is Controlled Execution: test files only. It can generate or apply a patch for unit tests, but it rejects production source targets.

## Important Warning

Execution Mode is experimental. Review generated diffs carefully before applying.

Local LLMs can produce structurally valid but semantically wrong code. Execution Mode includes guardrails, but it does not replace tests, code review, or developer judgment.

## Commands

### `trevvos plan`

Creates a behavior-first plan for a requested change.

```bash
trevvos plan "add sqrt to the calculator CLI"
trevvos plan --retry
```

### `trevvos diff`

Generates a patch for the current session.

```bash
trevvos diff
trevvos diff --retry
```

### `trevvos test`

Runs verification commands.

```bash
trevvos test
trevvos test --sandbox
```

### `trevvos tests add`

Generates or appends unit tests for a Python symbol. By default it is a dry-run: it creates a session, writes auditable artifacts, validates the patch with `git apply --check`, applies the patch in a temporary sandbox, runs the detected test command there, and does not modify the working tree.

```bash
trevvos tests add calculator.py --symbol divide
trevvos tests add calculator.py --all
trevvos tests add calculator.py --symbol divide --test-file tests/test_calculator.py
trevvos tests add calculator.py --symbol divide --force
trevvos tests add calculator.py --symbol divide --write
trevvos tests add calculator.py --symbol divide --keep-sandbox
```

With `--write`, Forge applies the generated patch only after sandbox tests pass and after confirmation, or immediately with `--yes`. A sandbox failure blocks writing even with `--yes`. The destination must be inside a test directory or match `test_*.py` / `*_test.py`.
Use `--symbol` for one function/class or `--all` for all public testable symbols in a Python file. The options are mutually exclusive.

When no `.trevvos/config.json` `test_commands` override is present, Forge tries to run the generated test file directly, such as `pytest tests/test_calculator.py` or `python -m unittest tests.test_calculator`. For pytest single-symbol generation, Forge uses a safe selector when possible, for example `pytest tests/test_calculator.py -k divide`. Configured `test_commands` take precedence over targeted commands.

Before calling the provider, Forge checks the target test file for existing tests that appear to cover the requested symbol(s). A covered `--symbol` request is skipped by default; `--all` targets only missing symbols when coverage is partial. Use `--force` to generate complementary tests anyway.

### `trevvos tests inspect`

Inspects detected test coverage by source symbol without calling the provider, generating a patch, applying changes, or running tests.

```bash
trevvos tests inspect calculator.py
trevvos tests inspect calculator.py --symbol divide
trevvos tests inspect calculator.py --all
trevvos tests inspect calculator.py --json
```

### `trevvos review`

Reviews a generated session using deterministic and optional LLM review.

```bash
trevvos review
trevvos review --no-llm
```

### `trevvos repair`

Attempts to generate a repair diff when there is a valid previous diff and repairable evidence.

```bash
trevvos repair
```

### `trevvos apply`

Applies a validated patch after confirmation.

```bash
trevvos apply
```

### `trevvos commit`

Commits related working-tree changes.

```bash
trevvos commit
```

### `trevvos work`

Runs a controlled experimental agent loop. It can plan, diff, retry, sandbox test, review, and repair. It stops before apply by default.

```bash
trevvos work "add sqrt to the calculator CLI"
```

## Guardrails

Execution Mode includes:

- structured plan artifacts;
- schema validation for model outputs;
- generated patch validation;
- test-file-only validation for `trevvos tests add`;
- `git apply --check`;
- sandbox validation before `trevvos tests add --write`;
- sandbox testing;
- retry metadata;
- repair metadata;
- warning artifacts;
- CLI regression checks;
- verification coverage checks;
- confirmation before apply.

## Recommended Experimental Flow

```bash
trevvos plan "add sqrt to the calculator CLI"
trevvos diff
trevvos test --sandbox
trevvos review --no-llm
trevvos apply
```

Before applying:

- inspect `diff.patch`;
- inspect warnings and review artifacts;
- run relevant tests;
- make sure existing behavior is preserved.

## When To Prefer Advisory Mode

Prefer Advisory Mode when:

- the change is structural;
- the project is unfamiliar;
- local model quality is uncertain;
- you want a proposal or handoff instead of automatic editing;
- you need a review before commit.


