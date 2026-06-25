# Alpha Release Checklist

Internal checklist to complete before sending Forge to Alpha testers.

---

## Code Health

```bash
python -m unittest discover -s tests
python -m compileall trevvos_forge tests
python -m pip install -e .
trevvos --help
trevvos setup --help
trevvos doctor --json
trevvos api start --help
```

- [ ] All tests pass
- [ ] No compile errors in `trevvos_forge` or `tests`
- [ ] Package installs cleanly in a fresh venv
- [ ] `trevvos --help` shows all expected commands
- [ ] `trevvos setup --help` shows all options including `--provider`, `--model`, `--yes`
- [ ] `trevvos doctor --json` returns valid JSON
- [ ] `trevvos api start --help` shows `--open` and `--port`

---

## Smoke Test — Ollama

Run these against a small Python project:

```bash
trevvos setup --provider ollama --model qwen2.5-coder:7b --yes
trevvos doctor
trevvos inspect
trevvos analyze <file>
trevvos explain <file>
trevvos tests inspect <file>
trevvos tests add <file> --symbol <function>
trevvos tests apply --latest --yes
trevvos api start --open
trevvos sessions export latest
```

- [ ] Setup writes config correctly
- [ ] Doctor shows green for Ollama
- [ ] Inspect writes `.trevvos/project_profile.json`
- [ ] Analyze produces a relevant report
- [ ] Explain produces a relevant explanation
- [ ] Tests inspect shows symbols
- [ ] Tests add succeeds and sandbox passes
- [ ] Tests apply applies to test file only (verify with `git status`)
- [ ] Dashboard opens and shows sessions
- [ ] Export creates a valid ZIP or JSON

---

## Smoke Test — OpenAI-compatible

```bash
trevvos setup --provider openai-compatible --base-url http://localhost:1234/v1 --model <model> --yes
trevvos doctor
trevvos analyze <file>
```

- [ ] Setup writes config with `provider: openai-compatible` and `runtime: external`
- [ ] Doctor shows connectivity check for openai-compatible
- [ ] Analyze produces output

---

## Documentation Review

- [ ] `README.md` links to `ALPHA.md`
- [ ] `ALPHA.md` is accurate and links to sub-docs
- [ ] `docs/alpha-quickstart.md` has working install + setup commands
- [ ] `docs/alpha-test-plan.md` is complete and a new tester can follow it
- [ ] `docs/feedback-template.md` is clear
- [ ] `docs/known-limitations.md` mentions Execution Mode as experimental
- [ ] `docs/alpha-safety.md` covers advisory, controlled testing, API keys, and export
- [ ] `docs/troubleshooting.md` covers common issues

---

## Safety Checks

- [ ] Execution Mode commands (`plan`, `diff`, `apply`, `repair`, `work`) are clearly marked experimental in docs
- [ ] API key is not saved to config by `trevvos setup` (verify `.trevvos/config.json` after setup with `TREVVOS_FORGE_API_KEY` set)
- [ ] Local API binds to `127.0.0.1` by default (verify `trevvos api start` output)
- [ ] Session export masks `api_key` and other sensitive keys in JSON artifacts
- [ ] Advisory commands do not modify working tree (verify with `git status` after `analyze`, `explain`, `propose`, `spec`, `review-diff`)
- [ ] `tests add` does not modify working tree (verify with `git status` after `tests add`)

---

## Binary Build

```bash
# Windows
.\packaging\build_windows.ps1

# Linux (or GitHub Actions)
chmod +x packaging/build_linux.sh
./packaging/build_linux.sh

# Checksums
python packaging/build_release.py
```

- [ ] Windows binary builds without errors
- [ ] Linux binary builds without errors
- [ ] `trevvos.exe --version` / `trevvos --version` shows `0.1.0-alpha.1`
- [ ] `trevvos.exe setup --help` shows expected options
- [ ] `trevvos.exe api start --help` shows `--open` and `--port`
- [ ] `SHA256SUMS.txt` generated
- [ ] Smoke test outside the repo (no Python, no venv): `trevvos setup`, `trevvos inspect`, `trevvos api start --port 8765`

---

## Release Logistics

- [ ] Git tag created: `v0.1.0-alpha.1`
- [ ] GitHub Release created (Pre-release)
- [ ] Release assets uploaded: Windows ZIP, Linux tar.gz, SHA256SUMS.txt
- [ ] Testers selected (2–5 developers)
- [ ] Testers briefed on scope (advisory + controlled testing; no execution mode)
- [ ] Testers given the GitHub Release URL
- [ ] Feedback channel ready (issue tracker, Slack, email, or similar)
- [ ] Point of contact for tester questions identified
- [ ] Estimated Alpha duration communicated to testers

---

## Known Issues to Communicate

Before sending to testers, prepare a short "known issues" note covering:

- Current limitations from `docs/known-limitations.md`
- Any issues discovered during smoke testing above
- Any provider-specific quirks observed

---

## Post-Alpha

After Alpha:

- [ ] Collect all feedback reports
- [ ] Triage into: bugs, UX issues, feature requests, documentation gaps
- [ ] Update `docs/known-limitations.md` with newly discovered limitations
- [ ] Tag a new release or plan a Beta if Alpha goals are met
