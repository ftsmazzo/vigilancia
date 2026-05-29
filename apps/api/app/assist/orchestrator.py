"""VigIA — orquestrador conversacional (RAG + AgenteSQL + resposta humanizada)."""

from __future__ import annotations

import json
import re
from typing import Any

from sqlalchemy.engine import Connection
from sqlalchemy.orm import Session

from ..models import User
from ..municipio_context import load_context_prompt
from .cras_breakdown import format_cras_breakdown_answer
from .canonical_metrics import try_canonical_metric
from .kb_client import query_knowledge_base
from .llm import chat_completion
from .sql_agent import SqlAgentResult, run_sql_agent

ORCHESTRATOR_PLAN_SYSTEM = """Você é VigIA, orquestrador do assistente de vigilância socioassistencial municipal.

Analise a mensagem atual e o histórico da conversa.

**mode = "chat"** quando:
- Cumprimentos, agradecimentos, conversa geral
- Dúvidas sobre políticas, conceitos SUAS, orientações (use contexto RAG se fornecido)
- Não há pedido de número, total, percentual ou cruzamento de dados

**mode = "data"** quando:
- O usuário pede quantidade, total, percentual, listagem agregada
- Perguntas sobre CADU, PBF, SISC, CRAS, famílias, pessoas, renda, deficiência, etc.
- Follow-up numérico ("dessas", "entre elas", "e quantas têm...") — reformule com o contexto anterior

Quando mode = "data", preencha sql_question com UM pedido claro para o AgenteSQL:
- Objetivo, sem instruções de SQL
- Ex.: "Qual o total de famílias no Cadastro Único"
- Ex. follow-up: "Quantas famílias do CADU possuem criança com até 6 anos de idade"

Responda APENAS JSON: {"mode": "chat" | "data", "sql_question": "..." ou null}
"""

ORCHESTRATOR_CHAT_SYSTEM = """Você é VigIA, assistente de vigilância socioassistencial do município.
Converse de forma cordial, clara e profissional em português do Brasil.

- Trate o usuário pelo primeiro nome quando souber
- Use o contexto municipal e trechos de políticas SUAS (RAG) quando relevante
- Não invente estatísticas — se pedirem números, diga que pode consultar o CADU e sugira uma pergunta objetiva
- Respostas curtas (2–4 parágrafos no máximo)
"""

ORCHESTRATOR_FINALIZE_SYSTEM = """Você é VigIA. Transforme o resultado numérico do AgenteSQL em resposta humanizada.

- Trate o usuário pelo primeiro nome
- Mencione o município quando souber
- Informe o número principal com clareza
- Contextualize em uma frase o que o indicador significa
- Tom cordial e profissional
- NÃO mostre SQL, JSON nem mensagens de erro técnicas
- Use APENAS números presentes nos resultados fornecidos
- Se o resultado for desdobramento por CRAS: liste TODOS os CRAS na ordem numérica (1 a 12),
  inclua CRAS 9 (Bonfim Paulista) e famílias sem referência territorial — NUNCA resuma só os 5 maiores
"""


def _municipio_nome(municipio_block: str) -> str:
    m = re.search(r"Município:\s*\*\*([^*]+)\*\*", municipio_block)
    return m.group(1).strip() if m else ""


def _cras_answer_with_context(
    rows: list[dict[str, Any]],
    user: User,
    municipio_block: str,
) -> str:
    return format_cras_breakdown_answer(
        rows,
        user_first_name=_first_name(user.name),
        municipio_nome=_municipio_nome(municipio_block),
    )


def _first_name(full_name: str | None) -> str:
    if not full_name:
        return ""
    return full_name.strip().split()[0]


def _user_context_block(user: User, municipio_block: str) -> str:
    parts = []
    if user.name:
        parts.append(f"Usuário logado: {user.name} (trate por {_first_name(user.name)}).")
    if municipio_block:
        parts.append(municipio_block)
    return "\n".join(parts)


def _parse_plan(raw: str) -> dict[str, Any]:
    content = raw.strip()
    try:
        if content.startswith("{"):
            return json.loads(content)
    except json.JSONDecodeError:
        pass
    m = re.search(r"\{[\s\S]*\}", content)
    if m:
        try:
            return json.loads(m.group(0))
        except json.JSONDecodeError:
            pass
    if re.search(r"\b(data|sql)\b", content, re.I):
        return {"mode": "data", "sql_question": None}
    return {"mode": "chat", "sql_question": None}


def _plan_turn(
    message: str,
    transcript: list[dict[str, str]],
    rag_block: str,
    user_block: str,
) -> dict[str, Any]:
    system = ORCHESTRATOR_PLAN_SYSTEM
    if rag_block:
        system += f"\n\n### Contexto RAG (políticas SUAS)\n{rag_block[:4000]}"
    if user_block:
        system += f"\n\n{user_block}"

    messages: list[dict[str, str]] = [
        {"role": "system", "content": system},
        *transcript,
    ]
    raw = chat_completion(messages, json_mode=True, temperature=0.2, role="orch")
    plan = _parse_plan(raw)
    mode = (plan.get("mode") or "chat").lower()
    if mode not in ("chat", "data"):
        mode = "data" if plan.get("sql_question") else "chat"
    return {
        "mode": mode,
        "sql_question": (plan.get("sql_question") or "").strip() or None,
    }


def _chat_reply(
    message: str,
    transcript: list[dict[str, str]],
    rag_block: str,
    user_block: str,
) -> str:
    system = ORCHESTRATOR_CHAT_SYSTEM
    if rag_block:
        system += f"\n\n### Políticas e referências SUAS\n{rag_block[:6000]}"
    if user_block:
        system += f"\n\n{user_block}"

    messages: list[dict[str, str]] = [
        {"role": "system", "content": system},
        *transcript,
    ]
    return chat_completion(messages, temperature=0.5, role="orch").strip()


def _finalize_data_reply(
    message: str,
    transcript: list[dict[str, str]],
    sql_question: str,
    sql_result: SqlAgentResult,
    user_block: str,
) -> str:
    if not sql_result.ok:
        # Resposta amigável mesmo em falha
        fail_messages: list[dict[str, str]] = [
            {
                "role": "system",
                "content": (
                    ORCHESTRATOR_FINALIZE_SYSTEM
                    + "\n\nO AgenteSQL não conseguiu obter o dado. Explique com empatia, "
                    "sugira reformular a pergunta ou ser mais específico (CRAS, PBF, faixa etária). "
                    "Não repita erro técnico cru."
                )
                + (f"\n\n{user_block}" if user_block else ""),
            },
            *transcript,
            {
                "role": "user",
                "content": (
                    f"Pergunta original: {message}\n"
                    f"Pedido ao AgenteSQL: {sql_question}\n"
                    f"Problema: {sql_result.error}"
                ),
            },
        ]
        return chat_completion(fail_messages, temperature=0.4, role="orch").strip()

    messages: list[dict[str, str]] = [
        {
            "role": "system",
            "content": ORCHESTRATOR_FINALIZE_SYSTEM + (f"\n\n{user_block}" if user_block else ""),
        },
        *transcript,
        {
            "role": "user",
            "content": (
                f"Pergunta do usuário: {message}\n"
                f"Consulta formulada: {sql_question}\n"
                f"Resultado AgenteSQL ({sql_result.row_count} linha(s)): {sql_result.summary}"
            ),
        },
    ]
    return chat_completion(messages, temperature=0.35, role="orch").strip()


def _personalize_canonical(answer: str, user: User) -> str:
    first = _first_name(user.name)
    if not first or answer.startswith(first):
        return answer
    if answer.startswith("Há "):
        return f"{first}, h{answer[2:]}"
    return f"{first}, {answer}"


def run_orchestrator_turn(
    conn: Connection,
    db: Session,
    user: User,
    message: str,
    transcript: list[dict[str, str]],
) -> dict[str, Any]:
    """
    Pipeline VigIA nativo:
    RAG → plano → (chat | canonical | AgenteSQL) → humanização
    """
    municipio_block = load_context_prompt(db)
    user_block = _user_context_block(user, municipio_block)
    rag_block = query_knowledge_base(message)

    # Métricas canônicas (SISC×CADU, CRAS, PBF) têm prioridade — sempre com SQL explícito
    canonical = try_canonical_metric(conn, message, transcript)
    if canonical:
        answer = canonical["answer"]
        if canonical.get("metric") == "cadu_familias_por_cras":
            answer = _cras_answer_with_context(
                canonical.get("preview") or [],
                user,
                municipio_block,
            )
        elif canonical.get("source") == "vig.mvw_sisc_qualificado":
            answer = _personalize_canonical(answer, user)
        return {
            "answer": answer,
            "sql": canonical.get("sql"),
            "row_count": canonical.get("row_count", 0),
            "preview": canonical.get("preview") or [],
            "mode": canonical.get("mode", "canonical"),
        }

    plan = _plan_turn(message, transcript, rag_block, user_block)

    if plan["mode"] == "chat":
        answer = _chat_reply(message, transcript, rag_block, user_block)
        return {
            "answer": answer,
            "sql": None,
            "row_count": 0,
            "preview": [],
            "mode": "chat",
        }

    sql_question = plan.get("sql_question") or message.strip()

    sql_result = run_sql_agent(conn, db, sql_question)
    if sql_result.ok and sql_result.formatted_answer:
        answer = _cras_answer_with_context(sql_result.rows, user, municipio_block)
    else:
        answer = _finalize_data_reply(message, transcript, sql_question, sql_result, user_block)

    return {
        "answer": answer,
        "sql": sql_result.sql,
        "row_count": sql_result.row_count,
        "preview": sql_result.preview,
        "mode": "data",
        "error": sql_result.error if not sql_result.ok else None,
    }
