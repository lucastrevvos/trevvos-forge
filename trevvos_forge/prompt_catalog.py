from dataclasses import dataclass

from trevvos_forge.exceptions import PromptError


@dataclass(frozen=True)
class PromptTemplate:
    name: str
    version: str
    description: str
    template: str

    @property
    def ref(self) -> str:
        return f"{self.name}@{self.version}"

    def render(self, **variables: str) -> str:
        try:
            return self.template.format(**variables).strip()
        except KeyError as exc:
            missing_key = exc.args[0]

            raise PromptError(
                f"Missing prompt variable {missing_key!r} for {self.ref}."
            ) from exc


PROMPT_CATALOG: dict[str, PromptTemplate] = {
    "ask": PromptTemplate(
        name="ask",
        version="1.0.0",
        description="Answers general technical questions.",
        template="""
Você é a Trevvos Forge, uma assistente local de engenharia de software.

Responda de forma clara, objetiva e útil.
Quando fizer sentido, explique o raciocínio técnico.
Evite enrolação.

Pergunta:
{question}
""",
    ),
    "generate_code": PromptTemplate(
        name="generate_code",
        version="1.0.0",
        description="Generates clean and useful code from an instruction.",
        template="""
Você é a Trevvos Forge, uma assistente local especializada em geração de código.

Gere código limpo, direto e funcional.
Siga boas práticas da linguagem.
Evite explicações longas antes do código.
Quando necessário, inclua uma explicação curta depois do código.

Linguagem desejada: {language_context}

Instrução:
{instruction}
""",
    ),
    "plan_change": PromptTemplate(
        name="plan_change",
        version="1.0.0",
        description="Creates a technical project change plan based on workspace context.",
        template="""
Você é a Trevvos Forge, uma assistente local de engenharia de software.

Sua tarefa é analisar a estrutura de um projeto e propor um plano técnico de mudança.
Não gere código completo agora.
Não diga que alterou arquivos.
Não invente arquivos se a estrutura não indicar necessidade.
Se faltar informação, diga quais arquivos precisam ser analisados depois.

Responda com:

1. Resumo da intenção
2. Leitura do projeto
3. Arquivos provavelmente envolvidos
4. Plano passo a passo
5. Riscos/cuidados
6. Próximo comando sugerido

Contexto do projeto:
{workspace_context}

Pedido do usuário:
{instruction}
""",
    ),
    "plan_change_json": PromptTemplate(
        name="plan_change_json",
        version="1.0.0",
        description="Creates a structured JSON technical project change plan.",
        template="""
Você é a Trevvos Forge, uma assistente local de engenharia de software.

Sua tarefa é analisar a estrutura de um projeto e propor um plano técnico de mudança.

Responda SOMENTE com um JSON válido.
Não use Markdown.
Não use bloco de código.
Não escreva texto antes ou depois do JSON.
Não diga que alterou arquivos.
Não gere código completo agora.
Não invente arquivos se a estrutura não indicar necessidade.
Se faltar informação, diga isso nos riscos.

O JSON deve seguir exatamente este formato:

{{
  "summary": "Resumo curto da intenção do usuário.",
  "project_reading": "Leitura técnica curta do projeto com base no contexto.",
  "files_involved": [
    "arquivo/ou/pasta/provavel.py"
  ],
  "steps": [
    "Passo técnico 1",
    "Passo técnico 2"
  ],
  "risks": [
    "Risco ou cuidado técnico"
  ],
  "next_command": "trevvos diff"
}}

Contexto do projeto:
{workspace_context}

Pedido do usuário:
{instruction}
""",
    ),
}


def get_prompt(name: str) -> PromptTemplate:
    prompt = PROMPT_CATALOG.get(name)

    if prompt is None:
        raise PromptError(f"Prompt not found: {name}")

    return prompt


def list_prompts() -> list[PromptTemplate]:
    return list(PROMPT_CATALOG.values())
