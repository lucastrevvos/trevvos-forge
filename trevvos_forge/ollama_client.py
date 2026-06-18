import requests

OLLAMA_URL = "http://localhost:11434/api/generate"

def generate(prompt: str, model: str) -> str:
    payload = {
        "model": model,
        "prompt": prompt,
        "stream": False
    }

    response = requests.post(OLLAMA_URL, json=payload)
    response.raise_for_status()

    data = response.json()

    return data["response"]
