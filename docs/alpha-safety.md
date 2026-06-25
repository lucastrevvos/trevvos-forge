# Safety Model

Trevvos Forge is designed to be safe by default. This document describes the safety properties of each workflow.

---

## Safe-by-Default Workflows

### Advisory Mode

Advisory Mode commands are **read-only**. They do not modify code, do not create patches, and do not apply changes.

```bash
trevvos inspect
trevvos analyze
trevvos explain
trevvos propose
trevvos spec
trevvos review-diff
trevvos tests inspect
```

You can run any of these commands on a production codebase without risk of modification. The worst-case outcome is a bad advisory report.

**Verification:** After any advisory command, run `git status` to confirm no files were modified.

### Controlled Testing Mode

Controlled Testing Mode is designed to apply changes in a bounded, auditable way: only to test files, only after validation.

```bash
trevvos tests inspect     # read-only, no LLM call
trevvos tests add         # sandbox only â€” does NOT modify working tree
trevvos tests apply       # explicit apply, test files only
```

Safety properties of this mode:

| Property | Detail |
|---|---|
| Working tree unchanged during `tests add` | Sandbox runs in a temp directory |
| No automatic apply | Apply requires explicit `trevvos tests apply` invocation |
| Validated patch only | `tests apply` applies only patches that passed sandbox validation |
| Test files only | The test-only guardrail prevents patches touching production source |
| Structural validation | Generated patch is validated for correct diff format before sandbox |
| Session artifacts preserved | Patch, sandbox result, prompts, and metadata saved for audit |
| No LLM at apply time | Provider is called only during `tests add`, not during `tests apply` |
| `git apply --check` before apply | Detects already-applied or obsolete patches before touching the tree |

If `tests add` fails (sandbox test failure, structural error, diff error), the session is saved as `failed` and no patch is applied. You can inspect the failure in the session artifacts and retry.

---

## Experimental Mode (Not Recommended for Alpha)

Execution Mode commands may modify production source code and should not be used in Alpha unless specifically guided:

```bash
trevvos plan      # plans changes (read-only)
trevvos diff      # generates a patch (read-only)
trevvos repair    # generates a repair patch (read-only)
trevvos apply     # MODIFIES WORKING TREE â€” requires confirmation
trevvos work      # agent loop, may reach apply
trevvos commit    # CREATES GIT COMMIT
```

`trevvos apply` requires explicit user confirmation before modifying the working tree, but it can modify any file in the project. Do not run it on a project without a clean git state.

---

## Local Data and Privacy

### What Forge Stores Locally

Session data is written to `.trevvos/sessions/<id>/` under the project root. Typical artifacts:

- Prompts sent to the LLM (may contain source code)
- Raw LLM responses
- Generated patches and diffs
- Sandbox results
- Metadata (timing, provider, model, status)
- Selected source files used as context

Forge does **not** send data to any external service â€” only to the configured LLM provider endpoint.

### API Keys

- `trevvos setup` does not save `api_key` to `.trevvos/config.json`.
- Set `TREVVOS_FORGE_API_KEY` in the environment when using OpenAI or other API-key-based providers.
- The local API masks secrets in JSON responses (keys matching `api_key`, `token`, `secret`, `password`, `authorization`, `auth` are replaced with `"present"`).
- Session exports mask the same keys in JSON artifacts.
- Source files in exports are not redacted â€” review before sharing.

### Local API

- The API server binds to `127.0.0.1` by default.
- It is not accessible from other machines on the network.
- All endpoints are read-only.
- Do not expose the API on a public network.

### Session Exports

Exports created with `trevvos sessions export` may contain:

- Source code snippets used as LLM context
- LLM prompts and raw responses
- Generated test patches

Secrets in JSON artifacts are masked automatically. Source file content is not redacted.

**Always review exports before sharing with anyone outside your team.**

---

## Summary Table

| Feature | Safe? | Notes |
|---|---|---|
| Advisory commands | Yes â€” read-only | No code changes possible |
| `tests inspect` | Yes â€” read-only | No LLM call |
| `tests add` | Yes â€” sandbox only | Working tree unchanged |
| `tests apply` | Bounded â€” test files only | Explicit invocation required |
| `trevvos apply` | Experimental | Modifies working tree after confirmation |
| Local API | Yes â€” read-only | Localhost only, secrets masked |
| Session export | Yes | Review before sharing |
| `api_key` in config | No | Never saved to disk by setup |


