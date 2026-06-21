from trevvos_forge.prompt_catalog import get_prompt


def build_ask_prompt(question: str) -> str:
    return get_prompt("ask").render(question=question)


def build_code_generation_prompt(instruction: str, language: str | None = None) -> str:
    language_context = language if language else "não especificada"

    return get_prompt("generate_code").render(
        instruction=instruction,
        language_context=language_context,
    )


def build_project_plan_prompt(instruction: str, workspace_context: str) -> str:
    return get_prompt("plan_change").render(
        instruction=instruction,
        workspace_context=workspace_context,
    )
