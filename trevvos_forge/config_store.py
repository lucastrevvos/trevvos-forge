import json
from pathlib import Path

from trevvos_forge.exceptions import ConfigurationError


CONFIG_PATH = Path(".trevvos") / "config.json"
SUPPORTED_LANGUAGES = ("en", "pt-BR")
LANGUAGE_ALIASES = {
    "en": "en",
    "english": "en",
    "en-us": "en",
    "pt": "pt-BR",
    "pt-br": "pt-BR",
    "portuguese": "pt-BR",
    "português": "pt-BR",
}


def normalize_language(language: str) -> str:
    value = language.strip()
    if not value:
        raise ConfigurationError(
            "Unsupported language: ''\nSupported languages: en, pt-BR"
        )

    normalized = LANGUAGE_ALIASES.get(value.lower(), value if value in SUPPORTED_LANGUAGES else None)
    if normalized in SUPPORTED_LANGUAGES:
        return normalized

    raise ConfigurationError(f"Unsupported language: {language}\nSupported languages: en, pt-BR")


def load_config(repo_root: Path) -> dict:
    config_file = repo_root / CONFIG_PATH

    if not config_file.exists():
        return {}

    try:
        payload = json.loads(config_file.read_text(encoding="utf-8"))
    except json.JSONDecodeError as exc:
        raise ConfigurationError(f"Invalid JSON in {CONFIG_PATH}.") from exc

    if not isinstance(payload, dict):
        raise ConfigurationError(f"{CONFIG_PATH} must contain a JSON object.")

    return payload


def save_config(repo_root: Path, config: dict) -> Path:
    config_file = repo_root / CONFIG_PATH
    config_file.parent.mkdir(parents=True, exist_ok=True)
    config_file.write_text(json.dumps(config, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    return config_file


def get_language(repo_root: Path) -> str:
    config = load_config(repo_root)
    language = config.get("language")

    if isinstance(language, str) and language.strip():
        return normalize_language(language)

    return "en"


def set_language(repo_root: Path, language: str) -> dict:
    config = load_config(repo_root)
    config["language"] = normalize_language(language)
    save_config(repo_root, config)
    return config


def build_language_prompt_section(language: str) -> str:
    normalized = normalize_language(language)

    if normalized == "pt-BR":
        return "\n".join(
            [
                "Write the final report in Brazilian Portuguese (pt-BR).",
                "Keep code identifiers, file names, function names, class names, commands, and exact error messages unchanged.",
                "Do not translate code or CLI commands.",
            ]
        )

    return "\n".join(
        [
            "Write the final report in English.",
            "Keep code identifiers, file names, function names, class names, commands, and exact error messages unchanged.",
            "Do not translate code or CLI commands.",
        ]
    )
