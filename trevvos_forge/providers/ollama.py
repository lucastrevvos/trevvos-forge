from dataclasses import dataclass

import requests

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

        response = requests.post(url, json=payload, timeout=self.timeout)
        response.raise_for_status()

        data = response.json()

        return data["response"].strip()
