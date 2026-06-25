# Controlled Testing Mode

Controlled Testing Mode is an auditable, sandboxed workflow for generating unit tests. It only modifies test files, never production source code.

The mode is suitable for Alpha testing. It is distinct from Advisory Mode (read-only) and from Execution Mode (experimental, general code changes).

---

## The Flow

```
trevvos tests inspect <file>      â† coverage report, no LLM call
         â†“
trevvos tests add <file>          â† generates patch, validates in sandbox
         â†“ (review artifacts)
trevvos tests apply --latest      â† applies validated patch to working tree
         â†“
python -m unittest discover -s tests  â† run tests
```

Each step is explicit. No automatic apply. No LLM call at apply time.

---

## Commands

### `trevvos tests inspect`

Inspects coverage for a source file without calling the provider.

```bash
trevvos tests inspect calculator.py
trevvos tests inspect src/domain/money.py
trevvos tests inspect calculator.py --symbol divide
```

Output shows which symbols are detected, whether a test file exists, and which symbols appear to have coverage.

```bash
trevvos tests inspect --json
```

Returns structured JSON for scripting.

### `trevvos tests add`

Generates a test patch for a source file and validates it in a sandbox.

```bash
trevvos tests add calculator.py
trevvos tests add calculator.py --symbol add
trevvos tests add calculator.py --symbol "add,subtract"
```

Forge:
1. Inspects the source file for symbols.
2. Reads existing tests to avoid duplicates.
3. Calls the provider to generate test cases.
4. Writes the patch to a temp directory and validates it (runs the test commands in a sandbox).
5. Saves session artifacts: patch, sandbox result, prompts, metadata.
6. Does **not** modify the working tree by default.

If the patch is invalid or tests fail in sandbox, Forge retries (up to the configured budget). If all retries fail, the session is saved as `failed` and no patch is applied.

**Options:**

```bash
trevvos tests add calculator.py --session-id my-session
trevvos tests add calculator.py --no-progress
trevvos tests add calculator.py --json
```

**Dry-run (inspect only, no LLM call):**

```bash
trevvos tests add calculator.py --dry-run
```

### `trevvos tests apply`

Applies an already-validated test patch to the working tree.

```bash
trevvos tests apply                  # apply current session
trevvos tests apply --latest         # apply latest session
trevvos tests apply --session <id>   # apply specific session
trevvos tests apply --latest --yes   # skip confirmation prompt
```

`tests apply` does not call the LLM. It applies the patch saved by `tests add` using `git apply`. If the patch is already applied, it exits cleanly.

**After applying:**

```bash
python -m unittest discover -s tests
```

Or use whichever test command is configured:

```bash
trevvos config get test_commands
```

---

## Session Artifacts

After `tests add`, artifacts are saved to:

```text
.trevvos/sessions/<session-id>/
  metadata.json           â† session id, status, timestamps
  test_patch.diff         â† the generated patch
  sandbox_result.json     â† sandbox validation result
  selected_files.json     â† files selected as context
  system_prompt.txt       â† system prompt used
  user_prompt.txt         â† user prompt used
  raw_llm_response.txt    â† raw LLM response
```

Review artifacts before applying:

```bash
cat .trevvos/sessions/<id>/test_patch.diff
cat .trevvos/sessions/<id>/sandbox_result.json
```

Or open the dashboard:

```bash
trevvos api start --open
```

---

## Listing and Exporting Sessions

```bash
trevvos sessions list
trevvos sessions show <session-id>
trevvos sessions export latest
trevvos sessions export latest --format json
```

---

## Safety Properties

- Controlled Testing Mode only modifies test files, never production source.
- `tests add` does not modify the working tree during generation â€” the sandbox runs in a temporary directory.
- `tests apply` requires explicit invocation. There is no automatic apply.
- `tests apply` uses `git apply --check` before applying. If the patch is already applied, it exits cleanly.
- Session artifacts are preserved for audit: the patch, sandbox result, prompts, and metadata are all saved.
- The provider is called only during `tests add`, never during `tests apply`.
- Secrets in session JSON artifacts are masked when exported via `trevvos sessions export`.

---

## Retry Budget

If the provider generates an invalid patch, `tests add` retries automatically:
- Structure validation failure (malformed JSON or code) â†’ retry with clarified prompt
- Diff application failure â†’ retry with error context
- Sandbox test failure â†’ retry with failure context

The default retry budget is 3 attempts. When all retries are exhausted, the session is saved as `failed`.

To see a failed session:

```bash
trevvos sessions list
trevvos sessions show <failed-session-id>
trevvos sessions export <failed-session-id>
```

---

## Example: Python Calculator

```bash
# 1. Inspect coverage
trevvos tests inspect calculator.py

# 2. Add tests for the subtract symbol
trevvos tests add calculator.py --symbol subtract

# 3. Review the patch
cat .trevvos/sessions/$(trevvos sessions current)/test_patch.diff

# 4. Apply the patch
trevvos tests apply --latest --yes

# 5. Run tests
python -m unittest discover -s tests
```

---

## Troubleshooting

**Session shows as `failed`:**  
Run `trevvos sessions show <id>` and check `sandbox_result.json`. The failure reason is usually a syntax error in the generated patch or a test that fails on import. Try with a different model or a smaller `--symbol` scope.

**Patch already applied:**  
`tests apply` detects this via `git apply --reverse --check` and exits cleanly. This is not an error.

**Obsolete patch (source changed since generation):**  
`tests apply --latest` skips sessions with obsolete patches. Generate a new patch with `tests add`.

See [troubleshooting.md](troubleshooting.md) for more.


