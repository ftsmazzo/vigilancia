"""Camada de síntese VigIA — cruza fatos de Vigilância com conhecimento para apoiar decisão."""

from __future__ import annotations

from sqlalchemy.engine import Connection
from sqlalchemy.orm import Session

from .analyst_context import AnalystContext, build_analyst_context
from .answer_trim import trim_answer_boilerplate
from .evidence import EvidencePack
from .llm import chat_completion
from .response_mode import response_mode_hint

SYNTHESIS_CORE = """Você é a **camada de síntese** do VigIA — apoia gestores na decisão socioassistencial.

Você NÃO é um quinto agente de dados. Os números vêm do **tronco CADU** e das **camadas de Vigilância**
(SISC, IVS, SIBEC manutenções, geo). Sua função é **interpretar** fatos verificados com conhecimento técnico.

## Como escrever (inteligência, não dureza)
- Tom **cordial e técnico** — como um analista sênior da rede, não um robô de KPI.
- **Objetivo**, mas útil: número + o que significa + (se couber) uma leitura para decisão em 1 frase.
- Em **comparativos** ou **saltos relevantes**: destaque a variação e sugira leitura prática
  (ex.: revisão cadastral, acompanhamento PAIF, cruzar com demanda CADU no território).
- Em pergunta **só numérica**: responda direto; reflexão só se agregar valor real.
- Use RAG/normas para **contextualizar**, nunca para inventar estatística.

## Hierarquia de verdade
1. Fatos verificados — únicos números citáveis.
2. Rede municipal e playbook — situam a decisão.
3. RAG (políticas SUAS) — fundamenta a leitura, sem substituir dados.

## Proibido
- SQL, JSON, nomes de tabelas/views, siglas de banco.
- Respostas secas tipo "reformule a pergunta" sem orientar o próximo passo.
- Metodologia longa ou percorrer todos os eixos quando a pergunta foi pontual.
"""


def interpret_evidence(
    pack: EvidencePack,
    *,
    user_first_name: str = "",
    conn: Connection | None = None,
    db: Session | None = None,
    municipio_block: str = "",
    rag_block: str = "",
    context: AnalystContext | None = None,
) -> str:
    if not pack.facts:
        prefix = f"{user_first_name}, " if user_first_name else ""
        return (
            f"{prefix}não encontrei base suficiente para cruzar essa pergunta com os dados de Vigilância. "
            "Indique CRAS, bairro, competência (mês/ano) ou se quer olhar famílias, pessoas ou manutenções PBF."
        )

    ctx = context
    if ctx is None and conn is not None and db is not None:
        ctx = build_analyst_context(
            conn,
            db,
            message=pack.question,
            pack=pack,
            municipio_block=municipio_block,
            rag_block=rag_block,
        )
    elif ctx is None:
        ctx = AnalystContext(
            municipio_block=municipio_block,
            rag_block=rag_block,
        )

    system = SYNTHESIS_CORE
    sections = ctx.to_system_sections()
    if sections:
        system += f"\n\n## Contexto para leitura e decisão\n\n{sections}"

    mode_line = response_mode_hint(pack.question, pack.metric)
    user_content = f"{mode_line}\n\n{pack.to_prompt_block()}"

    messages = [
        {"role": "system", "content": system},
        {
            "role": "user",
            "content": user_content,
        },
    ]
    raw = chat_completion(messages, temperature=0.25, role="analyst").strip()
    raw = trim_answer_boilerplate(raw)
    if user_first_name and raw and not raw.lower().startswith(user_first_name.lower()):
        return f"{user_first_name}, {raw[0].lower()}{raw[1:]}"
    return raw
