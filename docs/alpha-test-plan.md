# Alpha Test Plan

This is the guided test plan for Trevvos Forge Alpha testers. Follow the steps in order. Report any issues using the template in [feedback-template.md](feedback-template.md).

---

## Before You Start

Have ready:

- A Python project to test against (any real project works — small is fine)
- An LLM provider: Ollama (recommended), LM Studio, or OpenAI API credentials

**Not required:** root access, Docker, cloud accounts.

---

## Step 0 — Environment Info

Before running anything, note your environment. You will need this for feedback reports:

```
OS:                      (e.g. Windows 11, Ubuntu 24.04, macOS 15)
Python version:          (python --version)
Shell:                   (bash, zsh, PowerShell)
Forge version/commit:    (git rev-parse --short HEAD)
Provider:                (ollama / openai-compatible)
Runtime:                 (ollama / external)
Base URL:                (e.g. http://localhost:11434)
Model:                   (e.g. qwen2.5-coder:7b)
Project language:        (Python, Node, .NET, other)
```

---

## Step 1 — Install

**Linux/macOS:**

```bash
git clone https://github.com/your-org/trevvos-forge.git
cd trevvos-forge
python -m venv .venv
source .venv/bin/activate
python -m pip install -e .
trevvos --help
```

**Windows PowerShell:**

```powershell
git clone https://github.com/your-org/trevvos-forge.git
cd trevvos-forge
python -m venv .venv
.\.venv\Scripts\Activate.ps1
python -m pip install -e .
trevvos --help
```

**Expected:** `trevvos --help` shows available commands with no errors.

**Report if:** install fails, `trevvos` command not found, or `--help` throws an exception.

---

## Step 2 — Setup

Navigate to the project you want to test with:

```bash
cd path/to/your/project
```

**Ollama:**

```bash
trevvos setup --provider ollama --model qwen2.5-coder:7b --yes
```

**OpenAI-compatible (LM Studio):**

```bash
trevvos setup --provider openai-compatible --base-url http://localhost:1234/v1 --model qwen2.5-coder-7b-instruct --yes
```

**OpenAI API (Linux/macOS):**

```bash
export TREVVOS_FORGE_API_KEY="sk-..."
trevvos setup --provider openai-compatible --base-url https://api.openai.com/v1 --model gpt-4.1-mini --yes
```

**OpenAI API (Windows PowerShell):**

```powershell
$env:TREVVOS_FORGE_API_KEY = "sk-..."
trevvos setup --provider openai-compatible --base-url https://api.openai.com/v1 --model gpt-4.1-mini --yes
```

**Expected:**
- Output shows provider, model, base URL, language.
- `.trevvos/config.json` created in the project directory.
- Doctor check runs (unless `--no-doctor` passed).

**Report if:** setup fails, config not created, provider/model not shown in output.

---

## Step 3 — Doctor

```bash
trevvos doctor
trevvos doctor --json
```

**Expected:**
- Provider shown.
- Model shown.
- Connectivity check passes (green).
- Duration shown.
- JSON output is valid JSON.

**Report if:** connectivity check fails unexpectedly, duration not shown, JSON not parseable.

---

## Step 4 — Inspect

```bash
trevvos inspect
trevvos inspect --json
```

**Expected:**
- `.trevvos/project_profile.json` written.
- Language, file count, and detected test commands shown.
- JSON output matches the human output.

**Report if:** profile not written, language not detected, exception thrown.

---

## Step 5 — Advisory Mode

Run each command against a real source file in your project. Replace `<file>` with a Python file, a module, or a directory.

```bash
trevvos analyze <file>
trevvos explain <file>
trevvos propose "Suggest improvements for this module" --target <file>
trevvos spec "Add a small new function to this module" --target generic
trevvos review-diff
```

**Check after each command:**

- No source files were modified (run `git status` to verify).
- Session artifacts created in `.trevvos/sessions/<id>/`.
- Duration shown.
- Output is relevant and in the correct language.

**Specific things to verify:**

| Command | Check |
|---|---|
| `analyze` | Report appears; mentions the file/module |
| `explain` | Explanation is clear; mentions code elements |
| `propose` | Proposal is relevant to the prompt |
| `spec` | Generates `external_ai_prompt.md` artifact |
| `review-diff` | Runs without error (empty output is OK if no staged changes) |

**Report if:** source files modified, no session created, error thrown, output clearly wrong.

---

## Step 6 — Controlled Testing Mode

Use a small Python file with simple functions for this step. A calculator or utility file works well.

```bash
# 6a. Inspect coverage
trevvos tests inspect <file>

# 6b. Generate a test patch (sandbox only — does NOT modify working tree)
trevvos tests add <file> --symbol <function_name>

# 6c. Review the patch before applying
cat .trevvos/sessions/$(trevvos sessions current)/test_patch.diff

# 6d. Apply the validated patch
trevvos tests apply --latest --yes

# 6e. Run the tests
python -m unittest discover -s tests

# 6f. Review the diff to confirm only test files changed
trevvos review-diff --staged
```

**Expected:**

- `tests inspect` shows symbols and coverage without calling the LLM.
- `tests add` generates a patch, runs sandbox validation, saves artifacts.
- Working tree unchanged after `tests add` (verify with `git status`).
- `tests apply` applies the patch to the test file only.
- Tests pass after apply.
- `review-diff` shows only test file changes.

**Report if:** production source files modified, sandbox failure not reported, `tests apply` applies without prior validation, tests fail after apply.

---

## Step 7 — Dashboard

```bash
trevvos api start --open
```

If `--open` does not open a browser, open `http://127.0.0.1:8765/` manually.

**Check:**

- Dashboard loads in the browser.
- Sessions panel shows sessions from previous steps.
- Clicking a session shows metadata and artifacts list.
- Clicking an artifact shows content (JSON, diff, text).
- Export command shown at the bottom of the session panel.
- Stop the server with `Ctrl+C`.

**Report if:** server fails to start, dashboard does not load, sessions not shown, artifact viewer crashes.

---

## Step 8 — Session Export

```bash
trevvos sessions export latest
trevvos sessions export latest --format json
```

**Expected:**

- Export file created (ZIP or JSON).
- File name printed.
- JSON format is valid JSON.
- Secrets in JSON artifacts are replaced with `"present"` (not real values).

**Review the export before reporting:** it contains source files and LLM prompts. Remove sensitive content if needed.

**Report if:** export fails, file not created, secrets not masked, large session causes error.

---

## Step 9 — Report Feedback

Use [docs/feedback-template.md](feedback-template.md) to structure your report.

Include:

1. Your environment info (Step 0).
2. Which steps you completed.
3. Any issues encountered (command, expected, actual, output).
4. Session export attached (after reviewing for sensitive content).

---

## Scope: What Is Out of Scope for This Alpha

Do not test these unless specifically asked:

- `trevvos plan`
- `trevvos diff`
- `trevvos repair`
- `trevvos apply`
- `trevvos work`
- `trevvos commit`

These are part of the experimental Execution Mode and are not ready for external testing.
