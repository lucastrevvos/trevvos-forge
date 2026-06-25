# Trevvos Forge Alpha Feedback

Copy this template for each bug report or piece of feedback. Fill in the relevant sections.

---

## Summary

*One sentence: what happened?*

---

## Environment

```
OS:
Python version:        (python --version)
Shell:                 (bash / zsh / PowerShell)
Forge version/commit:  (git rev-parse --short HEAD)
Provider:              (ollama / openai-compatible)
Runtime:               (ollama / external)
Base URL:
Model:
Project language:
Project framework:     (optional)
```

---

## Command Used

```bash
trevvos ...
```

---

## Expected Behavior

*What did you expect to happen?*

---

## Actual Behavior

*What actually happened?*

---

## Output / Error

```
paste the terminal output here
```

---

## Steps to Reproduce

1. ...
2. ...
3. ...

---

## Session Export

Export your session and attach it to the report:

```bash
trevvos sessions export latest
```

Or for a specific session:

```bash
trevvos sessions export <session_id>
```

**Before attaching:** review the export for sensitive project data. Secrets in JSON artifacts are masked automatically, but source file content is included. Remove or redact anything you cannot share.

---

## Safety Check

- [ ] I reviewed the session export before attaching.
- [ ] The export does not contain credentials, private keys, or confidential source code that I cannot share.
- [ ] Not applicable â€” I am not attaching an export.

---

## Additional Context

*Anything else that may be relevant: model behavior, project characteristics, related commands, workarounds you tried.*


