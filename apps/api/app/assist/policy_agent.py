"""Especialista Políticas e Normativas — SUAS, legislação e referências via RAG."""

from __future__ import annotations

import re
from dataclasses import dataclass

from .answer_trim import trim_answer_boilerplate
from .kb_client import query_knowledge_base
from .llm import chat_completion

POLICY_AGENT_SYSTEM = """Você é o **Especialista em Políticas e Normativas** do VigIA — socioassistencial municipal.

Missão:
- Explicar conceitos SUAS, regras de programas (PBF, BPC, SCFV, PAIF), tipificações e fluxos normativos.
- Fundamentar respostas nos trechos de referência (RAG) com clareza técnica.
- Quando pedirem números do município, reconheça o limite e indique como formular a pergunta ao especialista de **Dados de Vigilância** (CADU, SISC, SIBEC…).

Tom: cordial, técnico, orientado à prática da gestão — não burocrático.
"""

_POLICY_INTENT = re.compile(
    r"pol[ií]tica|normativ|legisla|decreto|portaria|resolu[cç][ãa]o|"
    r"orienta[cç][ãa]o\s+t[eé]cnica|tipifica|"
    r"\bsuas\b|loas|tipos?\s+de\s+servi[cç]o|"
    r"o\s+que\s+[eé]\s+(?:o\s+)?(?:pbf|bolsa|scfv|paif|cras|creas)|"
    r"como\s+funciona|quem\s+tem\s+direito|eleg[ií]vel\s+(?:ao|à|para)|"
    r"requisito|crit[eé]rio\s+(?:de\s+)?(?:eleg|acesso|ingresso)|"
    r"bloco\s+de\s+(?:gest[aã]o|financiamento)|"
    r"descentraliza[cç][ãa]o|piso\s+(?:social|assistencial)",
    re.I,
)

_DATA_OVERRIDE = re.compile(
    r"quantas?|quantos?|total|n[uú]mero|percentual|%|"
    r"liste|mostre|conte|ranking|compar",
    re.I,
)


@dataclass(frozen=True)
class PolicyAgentResult:
    ok: bool
    answer: str
    rag_used: bool
    snippets_chars: int = 0


def is_policy_turn(message: str) -> bool:
    text = message.strip()
    if not text:
        return False
    if _DATA_OVERRIDE.search(text):
        return False
    return bool(_POLICY_INTENT.search(text))


def run_policy_agent(
    message: str,
    transcript: list[dict[str, str]] | None,
    *,
    user_first_name: str = "",
    municipio_block: str = "",
) -> PolicyAgentResult:
    rag_block = query_knowledge_base(message)
    system = POLICY_AGENT_SYSTEM
    if municipio_block:
        system += f"\n\n### Município atendido\n{municipio_block[:3000]}"
    if rag_block:
        system += f"\n\n### Trechos de referência (RAG)\n{rag_block[:8000]}"
    else:
        system += (
            "\n\n### Trechos de referência\n"
            "Nenhum trecho RAG retornado. Responda com conhecimento geral SUAS, "
            "deixando claro que não há citação documental nesta resposta."
        )

    messages: list[dict[str, str]] = [
        {"role": "system", "content": system},
        *(transcript or []),
    ]
    raw = chat_completion(messages, temperature=0.35, role="policy").strip()
    answer = trim_answer_boilerplate(raw)
    if user_first_name and answer and not answer.lower().startswith(user_first_name.lower()):
        answer = f"{user_first_name}, {answer[0].lower()}{answer[1:]}"
    return PolicyAgentResult(
        ok=True,
        answer=answer,
        rag_used=bool(rag_block),
        snippets_chars=len(rag_block),
    )
