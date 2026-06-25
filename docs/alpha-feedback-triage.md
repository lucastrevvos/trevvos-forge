# Alpha Feedback Triage

Guide for triaging issues reported during the closed Alpha test run.

---

## GitHub Labels

Apply these labels to Alpha issues. Create them in the repository before the test window opens.

**Status:**

| Label | Use |
|---|---|
| `alpha` | All issues from the Alpha test run |
| `alpha.2` | Targeted for v0.1.0-alpha.1 |
| `needs-export` | Waiting for session export from tester |
| `needs-reproduction` | Cannot reproduce yet |
| `confirmed` | Issue confirmed by maintainer |
| `wontfix` | Acknowledged, not planned |

**Severity:**

| Label | Meaning |
|---|---|
| `critical` | Blocks Alpha; immediate action required |
| `high` | Significant UX/functionality failure |
| `medium` | Friction or confusion, workaround exists |
| `low` | Polish, wording, minor doc gap |

**Area:**

| Label | Use |
|---|---|
| `installer` | Binary extraction, first launch |
| `setup` | `trevvos setup` command |
| `provider` | Provider connectivity issues |
| `ollama` | Ollama-specific issues |
| `openai-compatible` | OpenAI-compatible provider issues |
| `doctor` | `trevvos doctor` issues |
| `advisory` | Advisory mode commands |
| `controlled-testing` | `tests add`, `tests apply`, `tests inspect` |
| `dashboard` | Local API / dashboard |
| `session-export` | `trevvos sessions export` |
| `docs` | Documentation gaps or errors |
| `windows` | Windows-specific issues |
| `linux` | Linux-specific issues |
| `feedback` | Observation or suggestion (not a bug) |

---

## Severity Definitions

### Critical

Requires immediate action. Alpha should be paused if more than one critical issue is open.

- Binary does not start for most testers
- `trevvos setup` completely unusable
- `trevvos doctor` crashes or produces invalid output
- Binary missing essential files after extraction
- Advisory command modifies source code (safety violation)
- Session export leaks real secrets (api_key, tokens) in plain text
- `tests apply` modifies production source files

### High

Significant failure. Fix targeted for alpha.2.

- Provider setup fails for one major provider (Ollama or openai-compatible)
- Dashboard fails to load or crash on artifact view
- `tests apply` applies patch to wrong file (still a test file)
- `tests add` never succeeds (all retries exhausted) with a reasonable model
- Session export fails to produce output file
- `trevvos inspect` crashes on a typical project

### Medium

Friction or confusion. Workaround exists or limited impact.

- Error message is confusing or missing
- Doc step is inaccurate or outdated
- Install requires extra steps not documented
- Model name mismatch not explained clearly
- `--help` output missing useful detail
- Dashboard shows sessions from wrong directory
- Advisory output language mismatch

### Low

Polish, typos, minor improvements.

- Wording in output could be clearer
- Minor doc typo or formatting issue
- Non-essential feature missing
- Cosmetic dashboard issue

---

## Triage Workflow

For each new issue:

```
1. Confirm OS, provider, model, Forge version
   â†’ Ask if not provided: "Could you share your OS, provider, and model?"

2. Confirm the command used
   â†’ Ask: "What exact command did you run?"

3. Confirm the output / error message
   â†’ Ask: "Could you paste the full terminal output?"

4. Request session export if not attached
   â†’ "Could you run `trevvos sessions export latest` and attach the output?
      Please review it for sensitive content before sharing."

5. Try to reproduce locally with the same OS/provider/model

6. Assign severity label (critical/high/medium/low)

7. Assign area label (installer/setup/provider/etc.)

8. Decide disposition:
   - alpha.2 blocker â†’ label alpha.2, link to known issues
   - docs fix â†’ fix immediately, label docs
   - not a bug â†’ explain and close with wontfix
   - cannot reproduce â†’ label needs-reproduction, ask for more info
   - deferred â†’ label later or not planned
```

---

## Asking for Session Exports

Template message:

```
Thanks for the report! Could you attach a session export to help us investigate?

```bash
trevvos sessions export latest
```

Please review the export before attaching â€” it contains source code and LLM prompts.
If there is anything sensitive, describe the issue in general terms instead.
```

---

## Weekly Triage Cadence

During the Alpha test window, triage new issues once per day:

1. Assign labels to unlabeled Alpha issues.
2. Respond to issues pending tester input (`needs-export`, `needs-reproduction`).
3. Update `docs/alpha-known-issues.md` with confirmed bugs.
4. Flag any critical issues for immediate attention.
5. Note triage count in `docs/alpha-results-template.md`.


