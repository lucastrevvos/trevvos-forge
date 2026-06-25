# Alpha Success Criteria

Objective criteria for evaluating the outcome of the Trevvos Forge v0.1.0-alpha.1 test run.

---

## Minimum Viable Alpha

The Alpha is considered **successful** if all of the following are met:

| Criterion | Target |
|---|---|
| Successful installs (binary works on first launch) | â‰¥ 3 testers |
| Setup + Doctor completed | â‰¥ 2 testers |
| Advisory command completed successfully | â‰¥ 2 testers |
| Dashboard opened | â‰¥ 1 tester |
| Session exported | â‰¥ 1 tester |
| No critical safety issue found | Required |
| Advisory mode never modifies source code | Required |
| Actionable feedback items collected | â‰¥ 5 |

All "Required" criteria must pass. The numeric targets are minimums.

---

## Safety Hard Requirements

These are non-negotiable. If any fails, the Alpha is paused immediately:

- **Advisory mode must never modify source code.** Any confirmed case is a blocker.
- **`tests apply` must never modify production source files.** Test-only guardrail must hold.
- **Session exports must not expose real secrets in plain text.** Masking must work.
- **Local API must not be accessible from outside `127.0.0.1` by default.**

---

## Extended Success (Nice to Have)

If minimum criteria are met, these indicate a stronger Alpha:

| Criterion | Target |
|---|---|
| Controlled Testing Mode completed (tests add + apply) | â‰¥ 1 tester |
| At least 1 tester used Ollama | âœ“ |
| At least 1 tester used openai-compatible | âœ“ |
| Issues reported are medium/low severity (no critical) | âœ“ |
| Session exports received with no privacy concerns | âœ“ |
| Testers express willingness to test again | â‰¥ 2 |

---

## Alpha Pause Conditions

The Alpha should be **paused** if any of the following occurs:

- Binary fails to launch for the majority of testers (> 50%)
- `trevvos setup` or `trevvos doctor` is unusable for any single provider
- Session export leaks real secrets or credentials in plain text
- Advisory command modifies source files
- `tests apply` touches production source
- A critical security issue is discovered
- Multiple testers report data loss or unrecoverable project state

Pausing means: notify testers to stop, investigate, and either fix quickly or postpone.

---

## Decision Framework After the Test Window

Based on results, the following decisions are possible:

| Situation | Decision |
|---|---|
| All minimum criteria met, no critical bugs | Proceed to alpha.2 with fixes |
| Minimum criteria met, 1â€“2 high-priority bugs | alpha.2 with targeted fixes |
| < 3 successful installs, root cause identifiable | Fix installer, re-run alpha.1 |
| Critical safety issue found and fixed | Re-run alpha.1 after fix |
| Insufficient testers participated | Extend window or invite more |
| Fundamental flow broken for multiple testers | Assess and re-scope before alpha.2 |

---

## Metrics to Collect

Track these during the test window (fill in `docs/alpha-results-template.md`):

```
Testers invited:
Testers who installed successfully:
Testers who completed setup + doctor:
Testers who ran an advisory command:
Testers who opened the dashboard:
Testers who exported a session:
Testers who tested Controlled Testing Mode:
Issues opened (total):
Issues by severity: critical=  high=  medium=  low=
Session exports received:
```

---

## alpha.2 Scope Signal

After the Alpha, prioritize for `v0.1.0-alpha.1`:

1. All critical bugs (mandatory)
2. High-priority bugs affecting > 1 tester
3. Install friction that blocked testers
4. Docs gaps that caused confusion
5. Error messages that were unhelpful
6. Provider issues for a major provider

Do not include new features in alpha.2 unless the core flow is unblocked.


