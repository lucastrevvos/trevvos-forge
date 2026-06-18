from trevvos_forge.engine import TrevvosForgeEngine
from trevvos_forge.providers.ollama import OllamaProvider

MODEL_NAME = "qwen2.5-coder:7b"

def main() -> None:
    provider = OllamaProvider(model=MODEL_NAME)

    engine = TrevvosForgeEngine(provider=provider)

    answer = engine.ask("Explique em poucas linhas o que é uma biblioteca de software.");

    generated_code = engine.generate_code(
        instruction="Crie uma função que soma dois números.",
        language="python"
    )

    print("=== ASK ===")
    print(answer)

    print("\n=== GENERATED CODE ===")
    print(generated_code)

if __name__ == "__main__":
    main()
