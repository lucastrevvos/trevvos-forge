from typing import Annotated

import typer
from rich.console import Console

from trevvos_forge.engine import TrevvosForgeEngine
from trevvos_forge.exceptions import ForgeError
from trevvos_forge.providers.ollama import OllamaProvider
from trevvos_forge.settings import ForgeSettings

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


def main() -> None:
    app()
