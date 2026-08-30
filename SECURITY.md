# Security Policy

Trevvos Forge is currently in Alpha and should be treated as experimental software.

## Reporting a vulnerability

Please **do not open a public issue** for a vulnerability that could expose credentials, execute unintended code, bypass an explicit safety boundary, disclose local source code, or leak session artifacts.

Prefer GitHub's private vulnerability reporting when it is available for this repository. If private reporting is unavailable, contact the maintainer privately before publishing details.

A useful report should include:

- affected version or commit;
- operating system and Python version;
- provider/runtime involved;
- minimal reproduction steps;
- expected vs actual behavior;
- potential impact;
- whether credentials, source code, or session data may have been exposed.

Do not include real API keys, private repositories, customer code, or unredacted sensitive session exports in the report.

## Scope

Security-sensitive areas include:

- secret masking;
- session export;
- provider configuration;
- sandbox boundaries;
- patch application;
- file/path validation;
- local API exposure;
- subprocess or command execution;
- model-generated instructions that could cross an explicit user boundary.

## Alpha expectations

Forge does not claim to provide a hardened sandbox or production security boundary. Experimental execution workflows should be used only on code and environments the user is authorized to modify.

The local API is intended to bind to loopback by default. Review configuration before exposing any development service beyond the local machine.
