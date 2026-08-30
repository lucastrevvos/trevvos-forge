# Contributing to Trevvos Forge

Thanks for considering a contribution.

Trevvos Forge is currently in Alpha, so the best contributions are small, reviewable, and easy to validate.

## Good first contributions

- Fix inaccurate or unclear documentation.
- Add or improve unit tests.
- Improve error messages and diagnostics.
- Reproduce and document a bug.
- Add focused provider compatibility fixes.
- Improve masking, validation, or safety boundaries.

## Before opening a pull request

1. Open an issue first for changes that alter behavior, architecture, or public CLI commands.
2. Keep the pull request focused on one concern.
3. Do not include credentials, API keys, private prompts, customer code, or exported sessions containing sensitive data.
4. Add or update tests when behavior changes.
5. Update documentation when a command, option, workflow, or limitation changes.

## Local setup

```bash
git clone https://github.com/lucastrevvos/trevvos-forge.git
cd trevvos-forge
python -m venv .venv
source .venv/bin/activate
python -m pip install -e .
```

Windows PowerShell:

```powershell
python -m venv .venv
.\.venv\Scripts\Activate.ps1
python -m pip install -e .
```

Run the available test suite before submitting your change.

## Pull request expectations

A useful pull request should explain:

- the problem;
- the proposed change;
- how it was validated;
- any user-visible behavior change;
- remaining limitations or follow-up work.

Generated code is welcome only when the contributor has reviewed, understood, and validated it. The contributor remains responsible for the submitted change.

## Security issues

Please do not publish exploitable security vulnerabilities in a public issue. Use GitHub's private vulnerability reporting when available, or contact the maintainer privately.

## License

By contributing, you agree that your contributions will be licensed under the Apache License 2.0.
