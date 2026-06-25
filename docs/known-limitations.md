# Known Limitations

This document lists known limitations and constraints in Trevvos Forge Alpha. Being transparent about these helps testers focus on the right areas and avoid frustration.

---

## Experimental Execution Mode

The following commands are **experimental** and are **not recommended** for Alpha testing unless specifically guided:

```bash
trevvos plan
trevvos diff
trevvos repair
trevvos apply
trevvos work
trevvos commit
```

These commands can modify production source code. They are under active development and may produce incorrect patches, fail silently, or leave the working tree in an inconsistent state.

Use `trevvos tests apply` (Controlled Testing Mode) instead for any apply workflows in this Alpha.

---

## AI Output Quality

- **Advisory reports are AI-generated.** They may contain errors, hallucinations, or irrelevant content. Review before acting on any recommendation.
- **Generated test patches may be wrong.** The sandbox validates that tests run, not that they are correct. Always review generated tests before applying.
- **Explanations and proposals are not authoritative.** Treat them as a first draft from a fast junior reviewer, not as architectural decisions.
- **Output quality depends heavily on the model.** Smaller models (3b, 7b) will produce lower-quality results than larger models (14b, 32b). OpenAI API models generally outperform small local models for code tasks.

---

## Controlled Testing Mode

- **Strongest on small Python files with simple functions.** Complex modules with many dependencies, metaclasses, or heavy I/O may produce lower-quality patches.
- **Non-Python test generation is limited.** Basic Node.js and .NET support exists but is less tested.
- **Test sandbox may not replicate your full environment.** If the sandbox passes but real tests fail, the generated test may have missing imports or incorrect assumptions.
- **`tests add` retries up to 3 times** on failure. If all retries fail, the session is saved as `failed` and no patch is applied. This is the correct behavior.
- **`tests apply` only applies validated patches.** If a session is `failed` or `obsolete`, apply will not proceed.

---

## Advisory Mode

- **`review-diff` requires local git changes to show anything.** If there are no uncommitted changes, the output will be empty or minimal.
- **`spec` generates a prompt for an external AI, not an implementation.** Use it to hand off a task to Copilot, Codex, or similar â€” it does not implement changes itself.
- **Report quality depends on how much context Forge can gather.** Projects with unusual structures or no Python/Node/.NET markers may produce generic reports.

---

## Provider and Runtime

- **Ollama must be running before any command that calls the provider.** Forge can start Ollama via `trevvos runtime start` but this only works if Ollama is installed and in the system PATH.
- **`trevvos doctor` may not detect all issues.** The doctor checks connectivity, but does not validate model output quality.
- **Some OpenAI-compatible runtimes do not implement `/v1/models`.** The doctor will report a warning but this does not prevent Forge from working.
- **API key is expected via environment variable.** `trevvos setup` does not save `api_key` to `.trevvos/config.json`. Set `TREVVOS_FORGE_API_KEY` before running commands.
- **Timeout is 320 seconds by default.** Large models on slow hardware may exceed this. Set `TREVVOS_FORGE_TIMEOUT` to a higher value if needed.

---

## Dashboard and Local API

- **Dashboard is basic.** It shows session metadata and artifacts but has no filtering, search, or timeline view.
- **No auto-refresh.** The dashboard does not update automatically. Click Refresh or reload the page.
- **Local API is read-only.** No endpoints modify sessions or configuration.
- **Local API binds to `127.0.0.1`.** It is not accessible from other machines.

---

## Session Export

- **Files over 1 MB are skipped by default.** Use `--include-large-files` to include them.
- **Source files are included in exports.** Secrets in JSON and config artifacts are masked, but raw source code is not redacted. Review exports before sharing.
- **Symlinks are skipped** in session exports.

---

## Not Yet Implemented

- Managed llama.cpp runtime (planned).
- Cloud sync or remote session access.
- PyPI package distribution (install from source only for now).
- Portuguese-language UI strings (reports can be in Portuguese, but CLI output is English).
- Prompt customization or catalog.
- Auto-detection of Python venv for sandbox (uses the active venv at command time).

---

## Platform Notes

- **Windows support is best-effort.** The core workflows are tested on Windows but some edge cases may differ from Linux/macOS.
- **Python 3.11+ required.** Earlier versions are not supported.


