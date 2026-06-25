# Alpha Runbook

Operational guide for the maintainer during the Trevvos Forge closed Alpha test run.

---

## Before Inviting Testers

Complete the release checklist (`docs/release-checklist.md`) first, then verify:

```
- [ ] Release v0.1.0-alpha.1 published as pre-release on GitHub
- [ ] Windows ZIP uploaded and download confirmed
- [ ] Linux tar.gz uploaded and download confirmed
- [ ] SHA256SUMS.txt uploaded
- [ ] Release notes accurate (RELEASE_NOTES.md)
- [ ] Download/install guide reviewed (docs/alpha-download-install.md)
- [ ] Issue template available (.github/ISSUE_TEMPLATE/alpha-feedback.md)
- [ ] Feedback channel ready (GitHub Issues / Slack / email)
- [ ] Alpha invite message ready (docs/alpha-tester-invite.md)
- [ ] Known issues documented (docs/alpha-known-issues.md)
- [ ] Success criteria defined (docs/alpha-success-criteria.md)
```

---

## Tester Selection

**Recommended number:** 2–5 developers.

**Selection criteria:**

- Comfortable with terminal and CLI tools
- Has a small-to-medium Python project available (non-sensitive for first test)
- Willing to spend 1–3 hours on structured testing
- Can provide specific feedback with session exports

**Platform diversity:**

- At least 1 Windows tester
- At least 1 Linux tester (Ubuntu 22.04 preferred for glibc compatibility)
- macOS testers: inform that macOS binary is not available; source install is possible if they have Python

**Provider diversity:**

- At least 1 Ollama tester
- At least 1 OpenAI-compatible tester (LM Studio or API)

**Avoid:**

- Projects with credentials, private keys, or highly sensitive business logic in source files
- Testers unfamiliar with basic git/terminal workflows
- More than 5 testers in the first run (keep it manageable)

---

## Test Window

**Recommended duration:** 3–7 days.

**Suggested schedule:**

```
Day 0: Send invite + release URL
Day 1: Check if testers can install; troubleshoot blockers
Day 2-5: Active testing period; respond to issues within 24h
Day 6: Remind testers to submit feedback
Day 7: Close test window; collect final feedback
Day 8+: Triage results; prepare alpha.2 scope
```

---

## Sending the Invite

Customize `docs/alpha-tester-invite.md` with:
- Specific GitHub Release URL
- Test window dates
- Feedback channel info (GitHub Issues URL, Slack channel, email)

Send individually or in a group channel. Include:
- Release URL
- Invite text (English or Portuguese version)
- Link to `docs/alpha-download-install.md`

---

## Daily Maintainer Routine

During the test window, check once per day:

```
1. Check GitHub Issues for new reports
2. Label new issues (see docs/alpha-feedback-triage.md)
3. Ask for session export when an issue lacks context
4. Update docs/alpha-known-issues.md with confirmed issues
5. Identify blockers (critical severity)
6. Ping testers if no activity after 2 days
7. Note any tester who completed the full test plan
```

**Responding to issues:**

- Acknowledge within 24 hours
- Ask for: OS, provider, model, command, output, session export
- Do not promise fixes during the Alpha window — log them for alpha.2
- For critical bugs: investigate and patch immediately if possible

---

## Handling Critical Issues

If a critical issue is found (binary fails for most testers, secrets leak, advisory mode modifies code):

1. Pause the Alpha — notify testers to stop testing.
2. Investigate immediately.
3. If fixable: patch and re-release as `v0.1.0-alpha.1.1` or `v0.1.0-alpha.2`.
4. If not immediately fixable: document in `alpha-known-issues.md` and limit scope.

See `docs/alpha-success-criteria.md` for pause conditions.

---

## After the Test Window

1. **Collect all feedback:** GitHub issues, direct messages, session exports.
2. **Fill in `docs/alpha-results-template.md`** with metrics.
3. **Triage all issues** (see `docs/alpha-feedback-triage.md`).
4. **Evaluate against success criteria** (see `docs/alpha-success-criteria.md`).
5. **Decide next step:**
   - Release `v0.1.0-alpha.2` with critical fixes
   - Expand to more testers
   - Continue alpha.1 if sufficient data not yet collected
   - Pause Alpha if critical unresolved bugs
6. **Prepare alpha.2 scope** based on high-priority findings.
7. **Thank testers** and share a brief summary of what was found.

---

## Escalation

If a tester reports sensitive data exposure in a session export:

1. Ask them not to share the export publicly.
2. Ask them to describe the issue in general terms without attaching the file.
3. Investigate the redaction logic (`trevvos_forge/redaction.py`).
4. If real exposure confirmed: treat as critical, pause Alpha, fix immediately.
