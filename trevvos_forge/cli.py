import json
from pathlib import Path
from typing import Annotated

import typer
from rich.console import Console
from rich.table import Table

from trevvos_forge.apply_patch import apply_patch, check_patch
from trevvos_forge.context_builder import build_context
from trevvos_forge.diff_builder import build_unified_diff_from_file_changes
from trevvos_forge.diff_validation import validate_diff_patch
from trevvos_forge.engine import TrevvosForgeEngine
from trevvos_forge.exceptions import (
    ApplyError,
    DiffError,
    DiffValidationError,
    FileChangeOutputError,
    ForgeError,
    TestRunError,
)
from trevvos_forge.file_change_outputs import parse_file_changes_output
from trevvos_forge.prompt_catalog import get_prompt, list_prompts
from trevvos_forge.providers.ollama import OllamaProvider
from trevvos_forge.review_artifacts import (
    build_change_summary_markdown,
    build_patch_preview,
    build_semantic_review_json,
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
from trevvos_forge.structured_outputs import parse_plan_output
from trevvos_forge.test_runner import (
    load_test_commands,
    run_test_commands,
    run_tests_in_sandbox,
    write_test_artifacts,
)
from trevvos_forge.workspace import read_workspace_file, scan_workspace


app = typer.Typer(
    name="trevvos",
    help="Trevvos Forge: local-first AI engineering assistant.",
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
        Path,
        typer.Argument(help="File path inside the workspace to inspect."),
    ],
    path: Annotated[
        Path,
        typer.Option("--path", "-p", help="Workspace root path."),
    ] = Path("."),
    max_chars: Annotated[
        int,
        typer.Option("--max-chars", help="Maximum number of characters to read."),
    ] = 12_000,
) -> None:
    """
    Safely inspect a file inside the workspace.
    """
    try:
        content = read_workspace_file(
            root=path,
            file_path=file_path,
            max_chars=max_chars,
        )

        console.print(f"[bold]File:[/bold] {file_path}\n")
        console.print(content)

    except ForgeError as exc:
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
def plan(
    instruction: str,
    path: Annotated[
        Path,
        typer.Option("--path", "-p", help="Workspace root path."),
    ] = Path("."),
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

        session = create_session(
            root=path,
            user_request=instruction,
            command="plan",
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

        plan_output = parse_plan_output(raw_plan_response)

        write_session_json(
            session=session,
            file_name="plan.json",
            data=plan_output.to_dict(),
        )

        plan_markdown = plan_output.to_markdown()

        write_session_text(
            session=session,
            file_name="plan.md",
            content=plan_markdown,
        )

        session = update_session_status(session, "planned")

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
) -> None:
    """
    Generate a unified diff from a saved plan session.
    """
    session = None

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

        instruction = read_session_text(session, "user_request.txt")
        workspace_context = read_session_text(session, "context.md")
        plan_markdown = read_session_text(session, "plan.md")

        prompt_template = get_prompt("file_changes_generation")

        prompt = prompt_template.render(
            instruction=instruction,
            workspace_context=workspace_context,
            plan=plan_markdown,
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

        diff_warnings: list[str] = []
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
        )
        semantic_review = build_semantic_review_json(
            request=instruction,
            file_changes=file_changes,
            warnings=diff_warnings,
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
                "diff_error.txt",
                "diff_validation_error.txt",
                "diff_check_error.txt",
            ],
        )

        session = update_session_status(session, "diff_validated")

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
        console.print(f"  - {session.path / 'diff.patch'}")
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
            write_session_text(
                session=session,
                file_name="file_changes_error.txt",
                content=str(exc),
            )
            update_session_status(session, "diff_generation_failed")

        print_error(str(exc))
        raise typer.Exit(code=1)

    except DiffValidationError as exc:
        if session is not None:
            write_session_text(
                session=session,
                file_name="diff_validation_error.txt",
                content=str(exc),
            )
            update_session_status(session, "diff_validation_failed")

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
            update_session_status(session, "diff_check_failed")

        print_error(message)
        raise typer.Exit(code=1)

    except ForgeError as exc:
        if session is not None:
            write_session_text(
                session=session,
                file_name="diff_error.txt",
                content=str(exc),
            )
            update_session_status(session, "diff_generation_failed")

        print_error(str(exc))
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

        if not yes and not typer.confirm("Apply this patch?", default=False):
            console.print("[yellow]Cancelled.[/yellow]")
            return

        result = apply_patch(workspace_root=workspace_root, session=session)

        write_session_json(
            session=session,
            file_name="apply_result.json",
            data=result.to_dict(),
        )

        session = update_session_status(session, "applied")

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

        patch_path = session.path / "diff.patch"

        if not patch_path.exists():
            raise TestRunError("Cannot test: diff.patch not found in session. Run trevvos diff first.")

        commands = load_test_commands(workspace_root)

        if not commands:
            result = run_test_commands(
                commands=[],
                repo_root=workspace_root,
                timeout_seconds=timeout,
                mode="sandbox" if sandbox else "working_tree",
                sandbox={"enabled": True, "kept": False, "path": None} if sandbox else None,
            )
            write_test_artifacts(session.path, result)

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

        for index, command in enumerate(commands, start=1):
            console.print(f"{index}. {command}")

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
            return

        console.print("\n[bold]Running tests...[/bold]\n")

        if sandbox:
            result = run_tests_in_sandbox(
                repo_root=workspace_root,
                patch_path=patch_path,
                commands=commands,
                timeout_seconds=timeout,
                keep_sandbox=keep_sandbox,
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
            result = run_test_commands(
                commands=commands,
                repo_root=workspace_root,
                timeout_seconds=timeout,
            )

        write_test_artifacts(session.path, result)

        for command_result in result.commands:
            marker = "[green]OK[/green]" if command_result.status == "passed" else "[red]FAIL[/red]"
            console.print(f"{marker} {command_result.command}")

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

        print_error(str(exc))
        raise typer.Exit(code=1)


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
        test_error_path = session.path / "test_error.txt"

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

        if test_error_path.exists():
            console.print("\n[bold]Test error[/bold]")
            console.print(read_session_text(session, "test_error.txt"))

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
