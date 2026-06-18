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

console = Console()

@app.callback()
def callback() -> None:
    """
    Trevvos Forge CLI
    """
    pass

def build_engine() -> TrevvosForgeEngine:
    settings = ForgeSettings.from_env()

    provider = OllamaProvider(
        model=settings.model,
        base_url=settings.base_url,
        timeout=settings.timeout
    )

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



def main() -> None:
    app()
