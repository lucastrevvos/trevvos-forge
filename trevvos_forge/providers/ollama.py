from dataclasses import dataclass

import requests

from trevvos_forge.exceptions import (
    ProviderConnectionError,
    ProviderHttpError,
    ProviderResponseError,
    ProviderTimeoutError
)



@dataclass
class OllamaProvider:
    model: str
    base_url: str = "http://localhost:11434"
    timeout: int = 120

    def generate(self, prompt: str) -> str:
        url = f"{self.base_url}/api/generate"

        payload = {
            "model": self.model,
            "prompt": prompt,
            "stream": False
        }

        try:
            response = requests.post(url, json=payload, timeout=self.timeout)
        except requests.exceptions.ConnectionError as exc:
            raise ProviderConnectionError(
                f"Não consegui conectar ao Ollama em {self.base_url}. "
                "Verifique se o Ollama está rodando."
            ) from exc

        except requests.exceptions.Timeout as exc:
            raise ProviderTimeoutError(
                f"Ollama demorou mais que {self.timeout} segundos para responder."
            ) from exc

        except requests.exceptions.RequestException as exc:
            raise ProviderHttpError(
                f"Erro inesperado ao chamar o Ollama em {self.base_url}"
            ) from exc

        try:
            data = response.json()
        except ValueError as exc:
            raise ProviderResponseError(
                "Ollama retornou uma resposta que não é um JSON válido."
            ) from exc

        generated_text = data.get("response")

        if not isinstance(generated_text, str):
            raise ProviderResponseError(
                "Ollama retornou uma resposta inesperada: campo 'response' ausente ou inválido."
            )

        return generated_text.strip()
