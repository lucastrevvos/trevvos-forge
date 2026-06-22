import ast
import json
import subprocess
from pathlib import Path
from typing import Annotated

import typer
from rich.console import Console
from rich.table import Table

from trevvos_forge.agent_state import determine_agent_state, determine_next_action
from trevvos_forge.apply_patch import apply_patch, check_patch
from trevvos_forge.commit_workflow import (
    CommitMessage,
    CommitResult,
    build_commit_plan,
    build_deterministic_commit_message,
    extract_patch_paths,
    parse_commit_message_response,
    render_commit_message,
    run_git_commit,
    write_commit_artifacts,
)
from trevvos_forge.cli_regression_check import build_cli_regression_check, write_cli_regression_check
from trevvos_forge.context_builder import build_context, content_with_line_numbers
from trevvos_forge.diff_builder import build_unified_diff_from_file_changes
from trevvos_forge.diff_validation import validate_diff_patch
from trevvos_forge.engine import TrevvosForgeEngine
from trevvos_forge.exceptions import (
    ApplyError,
    CommitError,
    DiffError,
    DiffValidationError,
    FileChangeOutputError,
    ForgeError,
    RepairNotRepairableError,
    StructuredOutputError,
    TestRunError,
)
from trevvos_forge.file_changes_error_artifacts import write_file_changes_error_artifacts
from trevvos_forge.file_change_outputs import parse_file_changes_output
from trevvos_forge.operation_error_artifacts import write_operation_error_artifacts
from trevvos_forge.plan_error_artifacts import write_plan_error_artifacts
from trevvos_forge.plan_constraints import (
    build_plan_constraints_prompt_section,
    check_file_changes_against_plan_constraints,
    load_plan_constraints,
    write_plan_constraints_check,
)
from trevvos_forge.prompt_catalog import get_prompt, list_prompts
from trevvos_forge.project_scanner import (
    build_project_profile_prompt_section,
    load_project_profile,
    render_project_profile,
    save_project_profile,
    scan_project,
)
from trevvos_forge.providers.ollama import OllamaProvider
from trevvos_forge.review_artifacts import (
    build_change_summary_markdown,
    build_patch_preview,
    build_semantic_review_json,
    build_semantic_review_json_from_context,
    render_deterministic_review_text,
)
from trevvos_forge.review_workflow import (
    build_review_context,
    build_semantic_review_prompt,
    parse_llm_review_response,
    render_llm_review_markdown,
    write_llm_review_artifacts,
)
from trevvos_forge.repair_workflow import (
    build_not_repairable_metadata,
    build_repair_context,
    build_repair_metadata,
    build_repair_prompt,
    write_repair_metadata,
)
from trevvos_forge.retry_workflow import (
    build_retry_context,
    build_retry_metadata,
    build_retry_prompt,
    write_retry_metadata,
)
from trevvos_forge.sessions import (
    clean_sessions,
    create_session,
    get_current_session,
    get_session,
    list_sessions,
    read_session_text,
    update_session_status,
    write_session_json,
    write_session_text,
)
from trevvos_forge.settings import ForgeSettings
from trevvos_forge.small_file_policy import detect_small_file_structural_edit_risk
from trevvos_forge.structured_outputs import parse_plan_output
from trevvos_forge.status_workflow import (
    build_session_status,
    render_status_text,
    write_session_status,
)
from trevvos_forge.test_runner import (
    TestRunResult,
    load_test_commands,
    load_plan_verification_commands,
    merge_test_commands,
    run_test_command_specs,
    run_test_specs_in_sandbox,
    write_test_artifacts,
)
from trevvos_forge.timeline import append_timeline_event, write_timeline_markdown
from trevvos_forge.verification_coverage import (
    has_failed_verification_coverage,
    high_risk_warnings,
    write_verification_coverage,
)
from trevvos_forge.work_workflow import build_work_metadata, write_work_artifacts
from trevvos_forge.workspace import read_workspace_file, scan_workspace


app = typer.Typer(
    name="trevvos",
    help="Trevvos Forge: local-first AI engineering assistant. Advisory: inspect/analyze. Execution: plan/diff/test/repair/apply/commit/work.",
    no_args_is_help=True,
)

models_app = typer.Typer(
    name="models",
    help="Manage local LLM models.",
    no_args_is_help=True,
)

sessions_app = typer.Typer(
    name="sessions",
    help="Manage Trevvos Forge local sessions.",
    no_args_is_help=True,
)

prompts_app = typer.Typer(
    name="prompts",
    help="Inspect Trevvos Forge prompt catalog.",
    no_args_is_help=True,
)

app.add_typer(sessions_app, name="sessions")
app.add_typer(prompts_app, name="prompts")
app.add_typer(models_app, name="models")

console = Console()
err_console = Console(stderr=True)


def print_error(message: str) -> None:
    err_console.print(f"[red][trevvos-forge][/red] {message}")


@app.callback()
def callback() -> None:
    """
    Trevvos Forge CLI.
    """
    pass


def load_settings() -> ForgeSettings:
    return ForgeSettings.from_env()


def build_provider(settings: ForgeSettings) -> OllamaProvider:
    return OllamaProvider(
        model=settings.model,
        base_url=settings.base_url,
        timeout=settings.timeout,
    )


def build_engine() -> TrevvosForgeEngine:
    settings = load_settings()
    provider = build_provider(settings)

    return TrevvosForgeEngine(provider=provider)


def _load_diff_validation_changes(session_path: Path) -> list[dict]:
    validation_path = session_path / "diff_validation.json"

    if not validation_path.exists():
        raise ApplyError("Cannot apply: diff_validation.json not found in session.")

    try:
        validation = json.loads(validation_path.read_text(encoding="utf-8"))
    except json.JSONDecodeError as exc:
        raise ApplyError("Cannot apply: diff_validation.json is invalid JSON.") from exc

    changes = validation.get("changes")

    if not isinstance(changes, list):
        raise ApplyError("Cannot apply: diff_validation.json has no changes list.")

    return changes


def _load_session_json(session_path: Path, file_name: str) -> dict:
    file_path = session_path / file_name

    if not file_path.exists():
        raise ApplyError(f"Cannot apply: {file_name} not found in session.")

    try:
        value = json.loads(file_path.read_text(encoding="utf-8"))
    except json.JSONDecodeError as exc:
        raise ApplyError(f"Cannot apply: {file_name} is invalid JSON.") from exc

    if not isinstance(value, dict):
        raise ApplyError(f"Cannot apply: {file_name} must contain a JSON object.")

    return value


def _load_diff_warnings(session_path: Path) -> list[str]:
    warnings_path = session_path / "diff_warnings.json"

    if not warnings_path.exists():
        return []

    try:
        payload = json.loads(warnings_path.read_text(encoding="utf-8"))
    except json.JSONDecodeError:
        return ["Unable to read diff_warnings.json."]

    warnings = payload.get("warnings") if isinstance(payload, dict) else None

    if not isinstance(warnings, list):
        return ["diff_warnings.json has an invalid warnings field."]

    return [warning for warning in warnings if isinstance(warning, str)]


def _format_change_action(change_type: object) -> str:
    return "CREATE" if change_type == "created" else "MODIFY"


def _format_change_line(change: dict) -> str:
    path = change.get("path")
    change_type = change.get("change_type")
    mode = change.get("mode")
    operation = change.get("operation")

    if not isinstance(path, str):
        return ""

    descriptor = ""

    if isinstance(mode, str):
        descriptor = mode

        if isinstance(operation, str):
            descriptor = f"{descriptor} / {operation}"

    suffix = f" {descriptor}" if descriptor else ""

    return f"- {path} [{change_type}]{suffix}"


def _delete_session_files(session_path: Path, file_names: list[str]) -> None:
    for file_name in file_names:
        file_path = session_path / file_name

        if file_path.exists():
            file_path.unlink()


def _record_timeline_event(session, event: str, command: str, status: str, **fields) -> None:
    if session is None:
        return

    try:
        payload = {
            "event": event,
            "command": command,
            "status": status,
            "session_id": session.metadata.id,
            **fields,
        }
        append_timeline_event(session.path, payload)
        write_timeline_markdown(session.path)
    except Exception:
        return


def _build_plan_retry_context(session) -> str:
    error = _read_json_file(session.path / "plan_error.json")
    verification_coverage = _read_json_file(session.path / "verification_coverage.json")
    user_request = _read_optional_text(session.path / "user_request.txt")
    prompt = _read_optional_text(session.path / "prompt.md")
    raw_response = _read_optional_text(session.path / "plan_raw_response.md")
    context = _read_optional_text(session.path / "context.md")

    return "\n\n".join(
        [
            "Original user request:",
            user_request or "",
            "Previous plan error:",
            json.dumps(error, indent=2, ensure_ascii=False) if isinstance(error, dict) else "",
            "Verification coverage:",
            json.dumps(verification_coverage, indent=2, ensure_ascii=False)
            if isinstance(verification_coverage, dict)
            else "",
            "Previous raw response:",
            raw_response or "",
            "Previous prompt:",
            prompt or "",
            "Workspace context:",
            context or "",
        ]
    )


def _read_optional_text(path: Path) -> str | None:
    if not path.exists():
        return None
    return path.read_text(encoding="utf-8")


def _read_json_file(path: Path):
    if not path.exists():
        return None
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError:
        return None


def _plan_retry_count(session) -> int:
    metadata = _read_json_file(session.path / "plan_retry_metadata.json")
    if isinstance(metadata, dict) and isinstance(metadata.get("retry_count"), int):
        return metadata["retry_count"] + 1
    return 1


def _write_plan_retry_metadata(
    session,
    *,
    retry_count: int,
    previous_error_type: str | None,
    status: str,
) -> None:
    write_session_json(
        session,
        "plan_retry_metadata.json",
        {
            "retry": True,
            "retry_count": retry_count,
            "previous_error_type": previous_error_type,
            "prompt": "plan_retry@1.0.0",
            "status": status,
        },
    )


def _clear_plan_error_artifacts(session) -> None:
    _delete_session_files(
        session.path,
        [
            "plan_error.json",
            "plan_error.md",
        ],
    )


def _build_analysis_context(
    *,
    repo_root: Path,
    target: Path | None,
    profile: dict,
    max_files: int = 8,
    max_chars_per_file: int = 12_000,
) -> tuple[str, list[str]]:
    profile_section = build_project_profile_prompt_section(profile)
    selected_paths = _select_analysis_files(
        repo_root=repo_root,
        target=target,
        profile=profile,
        max_files=max_files,
    )
    file_sections: list[str] = []

    for relative_path in selected_paths:
        content = read_workspace_file(
            root=repo_root,
            file_path=Path(relative_path),
            max_chars=max_chars_per_file,
        )
        file_sections.append(
            "\n".join(
                [
                    f"## File: {relative_path}",
                    "",
                    "Content with line numbers:",
                    "",
                    "```text",
                    content_with_line_numbers(content),
                    "```",
                ]
            )
        )

    target_text = str(target) if target is not None else "project"
    files_text = "\n\n".join(file_sections) if file_sections else "No file contents selected."
    context = "\n\n".join(
        [
            "# Advisory Analysis Context",
            "",
            f"Target: {target_text}",
            "",
            profile_section,
            "",
            "# Selected files",
            "",
            files_text,
        ]
    )
    return context, selected_paths


def _select_analysis_files(*, repo_root: Path, target: Path | None, profile: dict, max_files: int) -> list[str]:
    if target is not None:
        resolved_target = (repo_root / target).resolve()
        try:
            resolved_target.relative_to(repo_root.resolve())
        except ValueError as exc:
            raise DiffError(f"Analyze target is outside workspace: {target}") from exc
        if not resolved_target.exists():
            raise DiffError(f"Analyze target does not exist: {target}")
        if resolved_target.is_file():
            return [resolved_target.relative_to(repo_root.resolve()).as_posix()]
        if resolved_target.is_dir():
            source_files = [
                path
                for path in profile.get("source_files", [])
                if isinstance(path, str) and (repo_root / path).resolve().is_relative_to(resolved_target)
            ]
            return source_files[:max_files]
        raise DiffError(f"Analyze target is not a file or directory: {target}")

    candidates: list[str] = []
    for key in ["entrypoints", "source_files", "config_files", "docs_files"]:
        values = profile.get(key)
        if isinstance(values, list):
            candidates.extend(value for value in values if isinstance(value, str))
    return list(dict.fromkeys(candidates))[:max_files]


def _build_explanation_context(
    *,
    repo_root: Path,
    target: Path,
    symbol: str | None,
    flow: bool,
    profile: dict,
    max_chars_per_file: int = 12_000,
) -> tuple[str, list[str]]:
    relative_path = _validate_explain_target(repo_root=repo_root, target=target)
    content = read_workspace_file(root=repo_root, file_path=Path(relative_path), max_chars=max_chars_per_file)
    symbol_block = ""

    if symbol:
        symbol_info = _find_python_symbol(content, symbol)
        if symbol_info is None:
            raise DiffError(f"Symbol `{symbol}` not found in {relative_path}.")
        symbol_block = "\n".join(
            [
                "Symbol focus:",
                f"- name: {symbol}",
                f"- kind: {symbol_info['kind']}",
                f"- approximate lines: {symbol_info['start_line']}-{symbol_info['end_line']}",
                "",
                "Symbol source:",
                "```text",
                content_with_line_numbers(symbol_info["source"]),
                "```",
            ]
        )

    related_sections, files_explained = _related_flow_sections(
        repo_root=repo_root,
        primary_path=relative_path,
        primary_content=content,
        flow=flow,
        profile=profile,
        max_chars_per_file=max_chars_per_file,
    )

    mode = "flow" if flow else "symbol" if symbol else "file"
    context = "\n\n".join(
        [
            "# Advisory Explanation Context",
            "",
            f"Mode: {mode}",
            f"Target: {relative_path}",
            f"Symbol: {symbol or 'none'}",
            "",
            build_project_profile_prompt_section(profile),
            "",
            "Primary file content with line numbers:",
            "",
            "```text",
            content_with_line_numbers(content),
            "```",
            "",
            symbol_block,
            "",
            related_sections,
        ]
    ).strip()
    return context, files_explained


def _build_handoff_context(
    *,
    repo_root: Path,
    request: str,
    target_ai: str,
    include_code: bool,
    profile: dict,
    max_files: int = 8,
    max_chars_per_file: int = 12_000,
) -> tuple[str, list[str]]:
    selected_paths = _select_analysis_files(
        repo_root=repo_root,
        target=None,
        profile=profile,
        max_files=max_files,
    )
    file_sections: list[str] = []

    if include_code:
        for relative_path in selected_paths:
            content = read_workspace_file(
                root=repo_root,
                file_path=Path(relative_path),
                max_chars=max_chars_per_file,
            )
            file_sections.append(
                "\n".join(
                    [
                        f"## File: {relative_path}",
                        "",
                        "Content with line numbers:",
                        "",
                        "```text",
                        content_with_line_numbers(content),
                        "```",
                    ]
                )
            )
    else:
        file_sections.append("Source code snippets were intentionally omitted by --no-code.")

    target_guidance = _handoff_target_guidance(target_ai)
    files_text = "\n\n".join(file_sections) if file_sections else "No file contents selected."
    context = "\n\n".join(
        [
            "# AI Handoff Context",
            "",
            "User request:",
            request,
            "",
            f"Target AI: {target_ai}",
            "",
            target_guidance,
            "",
            build_project_profile_prompt_section(profile),
            "",
            "# Relevant files and snippets",
            "",
            files_text,
            "",
            "# Safety requirements",
            "",
            "- Preserve existing behavior unless explicitly requested otherwise.",
            "- Preserve existing public functions, classes, and CLI commands.",
            "- For additive changes, add new behavior instead of replacing old behavior.",
            "- If modifying a CLI, keep existing commands working.",
            "- Keep changes minimal and scoped to the user request.",
            "- Run verification commands before declaring success.",
            "- Do not claim tests were run unless they were actually run.",
        ]
    )
    return context, selected_paths


def _handoff_target_guidance(target_ai: str) -> str:
    normalized = target_ai.lower().strip()
    if normalized == "codex":
        return "\n".join(
            [
                "Target-specific guidance:",
                "- Ask Codex to inspect the relevant files before editing.",
                "- Do not commit automatically.",
                "- Avoid changes outside the requested scope.",
                "- Run the verification commands and summarize results.",
            ]
        )
    if normalized == "cursor":
        return "\n".join(
            [
                "Target-specific guidance:",
                "- Use this as a Cursor Agent/Composer implementation brief.",
                "- Keep edits scoped and preserve existing behavior.",
                "- Run or request the listed verification commands before finishing.",
            ]
        )
    if normalized == "claude":
        return "\n".join(
            [
                "Target-specific guidance:",
                "- Ask Claude to reason about the plan before editing.",
                "- Prefer small, safe edits and stop if project context is missing.",
                "- Verify existing behavior and the requested new behavior.",
            ]
        )
    return "\n".join(
        [
            "Target-specific guidance:",
            "- Generate a generic copy-paste prompt for an external coding AI.",
            "- Keep the prompt tool-agnostic and implementation-focused.",
        ]
    )


def _build_diff_review_context(
    *,
    profile: dict,
    git_status: str,
    diff_stat: str,
    diff_text: str,
    staged: bool,
    max_diff_chars: int = 60_000,
) -> tuple[str, list[str]]:
    files_changed = extract_patch_paths(diff_text)
    diff_body = diff_text
    truncated = False

    if len(diff_body) > max_diff_chars:
        diff_body = diff_body[:max_diff_chars] + "\n\n[diff truncated]"
        truncated = True

    context = "\n\n".join(
        [
            "# Advisory Diff Review Context",
            "",
            f"Mode: {'staged' if staged else 'working tree'}",
            "",
            build_project_profile_prompt_section(profile),
            "",
            "# Git status",
            "",
            "```text",
            git_status.strip() or "<clean>",
            "```",
            "",
            "# Diff stat",
            "",
            "```text",
            diff_stat.strip() or "<none>",
            "```",
            "",
            "# Files changed",
            "",
            "\n".join(f"- {path}" for path in files_changed) if files_changed else "<none>",
            "",
            "# Diff",
            "",
            "```diff",
            diff_body,
            "```",
            "",
            f"Diff truncated: {str(truncated).lower()}",
            "",
            "# Available test artifacts",
            "",
            "No test artifacts were provided in this advisory review context.",
        ]
    )
    return context, files_changed


def _run_git_capture(repo_root: Path, args: list[str]) -> str:
    try:
        result = subprocess.run(
            ["git", *args],
            cwd=repo_root,
            capture_output=True,
            check=False,
            text=True,
            encoding="utf-8",
        )
    except OSError as exc:
        raise DiffError(f"git command failed to start: {exc}") from exc

    if result.returncode != 0:
        detail = result.stderr.strip() or result.stdout.strip()
        raise DiffError(f"git {' '.join(args)} failed: {detail}")

    return result.stdout


def _extract_final_recommendation(markdown: str) -> str | None:
    allowed = {"approve", "approve_with_comments", "request_changes", "needs_more_context"}
    lines = markdown.splitlines()

    for index, line in enumerate(lines):
        if line.strip().lower() == "## final recommendation":
            for candidate in lines[index + 1 : index + 8]:
                value = candidate.strip().strip("`").lower()
                if value in allowed:
                    return value
                if value.startswith("- "):
                    bullet = value[2:].strip().strip("`")
                    if bullet in allowed:
                        return bullet
    for value in allowed:
        if value in markdown:
            return value
    return None


def _validate_explain_target(*, repo_root: Path, target: Path) -> str:
    resolved = (repo_root / target).resolve()
    try:
        resolved.relative_to(repo_root.resolve())
    except ValueError as exc:
        raise DiffError(f"Explain target is outside workspace: {target}") from exc
    if not resolved.exists():
        raise DiffError(f"Explain target does not exist: {target}")
    if not resolved.is_file():
        raise DiffError(f"Explain target must be a file: {target}")
    return resolved.relative_to(repo_root.resolve()).as_posix()


def _find_python_symbol(content: str, symbol: str) -> dict | None:
    try:
        tree = ast.parse(content)
    except SyntaxError:
        return None
    lines = content.splitlines()
    for node in tree.body:
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)) and node.name == symbol:
            start = getattr(node, "lineno", 1)
            end = getattr(node, "end_lineno", start)
            return {
                "kind": "class" if isinstance(node, ast.ClassDef) else "function",
                "start_line": start,
                "end_line": end,
                "source": "\n".join(lines[start - 1 : end]),
            }
    return None


def _related_flow_sections(
    *,
    repo_root: Path,
    primary_path: str,
    primary_content: str,
    flow: bool,
    profile: dict,
    max_chars_per_file: int,
) -> tuple[str, list[str]]:
    files = [primary_path]
    if not flow:
        return "Related flow context: not requested.", files

    related: list[str] = []
    try:
        tree = ast.parse(primary_content)
    except SyntaxError:
        tree = None

    imported_names: set[str] = set()
    if tree is not None:
        for node in tree.body:
            if isinstance(node, ast.ImportFrom) and node.module:
                for alias in node.names:
                    imported_names.add(alias.name)

    modules = profile.get("python", {}).get("modules", {}) if isinstance(profile.get("python"), dict) else {}
    if isinstance(modules, dict):
        for path, module in modules.items():
            if path == primary_path or not isinstance(module, dict):
                continue
            functions = module.get("functions")
            if isinstance(functions, list) and imported_names.intersection(str(function) for function in functions):
                related.append(path)

    sections = ["Related flow context:"]
    for path in related[:3]:
        content = read_workspace_file(root=repo_root, file_path=Path(path), max_chars=max_chars_per_file)
        files.append(path)
        sections.extend(
            [
                "",
                f"## Related file: {path}",
                "",
                "```text",
                content_with_line_numbers(content),
                "```",
            ]
        )

    if len(sections) == 1:
        sections.append("No related files selected.")
    return "\n".join(sections), files


@app.command()
def ask(question: str) -> None:
    """
    Ask a technical question using your local LLM.
    """
    try:
        engine = build_engine()

        with console.status("[bold]Thinking with your local LLM...[/bold]", spinner="dots"):
            answer = engine.ask(question)

        console.print(answer)

    except ForgeError as exc:
        print_error(str(exc))
        raise typer.Exit(code=1)


@app.command()
def generate(
    instruction: str,
    language: Annotated[
        str | None,
        typer.Option("--language", "-l", help="Target programming language."),
    ] = None,
) -> None:
    """
    Generate code using your local LLM.
    """
    try:
        engine = build_engine()

        with console.status("[bold]Generating code with your local LLM...[/bold]", spinner="dots"):
            result = engine.generate_code(
                instruction=instruction,
                language=language,
            )

        console.print(result)

    except ForgeError as exc:
        print_error(str(exc))
        raise typer.Exit(code=1)


@app.command()
def doctor() -> None:
    """
    Check Trevvos Forge local environment.
    """
    try:
        settings = load_settings()
        provider = build_provider(settings)

        console.print("[bold]Trevvos Forge Doctor[/bold]\n")

        console.print("[bold]Settings[/bold]")
        console.print(f"   Model:       {settings.model}")
        console.print(f"   Base URL:    {settings.base_url}")
        console.print(f"   Timeout:     {settings.timeout}s")

        with console.status("[bold]Checking Ollama...[/bold]", spinner="dots"):
            models = provider.list_models()

        console.print("\n[bold]Ollama[/bold]")
        console.print("   Status:   [green]OK[/green]")
        console.print(f"   Models:   {len(models)} found")

        if models:
            console.print("\n[bold]Installed models[/bold]")
            for model in models:
                marker = "[green]*[/green]" if model == settings.model else "-"
                console.print(f"   {marker} {model}")

        if settings.model in models:
            console.print("\n[green]Environment OK. Trevvos Forge is ready.[/green]")
        else:
            console.print(
                f"\n[yellow]Configured model was not found:[/yellow] {settings.model}"
            )
            console.print(
                "Run `ollama list` to see available models or set TREVVOS_FORGE_MODEL."
            )
            raise typer.Exit(code=1)

    except ForgeError as exc:
        print_error(str(exc))
        raise typer.Exit(code=1)


@app.command()
def setup(
    model: Annotated[
        str | None,
        typer.Option("--model", "-m", help="Model to check or pull during setup."),
    ] = None,
) -> None:
    """
    Setup Trevvos Forge local environment.
    """
    try:
        settings = load_settings()
        target_model = model or settings.model

        provider = OllamaProvider(
            model=target_model,
            base_url=settings.base_url,
            timeout=settings.timeout,
        )

        console.print("[bold]Trevvos Forge Setup[/bold]\n")

        console.print("[bold]Settings[/bold]")
        console.print(f"  Base URL: {settings.base_url}")
        console.print(f"  Timeout:  {settings.timeout}s")
        console.print(f"  Model:    {target_model}")

        with console.status("[bold]Checking Ollama...[/bold]", spinner="dots"):
            models = provider.list_models()

        console.print("\n[bold]Ollama[/bold]")
        console.print("  Status: [green]OK[/green]")

        if target_model in models:
            console.print(
                f"\n[green]Model already available:[/green] [bold]{target_model}[/bold]"
            )
            console.print("[green]Setup complete. Trevvos Forge is ready.[/green]")
            return

        console.print(
            f"\n[yellow]Model not found locally:[/yellow] [bold]{target_model}[/bold]"
        )

        should_pull = typer.confirm(
            f"Do you want to pull {target_model} now?",
            default=False,
        )

        if not should_pull:
            console.print("\n[yellow]Setup stopped.[/yellow]")
            console.print("You can pull the model later with:")
            console.print(f"  trevvos models pull {target_model}")
            raise typer.Exit(code=1)

        console.print(f"\n[bold]Pulling model:[/bold] {target_model}")
        console.print("[yellow]This can take a while depending on the model size.[/yellow]\n")

        with console.status("[bold]Downloading model with Ollama...[/bold]", spinner="dots"):
            status = provider.pull_model(target_model)

        console.print(f"\n[green]Model pull finished:[/green] {status}")
        console.print(f"[green]Setup complete.[/green] Model ready: [bold]{target_model}[/bold]")

        if model and model != settings.model:
            console.print(
                "\n[yellow]Note:[/yellow] this model was downloaded, but it is not your default model."
            )
            console.print("To use it temporarily:")
            console.print(f'  TREVVOS_FORGE_MODEL="{model}" trevvos ask "hello"')

    except ForgeError as exc:
        print_error(str(exc))
        console.print("\nIf Ollama is not running, start it and try again:")
        console.print("  ollama serve")
        raise typer.Exit(code=1)


@app.command()
def scan(
    path: Annotated[
        Path,
        typer.Argument(help="Workspace path to scan."),
    ] = Path("."),
    max_files: Annotated[
        int,
        typer.Option("--max-files", help="Maximum number of files to show."),
    ] = 200,
) -> None:
    """
    Scan a project workspace without modifying files.
    """
    try:
        with console.status("[bold]Scanning workspace...[/bold]", spinner="dots"):
            result = scan_workspace(path, max_files=max_files)

        console.print("[bold]Trevvos Forge Workspace Scan[/bold]\n")

        console.print("[bold]Root[/bold]")
        console.print(f"  {result.root}")

        console.print("\n[bold]Detected stacks[/bold]")
        for stack in result.detected_stacks:
            console.print(f"   - {stack}")

        console.print("\n[bold]Summary[/bold]")
        console.print(f"  Files seen:      {result.total_files_seen}")
        console.print(f"  Files displayed: {len(result.files)}")
        console.print(f"  Directories:     {len(result.directories)}")

        if result.important_files:
            console.print("\n[bold]Important files[/bold]")
            for file_path in result.important_files:
                console.print(f"    - {file_path}")

        table = Table(title="Files")
        table.add_column("Path", overflow="fold")
        table.add_column("Ext")
        table.add_column("Size")

        for file in result.files[:50]:
            table.add_row(
                file.path,
                file.extension or "-",
                f"{file.size_bytes} bytes",
            )

        console.print()
        console.print(table)

        if len(result.files) > 50:
            console.print(
                "\n[yellow]Showing first 50 files. Use --max-files to control scan size.[/yellow]"
            )

    except (FileNotFoundError, NotADirectoryError) as exc:
        print_error(str(exc))
        raise typer.Exit(code=1)


@app.command()
def inspect(
    file_path: Annotated[
        Path | None,
        typer.Argument(help="Optional file path inside the workspace to inspect."),
    ] = None,
    path: Annotated[
        Path,
        typer.Option("--path", "-p", help="Workspace root path."),
    ] = Path("."),
    json_output: Annotated[
        bool,
        typer.Option("--json", help="Print project profile as JSON."),
    ] = False,
    refresh: Annotated[
        bool,
        typer.Option("--refresh", help="Refresh the saved project profile."),
    ] = False,
    max_chars: Annotated[
        int,
        typer.Option("--max-chars", help="Maximum number of characters to read."),
    ] = 12_000,
) -> None:
    """
    Inspect project structure or safely inspect a file inside the workspace.
    """
    try:
        if file_path is None:
            profile = None if refresh else load_project_profile(path)
            if profile is None:
                with console.status("[bold]Inspecting project...[/bold]", spinner="dots"):
                    profile = scan_project(path)
                save_project_profile(path, profile)

            if json_output:
                console.print(json.dumps(profile, indent=2, ensure_ascii=False))
            else:
                console.print(render_project_profile(profile))
            return

        content = read_workspace_file(
            root=path,
            file_path=file_path,
            max_chars=max_chars,
        )

        if json_output:
            console.print(json.dumps({"path": str(file_path), "content": content}, indent=2, ensure_ascii=False))
            return

        console.print(f"[bold]File:[/bold] {file_path}\n")
        console.print(content)

    except ForgeError as exc:
        print_error(str(exc))
        raise typer.Exit(code=1)


@app.command()
def analyze(
    target: Annotated[
        Path | None,
        typer.Argument(help="Optional file or directory to analyze."),
    ] = None,
    path: Annotated[
        Path,
        typer.Option("--path", "-p", help="Workspace root path."),
    ] = Path("."),
    json_output: Annotated[
        bool,
        typer.Option("--json", help="Print analysis metadata as JSON."),
    ] = False,
    max_files: Annotated[
        int,
        typer.Option("--max-files", help="Maximum number of files to include."),
    ] = 8,
    max_chars: Annotated[
        int,
        typer.Option("--max-chars", help="Maximum characters per file."),
    ] = 12_000,
) -> None:
    """
    Analyze code in advisory mode without modifying files.
    """
    session = None
    try:
        workspace_root = path.resolve()
        settings = load_settings()
        provider = build_provider(settings)
        profile = scan_project(workspace_root)
        save_project_profile(workspace_root, profile)

        context_markdown, files_analyzed = _build_analysis_context(
            repo_root=workspace_root,
            target=target,
            profile=profile,
            max_files=max_files,
            max_chars_per_file=max_chars,
        )

        session = create_session(
            root=workspace_root,
            user_request=f"analyze {target}" if target else "analyze project",
            command="analyze",
        )
        _record_timeline_event(session, "analyze_started", "trevvos analyze", "started")

        prompt_template = get_prompt("code_analysis")
        prompt = prompt_template.render(analysis_context=context_markdown)

        write_session_text(session=session, file_name="context.md", content=context_markdown)
        write_session_json(
            session,
            "selected_files.json",
            {
                "mode": "advisory",
                "target": str(target) if target else None,
                "files_analyzed": files_analyzed,
            },
        )
        write_session_json(session, "project_profile.json", profile)
        write_session_text(session=session, file_name="analysis_prompt.md", content=prompt)

        with console.status("[bold]Analyzing code with your local LLM...[/bold]", spinner="dots"):
            raw_response = provider.generate(prompt)

        write_session_text(session=session, file_name="analysis_raw_response.md", content=raw_response)
        write_session_text(session=session, file_name="analysis_report.md", content=raw_response)

        metadata = {
            "mode": "advisory",
            "command": "analyze",
            "target": str(target) if target else "project",
            "prompt": prompt_template.ref,
            "model": settings.model,
            "files_analyzed": files_analyzed,
            "status": "succeeded",
        }
        write_session_json(session, "analysis_metadata.json", metadata)
        session = update_session_status(session, "analysis_completed")
        _record_timeline_event(
            session,
            "analyze_completed",
            "trevvos analyze",
            "succeeded",
            artifacts=[
                "analysis_report.md",
                "analysis_metadata.json",
                "project_profile.json",
                "selected_files.json",
                "context.md",
            ],
        )

        if json_output:
            console.print(json.dumps(metadata, indent=2, ensure_ascii=False))
            return

        console.print("[green]Analysis completed.[/green]\n")
        console.print(f"Session:        [bold]{session.metadata.id}[/bold]")
        console.print("Mode:           advisory")
        console.print(f"Target:         {metadata['target']}")
        console.print(f"Files analyzed: {len(files_analyzed)}")
        console.print(f"Prompt:         {prompt_template.ref}")
        console.print(f"Model:          {settings.model}")
        console.print("\n[bold]Saved files[/bold]")
        console.print(f"  - {session.path / 'analysis_report.md'}")
        console.print(f"  - {session.path / 'analysis_metadata.json'}")
        console.print(f"  - {session.path / 'project_profile.json'}")
        console.print("\n[bold]Report[/bold]\n")
        console.print(raw_response)

    except ForgeError as exc:
        if session is not None:
            write_session_json(
                session,
                "analysis_metadata.json",
                {
                    "mode": "advisory",
                    "command": "analyze",
                    "target": str(target) if target else "project",
                    "status": "failed",
                    "error": str(exc),
                },
            )
            _record_timeline_event(
                session,
                "analyze_failed",
                "trevvos analyze",
                "failed",
                message=str(exc),
                artifacts=["analysis_metadata.json"],
            )
        print_error(str(exc))
        raise typer.Exit(code=1)


@app.command()
def explain(
    target: Annotated[
        Path,
        typer.Argument(help="File path to explain."),
    ],
    path: Annotated[
        Path,
        typer.Option("--path", "-p", help="Workspace root path."),
    ] = Path("."),
    symbol: Annotated[
        str | None,
        typer.Option("--symbol", help="Function or class to explain."),
    ] = None,
    flow: Annotated[
        bool,
        typer.Option("--flow", help="Explain execution flow."),
    ] = False,
    json_output: Annotated[
        bool,
        typer.Option("--json", help="Print explanation metadata as JSON."),
    ] = False,
    max_chars: Annotated[
        int,
        typer.Option("--max-chars", help="Maximum characters per file."),
    ] = 12_000,
) -> None:
    """
    Explain a file, symbol, or flow in advisory mode without modifying files.
    """
    session = None
    try:
        workspace_root = path.resolve()
        settings = load_settings()
        profile = scan_project(workspace_root)
        save_project_profile(workspace_root, profile)
        explanation_context, files_explained = _build_explanation_context(
            repo_root=workspace_root,
            target=target,
            symbol=symbol,
            flow=flow,
            profile=profile,
            max_chars_per_file=max_chars,
        )
        provider = build_provider(settings)

        session = create_session(
            root=workspace_root,
            user_request=f"explain {target}",
            command="explain",
        )
        _record_timeline_event(session, "explain_started", "trevvos explain", "started")

        prompt_template = get_prompt("code_explanation")
        prompt = prompt_template.render(explanation_context=explanation_context)

        write_session_text(session=session, file_name="context.md", content=explanation_context)
        write_session_json(
            session,
            "selected_files.json",
            {
                "mode": "advisory",
                "target": str(target),
                "symbol": symbol,
                "flow": flow,
                "files_explained": files_explained,
            },
        )
        write_session_json(session, "project_profile.json", profile)
        write_session_text(session=session, file_name="explanation_prompt.md", content=prompt)

        with console.status("[bold]Explaining code with your local LLM...[/bold]", spinner="dots"):
            raw_response = provider.generate(prompt)

        write_session_text(session=session, file_name="explanation_raw_response.md", content=raw_response)
        write_session_text(session=session, file_name="explanation.md", content=raw_response)

        metadata = {
            "mode": "advisory",
            "command": "explain",
            "target": str(target),
            "symbol": symbol,
            "flow": flow,
            "prompt": prompt_template.ref,
            "model": settings.model,
            "files_explained": files_explained,
            "status": "succeeded",
        }
        write_session_json(session, "explanation_metadata.json", metadata)
        session = update_session_status(session, "explanation_completed")
        _record_timeline_event(
            session,
            "explain_completed",
            "trevvos explain",
            "succeeded",
            artifacts=[
                "explanation.md",
                "explanation_metadata.json",
                "project_profile.json",
                "selected_files.json",
                "context.md",
            ],
        )

        if json_output:
            console.print(json.dumps(metadata, indent=2, ensure_ascii=False))
            return

        console.print("[green]Explanation completed.[/green]\n")
        console.print(f"Session:        [bold]{session.metadata.id}[/bold]")
        console.print("Mode:           advisory")
        console.print(f"Target:         {target}")
        console.print(f"Symbol:         {symbol}")
        console.print(f"Flow:           {str(flow).lower()}")
        console.print(f"Prompt:         {prompt_template.ref}")
        console.print(f"Model:          {settings.model}")
        console.print("\n[bold]Saved files[/bold]")
        console.print(f"  - {session.path / 'explanation.md'}")
        console.print(f"  - {session.path / 'explanation_metadata.json'}")
        console.print(f"  - {session.path / 'project_profile.json'}")
        console.print("\n[bold]Explanation[/bold]\n")
        console.print(raw_response)

    except ForgeError as exc:
        if session is not None:
            write_session_json(
                session,
                "explanation_metadata.json",
                {
                    "mode": "advisory",
                    "command": "explain",
                    "target": str(target),
                    "symbol": symbol,
                    "flow": flow,
                    "status": "failed",
                    "error": str(exc),
                },
            )
            _record_timeline_event(
                session,
                "explain_failed",
                "trevvos explain",
                "failed",
                message=str(exc),
                artifacts=["explanation_metadata.json"],
            )
        print_error(str(exc))
        raise typer.Exit(code=1)


@app.command()
def spec(
    request: Annotated[
        str,
        typer.Argument(help="Implementation request to turn into an AI handoff spec."),
    ],
    path: Annotated[
        Path,
        typer.Option("--path", "-p", help="Workspace root path."),
    ] = Path("."),
    target_ai: Annotated[
        str,
        typer.Option("--target", help="External AI target: generic, codex, cursor, or claude."),
    ] = "generic",
    include_code: Annotated[
        bool,
        typer.Option("--include-code/--no-code", help="Include selected source snippets in the handoff context."),
    ] = True,
    json_output: Annotated[
        bool,
        typer.Option("--json", help="Print handoff metadata as JSON."),
    ] = False,
    max_files: Annotated[
        int,
        typer.Option("--max-files", help="Maximum number of files to include."),
    ] = 8,
    max_chars: Annotated[
        int,
        typer.Option("--max-chars", help="Maximum characters per file."),
    ] = 12_000,
) -> None:
    """
    Generate an AI handoff implementation spec without modifying files.
    """
    session = None
    try:
        if not request.strip():
            raise DiffError("Spec request cannot be empty.")

        target_ai = target_ai.lower().strip() or "generic"
        if target_ai not in {"generic", "codex", "cursor", "claude"}:
            raise DiffError("Unsupported spec target. Use one of: generic, codex, cursor, claude.")

        workspace_root = path.resolve()
        settings = load_settings()
        profile = scan_project(workspace_root)
        save_project_profile(workspace_root, profile)
        handoff_context, files_included = _build_handoff_context(
            repo_root=workspace_root,
            request=request,
            target_ai=target_ai,
            include_code=include_code,
            profile=profile,
            max_files=max_files,
            max_chars_per_file=max_chars,
        )
        provider = build_provider(settings)

        session = create_session(
            root=workspace_root,
            user_request=request,
            command="spec",
        )
        _record_timeline_event(session, "spec_started", "trevvos spec", "started")

        prompt_template = get_prompt("implementation_handoff_spec")
        prompt = prompt_template.render(handoff_context=handoff_context)

        write_session_text(session=session, file_name="context.md", content=handoff_context)
        write_session_json(
            session,
            "selected_files.json",
            {
                "mode": "advisory",
                "command": "spec",
                "target": target_ai,
                "include_code": include_code,
                "files_included": files_included,
            },
        )
        write_session_json(session, "project_profile.json", profile)

        with console.status("[bold]Generating implementation handoff spec...[/bold]", spinner="dots"):
            raw_response = provider.generate(prompt)

        write_session_text(session=session, file_name="handoff_spec.md", content=raw_response)
        write_session_text(session=session, file_name="external_ai_prompt.md", content=raw_response)

        metadata = {
            "mode": "advisory",
            "command": "spec",
            "target": target_ai,
            "request": request,
            "prompt": prompt_template.ref,
            "model": settings.model,
            "files_included": files_included,
            "status": "succeeded",
            "artifacts": {
                "handoff_spec": "handoff_spec.md",
                "external_ai_prompt": "external_ai_prompt.md",
                "metadata": "handoff_metadata.json",
                "project_profile": "project_profile.json",
                "selected_files": "selected_files.json",
                "context": "context.md",
            },
        }
        write_session_text(session=session, file_name="handoff_prompt.md", content=prompt)
        write_session_json(session, "handoff_metadata.json", metadata)
        session = update_session_status(session, "spec_completed")
        _record_timeline_event(
            session,
            "spec_completed",
            "trevvos spec",
            "succeeded",
            artifacts=[
                "handoff_spec.md",
                "external_ai_prompt.md",
                "handoff_metadata.json",
                "project_profile.json",
                "selected_files.json",
                "context.md",
            ],
        )

        if json_output:
            console.print(json.dumps(metadata, indent=2, ensure_ascii=False))
            return

        console.print("[green]Implementation handoff spec generated.[/green]\n")
        console.print(f"Session:        [bold]{session.metadata.id}[/bold]")
        console.print("Mode:           advisory")
        console.print(f"Target AI:      {target_ai}")
        console.print(f"Files included: {len(files_included)}")
        console.print(f"Prompt:         {prompt_template.ref}")
        console.print(f"Model:          {settings.model}")
        console.print("\n[bold]Saved files[/bold]")
        console.print(f"  - {session.path / 'handoff_spec.md'}")
        console.print(f"  - {session.path / 'external_ai_prompt.md'}")
        console.print(f"  - {session.path / 'handoff_metadata.json'}")
        console.print(f"  - {session.path / 'project_profile.json'}")
        console.print("\n[bold]Next[/bold]")
        console.print(f"  Copy {session.path / 'external_ai_prompt.md'} into your preferred coding AI.")

    except ForgeError as exc:
        if session is not None:
            write_session_json(
                session,
                "handoff_metadata.json",
                {
                    "mode": "advisory",
                    "command": "spec",
                    "target": target_ai,
                    "request": request,
                    "status": "failed",
                    "error": str(exc),
                },
            )
            _record_timeline_event(
                session,
                "spec_failed",
                "trevvos spec",
                "failed",
                message=str(exc),
                artifacts=["handoff_metadata.json"],
            )
        print_error(str(exc))
        raise typer.Exit(code=1)


@app.command()
def context(
    instruction: str,
    path: Annotated[
        Path,
        typer.Option("--path", "-p", help="Workspace root path."),
    ] = Path("."),
    max_files: Annotated[
        int,
        typer.Option("--max-files", help="Maximum number of files to include."),
    ] = 8,
    max_chars: Annotated[
        int,
        typer.Option("--max-chars", help="Maximum total characters in context."),
    ] = 30_000,
) -> None:
    """
    Build and save automatic project context for a request.
    """
    try:
        session = create_session(
            root=path,
            user_request=instruction,
            command="context",
        )

        with console.status("[bold]Building project context...[/bold]", spinner="dots"):
            built_context = build_context(
                root=path,
                instruction=instruction,
                max_files=max_files,
                max_total_chars=max_chars,
            )

        write_session_text(
            session=session,
            file_name="context.md",
            content=built_context.to_markdown(),
        )

        write_session_text(
            session=session,
            file_name="selected_files.json",
            content=built_context.selected_files_json(),
        )

        console.print("[green]Context created.[/green]\n")
        console.print(f"Session:        [bold]{session.metadata.id}[/bold]")
        console.print(f"Selected files: {len(built_context.selected_files)}")
        console.print(f"Context chars:  {built_context.total_chars}")

        if built_context.selected_files:
            console.print("\n[bold]Selected files[/bold]")
            for selected_file in built_context.selected_files:
                console.print(
                    f"  - {selected_file.path} "
                    f"[dim](score={selected_file.score}; {selected_file.reason})[/dim]"
                )

        console.print("\n[bold]Saved files[/bold]")
        console.print(f"  - {session.path / 'context.md'}")
        console.print(f"  - {session.path / 'selected_files.json'}")

        console.print("\n[bold]Next[/bold]")
        console.print("  trevvos sessions show")
        console.print("  trevvos plan \"...\"")

    except ForgeError as exc:
        print_error(str(exc))
        raise typer.Exit(code=1)


@app.command()
def status(
    session_id: Annotated[
        str | None,
        typer.Option("--session", "-s", help="Session ID to use. Defaults to current session."),
    ] = None,
    path: Annotated[
        Path,
        typer.Option("--path", "-p", help="Workspace root path."),
    ] = Path("."),
    json_output: Annotated[
        bool,
        typer.Option("--json", help="Print status as JSON."),
    ] = False,
    verbose: Annotated[
        bool,
        typer.Option("--verbose", "-v", help="Show artifact paths and extra details."),
    ] = False,
) -> None:
    """
    Show an operational checklist for the current Forge session.
    """
    try:
        workspace_root = path.resolve()

        if session_id:
            session = get_session(root=workspace_root, session_id=session_id)
        else:
            session = get_current_session(workspace_root)

        session_status = build_session_status(
            session_dir=session.path,
            repo_root=workspace_root,
        )
        write_session_status(session.path, session_status)

        if json_output:
            console.print_json(json.dumps(session_status, ensure_ascii=False))
            return

        console.print(render_status_text(session_status, verbose=verbose))

    except ForgeError as exc:
        print_error(str(exc))
        raise typer.Exit(code=1)


@app.command("next")
def next_command(
    session_id: Annotated[
        str | None,
        typer.Option("--session", "-s", help="Session ID to use. Defaults to current session."),
    ] = None,
    path: Annotated[
        Path,
        typer.Option("--path", "-p", help="Workspace root path."),
    ] = Path("."),
    json_output: Annotated[
        bool,
        typer.Option("--json", help="Print next action as JSON."),
    ] = False,
) -> None:
    """
    Show the next recommended command for the current Forge session.
    """
    try:
        workspace_root = path.resolve()

        if session_id:
            session = get_session(root=workspace_root, session_id=session_id)
        else:
            session = get_current_session(workspace_root)

        agent_state = determine_agent_state(session.path)
        next_action = determine_next_action(agent_state)
        payload = {
            "session_id": agent_state.session_id,
            "phase": agent_state.phase,
            "status": agent_state.status,
            "next_action": next_action.to_dict(),
            "blockers": agent_state.blockers,
            "warnings": agent_state.warnings,
        }

        if json_output:
            console.print_json(json.dumps(payload, ensure_ascii=False))
            return

        console.print("[bold]Next recommended command:[/bold]")
        console.print(next_action.command or "None")
        console.print("\n[bold]Reason:[/bold]")
        console.print(next_action.reason or "Session complete.")
        console.print("\n[bold]State:[/bold]")
        console.print(f"  Phase:      {agent_state.phase}")
        console.print(f"  Confidence: {agent_state.confidence}")

        if agent_state.blockers:
            console.print("\n[bold]Blockers[/bold]")
            for blocker in agent_state.blockers:
                console.print(f"  - {blocker}")

    except ForgeError as exc:
        print_error(str(exc))
        raise typer.Exit(code=1)


@app.command()
def work(
    instruction: str,
    path: Annotated[
        Path,
        typer.Option("--path", "-p", help="Workspace root path."),
    ] = Path("."),
    max_retries: Annotated[
        int,
        typer.Option("--max-retries", help="Maximum diff retry attempts."),
    ] = 2,
    max_plan_retries: Annotated[
        int,
        typer.Option("--max-plan-retries", help="Maximum plan retry attempts."),
    ] = 2,
    max_repairs: Annotated[
        int,
        typer.Option("--max-repairs", help="Maximum repair attempts."),
    ] = 2,
    yes: Annotated[
        bool,
        typer.Option("--yes", "-y", help="Run non-interactively where confirmations would be required."),
    ] = False,
    max_files: Annotated[
        int,
        typer.Option("--max-files", help="Maximum number of files to include in planning context."),
    ] = 5,
    max_chars: Annotated[
        int,
        typer.Option("--max-chars", help="Maximum total characters in planning context."),
    ] = 16_000,
) -> None:
    """
    Run a controlled agent loop until the session is ready to apply.
    """
    workspace_root = path.resolve()
    session = None
    steps: list[dict] = []
    plan_retries_used = 0
    retries_used = 0
    repairs_used = 0
    force_action: str | None = None

    def current_session():
        return get_current_session(workspace_root)

    def finish(status: str, state, reason: str | None = None, exit_code: int = 0) -> None:
        metadata = build_work_metadata(
            request=instruction,
            status=status,
            max_retries=max_retries,
            max_repairs=max_repairs,
            max_plan_retries=max_plan_retries,
            retries_used=retries_used,
            repairs_used=repairs_used,
            plan_retries_used=plan_retries_used,
            final_phase=state.phase if state is not None else "unknown",
            next_command=state.next_command if state is not None else None,
            steps=steps,
            reason=reason,
        )
        if session is not None:
            write_work_artifacts(session, metadata)
            _record_timeline_event(
                session,
                "work_ready_to_apply" if status == "ready_to_apply" else "work_blocked",
                "trevvos work",
                "succeeded" if status == "ready_to_apply" else "failed",
                reason=reason,
                artifacts=["work_metadata.json", "work_summary.md"],
                next_recommended_command=metadata.get("next_command"),
            )
            _record_timeline_event(
                session,
                "work_stopped",
                "trevvos work",
                "succeeded" if exit_code == 0 else "failed",
                reason=reason,
                artifacts=["work_metadata.json", "work_summary.md"],
                next_recommended_command=metadata.get("next_command"),
            )

        if status == "ready_to_apply":
            console.print("[green]Work reached ready_to_apply.[/green]")
            console.print("Next: trevvos apply")
        else:
            console.print(f"[red]{reason or 'Work stopped.'}[/red]")
            if state is not None and state.next_command:
                console.print(f"Next: {state.next_command}")

        if exit_code:
            raise typer.Exit(code=exit_code)

    def run_step(step_name: str, callable_step) -> bool:
        nonlocal session
        if session is not None:
            _record_timeline_event(
                session,
                "work_step_started",
                "trevvos work",
                "started",
                message=step_name,
            )
        try:
            callable_step()
        except typer.Exit as exc:
            code = exc.exit_code if isinstance(exc.exit_code, int) else 1
            step = {"step": step_name, "status": "failed", "exit_code": code}
            steps.append(step)
            if session is None:
                try:
                    session = current_session()
                except ForgeError:
                    session = None
            if session is not None:
                state = determine_agent_state(session.path)
                if state.reason:
                    step["reason"] = state.phase
                _record_timeline_event(
                    session,
                    "work_step_failed",
                    "trevvos work",
                    "failed",
                    reason=step.get("reason"),
                    message=step_name,
                )
            return False

        if session is None:
            session = current_session()
        steps.append({"step": step_name, "status": "succeeded"})
        _record_timeline_event(
            session,
            "work_step_completed",
            "trevvos work",
            "succeeded",
            message=step_name,
        )
        return True

    try:
        if max_retries < 0 or max_repairs < 0 or max_plan_retries < 0:
            raise DiffError("--max-retries, --max-plan-retries, and --max-repairs must be zero or greater.")

        console.print("[bold]Starting Trevvos work loop...[/bold]\n")
        if not run_step(
            "plan",
            lambda: plan(
                instruction=instruction,
                path=workspace_root,
                max_files=max_files,
                max_chars=max_chars,
            ),
        ):
            if session is not None:
                state = determine_agent_state(session.path)
                if state.next_action != "retry_plan":
                    finish("blocked", state, "Plan failed.", exit_code=1)
                    return
            else:
                raise DiffError("Plan failed before a session was created.")
        session = current_session()
        _record_timeline_event(
            session,
            "work_started",
            "trevvos work",
            "started",
            message=instruction,
        )

        while True:
            state = determine_agent_state(session.path)

            if state.phase == "ready_to_apply":
                finish("ready_to_apply", state)
                return

            if state.phase == "blocked":
                finish("blocked", state, state.reason or "Work blocked.", exit_code=1)
                return

            action = force_action or state.next_action
            force_action = None

            if action == "diff":
                run_step("diff", lambda: diff(path=workspace_root, retry=False))
                continue

            if action == "retry_plan":
                if plan_retries_used >= max_plan_retries:
                    reason = (
                        "verification_coverage_failed"
                        if state.phase == "verification_coverage_failed"
                        else "max_plan_retries_reached"
                    )
                    finish("blocked", state, reason, exit_code=1)
                    return
                plan_retries_used += 1
                run_step("plan_retry", lambda: plan(instruction=None, path=workspace_root, retry=True))
                continue

            if action == "retry_diff":
                if retries_used >= max_retries:
                    finish("blocked", state, "Diff retry limit reached.", exit_code=1)
                    return
                retries_used += 1
                run_step("diff_retry", lambda: diff(path=workspace_root, retry=True))
                continue

            if action == "test_sandbox":
                run_step(
                    "sandbox_test",
                    lambda: test(
                        path=workspace_root,
                        yes=True or yes,
                        sandbox=True,
                        plan_commands=True,
                    ),
                )
                continue

            if action == "review":
                run_step("review", lambda: review(path=workspace_root, no_llm=True))
                continue

            if action == "repair":
                if repairs_used >= max_repairs:
                    finish("blocked", state, "Repair limit reached.", exit_code=1)
                    return
                repairs_used += 1
                if run_step("repair", lambda: repair(path=workspace_root)):
                    force_action = "test_sandbox"
                continue

            finish("blocked", state, state.reason or "No safe automatic work action is available.", exit_code=1)
            return

    except ForgeError as exc:
        if session is not None:
            state = determine_agent_state(session.path)
            finish("blocked", state, str(exc), exit_code=1)
            return
        print_error(str(exc))
        raise typer.Exit(code=1)


@app.command()
def plan(
    instruction: Annotated[
        str | None,
        typer.Argument(help="Change request. Omit when using --retry."),
    ] = None,
    path: Annotated[
        Path,
        typer.Option("--path", "-p", help="Workspace root path."),
    ] = Path("."),
    retry: Annotated[
        bool,
        typer.Option("--retry", help="Retry planning from plan_error.json in the current session."),
    ] = False,
    max_files: Annotated[
        int,
        typer.Option("--max-files", help="Maximum number of files to include in context."),
    ] = 5,
    max_chars: Annotated[
        int,
        typer.Option("--max-chars", help="Maximum total characters in context."),
    ] = 16_000,
) -> None:
    """
    Create a structured technical change plan and save it into a local session.
    """
    session = None

    try:
        settings = load_settings()
        provider = build_provider(settings)

        if retry:
            session = get_current_session(path)
            plan_error = _read_json_file(session.path / "plan_error.json")
            coverage_retry = has_failed_verification_coverage(session.path)
            if not isinstance(plan_error, dict) and not coverage_retry:
                raise DiffError("No plan_error.json found for current session.")

            retry_count = _plan_retry_count(session)
            previous_error_type = None
            if isinstance(plan_error, dict) and isinstance(plan_error.get("error_type"), str):
                previous_error_type = plan_error["error_type"]
            if previous_error_type is None and coverage_retry:
                previous_error_type = "verification_coverage_failed"
            prompt_template = get_prompt("plan_retry")
            prompt = prompt_template.render(retry_context=_build_plan_retry_context(session))

            write_session_text(session=session, file_name="plan_retry_prompt.md", content=prompt)
            _record_timeline_event(
                session,
                "plan_retry_started",
                "trevvos plan --retry",
                "started",
                reason=previous_error_type,
            )

            with console.status("[bold]Retrying plan with your local LLM...[/bold]", spinner="dots"):
                raw_plan_response = provider.generate(prompt)

            write_session_text(
                session=session,
                file_name="plan_raw_response.md",
                content=raw_plan_response,
            )

            try:
                plan_output = parse_plan_output(raw_plan_response)
            except StructuredOutputError as exc:
                artifact = write_plan_error_artifacts(session, str(exc))
                _write_plan_retry_metadata(
                    session,
                    retry_count=retry_count,
                    previous_error_type=previous_error_type,
                    status="failed",
                )
                update_session_status(session, "plan_failed")
                _record_timeline_event(
                    session,
                    "plan_retry_failed",
                    "trevvos plan --retry",
                    "failed",
                    reason=artifact.error_type,
                    message=artifact.message,
                    artifacts=["plan_raw_response.md", "plan_error.json", "plan_error.md", "plan_retry_metadata.json"],
                    next_recommended_command="trevvos plan --retry",
                )
                _record_timeline_event(
                    session,
                    "plan_failed",
                    "trevvos plan --retry",
                    "failed",
                    reason=artifact.error_type,
                    message=artifact.message,
                    artifacts=["plan_error.json", "plan_error.md"],
                    next_recommended_command="trevvos plan --retry",
                )
                print_error(str(exc))
                console.print("\n[bold]Saved error artifacts[/bold]")
                console.print(f"  - {session.path / 'plan_raw_response.md'}")
                console.print(f"  - {session.path / 'plan_error.json'}")
                console.print(f"  - {session.path / 'plan_error.md'}")
                raise typer.Exit(code=1)

            write_session_json(session=session, file_name="plan.json", data=plan_output.to_dict())
            verification_coverage = write_verification_coverage(session, plan_output.to_dict())
            plan_markdown = plan_output.to_markdown()
            write_session_text(session=session, file_name="plan.md", content=plan_markdown)
            retry_status = "failed" if verification_coverage["status"] == "failed" else "succeeded"
            if retry_status == "succeeded":
                _clear_plan_error_artifacts(session)
            _write_plan_retry_metadata(
                session,
                retry_count=retry_count,
                previous_error_type=previous_error_type,
                status=retry_status,
            )
            if retry_status == "failed":
                update_session_status(session, "plan_failed")
                _record_timeline_event(
                    session,
                    "plan_retry_failed",
                    "trevvos plan --retry",
                    "failed",
                    reason="verification_coverage_failed",
                    artifacts=["plan.json", "plan.md", "verification_coverage.json", "plan_retry_metadata.json"],
                    next_recommended_command="trevvos plan --retry",
                )
                console.print("[red]Plan retry failed verification coverage.[/red]")
                console.print(f"  - {session.path / 'verification_coverage.json'}")
                raise typer.Exit(code=1)
            session = update_session_status(session, "planned")
            _record_timeline_event(
                session,
                "plan_retry_completed",
                "trevvos plan --retry",
                "succeeded",
                reason=previous_error_type,
                artifacts=["plan_raw_response.md", "plan.json", "plan.md", "verification_coverage.json", "plan_retry_metadata.json"],
                next_recommended_command="trevvos diff",
            )
            _record_timeline_event(
                session,
                "plan_completed",
                "trevvos plan --retry",
                "succeeded",
                artifacts=["plan_raw_response.md", "plan.json", "plan.md", "verification_coverage.json", "plan_retry_metadata.json"],
                next_recommended_command="trevvos diff",
            )

            console.print("[green]Plan retry succeeded.[/green]\n")
            console.print(f"Session:        [bold]{session.metadata.id}[/bold]")
            console.print(f"Status:         {session.metadata.status}")
            console.print(f"Prompt:         {prompt_template.ref}")
            console.print("\n[bold]Saved files[/bold]")
            console.print(f"  - {session.path / 'plan_raw_response.md'}")
            console.print(f"  - {session.path / 'plan.json'}")
            console.print(f"  - {session.path / 'plan.md'}")
            console.print(f"  - {session.path / 'verification_coverage.json'}")
            console.print(f"  - {session.path / 'plan_retry_metadata.json'}")
            console.print("\n[bold]Next[/bold]")
            console.print("  trevvos diff")
            return

        if not instruction:
            raise DiffError('Missing plan instruction. Use trevvos plan "..." or trevvos plan --retry.')

        session = create_session(
            root=path,
            user_request=instruction,
            command="plan",
        )
        _record_timeline_event(
            session,
            "plan_started",
            "trevvos plan",
            "started",
            next_recommended_command=None,
        )

        with console.status("[bold]Building project context...[/bold]", spinner="dots"):
            built_context = build_context(
                root=path,
                instruction=instruction,
                max_files=max_files,
                max_total_chars=max_chars,
            )

        context_markdown = built_context.to_markdown()

        write_session_text(
            session=session,
            file_name="context.md",
            content=context_markdown,
        )

        write_session_text(
            session=session,
            file_name="selected_files.json",
            content=built_context.selected_files_json(),
        )

        prompt_template = get_prompt("plan_change_json")

        prompt = prompt_template.render(
            instruction=instruction,
            workspace_context=context_markdown,
        )

        write_session_text(
            session=session,
            file_name="prompt.md",
            content=prompt,
        )

        write_session_json(
            session=session,
            file_name="prompt_metadata.json",
            data={
                "name": prompt_template.name,
                "version": prompt_template.version,
                "ref": prompt_template.ref,
                "description": prompt_template.description,
                "model": settings.model,
                "provider": "ollama",
            },
        )

        with console.status("[bold]Planning change with your local LLM...[/bold]", spinner="dots"):
            raw_plan_response = provider.generate(prompt)

        write_session_text(
            session=session,
            file_name="plan_raw_response.md",
            content=raw_plan_response,
        )

        try:
            plan_output = parse_plan_output(raw_plan_response)
        except StructuredOutputError as exc:
            artifact = write_plan_error_artifacts(session, str(exc))
            update_session_status(session, "plan_failed")
            _record_timeline_event(
                session,
                "plan_failed",
                "trevvos plan",
                "failed",
                reason=artifact.error_type,
                message=artifact.message,
                artifacts=["plan_raw_response.md", "plan_error.json", "plan_error.md"],
                next_recommended_command="trevvos plan --retry",
            )
            console.print("[red]Plan failed.[/red]")
            print_error(str(exc))
            console.print("\n[bold]Saved error artifacts[/bold]")
            console.print(f"  - {session.path / 'plan_raw_response.md'}")
            console.print(f"  - {session.path / 'plan_error.json'}")
            console.print(f"  - {session.path / 'plan_error.md'}")
            raise typer.Exit(code=1)

        write_session_json(
            session=session,
            file_name="plan.json",
            data=plan_output.to_dict(),
        )
        verification_coverage = write_verification_coverage(session, plan_output.to_dict())

        plan_markdown = plan_output.to_markdown()

        write_session_text(
            session=session,
            file_name="plan.md",
            content=plan_markdown,
        )

        session = update_session_status(session, "planned")
        _record_timeline_event(
            session,
            "plan_completed",
            "trevvos plan",
            "succeeded",
            artifacts=[
                "context.md",
                "selected_files.json",
                "prompt.md",
                "prompt_metadata.json",
                "plan_raw_response.md",
                "plan.json",
                "plan.md",
                "verification_coverage.json",
            ],
            next_recommended_command="trevvos diff",
        )

        console.print("[green]Plan created.[/green]\n")
        console.print(f"Session:        [bold]{session.metadata.id}[/bold]")
        console.print(f"Status:         {session.metadata.status}")
        console.print(f"Prompt:         {prompt_template.ref}")
        console.print(f"Model:          {settings.model}")
        console.print(f"Selected files: {len(built_context.selected_files)}")
        console.print(f"Context chars:  {built_context.total_chars}")

        if built_context.selected_files:
            console.print("\n[bold]Selected files[/bold]")
            for selected_file in built_context.selected_files:
                console.print(
                    f"  - {selected_file.path} "
                    f"[dim](score={selected_file.score}; {selected_file.reason})[/dim]"
                )

        console.print("\n[bold]Saved files[/bold]")
        console.print(f"  - {session.path / 'context.md'}")
        console.print(f"  - {session.path / 'selected_files.json'}")
        console.print(f"  - {session.path / 'prompt.md'}")
        console.print(f"  - {session.path / 'prompt_metadata.json'}")
        console.print(f"  - {session.path / 'plan_raw_response.md'}")
        console.print(f"  - {session.path / 'plan.json'}")
        console.print(f"  - {session.path / 'plan.md'}")
        console.print(f"  - {session.path / 'verification_coverage.json'}")

        if verification_coverage["status"] == "failed":
            console.print("\n[bold yellow]Verification coverage warnings[/bold yellow]")
            for warning in verification_coverage.get("warnings", []):
                console.print(f"  - {warning}")

        console.print("\n[bold]Plan[/bold]\n")
        console.print(plan_markdown)

        console.print("\n[bold]Next[/bold]")
        console.print("  trevvos diff")

    except ForgeError as exc:
        if session is not None:
            write_session_text(
                session=session,
                file_name="error.txt",
                content=str(exc),
            )
            update_session_status(session, "plan_failed")
            _record_timeline_event(
                session,
                "plan_failed",
                "trevvos plan --retry" if retry else "trevvos plan",
                "failed",
                reason=type(exc).__name__,
                message=str(exc),
                artifacts=["error.txt"],
            )

        print_error(str(exc))
        raise typer.Exit(code=1)


@app.command()
def diff(
    session_id: Annotated[
        str | None,
        typer.Option("--session", "-s", help="Session ID to use. Defaults to current session."),
    ] = None,
    path: Annotated[
        Path,
        typer.Option("--path", "-p", help="Workspace root path."),
    ] = Path("."),
    retry: Annotated[
        bool,
        typer.Option(
            "--retry",
            help="Retry diff generation using operation_error.json or file_changes_error.json from the session.",
        ),
    ] = False,
) -> None:
    """
    Generate a unified diff from a saved plan session.
    """
    session = None
    retry_metadata: dict | None = None
    retry_context_loaded = False

    try:
        workspace_root = path.resolve()
        settings = load_settings()
        provider = build_provider(settings)

        if session_id:
            session = get_session(root=workspace_root, session_id=session_id)
        else:
            session = get_current_session(workspace_root)

        context_path = session.path / "context.md"
        plan_path = session.path / "plan.md"

        if not context_path.exists():
            raise DiffError("Session is missing context.md. Run trevvos plan before trevvos diff.")

        if not plan_path.exists():
            raise DiffError("Session is missing plan.md. Run trevvos plan before trevvos diff.")

        timeline_command = "trevvos diff --retry" if retry else "trevvos diff"
        _record_timeline_event(
            session,
            "diff_retry_started" if retry else "diff_started",
            timeline_command,
            "started",
        )

        instruction = read_session_text(session, "user_request.txt")
        workspace_context = read_session_text(session, "context.md")
        plan_markdown = read_session_text(session, "plan.md")
        plan_constraints = load_plan_constraints(session.path)
        plan_constraints_section = build_plan_constraints_prompt_section(plan_constraints)

        if retry:
            console.print("[bold]Retrying diff after previous diff generation error...[/bold]\n")
            retry_context = build_retry_context(session=session, repo_root=workspace_root)
            retry_context_loaded = True
            previous_error = retry_context["previous_error"]
            prompt_template = get_prompt("file_changes_retry")
            retry_metadata = build_retry_metadata(
                session=session,
                prompt_ref=prompt_template.ref,
                status="started",
                operation_error=previous_error,
            )

            console.print("[bold]Previous error[/bold]")
            console.print(f"  - source: {retry_context.get('retry_error_source', 'unknown')}")
            console.print(f"  - type: {previous_error.get('error_type', 'unknown')}")
            if previous_error.get("path") is not None:
                console.print(f"  - path: {previous_error.get('path', 'unknown')}")
            if previous_error.get("operation") is not None:
                console.print(f"  - operation: {previous_error.get('operation', 'unknown')}")
            if previous_error.get("target") is not None:
                console.print(f"  - target: {previous_error.get('target', 'unknown')}")

            prompt = build_retry_prompt(retry_context)
        else:
            prompt_template = get_prompt("file_changes_generation")

            prompt = prompt_template.render(
                instruction=instruction,
                workspace_context=workspace_context,
                plan=plan_markdown,
                plan_constraints=plan_constraints_section,
            )

        write_session_text(
            session=session,
            file_name="diff_prompt.md",
            content=prompt,
        )

        write_session_json(
            session=session,
            file_name="diff_prompt_metadata.json",
            data={
                "name": prompt_template.name,
                "version": prompt_template.version,
                "ref": prompt_template.ref,
                "description": prompt_template.description,
                "model": settings.model,
                "provider": "ollama",
            },
        )

        with console.status("[bold]Generating file changes with your local LLM...[/bold]", spinner="dots"):
            raw_file_changes_response = provider.generate(prompt)

        write_session_text(
            session=session,
            file_name="file_changes_raw_response.json",
            content=raw_file_changes_response,
        )

        file_changes = parse_file_changes_output(raw_file_changes_response)

        write_session_json(
            session=session,
            file_name="file_changes.json",
            data=file_changes.to_dict(),
        )

        plan_constraints_check = check_file_changes_against_plan_constraints(
            file_changes=file_changes,
            constraints=plan_constraints,
        )
        write_plan_constraints_check(session.path, plan_constraints_check)

        if plan_constraints_check["status"] == "failed":
            violations = plan_constraints_check.get("violations", [])
            detail = violations[0] if violations else "plan constraints were violated."
            _record_timeline_event(
                session,
                "plan_constraints_failed",
                timeline_command,
                "failed",
                reason="plan_constraints_failed",
                message=str(detail),
                artifacts=["plan_constraints_check.json"],
            )
            raise DiffError(f"Diff rejected: file {detail}")

        diff_warnings: list[str] = []
        if plan_constraints_check["status"] == "warning":
            diff_warnings.extend(plan_constraints_check.get("warnings", []))
        diff_warnings.extend(
            detect_small_file_structural_edit_risk(
                file_changes=file_changes,
                repo_root=workspace_root,
                plan=plan_constraints,
                request=instruction,
            )
        )
        cli_regression_check = build_cli_regression_check(
            workspace_root=workspace_root,
            file_changes=file_changes,
        )
        write_cli_regression_check(session, cli_regression_check)
        diff_warnings.extend(cli_regression_check.get("warnings", []))

        unified_diff = build_unified_diff_from_file_changes(
            workspace_root=workspace_root,
            file_changes=file_changes,
            warnings=diff_warnings,
        )

        write_session_text(
            session=session,
            file_name="diff.patch",
            content=unified_diff,
        )

        if diff_warnings:
            write_session_json(
                session=session,
                file_name="diff_warnings.json",
                data={"warnings": diff_warnings},
            )
        else:
            _delete_session_files(session.path, ["diff_warnings.json"])

        validation_result = validate_diff_patch(
            workspace_root=workspace_root,
            session=session,
            diff_text=unified_diff,
        )

        write_session_json(
            session=session,
            file_name="diff_validation.json",
            data=validation_result.to_dict(),
        )

        check_patch(workspace_root=workspace_root, session=session)

        write_session_json(
            session=session,
            file_name="diff_check.json",
            data={
                "git_apply_check": "passed",
                "patch_path": str(session.path / "diff.patch"),
            },
        )

        change_summary = build_change_summary_markdown(
            request=instruction,
            file_changes=file_changes,
            warnings=diff_warnings,
            plan_constraints_status=plan_constraints_check["status"],
        )
        semantic_review = build_semantic_review_json(
            request=instruction,
            file_changes=file_changes,
            warnings=diff_warnings,
            plan_constraints_status=plan_constraints_check["status"],
            plan=plan_constraints,
            plan_constraints_check=plan_constraints_check,
            verification_coverage=_read_json_file(session.path / "verification_coverage.json"),
            cli_regression_check=cli_regression_check,
        )

        write_session_text(
            session=session,
            file_name="change_summary.md",
            content=change_summary,
        )

        write_session_json(
            session=session,
            file_name="semantic_review.json",
            data=semantic_review,
        )

        _delete_session_files(
            session.path,
            [
                "file_changes_error.txt",
                "file_changes_error.json",
                "file_changes_error.md",
                "diff_error.txt",
                "operation_error.json",
                "operation_error.md",
                "diff_validation_error.txt",
                "diff_check_error.txt",
            ],
        )

        if retry and retry_metadata is not None:
            retry_metadata["status"] = "succeeded"
            write_retry_metadata(session, retry_metadata)

        session = update_session_status(session, "diff_validated")
        _record_timeline_event(
            session,
            "diff_retry_completed" if retry else "diff_completed",
            timeline_command,
            "succeeded",
            artifacts=[
                "file_changes_raw_response.json",
                "file_changes.json",
                "plan_constraints_check.json",
                "cli_regression_check.json",
                "diff.patch",
                "diff_validation.json",
                "diff_check.json",
                "change_summary.md",
                "semantic_review.json",
            ],
            files_changed=[change.path for change in file_changes.changes],
            warnings_count=len(diff_warnings),
            next_recommended_command="trevvos apply",
        )

        if retry:
            console.print("\n[green]Retry generated a new diff successfully.[/green]\n")
        else:
            console.print("[green]Diff generated successfully.[/green]\n")
        console.print(f"Session: {session.metadata.id}")
        console.print(f"Status:  {session.metadata.status}")
        console.print(f"Prompt:  {prompt_template.ref}")
        console.print(f"Model:   {settings.model}")

        console.print("\n[bold]Files changed[/bold]")
        for change in file_changes.changes:
            descriptor = change.mode

            if change.operation:
                descriptor = f"{descriptor} / {change.operation}"

            console.print(f"  - {change.path} [{change.change_type}] {descriptor}")

        console.print("\n[bold]Artifacts[/bold]")
        if retry:
            console.print(f"  - retry_metadata.json: {session.path / 'retry_metadata.json'}")
        console.print(f"  - plan_constraints_check.json: {session.path / 'plan_constraints_check.json'}")
        console.print(f"  - diff.patch: {session.path / 'diff.patch'}")
        console.print(f"  - change_summary.md: {session.path / 'change_summary.md'}")
        console.print(f"  - semantic_review.json: {session.path / 'semantic_review.json'}")

        console.print("\n[bold]Validations[/bold]")
        console.print("  - Forge safety validation: passed")
        console.print("  - git apply --check: passed")

        console.print("\n[bold]Warnings[/bold]")
        if diff_warnings:
            for warning in diff_warnings:
                console.print(f"  - [yellow]{warning}[/yellow]")
        else:
            console.print("  - None")

        console.print("\n[bold]Saved files[/bold]")
        console.print(f"  - {session.path / 'file_changes_raw_response.json'}")
        console.print(f"  - {session.path / 'file_changes.json'}")
        console.print(f"  - {session.path / 'plan_constraints_check.json'}")
        console.print(f"  - {session.path / 'diff.patch'}")
        if retry:
            console.print(f"  - {session.path / 'retry_metadata.json'}")
        if diff_warnings:
            console.print(f"  - {session.path / 'diff_warnings.json'}")
        console.print(f"  - {session.path / 'diff_validation.json'}")
        console.print(f"  - {session.path / 'diff_check.json'}")
        console.print(f"  - {session.path / 'change_summary.md'}")
        console.print(f"  - {session.path / 'semantic_review.json'}")

        console.print("\n[bold]Next[/bold]")
        console.print("  Run `trevvos apply` to review and apply the patch.")

    except FileChangeOutputError as exc:
        if session is not None:
            write_file_changes_error_artifacts(session, str(exc))
            write_session_text(
                session=session,
                file_name="file_changes_error.txt",
                content=str(exc),
            )
            if retry and retry_metadata is not None:
                retry_metadata["status"] = "failed"
                write_retry_metadata(session, retry_metadata)
            update_session_status(session, "diff_generation_failed")
            reason = (
                "invalid_file_changes_schema"
                if "Missing or invalid list field: changes" in str(exc)
                else "invalid_file_changes_output"
            )
            command_name = "trevvos diff --retry" if retry else "trevvos diff"
            _record_timeline_event(
                session,
                "file_changes_error",
                command_name,
                "failed",
                reason=reason,
                message=str(exc),
                artifacts=["file_changes_error.json", "file_changes_error.md"],
                next_recommended_command="trevvos diff --retry",
            )
            _record_timeline_event(
                session,
                "diff_retry_failed" if retry else "diff_failed",
                command_name,
                "failed",
                reason=reason,
                message=str(exc),
                artifacts=["file_changes_error.json", "file_changes_error.md"],
                next_recommended_command="trevvos diff --retry",
            )

        if retry:
            console.print("\n[red]Retry failed.[/red]")
        print_error(str(exc))
        if session is not None:
            console.print("\n[bold]File changes error artifacts[/bold]")
            console.print(f"  - {session.path / 'file_changes_error.json'}")
            console.print(f"  - {session.path / 'file_changes_error.md'}")
        raise typer.Exit(code=1)

    except DiffValidationError as exc:
        if session is not None:
            write_session_text(
                session=session,
                file_name="diff_validation_error.txt",
                content=str(exc),
            )
            if retry and retry_metadata is not None:
                retry_metadata["status"] = "failed"
                write_retry_metadata(session, retry_metadata)
            update_session_status(session, "diff_validation_failed")
            _record_timeline_event(
                session,
                "diff_retry_failed" if retry else "diff_failed",
                "trevvos diff --retry" if retry else "trevvos diff",
                "failed",
                reason="diff_validation_failed",
                message=str(exc),
                artifacts=["diff_validation_error.txt"],
            )

        if retry:
            console.print("\n[red]Retry failed.[/red]")
        print_error(str(exc))
        raise typer.Exit(code=1)

    except ApplyError as exc:
        message = (
            "Diff rejected: patch passed safety validation but failed git apply --check. "
            f"{exc}"
        )

        if session is not None:
            write_session_text(
                session=session,
                file_name="diff_check_error.txt",
                content=message,
            )
            if retry and retry_metadata is not None:
                retry_metadata["status"] = "failed"
                write_retry_metadata(session, retry_metadata)
            update_session_status(session, "diff_check_failed")
            _record_timeline_event(
                session,
                "diff_retry_failed" if retry else "diff_failed",
                "trevvos diff --retry" if retry else "trevvos diff",
                "failed",
                reason="git_apply_check_failed",
                message=message,
                artifacts=["diff_check_error.txt"],
            )

        if retry:
            console.print("\n[red]Retry failed.[/red]")
        print_error(message)
        raise typer.Exit(code=1)

    except ForgeError as exc:
        if session is not None:
            write_session_text(
                session=session,
                file_name="diff_error.txt",
                content=str(exc),
            )
            if not retry or retry_context_loaded:
                write_operation_error_artifacts(session, str(exc))
            if retry and retry_metadata is not None:
                retry_metadata["status"] = "failed"
                write_retry_metadata(session, retry_metadata)
            update_session_status(session, "diff_generation_failed")
            command_name = "trevvos diff --retry" if retry else "trevvos diff"
            if not retry or retry_context_loaded:
                _record_timeline_event(
                    session,
                    "operation_error",
                    command_name,
                    "failed",
                    reason="operation_error",
                    message=str(exc),
                    artifacts=["operation_error.json", "operation_error.md"],
                    next_recommended_command="trevvos diff --retry",
                )
            _record_timeline_event(
                session,
                "diff_retry_failed" if retry else "diff_failed",
                command_name,
                "failed",
                reason="diff_generation_failed",
                message=str(exc),
                artifacts=["diff_error.txt"],
                next_recommended_command="trevvos diff --retry",
            )

        if retry:
            console.print("\n[red]Retry failed.[/red]")
        print_error(str(exc))
        if session is not None and (not retry or retry_context_loaded):
            console.print("\n[bold]Operation error artifacts[/bold]")
            console.print(f"  - {session.path / 'operation_error.json'}")
            console.print(f"  - {session.path / 'operation_error.md'}")
        raise typer.Exit(code=1)


@app.command()
def repair(
    session_id: Annotated[
        str | None,
        typer.Option("--session", "-s", help="Session ID to use. Defaults to current session."),
    ] = None,
    path: Annotated[
        Path,
        typer.Option("--path", "-p", help="Workspace root path."),
    ] = Path("."),
    provider_name: Annotated[
        str,
        typer.Option("--provider", help="LLM provider to use for repair."),
    ] = "ollama",
    model: Annotated[
        str | None,
        typer.Option("--model", help="Model override for repair."),
    ] = None,
    source: Annotated[
        str | None,
        typer.Option("--from", help="Repair evidence source: sandbox, working-tree, or review."),
    ] = None,
) -> None:
    """
    Generate a repaired diff from failed tests, review concerns, and plan evidence.
    """
    session = None
    repair_metadata: dict | None = None
    repair_context: dict | None = None

    try:
        workspace_root = path.resolve()
        settings = load_settings()

        if session_id:
            session = get_session(root=workspace_root, session_id=session_id)
        else:
            session = get_current_session(workspace_root)

        console.print("[bold]Repairing diff from session evidence...[/bold]\n")
        _record_timeline_event(
            session,
            "repair_started",
            "trevvos repair",
            "started",
        )

        repair_context = build_repair_context(
            session=session,
            repo_root=workspace_root,
            source=source,
        )

        if provider_name != "ollama":
            raise DiffError(f"Unsupported repair provider: {provider_name}")

        provider = (
            OllamaProvider(
                model=model,
                base_url=settings.base_url,
                timeout=settings.timeout,
            )
            if model
            else build_provider(settings)
        )

        prompt_template = get_prompt("repair_file_changes")
        repair_metadata = build_repair_metadata(
            session=session,
            prompt_ref=prompt_template.ref,
            status="started",
            reason=repair_context["reason"],
            evidence_used=repair_context.get("evidence_used", []),
        )

        prompt = build_repair_prompt(repair_context)

        write_session_text(session=session, file_name="repair_prompt.md", content=prompt)
        write_repair_metadata(session, repair_metadata)

        with console.status("[bold]Generating repaired file changes with your local LLM...[/bold]", spinner="dots"):
            raw_file_changes_response = provider.generate(prompt)

        write_session_text(
            session=session,
            file_name="repair_raw_response.json",
            content=raw_file_changes_response,
        )

        file_changes = parse_file_changes_output(raw_file_changes_response)

        write_session_json(
            session=session,
            file_name="file_changes.json",
            data=file_changes.to_dict(),
        )

        plan_constraints = load_plan_constraints(session.path)
        plan_constraints_check = check_file_changes_against_plan_constraints(
            file_changes=file_changes,
            constraints=plan_constraints,
        )
        write_plan_constraints_check(session.path, plan_constraints_check)

        if plan_constraints_check["status"] == "failed":
            violations = plan_constraints_check.get("violations", [])
            detail = violations[0] if violations else "plan constraints were violated."
            raise DiffError(f"Diff rejected: file {detail}")

        diff_warnings: list[str] = []
        if plan_constraints_check["status"] == "warning":
            diff_warnings.extend(plan_constraints_check.get("warnings", []))
        instruction = read_session_text(session, "user_request.txt")
        diff_warnings.extend(
            detect_small_file_structural_edit_risk(
                file_changes=file_changes,
                repo_root=workspace_root,
                plan=plan_constraints,
                request=instruction,
            )
        )
        cli_regression_check = build_cli_regression_check(
            workspace_root=workspace_root,
            file_changes=file_changes,
        )
        write_cli_regression_check(session, cli_regression_check)
        diff_warnings.extend(cli_regression_check.get("warnings", []))

        unified_diff = build_unified_diff_from_file_changes(
            workspace_root=workspace_root,
            file_changes=file_changes,
            warnings=diff_warnings,
        )

        write_session_text(session=session, file_name="diff.patch", content=unified_diff)

        if diff_warnings:
            write_session_json(session=session, file_name="diff_warnings.json", data={"warnings": diff_warnings})
        else:
            _delete_session_files(session.path, ["diff_warnings.json"])

        validation_result = validate_diff_patch(
            workspace_root=workspace_root,
            session=session,
            diff_text=unified_diff,
        )
        write_session_json(session=session, file_name="diff_validation.json", data=validation_result.to_dict())

        check_patch(workspace_root=workspace_root, session=session)
        write_session_json(
            session=session,
            file_name="diff_check.json",
            data={
                "git_apply_check": "passed",
                "patch_path": str(session.path / "diff.patch"),
            },
        )

        change_summary = build_change_summary_markdown(
            request=instruction,
            file_changes=file_changes,
            warnings=diff_warnings,
            plan_constraints_status=plan_constraints_check["status"],
        )
        semantic_review = build_semantic_review_json(
            request=instruction,
            file_changes=file_changes,
            warnings=diff_warnings,
            plan_constraints_status=plan_constraints_check["status"],
            plan=plan_constraints,
            plan_constraints_check=plan_constraints_check,
            verification_coverage=_read_json_file(session.path / "verification_coverage.json"),
            cli_regression_check=cli_regression_check,
        )

        write_session_text(session=session, file_name="change_summary.md", content=change_summary)
        write_session_json(session=session, file_name="semantic_review.json", data=semantic_review)

        repair_metadata["status"] = "succeeded"
        write_repair_metadata(session, repair_metadata)

        _delete_session_files(
            session.path,
            [
                "file_changes_error.txt",
                "file_changes_error.json",
                "file_changes_error.md",
                "diff_error.txt",
                "operation_error.json",
                "operation_error.md",
                "diff_validation_error.txt",
                "diff_check_error.txt",
            ],
        )

        session = update_session_status(session, "diff_validated")
        _record_timeline_event(
            session,
            "repair_completed",
            "trevvos repair",
            "succeeded",
            reason=repair_context.get("reason"),
            artifacts=[
                "repair_metadata.json",
                "repair_prompt.md",
                "repair_raw_response.json",
                "file_changes.json",
                "diff.patch",
                "semantic_review.json",
            ],
            files_changed=[change.path for change in file_changes.changes],
            warnings_count=len(diff_warnings),
            repair_count=repair_metadata.get("repair_count"),
            next_recommended_command="trevvos test --sandbox",
        )

        console.print("[green]Repair generated a new diff successfully.[/green]\n")
        console.print(f"Session: {session.metadata.id}")
        console.print(f"Status:  {session.metadata.status}")
        console.print(f"Reason:  {repair_context['reason']}")
        console.print(f"Prompt:  {prompt_template.ref}")
        console.print(f"Model:   {model or settings.model}")

        console.print("\n[bold]Files changed[/bold]")
        for change in file_changes.changes:
            descriptor = change.mode
            if change.operation:
                descriptor = f"{descriptor} / {change.operation}"
            console.print(f"  - {change.path} [{change.change_type}] {descriptor}")

        console.print("\n[bold]Artifacts[/bold]")
        console.print(f"  - repair_metadata.json: {session.path / 'repair_metadata.json'}")
        console.print(f"  - repair_prompt.md: {session.path / 'repair_prompt.md'}")
        console.print(f"  - repair_raw_response.json: {session.path / 'repair_raw_response.json'}")
        console.print(f"  - diff.patch: {session.path / 'diff.patch'}")
        console.print(f"  - change_summary.md: {session.path / 'change_summary.md'}")
        console.print(f"  - semantic_review.json: {session.path / 'semantic_review.json'}")

        console.print("\n[bold]Validations[/bold]")
        console.print("  - Forge safety validation: passed")
        console.print("  - git apply --check: passed")

        console.print("\n[bold]Next[/bold]")
        console.print("  trevvos test --sandbox")

    except RepairNotRepairableError as exc:
        if session is not None:
            write_repair_metadata(session, build_not_repairable_metadata(session))
            update_session_status(session, "diff_generation_failed")
            _record_timeline_event(
                session,
                "repair_not_repairable",
                "trevvos repair",
                "not_repairable",
                reason="missing_valid_diff",
                message=str(exc),
                artifacts=["repair_metadata.json"],
                next_recommended_command="trevvos diff --retry",
            )

        console.print("\n[red]Repair failed.[/red]")
        print_error(str(exc))
        if session is not None:
            console.print("\n[bold]Repair artifacts[/bold]")
            console.print(f"  - {session.path / 'repair_metadata.json'}")
        raise typer.Exit(code=1)

    except (FileChangeOutputError, DiffValidationError, ApplyError, ForgeError) as exc:
        if session is not None:
            error_message = str(exc)
            if repair_metadata is not None:
                repair_metadata["status"] = "failed"
                repair_metadata["error"] = error_message
                write_repair_metadata(session, repair_metadata)
            elif repair_context is not None:
                failed_metadata = build_repair_metadata(
                    session=session,
                    prompt_ref="repair_file_changes@1.0.0",
                    status="failed",
                    reason=repair_context.get("reason", "unknown"),
                    evidence_used=repair_context.get("evidence_used", []),
                    error=error_message,
                )
                write_repair_metadata(session, failed_metadata)

            write_session_text(session=session, file_name="diff_error.txt", content=error_message)
            write_operation_error_artifacts(session, error_message)
            update_session_status(session, "diff_generation_failed")
            _record_timeline_event(
                session,
                "repair_failed",
                "trevvos repair",
                "failed",
                reason=type(exc).__name__,
                message=error_message,
                artifacts=["repair_metadata.json", "diff_error.txt", "operation_error.json", "operation_error.md"],
                repair_count=repair_metadata.get("repair_count") if repair_metadata else None,
            )

        console.print("\n[red]Repair failed.[/red]")
        print_error(str(exc))
        if session is not None:
            console.print("\n[bold]Repair artifacts[/bold]")
            console.print(f"  - {session.path / 'repair_metadata.json'}")
            console.print(f"  - {session.path / 'repair_prompt.md'}")
            console.print("\n[bold]Operation error artifacts[/bold]")
            console.print(f"  - {session.path / 'operation_error.json'}")
            console.print(f"  - {session.path / 'operation_error.md'}")
        raise typer.Exit(code=1)


@app.command()
def apply(
    session_id: Annotated[
        str | None,
        typer.Option("--session", "-s", help="Session ID to use. Defaults to current session."),
    ] = None,
    path: Annotated[
        Path,
        typer.Option("--path", "-p", help="Workspace root path."),
    ] = Path("."),
    yes: Annotated[
        bool,
        typer.Option("--yes", "-y", help="Apply without interactive confirmation."),
    ] = False,
) -> None:
    """
    Apply a validated diff patch to the workspace.
    """
    session = None

    try:
        workspace_root = path.resolve()

        if session_id:
            session = get_session(root=workspace_root, session_id=session_id)
        else:
            session = get_current_session(workspace_root)

        _record_timeline_event(session, "apply_started", "trevvos apply", "started")

        if session.metadata.status != "diff_validated":
            raise ApplyError(
                "Cannot apply: session status must be diff_validated. "
                f"Current status: {session.metadata.status}."
            )

        patch_path = session.path / "diff.patch"

        if not patch_path.exists():
            raise ApplyError("Cannot apply: diff.patch not found in session.")

        validation_changes = _load_diff_validation_changes(session.path)
        file_changes_payload = _load_session_json(session.path, "file_changes.json")
        file_changes_for_display = file_changes_payload.get("changes")

        if not isinstance(file_changes_for_display, list):
            file_changes_for_display = validation_changes

        console.print(f"[green]About to apply session:[/green] {session.metadata.id}\n")
        console.print(f"Status: {session.metadata.status}")

        console.print("\n[bold]Files changed[/bold]")
        for change in file_changes_for_display:
            if not isinstance(change, dict):
                continue

            line = _format_change_line(change)

            if line:
                console.print(f"  {line}")

        warnings = _load_diff_warnings(session.path)
        verification_coverage = _read_json_file(session.path / "verification_coverage.json")
        high_risk = high_risk_warnings(warnings)
        coverage_failed = isinstance(verification_coverage, dict) and verification_coverage.get("status") == "failed"

        console.print("\n[bold]Validations[/bold]")
        console.print("  - Forge safety validation: passed")
        check_patch(workspace_root=workspace_root, session=session)
        console.print("  - git apply --check: passed")

        console.print("\n[bold]Warnings[/bold]")
        if warnings:
            for warning in warnings:
                console.print(f"  - [yellow]{warning}[/yellow]")
        else:
            console.print("  - None")

        if high_risk or coverage_failed:
            console.print("\n[bold red]High-risk warnings detected.[/bold red]")
            console.print("This patch may be syntactically valid but behaviorally unsafe.")
            console.print("\nRecommended:")
            console.print("  trevvos review --no-llm")
            console.print("  trevvos test --sandbox --plan-commands")

        console.print("\n[bold]Patch[/bold]")
        console.print(f"  {patch_path}")

        patch_preview, preview_truncated = build_patch_preview(
            patch_path.read_text(encoding="utf-8"),
            max_lines=80,
        )

        console.print("\n[bold]Patch preview[/bold]")
        console.print(patch_preview)

        if preview_truncated:
            console.print(f"\n[yellow]Preview truncated. Full patch available at {patch_path}[/yellow]")

        if not yes:
            if high_risk or coverage_failed:
                confirmation = typer.prompt("Type 'apply' to confirm", default="")
                if confirmation != "apply":
                    console.print("[yellow]Cancelled.[/yellow]")
                    _record_timeline_event(
                        session,
                        "apply_cancelled",
                        "trevvos apply",
                        "cancelled",
                        reason="strong_confirmation_required",
                    )
                    return
            elif not typer.confirm("Apply this patch?", default=False):
                console.print("[yellow]Cancelled.[/yellow]")
                _record_timeline_event(
                    session,
                    "apply_cancelled",
                    "trevvos apply",
                    "cancelled",
                    reason="user_cancelled",
                )
                return

        result = apply_patch(workspace_root=workspace_root, session=session)

        write_session_json(
            session=session,
            file_name="apply_result.json",
            data=result.to_dict(),
        )

        session = update_session_status(session, "applied")
        _record_timeline_event(
            session,
            "apply_completed",
            "trevvos apply",
            "succeeded",
            artifacts=["apply_result.json"],
            next_recommended_command="trevvos test",
        )

        console.print("\n[green]Patch applied successfully.[/green]\n")
        console.print(f"Session: {session.metadata.id}")
        console.print(f"Status:  {session.metadata.status}")

        console.print("\n[bold]Saved files[/bold]")
        console.print(f"  - {session.path / 'apply_result.json'}")

    except ForgeError as exc:
        if session is not None:
            write_session_text(
                session=session,
                file_name="apply_error.txt",
                content=str(exc),
            )
            update_session_status(session, "apply_failed")
            _record_timeline_event(
                session,
                "apply_failed",
                "trevvos apply",
                "failed",
                reason=type(exc).__name__,
                message=str(exc),
                artifacts=["apply_error.txt"],
            )

        print_error(str(exc))
        raise typer.Exit(code=1)


@app.command()
def test(
    session_id: Annotated[
        str | None,
        typer.Option("--session", "-s", help="Session ID to use. Defaults to current session."),
    ] = None,
    path: Annotated[
        Path,
        typer.Option("--path", "-p", help="Workspace root path."),
    ] = Path("."),
    yes: Annotated[
        bool,
        typer.Option("--yes", "-y", help="Run without interactive confirmation."),
    ] = False,
    timeout: Annotated[
        int,
        typer.Option("--timeout", help="Timeout per command in seconds."),
    ] = 120,
    sandbox: Annotated[
        bool,
        typer.Option("--sandbox", help="Run tests in a temporary copy with the session patch applied."),
    ] = False,
    keep_sandbox: Annotated[
        bool,
        typer.Option("--keep-sandbox", help="Keep the sandbox directory after running tests."),
    ] = False,
    plan_commands: Annotated[
        bool,
        typer.Option("--plan-commands", help="Use only suggested_verification_commands from plan.json."),
    ] = False,
    configured_commands: Annotated[
        bool,
        typer.Option("--configured-commands", help="Use only configured or autodetected test commands."),
    ] = False,
) -> None:
    """
    Run configured validation commands against the current workspace state.
    """
    session = None

    try:
        workspace_root = path.resolve()

        if session_id:
            session = get_session(root=workspace_root, session_id=session_id)
        else:
            session = get_current_session(workspace_root)

        test_event_prefix = "sandbox_test" if sandbox else "working_tree_test"
        test_command_name = "trevvos test --sandbox" if sandbox else "trevvos test"
        test_mode = "sandbox" if sandbox else "working_tree"
        _record_timeline_event(
            session,
            f"{test_event_prefix}_started",
            test_command_name,
            "started",
            test_mode=test_mode,
        )

        patch_path = session.path / "diff.patch"

        if not patch_path.exists():
            raise TestRunError("Cannot test: diff.patch not found in session. Run trevvos diff first.")

        if plan_commands and configured_commands:
            raise TestRunError("Use only one of --plan-commands or --configured-commands.")

        configured = load_test_commands(workspace_root)
        plan = load_plan_verification_commands(session.path)
        selection = "configured"

        if plan_commands:
            selection = "plan"
        elif configured_commands:
            selection = "configured"
        elif sandbox:
            selection = "combined"

        command_specs, skipped_unsafe = merge_test_commands(
            configured=configured,
            plan=plan,
            selection=selection,
        )

        if sandbox and skipped_unsafe:
            result = TestRunResult(
                status="failed",
                commands=[],
                summary={
                    "total": 0,
                    "passed": 0,
                    "failed": 1,
                    "timed_out": 0,
                },
                mode="sandbox",
                sandbox={
                    "enabled": True,
                    "kept": False,
                    "path": None,
                    "patch_apply_check": "not_run",
                    "patch_apply": "not_run",
                },
                command_sources={
                    "configured": [spec.command for spec in command_specs if spec.source == "configured"],
                    "plan": [spec.command for spec in command_specs if spec.source == "plan"],
                    "executed": [],
                    "skipped_unsafe": [unsafe.to_dict() for unsafe in skipped_unsafe],
                },
            )
            write_test_artifacts(session.path, result)
            _record_timeline_event(
                session,
                "unsafe_command_blocked",
                test_command_name,
                "failed",
                reason="unsafe_command_blocked",
                message="Unsafe plan verification command blocked.",
                artifacts=["test_results.json", "test_output.log"],
                test_mode=test_mode,
                test_status=result.status,
            )
            _record_timeline_event(
                session,
                "sandbox_test_failed",
                test_command_name,
                "failed",
                reason="unsafe_command_blocked",
                artifacts=["test_results.json", "test_output.log"],
                test_mode=test_mode,
                test_status=result.status,
            )

            console.print("[red]Unsafe plan verification command blocked.[/red]\n")
            for unsafe in skipped_unsafe:
                console.print(f"  - {unsafe.command}: {unsafe.reason}")

            console.print("\n[bold]Artifacts[/bold]")
            console.print(f"  - test_results.json: {session.path / 'test_results.json'}")
            console.print(f"  - test_output.log: {session.path / 'test_output.log'}")
            raise typer.Exit(code=1)

        if not command_specs:
            result = run_test_command_specs(
                command_specs=[],
                repo_root=workspace_root,
                timeout_seconds=timeout,
                mode="sandbox" if sandbox else "working_tree",
                sandbox={"enabled": True, "kept": False, "path": None} if sandbox else None,
                skipped_unsafe=skipped_unsafe,
            )
            write_test_artifacts(session.path, result)
            _record_timeline_event(
                session,
                f"{test_event_prefix}_failed",
                test_command_name,
                "failed",
                reason="no_test_commands",
                artifacts=["test_results.json", "test_output.log"],
                test_mode=test_mode,
                test_status=result.status,
            )

            console.print("[yellow]No test commands configured or detected.[/yellow]\n")
            console.print("Configure .trevvos/config.json, for example:")
            console.print(
                '{\n'
                '  "test_commands": [\n'
                '    "python -m unittest discover -s tests",\n'
                '    "python -m compileall trevvos_forge tests"\n'
                "  ]\n"
                "}"
            )
            console.print("\n[bold]Artifacts[/bold]")
            console.print(f"  - test_results.json: {session.path / 'test_results.json'}")
            console.print(f"  - test_output.log: {session.path / 'test_output.log'}")
            raise typer.Exit(code=1)

        mode_label = "sandbox" if sandbox else "working_tree"
        console.print(f"[bold]Test mode:[/bold] {mode_label}\n")
        console.print("[bold]Test commands[/bold]\n")

        for index, spec in enumerate(command_specs, start=1):
            console.print(f"{index}. [{spec.source}] {spec.command}")

        if not sandbox and session.metadata.status != "applied":
            console.print(
                "\n[yellow]Patch is not marked as applied. "
                "Tests will run against the current working tree.[/yellow]"
            )

        confirmation_prompt = (
            "\nRun these commands in sandbox?"
            if sandbox
            else "\nRun these commands?"
        )

        if not yes and not typer.confirm(confirmation_prompt, default=False):
            console.print("[yellow]Cancelled.[/yellow]")
            _record_timeline_event(
                session,
                f"{test_event_prefix}_failed",
                test_command_name,
                "cancelled",
                reason="user_cancelled",
                test_mode=test_mode,
            )
            return

        console.print("\n[bold]Running tests...[/bold]\n")

        if sandbox:
            result = run_test_specs_in_sandbox(
                repo_root=workspace_root,
                patch_path=patch_path,
                command_specs=command_specs,
                timeout_seconds=timeout,
                keep_sandbox=keep_sandbox,
                skipped_unsafe=skipped_unsafe,
            )
            sandbox_metadata = result.sandbox or {}
            sandbox_path = sandbox_metadata.get("runtime_path") or sandbox_metadata.get("path")

            if sandbox_path:
                console.print(f"Sandbox created:\n{sandbox_path}\n")

            console.print("[bold]Patch[/bold]")
            console.print(f"  - git apply --check: {sandbox_metadata.get('patch_apply_check', 'not_run')}")
            console.print(f"  - git apply: {sandbox_metadata.get('patch_apply', 'not_run')}")

            if result.status == "failed" and not result.commands:
                console.print("\n[red]Patch apply check failed in sandbox.[/red]")
                console.print("No tests were run.")
        else:
            result = run_test_command_specs(
                command_specs=command_specs,
                repo_root=workspace_root,
                timeout_seconds=timeout,
                mode="working_tree",
                skipped_unsafe=skipped_unsafe,
            )

        write_test_artifacts(session.path, result)
        _record_timeline_event(
            session,
            f"{test_event_prefix}_completed" if result.status == "passed" else f"{test_event_prefix}_failed",
            test_command_name,
            "succeeded" if result.status == "passed" else "failed",
            reason=None if result.status == "passed" else result.status,
            artifacts=[
                "sandbox_test_results.json" if sandbox else "working_tree_test_results.json",
                "sandbox_test_output.log" if sandbox else "working_tree_test_output.log",
                "test_results.json",
                "test_output.log",
            ],
            test_mode=test_mode,
            test_status=result.status,
            next_recommended_command="trevvos review" if result.status == "passed" else "trevvos repair",
        )

        for command_result in result.commands:
            marker = "[green]OK[/green]" if command_result.status == "passed" else "[red]FAIL[/red]"
            console.print(f"{marker} [{command_result.source}] {command_result.command}")

            if command_result.status != "passed":
                if command_result.exit_code is not None:
                    console.print(f"Exit code: {command_result.exit_code}")
                else:
                    console.print("Exit code: timeout")

        console.print(f"\n[bold]Test status:[/bold] {result.status}")

        console.print("\n[bold]Artifacts[/bold]")
        console.print(f"  - test_results.json: {session.path / 'test_results.json'}")
        console.print(f"  - test_output.log: {session.path / 'test_output.log'}")

        if sandbox:
            sandbox_metadata = result.sandbox or {}

            if keep_sandbox:
                console.print(f"\n[yellow]Sandbox kept at:[/yellow]\n{sandbox_metadata.get('path')}")
            else:
                console.print("\n[green]Sandbox removed.[/green]")

        if result.status != "passed":
            raise typer.Exit(code=1)

    except ForgeError as exc:
        if session is not None:
            write_session_text(
                session=session,
                file_name="test_error.txt",
                content=str(exc),
            )
            _record_timeline_event(
                session,
                "sandbox_test_failed" if sandbox else "working_tree_test_failed",
                "trevvos test --sandbox" if sandbox else "trevvos test",
                "failed",
                reason=type(exc).__name__,
                message=str(exc),
                artifacts=["test_error.txt"],
                test_mode="sandbox" if sandbox else "working_tree",
            )

        print_error(str(exc))
        raise typer.Exit(code=1)


@app.command()
def review(
    session_id: Annotated[
        str | None,
        typer.Option("--session", "-s", help="Session ID to use. Defaults to current session."),
    ] = None,
    path: Annotated[
        Path,
        typer.Option("--path", "-p", help="Workspace root path."),
    ] = Path("."),
    no_llm: Annotated[
        bool,
        typer.Option("--no-llm", help="Use deterministic session artifacts only."),
    ] = False,
    provider_name: Annotated[
        str,
        typer.Option("--provider", help="LLM provider to use for semantic review."),
    ] = "ollama",
    model: Annotated[
        str | None,
        typer.Option("--model", help="Model override for semantic review."),
    ] = None,
) -> None:
    """
    Review a generated patch using deterministic evidence and optional LLM assistance.
    """
    try:
        workspace_root = path.resolve()

        if session_id:
            session = get_session(root=workspace_root, session_id=session_id)
        else:
            session = get_current_session(workspace_root)

        _record_timeline_event(session, "review_started", "trevvos review", "started")
        context = build_review_context(session.path)

        if no_llm:
            _print_deterministic_review(session.path, context, reason=None)
            _record_timeline_event(
                session,
                "review_completed",
                "trevvos review --no-llm",
                "succeeded",
                artifacts=["semantic_review.json"],
            )
            return

        if provider_name != "ollama":
            _print_deterministic_review(
                session.path,
                context,
                reason=f"Unsupported review provider: {provider_name}",
            )
            _record_timeline_event(
                session,
                "review_completed",
                "trevvos review",
                "succeeded",
                reason="deterministic_fallback",
                artifacts=["semantic_review.json"],
            )
            return

        settings = load_settings()
        review_model = model or settings.model
        provider = OllamaProvider(
            model=review_model,
            base_url=settings.base_url,
            timeout=settings.timeout,
        )
        prompt = build_semantic_review_prompt(context)

        try:
            with console.status("[bold]Reviewing patch with local LLM...[/bold]", spinner="dots"):
                raw_review = provider.generate(prompt)
        except ForgeError as exc:
            _print_deterministic_review(
                session.path,
                context,
                reason=f"LLM semantic review unavailable: {exc}",
            )
            _record_timeline_event(
                session,
                "review_completed",
                "trevvos review",
                "succeeded",
                reason="deterministic_fallback",
                message=str(exc),
                artifacts=["semantic_review.json"],
            )
            return

        review_payload = parse_llm_review_response(raw_review)
        review_markdown = render_llm_review_markdown(review_payload)
        raw_text = raw_review if review_payload.get("status") == "parse_failed" else None

        write_llm_review_artifacts(
            session_dir=session.path,
            review=review_payload,
            markdown=review_markdown,
            raw_text=raw_text,
        )

        console.print("[green]Review mode: LLM-assisted[/green]\n")
        console.print(f"Session: {session.metadata.id}")
        console.print(f"Model:   {review_model}")

        if review_payload.get("status") == "parse_failed":
            console.print("\n[yellow]LLM review response could not be parsed.[/yellow]")
            console.print("Saved raw response for inspection.")

        console.print("\n[bold]Evidence[/bold]")
        for evidence in context.get("evidence_used", []):
            console.print(f"  - {evidence}")

        console.print("\n[bold]LLM verdict[/bold]")
        console.print(f"  Verdict:           {review_payload.get('verdict')}")
        console.print(f"  Risk level:        {review_payload.get('risk_level')}")
        console.print(f"  Request alignment: {review_payload.get('request_alignment')}")

        summary = review_payload.get("summary")

        if isinstance(summary, str) and summary.strip():
            console.print("\n[bold]Summary[/bold]")
            console.print(summary)

        suggested_checks = review_payload.get("suggested_checks")

        if isinstance(suggested_checks, list) and suggested_checks:
            console.print("\n[bold]Suggested checks[/bold]")
            for check in suggested_checks:
                if isinstance(check, str):
                    console.print(f"  - {check}")

        console.print("\n[bold]Artifacts[/bold]")
        console.print(f"  - llm_review.md: {session.path / 'llm_review.md'}")
        console.print(f"  - llm_review.json: {session.path / 'llm_review.json'}")

        if raw_text is not None:
            console.print(f"  - llm_review_raw.txt: {session.path / 'llm_review_raw.txt'}")
        _record_timeline_event(
            session,
            "review_completed",
            "trevvos review",
            "succeeded",
            artifacts=["llm_review.md", "llm_review.json"],
            concerns_count=len(review_payload.get("concerns", [])) if isinstance(review_payload.get("concerns"), list) else 0,
        )

    except ForgeError as exc:
        if "session" in locals():
            _record_timeline_event(
                session,
                "review_failed",
                "trevvos review",
                "failed",
                reason=type(exc).__name__,
                message=str(exc),
            )
        print_error(str(exc))
        raise typer.Exit(code=1)


def _print_deterministic_review(session_path: Path, context: dict, reason: str | None) -> None:
    review_payload = build_semantic_review_json_from_context(context)
    semantic_review_path = session_path / "semantic_review.json"
    semantic_review_path.write_text(
        json.dumps(review_payload, indent=2, ensure_ascii=False),
        encoding="utf-8",
    )

    console.print("[yellow]Review mode: deterministic[/yellow]\n")

    if reason:
        console.print(f"[yellow]{reason}[/yellow]\n")
        console.print(
            "Configure a local Ollama model with TREVVOS_FORGE_MODEL or pass --model "
            "to run LLM-assisted review.\n"
        )

    files_changed = context.get("files_changed")

    console.print("[bold]Deterministic review[/bold]")
    console.print(f"  Files changed: {len(files_changed) if isinstance(files_changed, list) else 0}")
    console.print(f"  Warnings:      {len(review_payload.get('warnings', []))}")

    validations = review_payload.get("validations")
    if isinstance(validations, dict):
        console.print(f"  Safety validation: {validations.get('safety_validation', 'unknown')}")
        console.print(f"  git apply --check: {validations.get('git_apply_check', 'unknown')}")

    console.print()
    console.print(render_deterministic_review_text(review_payload))

    console.print("\n[bold]Artifacts[/bold]")
    console.print(f"  - semantic_review.json: {semantic_review_path}")


@app.command()
def commit(
    session_id: Annotated[
        str | None,
        typer.Option("--session", "-s", help="Session ID to use. Defaults to current session."),
    ] = None,
    path: Annotated[
        Path,
        typer.Option("--path", "-p", help="Workspace root path."),
    ] = Path("."),
    message: Annotated[
        str | None,
        typer.Option("--message", "-m", help="Commit message to use."),
    ] = None,
    no_llm: Annotated[
        bool,
        typer.Option("--no-llm", help="Generate commit message deterministically."),
    ] = False,
    yes: Annotated[
        bool,
        typer.Option("--yes", "-y", help="Commit without interactive confirmation."),
    ] = False,
    dry_run: Annotated[
        bool,
        typer.Option("--dry-run", help="Create commit artifacts without staging or committing."),
    ] = False,
    provider_name: Annotated[
        str,
        typer.Option("--provider", help="LLM provider to use for commit message generation."),
    ] = "ollama",
    model: Annotated[
        str | None,
        typer.Option("--model", help="Model override for commit message generation."),
    ] = None,
) -> None:
    """
    Create a Git commit from files related to the current Trevvos Forge session.
    """
    try:
        workspace_root = path.resolve()

        if session_id:
            session = get_session(root=workspace_root, session_id=session_id)
        else:
            session = get_current_session(workspace_root)

        _record_timeline_event(session, "commit_started", "trevvos commit", "started")
        manual_message = _manual_commit_message(message) if message else None

        if manual_message is not None:
            commit_message = manual_message
            mode = "manual"
        elif no_llm:
            commit_message = None
            mode = "deterministic"
        else:
            commit_message = _try_generate_llm_commit_message(
                session_path=session.path,
                workspace_root=workspace_root,
                provider_name=provider_name,
                model=model,
            )
            mode = "llm" if commit_message is not None else "deterministic"

        plan = build_commit_plan(
            session_dir=session.path,
            repo_root=workspace_root,
            message=commit_message,
            mode=mode,
        )

        write_commit_artifacts(session_dir=session.path, plan=plan)
        _print_commit_plan(plan)

        if dry_run:
            result = CommitResult(
                status="dry_run",
                files_staged=plan.files_to_stage,
                message_subject=plan.message.subject,
            )
            write_commit_artifacts(session_dir=session.path, plan=plan, result=result)
            _record_timeline_event(
                session,
                "commit_dry_run",
                "trevvos commit --dry-run",
                "succeeded",
                artifacts=["commit_message.txt", "commit_plan.json", "commit_result.json"],
            )
            console.print("\n[yellow]Dry run only. No files were staged and no commit was created.[/yellow]")
            _print_commit_artifacts(session.path)
            return

        if not yes and not typer.confirm("Proceed with commit?", default=False):
            result = CommitResult(status="cancelled")
            write_commit_artifacts(session_dir=session.path, plan=plan, result=result)
            _record_timeline_event(
                session,
                "commit_cancelled",
                "trevvos commit",
                "cancelled",
                reason="user_cancelled",
                artifacts=["commit_message.txt", "commit_plan.json", "commit_result.json"],
            )
            console.print("[yellow]Cancelled.[/yellow]")
            return

        result = run_git_commit(
            repo_root=workspace_root,
            files=plan.files_to_stage,
            message_text=render_commit_message(plan.message),
        )
        write_commit_artifacts(session_dir=session.path, plan=plan, result=result)

        if result.status != "committed":
            _record_timeline_event(
                session,
                "commit_failed",
                "trevvos commit",
                "failed",
                reason="git_commit_failed",
                message=result.error,
                artifacts=["commit_message.txt", "commit_plan.json", "commit_result.json"],
            )
            print_error(result.error or "git commit failed")
            raise typer.Exit(code=1)

        _record_timeline_event(
            session,
            "commit_completed",
            "trevvos commit",
            "succeeded",
            artifacts=["commit_message.txt", "commit_plan.json", "commit_result.json"],
            commit_hash=result.commit_hash,
        )
        console.print(f"\n[green]Commit created:[/green] {result.commit_hash}")
        _print_commit_artifacts(session.path)

    except ForgeError as exc:
        if "session" in locals():
            _record_timeline_event(
                session,
                "commit_failed",
                "trevvos commit",
                "failed",
                reason=type(exc).__name__,
                message=str(exc),
            )
        print_error(str(exc))
        raise typer.Exit(code=1)


def _try_generate_llm_commit_message(
    *,
    session_path: Path,
    workspace_root: Path,
    provider_name: str,
    model: str | None,
) -> CommitMessage | None:
    if provider_name != "ollama":
        return None

    deterministic_message = build_deterministic_commit_message(session_path, [])
    context = build_review_context(session_path)
    context["deterministic_subject"] = deterministic_message.subject

    try:
        settings = load_settings()
        provider = OllamaProvider(
            model=model or settings.model,
            base_url=settings.base_url,
            timeout=settings.timeout,
        )
        prompt = get_prompt("commit_message_generation").render(
            commit_context=json.dumps(context, indent=2, ensure_ascii=False),
        )

        with console.status("[bold]Generating commit message with local LLM...[/bold]", spinner="dots"):
            raw_response = provider.generate(prompt)

        try:
            commit_message = parse_commit_message_response(raw_response)
        except CommitError:
            (session_path / "commit_message_raw.txt").write_text(raw_response, encoding="utf-8")
            return None

        return commit_message
    except ForgeError:
        return None


def _manual_commit_message(raw_message: str) -> CommitMessage:
    lines = raw_message.replace("\r\n", "\n").replace("\r", "\n").splitlines()
    subject = lines[0].strip() if lines else raw_message.strip()
    body = [line.strip() for line in lines[1:] if line.strip()]

    return CommitMessage(subject=subject, body=body, confidence="manual")


def _print_commit_plan(plan) -> None:
    console.print(f"[bold]Commit plan for session:[/bold] {plan.session_id}\n")

    console.print("[bold]Files to stage[/bold]")
    for file_path in plan.files_to_stage:
        console.print(f"  - {file_path}")

    console.print("\n[bold]Unrelated changes[/bold]")
    if plan.unrelated_changes:
        for file_path in plan.unrelated_changes:
            console.print(f"  - [yellow]{file_path}[/yellow]")
        console.print("[yellow]These will NOT be staged.[/yellow]")
    else:
        console.print("  - None")

    console.print("\n[bold]Validation evidence[/bold]")
    console.print(f"  - Test status: {plan.test_status or 'not available'}")
    console.print(f"  - Sandbox test status: {plan.sandbox_test_status or 'not available'}")
    console.print(f"  - Working tree test status: {plan.working_tree_test_status or 'not available'}")
    console.print(
        "  - LLM review: "
        f"{plan.review_verdict or 'not available'}"
        + (f" / {plan.review_risk_level} risk" if plan.review_risk_level else "")
    )

    if plan.test_status and plan.test_status != "passed":
        console.print(f"[yellow]Warning: latest test status is {plan.test_status}.[/yellow]")

    if plan.review_verdict in {"has_concerns", "blocked"}:
        console.print(f"[yellow]Warning: latest review verdict is {plan.review_verdict}.[/yellow]")

    console.print("\n[bold]Commit message[/bold]\n")
    console.print(render_commit_message(plan.message).rstrip("\n"))


def _print_commit_artifacts(session_path: Path) -> None:
    console.print("\n[bold]Artifacts[/bold]")
    console.print(f"  - commit_message.txt: {session_path / 'commit_message.txt'}")
    console.print(f"  - commit_plan.json: {session_path / 'commit_plan.json'}")
    console.print(f"  - commit_result.json: {session_path / 'commit_result.json'}")


@models_app.command("list")
def list_models() -> None:
    """
    List local models available in Ollama.
    """
    try:
        settings = load_settings()
        provider = build_provider(settings)

        with console.status("[bold]Listing local models...[/bold]", spinner="dots"):
            models = provider.list_models()

        console.print("[bold]Local Ollama models[/bold]\n")

        if not models:
            console.print("[yellow]No models found.[/yellow]")
            console.print("Install one with Ollama, for example:")
            console.print("   ollama pull qwen2.5-coder:7b")
            raise typer.Exit(code=1)

        for model in models:
            marker = "[green]*[/green]" if model == settings.model else "-"
            console.print(f"   {marker} {model}")

        console.print(
            f"\nConfigured model: [bold]{settings.model}[/bold]"
        )

    except ForgeError as exc:
        print_error(str(exc))
        raise typer.Exit(code=1)


@models_app.command("pull")
def pull_model(model: str) -> None:
    """
    Pull a model using Ollama.
    """
    try:
        settings = load_settings()
        provider = build_provider(settings)

        console.print(f"[bold]Pulling model:[/bold] {model}")
        console.print("[yellow]This can take a while depending on the model size.[/yellow]\n")

        with console.status("[bold]Downloading model with Ollama...[/bold]", spinner="dots"):
            status = provider.pull_model(model)

        console.print(f"\n[green]Model pull finished:[/green] {status}")
        console.print(f"Model: [bold]{model}[/bold]")

        if model != settings.model:
            console.print(
                "\n[yellow]Note:[/yellow] this model was downloaded, but it is not your configured default model."
            )
            console.print(
                f"To use it temporarily:\n  TREVVOS_FORGE_MODEL=\"{model}\" trevvos ask \"hello\""
            )

    except ForgeError as exc:
        print_error(str(exc))
        raise typer.Exit(code=1)


@sessions_app.command("new")
def new_session(
    user_request: str,
    path: Annotated[
        Path,
        typer.Option("--path", "-p", help="Workspace root path."),
    ] = Path("."),
) -> None:
    """
    Create a new local Forge session.
    """
    try:
        session = create_session(
            root=path,
            user_request=user_request,
            command="sessions new",
        )

        console.print("[green]Session created.[/green]")
        console.print(f"ID:      [bold]{session.metadata.id}[/bold]")
        console.print(f"Status:  {session.metadata.status}")
        console.print(f"Path:    {session.path}")

    except ForgeError as exc:
        print_error(str(exc))
        raise typer.Exit(code=1)


@sessions_app.command("current")
def current_session(
    path: Annotated[
        Path,
        typer.Option("--path", "-p", help="Workspace root path."),
    ] = Path("."),
) -> None:
    """
    Show the current active session.
    """
    try:
        session = get_current_session(path)

        console.print("[bold]Current session[/bold]\n")
        console.print(f"ID:        {session.metadata.id}")
        console.print(f"Created:   {session.metadata.created_at}")
        console.print(f"Status:    {session.metadata.status}")
        console.print(f"Command:   {session.metadata.command}")
        console.print(f"Workspace: {session.metadata.workspace_root}")

    except ForgeError as exc:
        print_error(str(exc))
        raise typer.Exit(code=1)


@sessions_app.command("list")
def list_local_sessions(
    path: Annotated[
        Path,
        typer.Option("--path", "-p", help="Workspace root path."),
    ] = Path("."),
) -> None:
    """
    List local Forge sessions.
    """
    try:
        sessions = list_sessions(path)

        if not sessions:
            console.print("[yellow]No sessions found.[/yellow]")
            return

        current_id: str | None = None

        try:
            current_id = get_current_session(path).metadata.id
        except ForgeError:
            current_id = None

        table = Table(title="Trevvos Forge Sessions")
        table.add_column("Current")
        table.add_column("ID")
        table.add_column("Status")
        table.add_column("Command")
        table.add_column("Created")

        for session in sessions:
            marker = "*" if session.metadata.id == current_id else ""
            table.add_row(
                marker,
                session.metadata.id,
                session.metadata.status,
                session.metadata.command,
                session.metadata.created_at,
            )

        console.print(table)

    except ForgeError as exc:
        print_error(str(exc))
        raise typer.Exit(code=1)


@sessions_app.command("show")
def show_session(
    session_id: Annotated[
        str | None,
        typer.Argument(help="Session ID to show. If omitted, shows current session."),
    ] = None,
    path: Annotated[
        Path,
        typer.Option("--path", "-p", help="Workspace root path."),
    ] = Path("."),
) -> None:
    """
    Show session details.
    """
    try:
        if session_id:
            session = get_session(root=path, session_id=session_id)
        else:
            session = get_current_session(path)

        console.print("[bold]Session[/bold]\n")
        console.print(f"ID:        {session.metadata.id}")
        console.print(f"Created:   {session.metadata.created_at}")
        console.print(f"Status:    {session.metadata.status}")
        console.print(f"Command:   {session.metadata.command}")
        console.print(f"Workspace: {session.metadata.workspace_root}")
        console.print(f"Path:      {session.path}")

        user_request = read_session_text(session, "user_request.txt")

        selected_files_path = session.path / "selected_files.json"
        context_path = session.path / "context.md"
        prompt_metadata_path = session.path / "prompt_metadata.json"
        prompt_path = session.path / "prompt.md"
        plan_json_path = session.path / "plan.json"
        plan_raw_response_path = session.path / "plan_raw_response.md"
        plan_path = session.path / "plan.md"
        diff_prompt_metadata_path = session.path / "diff_prompt_metadata.json"
        diff_prompt_path = session.path / "diff_prompt.md"
        file_changes_raw_response_path = session.path / "file_changes_raw_response.json"
        file_changes_path = session.path / "file_changes.json"
        file_changes_error_path = session.path / "file_changes_error.txt"
        diff_raw_response_path = session.path / "diff_raw_response.patch"
        diff_path = session.path / "diff.patch"
        diff_warnings_path = session.path / "diff_warnings.json"
        diff_error_path = session.path / "diff_error.txt"
        operation_error_json_path = session.path / "operation_error.json"
        operation_error_markdown_path = session.path / "operation_error.md"
        diff_validation_path = session.path / "diff_validation.json"
        diff_validation_error_path = session.path / "diff_validation_error.txt"
        diff_check_path = session.path / "diff_check.json"
        diff_check_error_path = session.path / "diff_check_error.txt"
        change_summary_path = session.path / "change_summary.md"
        semantic_review_path = session.path / "semantic_review.json"
        apply_result_path = session.path / "apply_result.json"
        apply_error_path = session.path / "apply_error.txt"
        test_results_path = session.path / "test_results.json"
        test_output_path = session.path / "test_output.log"
        sandbox_test_results_path = session.path / "sandbox_test_results.json"
        sandbox_test_output_path = session.path / "sandbox_test_output.log"
        working_tree_test_results_path = session.path / "working_tree_test_results.json"
        working_tree_test_output_path = session.path / "working_tree_test_output.log"
        test_error_path = session.path / "test_error.txt"
        llm_review_path = session.path / "llm_review.md"
        llm_review_json_path = session.path / "llm_review.json"
        llm_review_raw_path = session.path / "llm_review_raw.txt"
        commit_message_path = session.path / "commit_message.txt"
        commit_plan_path = session.path / "commit_plan.json"
        commit_result_path = session.path / "commit_result.json"
        commit_message_raw_path = session.path / "commit_message_raw.txt"
        session_status_path = session.path / "session_status.json"

        if prompt_metadata_path.exists():
            console.print("\n[bold]Prompt metadata[/bold]")
            console.print(read_session_text(session, "prompt_metadata.json"))

        if prompt_path.exists():
            console.print("\n[bold]Prompt[/bold]")
            console.print(f"Saved at: {prompt_path}")

        if plan_json_path.exists():
            console.print("\n[bold]Structured plan[/bold]")
            console.print(f"Saved at: {plan_json_path}")

        if plan_raw_response_path.exists():
            console.print("\n[bold]Raw plan response[/bold]")
            console.print(f"Saved at: {plan_raw_response_path}")

        if plan_path.exists():
            console.print("\n[bold]Plan[/bold]")
            console.print(read_session_text(session, "plan.md"))

        if selected_files_path.exists():
            console.print("\n[bold]Selected files[/bold]")
            console.print(read_session_text(session, "selected_files.json"))

        if context_path.exists():
            console.print("\n[bold]Context[/bold]")
            console.print(f"Saved at: {context_path}")

        if diff_prompt_metadata_path.exists():
            console.print("\n[bold]Diff prompt metadata[/bold]")
            console.print(read_session_text(session, "diff_prompt_metadata.json"))

        if diff_prompt_path.exists():
            console.print("\n[bold]Diff prompt[/bold]")
            console.print(f"Saved at: {diff_prompt_path}")

        if file_changes_raw_response_path.exists():
            console.print("\n[bold]Raw file changes response[/bold]")
            console.print(f"Saved at: {file_changes_raw_response_path}")

        if file_changes_path.exists():
            console.print("\n[bold]File changes[/bold]")
            console.print(f"Saved at: {file_changes_path}")

        if file_changes_error_path.exists():
            console.print("\n[bold]File changes error[/bold]")
            console.print(read_session_text(session, "file_changes_error.txt"))

        if diff_raw_response_path.exists():
            console.print("\n[bold]Raw diff response[/bold]")
            console.print(f"Saved at: {diff_raw_response_path}")

        if diff_path.exists():
            console.print("\n[bold]Diff[/bold]")
            console.print(f"Saved at: {diff_path}")

        if diff_warnings_path.exists():
            console.print("\n[bold yellow]Diff warnings[/bold yellow]")
            console.print(read_session_text(session, "diff_warnings.json"))

        if diff_error_path.exists():
            console.print("\n[bold]Diff error[/bold]")
            console.print(read_session_text(session, "diff_error.txt"))

        if operation_error_json_path.exists():
            console.print("\n[bold]Operation error[/bold]")
            console.print(f"Saved at: {operation_error_json_path}")

        if operation_error_markdown_path.exists():
            console.print("\n[bold]Operation error details[/bold]")
            console.print(f"Saved at: {operation_error_markdown_path}")

        if diff_validation_path.exists():
            console.print("\n[bold]Diff validation[/bold]")
            console.print(f"Saved at: {diff_validation_path}")

        if diff_validation_error_path.exists():
            console.print("\n[bold]Diff validation error[/bold]")
            console.print(read_session_text(session, "diff_validation_error.txt"))

        if diff_check_path.exists():
            console.print("\n[bold]Diff git check[/bold]")
            console.print(f"Saved at: {diff_check_path}")

        if diff_check_error_path.exists():
            console.print("\n[bold]Diff git check error[/bold]")
            console.print(read_session_text(session, "diff_check_error.txt"))

        if change_summary_path.exists():
            console.print("\n[bold]Change summary[/bold]")
            console.print(f"Saved at: {change_summary_path}")

        if semantic_review_path.exists():
            console.print("\n[bold]Semantic review[/bold]")
            console.print(f"Saved at: {semantic_review_path}")

        if apply_result_path.exists():
            console.print("\n[bold]Apply result[/bold]")
            console.print(f"Saved at: {apply_result_path}")

        if apply_error_path.exists():
            console.print("\n[bold]Apply error[/bold]")
            console.print(read_session_text(session, "apply_error.txt"))

        if test_results_path.exists():
            console.print("\n[bold]Test results[/bold]")
            console.print(f"Saved at: {test_results_path}")

        if test_output_path.exists():
            console.print("\n[bold]Test output[/bold]")
            console.print(f"Saved at: {test_output_path}")

        if sandbox_test_results_path.exists():
            console.print("\n[bold]Sandbox test results[/bold]")
            console.print(f"Saved at: {sandbox_test_results_path}")

        if sandbox_test_output_path.exists():
            console.print("\n[bold]Sandbox test output[/bold]")
            console.print(f"Saved at: {sandbox_test_output_path}")

        if working_tree_test_results_path.exists():
            console.print("\n[bold]Working tree test results[/bold]")
            console.print(f"Saved at: {working_tree_test_results_path}")

        if working_tree_test_output_path.exists():
            console.print("\n[bold]Working tree test output[/bold]")
            console.print(f"Saved at: {working_tree_test_output_path}")

        if test_error_path.exists():
            console.print("\n[bold]Test error[/bold]")
            console.print(read_session_text(session, "test_error.txt"))

        if llm_review_path.exists():
            console.print("\n[bold]LLM review[/bold]")
            console.print(f"Saved at: {llm_review_path}")

        if llm_review_json_path.exists():
            console.print("\n[bold]LLM review JSON[/bold]")
            console.print(f"Saved at: {llm_review_json_path}")

        if llm_review_raw_path.exists():
            console.print("\n[bold]Raw LLM review[/bold]")
            console.print(f"Saved at: {llm_review_raw_path}")

        if commit_message_path.exists():
            console.print("\n[bold]Commit message[/bold]")
            console.print(f"Saved at: {commit_message_path}")

        if commit_plan_path.exists():
            console.print("\n[bold]Commit plan[/bold]")
            console.print(f"Saved at: {commit_plan_path}")

        if commit_result_path.exists():
            console.print("\n[bold]Commit result[/bold]")
            console.print(f"Saved at: {commit_result_path}")

        if commit_message_raw_path.exists():
            console.print("\n[bold]Raw commit message response[/bold]")
            console.print(f"Saved at: {commit_message_raw_path}")

        if session_status_path.exists():
            console.print("\n[bold]Session status[/bold]")
            console.print(f"Saved at: {session_status_path}")

        console.print("\n[bold]User request[/bold]")
        console.print(user_request)

    except ForgeError as exc:
        print_error(str(exc))
        raise typer.Exit(code=1)


@sessions_app.command("clean")
def clean_local_sessions(
    path: Annotated[
        Path,
        typer.Option("--path", "-p", help="Workspace root path."),
    ] = Path("."),
) -> None:
    """
    Delete all local Forge sessions for this workspace.
    """
    confirmed = typer.confirm(
        "This will delete .trevvos sessions for this workspace. Continue?",
        default=False,
    )

    if not confirmed:
        console.print("[yellow]Cancelled.[/yellow]")
        return

    try:
        clean_sessions(path)
        console.print("[green]Local sessions cleaned.[/green]")

    except ForgeError as exc:
        print_error(str(exc))
        raise typer.Exit(code=1)


@prompts_app.command("list")
def list_prompt_catalog() -> None:
    """
    List available versioned prompts.
    """
    table = Table(title="Trevvos Forge Prompts")
    table.add_column("Name")
    table.add_column("Version")
    table.add_column("Reference")
    table.add_column("Description", overflow="fold")

    for prompt in list_prompts():
        table.add_row(
            prompt.name,
            prompt.version,
            prompt.ref,
            prompt.description,
        )

    console.print(table)


@prompts_app.command("show")
def show_prompt(name: str) -> None:
    """
    Show a prompt template by name.
    """
    try:
        prompt = get_prompt(name)

        console.print("[bold]Prompt[/bold]\n")
        console.print(f"Name:        {prompt.name}")
        console.print(f"Version:     {prompt.version}")
        console.print(f"Reference:   {prompt.ref}")
        console.print(f"Description: {prompt.description}")

        console.print("\n[bold]Template[/bold]\n")
        console.print(prompt.template.strip())

    except ForgeError as exc:
        print_error(str(exc))
        raise typer.Exit(code=1)


def main() -> None:
    app()
