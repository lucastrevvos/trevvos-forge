from typing import Annotated

import typer
from rich.console import Console
from pathlib import Path
from rich.table import Table


from trevvos_forge.engine import TrevvosForgeEngine
from trevvos_forge.exceptions import ForgeError
"""from trevvos_forge.exceptions import FileNotFoundError
from trevvos_forge.exceptions import NotADirectoryError"""
from trevvos_forge.providers.ollama import OllamaProvider
from trevvos_forge.settings import ForgeSettings

from trevvos_forge.workspace import scan_workspace, format_workspace_context

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

app.add_typer(models_app, name="models")

console = Console()

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
        console.print(f"[red][trevvos-forge][/red] {exc}", stderr=True)
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
        console.print(f"[red][trevvos-forge][/red] {exc}", stderr=True)
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
        console.print(f"[red][trevvos-forge][/red] {exc}", stderr=True)
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
        console.print(f"[red][trevvos-forge][/red] {exc}", stderr=True)
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
        console.print(f"[red][trevvos-forge][/red] {exc}", stderr=True)
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
            console.print(f"[red][trevvos-forge][/red] {exc}", stderr=True)
            raise typer.Exit(code=1)
    except ForgeError as exc:
            console.print(f"[red][trevvos-forge][/red] {exc}", stderr=True)
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
        console.print(f"[red][trevvos-forge][/red] {exc}", stderr=True)
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
        console.print(f"[red][trevvos-forge][/red] {exc}", stderr=True)
        raise typer.Exit(code=1)



def main() -> None:
    app()
