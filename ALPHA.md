# Trevvos Forge Alpha

Trevvos Forge is in closed technical Alpha.

This Alpha is intended for developers who are comfortable testing CLI tools, local LLM runtimes, and AI-assisted engineering workflows. It is not a production tool yet.

---

## What to Test

### Recommended (stable)

These workflows are the main focus of Alpha testing:

- **Advisory Mode** — `analyze`, `explain`, `propose`, `spec`, `review-diff`
- **Controlled Testing Mode** — `tests inspect`, `tests add`, `tests apply`
- **Local Dashboard** — `trevvos api start --open`
- **Session Export** — `trevvos sessions export`
- **Setup and Doctor** — `trevvos setup`, `trevvos doctor`

### Guided Only (experimental)

Do not test these unless specifically guided:

- General Execution Mode: `plan`, `diff`, `apply`, `repair`, `work`
- Direct patch apply workflows outside `trevvos tests apply`

---

## Installation

Download the standalone binary for your OS from the GitHub Release — no Python, Git, or pip required.

**Windows x64:**

```powershell
# Download trevvos-forge-v0.1.0-alpha.1-windows-x64.zip from the release
Expand-Archive -Path trevvos-forge-v0.1.0-alpha.1-windows-x64.zip -DestinationPath trevvos
cd trevvos
.\trevvos.exe --version
```

**Linux x64:**

```bash
# Download trevvos-forge-v0.1.0-alpha.1-linux-x64.tar.gz from the release
tar -xzf trevvos-forge-v0.1.0-alpha.1-linux-x64.tar.gz
cd trevvos
./trevvos --version
```

See [docs/alpha-quickstart.md](docs/alpha-quickstart.md) for detailed setup guides.

---

## Quick Start

```bash
# 1. Extract the binary (see Installation above)
cd trevvos

# 2. Set up for your project
cd path/to/your/project
trevvos setup --provider ollama --model qwen2.5-coder:7b --yes

# 3. Verify
trevvos doctor

# 4. Inspect
trevvos inspect

# 5. Analyze a file
trevvos analyze main.py

# 6. Open the dashboard
trevvos api start --open

# 7. Export your session for feedback
trevvos sessions export latest
```

See [docs/alpha-test-plan.md](docs/alpha-test-plan.md) for the full guided test plan.

---

## Supported Providers

| Provider | Status | Setup |
|---|---|---|
| Ollama | Supported | `trevvos setup --provider ollama` |
| LM Studio | Supported (openai-compatible) | `trevvos setup --provider openai-compatible` |
| llama.cpp server | Supported (openai-compatible) | `trevvos setup --provider openai-compatible` |
| OpenAI API | Supported (openai-compatible) | `trevvos setup --provider openai-compatible` |
| OpenRouter | Supported (openai-compatible) | `trevvos setup --provider openai-compatible` |

See [docs/providers.md](docs/providers.md) for detailed setup instructions.

---

## How to Report Feedback

After any session, export the session:

```bash
trevvos sessions export latest
```

Review the export for sensitive project data before sharing. Secrets in JSON artifacts are masked automatically, but source file content is not redacted.

Then fill out the feedback template: [docs/feedback-template.md](docs/feedback-template.md)

---

## Safety Notes

- **Advisory commands are read-only.** They do not modify code, create patches, or apply changes.
- **Controlled Testing Mode only edits test files**, and only after sandbox validation. Apply is explicit.
- **Local API binds to `127.0.0.1` by default.** It is not accessible from other machines.
- **`trevvos setup` does not save `api_key` to disk.** Use the `TREVVOS_FORGE_API_KEY` environment variable.
- **Session exports mask secrets** in JSON artifacts. Review before sharing.

See [docs/alpha-safety.md](docs/alpha-safety.md) for the full safety model.

---

## Known Limitations

See [docs/known-limitations.md](docs/known-limitations.md) for a full list.

Key limitations to be aware of:

- Advisory reports are AI-generated — review before acting on them.
- Controlled test generation is strongest on small Python files.
- Execution Mode is experimental and not recommended for Alpha.
- Dashboard is basic and local — no auto-refresh.
- No cloud sync or remote access.

---

## Docs

- [Alpha Quickstart](docs/alpha-quickstart.md)
- [Alpha Test Plan](docs/alpha-test-plan.md)
- [Provider Configuration](docs/providers.md)
- [Advisory Mode](docs/advisory-mode.md)
- [Controlled Testing Mode](docs/controlled-testing-mode.md)
- [Local API and Dashboard](docs/local-api-dashboard.md)
- [Known Limitations](docs/known-limitations.md)
- [Safety Model](docs/alpha-safety.md)
- [Troubleshooting](docs/troubleshooting.md)
- [Feedback Template](docs/feedback-template.md)
