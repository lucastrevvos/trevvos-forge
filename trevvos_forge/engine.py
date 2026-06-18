from dataclasses import dataclass

from trevvos_forge.providers.base import LLMProvider
from trevvos_forge.prompts import build_ask_prompt, build_code_generation_prompt

@dataclass
class TrevvosForgeEngine:
    provider: LLMProvider

    def ask(self, question: str) -> str:
        prompt = build_ask_prompt(question)

        return self.provider.generate(prompt)

    def generate_code(self, instruction: str, language: str | None = None) -> str:
        prompt = build_code_generation_prompt(
            instruction=instruction,
            language=language
        )

        return self.provider.generate(prompt)
