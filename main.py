from trevvos_forge.engine import TrevvosForgeEngine
from trevvos_forge.providers.ollama import OllamaProvider
from trevvos_forge.settings import ForgeSettings

MODEL_NAME = "qwen2.5-coder:7b"

def main() -> None:
    settings = ForgeSettings.from_env()

    provider = OllamaProvider(
        model=settings.model,
        base_url=settings.base_url,
        timeout=settings.timeout
    )

    engine = TrevvosForgeEngine(provider=provider)

    answer = engine.ask("Explique em poucas linhas o que é uma biblioteca de software.");

    generated_code = engine.generate_code(
        instruction="Crie uma função que soma dois números.",
        language="python"
    )

    print("=== SETTINGS ===")
    print(f"Model: {settings.model}")
    print(f"Base URL: {settings.base_url}")
    print(f"Timeout: {settings.timeout}")

    print("=== ASK ===")
    print(answer)

    print("\n=== GENERATED CODE ===")
    print(generated_code)

if __name__ == "__main__":
    main()
