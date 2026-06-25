---
name: Alpha Feedback
about: Report feedback, bugs, or observations from the Trevvos Forge closed Alpha
title: "[Alpha feedback]: "
labels: alpha, feedback
assignees: ''
---

## Severity

- [ ] Critical (binary unusable, safety issue, data loss)
- [ ] High (significant workflow failure, major provider issue)
- [ ] Medium (friction, confusing error, docs gap)
- [ ] Low (wording, polish, minor doc typo)

---

## Artifact Used

- [ ] Windows x64 ZIP (`trevvos-forge-v0.1.0-alpha.1-windows-x64.zip`)
- [ ] Linux x64 tar.gz (`trevvos-forge-v0.1.0-alpha.1-linux-x64.tar.gz`)
- [ ] Source install (Python + pip)

---

## Environment

```
OS:                        (e.g. Windows 11, Ubuntu 24.04)
Trevvos Forge version:     (trevvos --version)
Provider:                  (ollama / openai-compatible)
Runtime:                   (ollama / external)
Base URL:                  (e.g. http://localhost:11434)
Model:                     (e.g. qwen2.5-coder:7b)
Shell:                     (PowerShell / bash / zsh)
Project language:          (Python / Node / .NET / other)
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
paste terminal output here
```

---

## Steps to Reproduce

1. ...
2. ...
3. ...

---

## Session Export

Export the relevant session and attach it:

```bash
trevvos sessions export latest
```

**Before attaching:** review the export for sensitive project data. Secrets in JSON artifacts are masked. Source file content is not redacted — remove anything confidential.

---

## Safety Check

- [ ] I reviewed the session export before attaching.
- [ ] The export does not contain credentials or confidential source code I cannot share.
- [ ] I am not attaching an export (not applicable to this report).
