# Golden Evals

These fixtures exercise Trevvos Forge's deterministic edit engine.

Each scenario contains:

- `input/`: files copied into a temporary workspace;
- `file_changes.json`: structured changes that use the same parser as `trevvos diff`;
- `expected/`: expected final workspace files for successful scenarios;
- `expected_error.txt`: expected error text for failing scenarios.

The evals do not call a real LLM. They test the parser, deterministic diff builder,
and `git apply` behavior using repeatable local fixtures.

Current scenarios cover deterministic inserts before and after lines/headings,
exact text replacement, multi-line block replacement, append-to-file behavior,
file creation, legacy full-file rewrites, missing targets, and ambiguous targets.

Add a new scenario by creating a new directory under `tests/fixtures/evals/` with
the same layout. Use `expected/` for success cases or `expected_error.txt` for
expected failures.

Run:

```bash
python -m unittest tests.test_golden_evals
```
