# Alpha Known Issues

This file tracks known issues during the Trevvos Forge v0.1.0-alpha.1 closed Alpha.

Update this file as issues are confirmed during the test run. Link to GitHub issues when available.

---

## Known Before Testing

These issues were identified before the Alpha test run began.

| Area | Summary | Severity | Workaround |
|---|---|---|---|
| Platform | macOS binary not available | Medium | Use source install (Python 3.11+ required) |
| Platform | Linux ARM64 not supported | Medium | Not yet available |
| Platform | Alpine/musl Linux not supported | Medium | Use a glibc-based distro |
| Runtime | Managed llama.cpp runtime not implemented | Low | Use `runtime: external` with a running llama.cpp server |
| Execution Mode | `plan`, `diff`, `apply`, `repair`, `work` are experimental | High | Do not use in Alpha unless guided |
| Dashboard | No auto-refresh | Low | Click Refresh or reload the page |
| Provider | Some OpenAI-compatible servers may not implement `/v1/models` | Low | Doctor shows a warning but Forge still works |
| AI output | Generated advisory output may be incorrect | Expected | Review all suggestions before acting |
| AI output | Test generation strongest on small Python files | Expected | Use smaller, self-contained source files |
| API key | Must be set as `TREVVOS_FORGE_API_KEY` env var; not saved by setup | Low | Set env var before running `trevvos setup` and `trevvos doctor` |
| Windows | First launch may be slow due to antivirus scanning | Low | Wait for scan to complete; add exception if needed |
| Windows | SmartScreen warning on first launch | Low | Click "More info" → "Run anyway" |

---

## Reported During Alpha

*This section is filled in as testers report issues. Add a row for each confirmed bug.*

| ID | Date | Severity | Area | Summary | Status | GitHub Issue |
|---|---|---|---|---|---|---|
| — | — | — | — | No issues reported yet | — | — |

---

## Resolved During Alpha

*Issues that were fixed during the Alpha window.*

| ID | Summary | Fixed In | Notes |
|---|---|---|---|
| — | — | — | — |

---

## How to Update This File

When a tester reports an issue:

1. Add a row to "Reported During Alpha" with the date, severity, and brief summary.
2. Link to the GitHub issue.
3. Update Status: `open`, `confirmed`, `fixed`, `wontfix`, `deferred`.
4. When fixed, move the row to "Resolved During Alpha".

Severity follows `docs/alpha-feedback-triage.md` definitions.
