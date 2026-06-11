"""Especialista Analítico — interpreta fatos com domínio IVS, RAG e rede municipal."""

from __future__ import annotations

from sqlalchemy.engine import Connection
from sqlalchemy.orm import Session

from .analyst_context import AnalystContext, build_analyst_context
from .evidence import EvidencePack
from .llm import chat_completion
from .response_mode import response_mode_hint

ANALYST_CORE = """Você é o **Especialista Analítico** do VigIA — socioassistencial municipal.

Pense com os eixos A–G e o playbook **internamente**; na **escrita**, seja **objetivo** — sem enrolação.

## Regra de ouro: proporcionalidade
- Pergunta pede **só dado** (quantos, qual, índice) → **1–2 frases**, número + recorte. Nada mais.
- Pergunta pede **lista/ranking** → entregue a lista; intro mínima.
- Pergunta pede **carência, indicar, implantar, analisar** → **2–4 frases**, só eixos **pertinentes** à pergunta.
- **Nunca** percorra todos os eixos coletados se a pergunta não pediu análise ampla.
- **Nunca** encha linguiça para parecer completo.

## Hierarquia de verdade
1. Fatos verificados — únicos números citáveis.
2. Playbook/guia — peso interno; na resposta, só o relevante.
3. RAG — sem inventar estatística.

## Formato
- Tom cordial; primeiro nome **uma vez**.
- Proibido: SQL, JSON, tabelas, "formule uma pergunta", parágrafos de metodologia.
- IVS (eixo D) só entra se a pergunta envolver vulnerabilidade ou planejamento — não em pergunta numérica simples.
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
            f"{prefix}não consegui reunir dados estruturados para responder com segurança. "
            "Tente reformular indicando CRAS, bairro ou faixa etária."
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

    system = ANALYST_CORE
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
    raw = chat_completion(messages, temperature=0.2, role="analyst").strip()
    if user_first_name and raw and not raw.lower().startswith(user_first_name.lower()):
        return f"{user_first_name}, {raw[0].lower()}{raw[1:]}"
    return raw
