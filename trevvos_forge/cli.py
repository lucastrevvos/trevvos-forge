from typing import Annotated

import typer
from rich.console import Console
from pathlib import Path
from rich.table import Table

from trevvos_forge.prompt_catalog import get_prompt, list_prompts
from trevvos_forge.engine import TrevvosForgeEngine
from trevvos_forge.exceptions import ForgeError
from trevvos_forge.providers.ollama import OllamaProvider
from trevvos_forge.settings import ForgeSettings

from trevvos_forge.sessions import (
    clean_sessions,
    create_session,
    get_current_session,
    list_sessions,
    read_session_text,
)

from trevvos_forge.workspace import scan_workspace, format_workspace_context, read_workspace_file

def print_error(message: str) -> None:
    err_console.print(f"[red][trevvos-forge][/red] {message}")

app = typer.Typer(
    name = "trevvos",
    help="Trevvos Forge: local-first AI engineering assistant.",
    no_args_is_help=True
)

models_app = typer.Typer(
    name="models",
    help="Manage local LLM models.",
    no_args_is_help=True
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

@app.callback()
def callback() -> None:
    """
    Trevvos Forge CLI
    """
    pass

def load_settings() -> ForgeSettings:
    return ForgeSettings.from_env()

def build_provider(settings: ForgeSettings) -> OllamaProvider:
    return OllamaProvider(
        model=settings.model,
        base_url=settings.base_url,
        timeout=settings.timeout
    )

def build_engine() -> TrevvosForgeEngine:
    settings = load_settings()
    provider = build_provider(settings)

    return TrevvosForgeEngine(provider=provider)


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
        typer.Option("--language", "-l", help="Target programming language.")
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
                language=language
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
        console.print(f"   Model:    {settings.model}")
        console.print(f"   Base URL:    {settings.base_url}")
        console.print(f"   Timeout:    {settings.timeout}s")

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
        typer.Option("--model", "-m", help="Model to check or pull during setup.")
    ] = None
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
            timeout=settings.timeout
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
            default=False
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
def scan(path: Annotated[
        Path,
        typer.Argument(help="Workspace path to scan.")
    ] = Path("."),
    max_files: Annotated[
        int,
        typer.Option("--max-files", help="Maxium number of files to show.")
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
                f"\n[yellow]Showing first 50 files. Use --max-files to control scan size.[/yellow]"
            )

    except (FileNotFoundError, NotADirectoryError) as exc:
        print_error(str(exc))
        raise typer.Exit(code=1)

@app.command()
def inspect(
    file_path: Annotated[
        Path,
        typer.Argument(help="File path inside the workspace to inspect.")
    ],
    path: Annotated[
        Path,
        typer.Option("--path", "-p", help="Workspace root path.")
    ] = Path("."),
    max_chars: Annotated[
        int,
        typer.Option("--max-chars", help="Maximum number of characters to read.")
    ] = 12_000

) -> None:
    """
    Safely inspect a file inside the workspace
    """
    try:
        content = read_workspace_file(
            root=path,
            file_path=file_path,
            max_chars=max_chars
        )

        console.print(f"[bold]File:[/bold] {file_path}\n")
        console.print(content)

    except ForgeError as exc:
        print_error(str(exc))
        raise typer.Exit(code=1)

@app.command()
def plan(
    instruction: str,
    path: Annotated[
        Path,
        typer.Option("--path", "-p", help="Workspace path to analyze.")
    ] = Path("."),
    max_files: Annotated[
        int,
        typer.Option("--max-files", help="Maximum number of files to include in context.")
    ] = 120
) -> None:
    """
    Create a technical change plan using the current project structure.
    """
    try:
        engine = build_engine()

        with console.status("[bold]Scanning workspace...[/bold]", spinner="dots"):
            scan_result = scan_workspace(path, max_files=max_files)
            workspace_context = format_workspace_context(
                scan=scan_result,
                max_files=max_files,
            )

        with console.status("[bold]Planning change with your local LLM...[/bold]", spinner="dots"):
            result = engine.plan_change(
                instruction=instruction,
                workspace_context=workspace_context,
            )

        console.print(result)

    except (FileNotFoundError, NotADirectoryError) as exc:
            print_error(str(exc))
            raise typer.Exit(code=1)
    except ForgeError as exc:
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
            from trevvos_forge.sessions import get_session

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
