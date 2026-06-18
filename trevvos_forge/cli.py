import sys

import typer

from trevvos_forge.engine import TrevvosForgeEngine
from trevvos_forge.exceptions import ForgeError
from trevvos_forge.providers.ollama import OllamaProvider
from trevvos_forge.settings import ForgeSettings

app = typer.Typer(
    name = "trevvos",
    help="Trevvos Forge: local-first AI engineering assistant.",
    no_args_is_help=True
)

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
        answer = engine.ask(question)
        typer.echo(answer)
    except ForgeError as exc:
        typer.echo(f"[trevvos-forge] {exc}", err=True)
        raise typer.Exit(code=1)

def main() -> None:
    app()
