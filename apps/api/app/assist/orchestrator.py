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
from .bairro_resolver import (
    BairroPreprocess,
    apply_bairro_correction_to_answer,
    message_has_territorial_intent,
    preprocess_bairro_turn,
    resolve_bairro,
    extract_location_term,
    format_bairro_disambiguation,
    should_resolve_bairro,
    try_pessoas_bairro_metric,
)
from .canonical_metrics import try_canonical_metric
from .kb_client import query_knowledge_base
from .llm import chat_completion
from .maestro_router import resolve_turn_route
from .planning_metrics import try_planning_demand_metric
from .sql_agent import SqlAgentResult, run_sql_agent

ORCHESTRATOR_PLAN_SYSTEM = """Você é VigIA, orquestrador do assistente de vigilância socioassistencial municipal.

Analise a mensagem atual e o histórico da conversa.

**mode = "chat"** quando:
- Cumprimentos, agradecimentos, conversa geral
- Dúvidas sobre políticas, conceitos SUAS, orientações (use contexto RAG se fornecido)
- Não há pedido de número, total, percentual ou cruzamento de dados

**mode = "data"** quando:
- O usuário pede quantidade, total, percentual, listagem agregada
- Perguntas sobre CADU, PBF, SISC, CRAS, famílias, pessoas, renda, deficiência, **IVS/IVCAD (índices de vulnerabilidade)**, etc.
- **Planejamento** (implantar novo serviço, qual CRAS indicar por demanda no CADU) — use CADU territorial, NÃO matrícula SISC existente
- Follow-up numérico ("dessas", "entre elas", "e quantas têm...") — reformule com o contexto anterior, sem arrastar bairro de turnos anteriores se a pergunta mudou de assunto

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

- Trate o usuário pelo primeiro nome (uma vez só)
- Responda APENAS o que foi perguntado — sem explicações extras, sem metodologia, sem fontes técnicas
- 1–2 frases diretas com o número principal
- Tom cordial e profissional
- NÃO liste outros CRAS/bairros salvo se o usuário pediu ranking ou comparação
- NÃO corrija grafia de bairro nem mencione bairro se a pergunta não citou território
- NÃO adicione parágrafo sobre PBF, SISC, CADU ou definições de indicador
- NÃO mostre SQL, JSON, nomes de campos/tabelas nem siglas de banco
- Use APENAS números presentes nos resultados fornecidos
- Se o resultado for desdobramento por CRAS pedido explicitamente: liste na ordem numérica
"""

_BOILERPLATE_TRAILERS = (
    re.compile(
        r"(?:\n\n|\.\s+)Esse número representa[^.!?]*[.!?]?\s*$",
        re.I | re.S,
    ),
    re.compile(
        r"(?:\n\n|\.\s+)Esse indicador (?:representa|mostra|reflete)[^.!?]*[.!?]?\s*$",
        re.I | re.S,
    ),
    re.compile(
        r"(?:\n\n|\.\s+)Isso (?:representa|corresponde|indica)[^.!?]*transferência de renda[^.!?]*[.!?]?\s*$",
        re.I | re.S,
    ),
    re.compile(
        r"(?:\n\n|\.\s+)Isso significa que[^.!?]*[.!?]?\s*$",
        re.I | re.S,
    ),
)


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


def _trim_answer_boilerplate(answer: str) -> str:
    text = answer.strip()
    for _ in range(4):
        prev = text
        for pat in _BOILERPLATE_TRAILERS:
            text = pat.sub("", text).strip()
        if text == prev:
            break
    return re.sub(r"\n{3,}", "\n\n", text).strip()


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
    return _trim_answer_boilerplate(chat_completion(messages, temperature=0.5, role="orch").strip())


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
        return _trim_answer_boilerplate(chat_completion(fail_messages, temperature=0.4, role="orch").strip())

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
    return _trim_answer_boilerplate(chat_completion(messages, temperature=0.35, role="orch").strip())


def _personalize_canonical(answer: str, user: User) -> str:
    first = _first_name(user.name)
    if not first or answer.startswith(first):
        return answer
    if answer.startswith("Há "):
        return f"{first}, {answer[0].lower()}{answer[1:]}"
    if answer.startswith("O CRAS"):
        return f"{first}, {answer[0].lower()}{answer[1:]}"
    if answer.startswith("**Serviço"):
        return f"{first}, {answer}"
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
    first_name = _first_name(user.name)
    route = resolve_turn_route(message, transcript)

    if route.primary == "planning":
        planning = try_planning_demand_metric(
            conn, message, transcript, user_first_name=first_name
        )
        if planning:
            return {
                **planning,
                "answer": _trim_answer_boilerplate(planning["answer"]),
            }
        sql_result = run_sql_agent(
            conn, db, message, thread_brief=route.thread_brief
        )
        if sql_result.ok:
            answer = _finalize_data_reply(
                message, transcript, message, sql_result, user_block
            )
            return {
                "answer": _trim_answer_boilerplate(answer),
                "sql": sql_result.sql,
                "row_count": sql_result.row_count,
                "preview": sql_result.preview,
                "mode": "data",
            }

    if route.skip_bairro_preprocess:
        bairro_pre = BairroPreprocess(message=message)
    else:
        bairro_pre = preprocess_bairro_turn(conn, first_name, message, transcript)
    if bairro_pre.early_response:
        return {
            **bairro_pre.early_response,
            "answer": _trim_answer_boilerplate(bairro_pre.early_response["answer"]),
        }
    message = bairro_pre.message
    bairro_resolution = bairro_pre.resolution

    pessoas_bairro = try_pessoas_bairro_metric(conn, message, first_name)
    if pessoas_bairro:
        return {
            **pessoas_bairro,
            "answer": _trim_answer_boilerplate(pessoas_bairro["answer"]),
        }

    # Métricas canônicas (SISC×CADU, CRAS, PBF) têm prioridade — sempre com SQL explícito
    canonical = try_canonical_metric(
        conn,
        message,
        transcript,
        user_first_name=first_name,
        block_sisc=route.block_sisc,
    )
    if canonical:
        answer = canonical["answer"]
        if canonical.get("metric") == "cadu_familias_por_cras":
            answer = _cras_answer_with_context(
                canonical.get("preview") or [],
                user,
                municipio_block,
            )
        elif canonical.get("metric", "").startswith("geo_"):
            answer = _personalize_canonical(answer, user)
        elif canonical.get("metric", "").startswith("ivs_"):
            pass
        elif canonical.get("metric", "").startswith("planning_"):
            pass
        elif canonical.get("mode") == "disambiguation":
            answer = _personalize_canonical(answer, user)
        elif canonical.get("source") == "vig.mvw_sisc_qualificado":
            answer = _personalize_canonical(answer, user)
        skip_bairro_wrap = (
            canonical.get("metric", "").startswith(("planning_", "ivs_"))
            or canonical.get("mode") == "disambiguation"
        )
        if canonical.get("mode") != "disambiguation" and not skip_bairro_wrap:
            answer = apply_bairro_correction_to_answer(
                answer, bairro_resolution, first_name, message=message
            )
        return {
            "answer": _trim_answer_boilerplate(answer),
            "sql": canonical.get("sql"),
            "row_count": canonical.get("row_count", 0),
            "preview": canonical.get("preview") or [],
            "mode": canonical.get("mode", "canonical"),
        }

    plan = _plan_turn(message, transcript, rag_block, user_block)

    if plan["mode"] == "chat":
        answer = _chat_reply(message, transcript, rag_block, user_block)
        return {
            "answer": _trim_answer_boilerplate(answer),
            "sql": None,
            "row_count": 0,
            "preview": [],
            "mode": "chat",
        }

    sql_question = plan.get("sql_question") or message.strip()
    if (
        bairro_resolution
        and bairro_resolution.canonical
        and message_has_territorial_intent(message)
    ):
        sql_question = (
            f"{sql_question}\n\n"
            f"[Bairro territorial confirmado: {bairro_resolution.canonical}. "
            f"Filtre com lower(btrim(f.bairro::text)) = lower('{bairro_resolution.canonical.replace(chr(39), '')}').]"
        )

    sql_result = run_sql_agent(
        conn, db, sql_question, thread_brief=route.thread_brief
    )
    if sql_result.ok and sql_result.formatted_answer:
        answer = _cras_answer_with_context(sql_result.rows, user, municipio_block)
    elif sql_result.ok and sql_result.row_count == 0:
        term = extract_location_term(message)
        if term and should_resolve_bairro(message, term):
            resolution = resolve_bairro(conn, term)
            if resolution.status == "multiple":
                return {
                    "answer": _trim_answer_boilerplate(
                        format_bairro_disambiguation(resolution, first_name)
                    ),
                    "sql": None,
                    "row_count": 0,
                    "preview": resolution.matches,
                    "mode": "disambiguation",
                }
        answer = _finalize_data_reply(message, transcript, sql_question, sql_result, user_block)
    else:
        term = extract_location_term(message)
        if term and should_resolve_bairro(message, term):
            resolution = resolve_bairro(conn, term)
            if resolution.status == "multiple":
                return {
                    "answer": _trim_answer_boilerplate(
                        format_bairro_disambiguation(resolution, first_name)
                    ),
                    "sql": None,
                    "row_count": 0,
                    "preview": resolution.matches,
                    "mode": "disambiguation",
                }
        answer = _finalize_data_reply(message, transcript, sql_question, sql_result, user_block)

    answer = apply_bairro_correction_to_answer(
        answer, bairro_resolution, first_name, message=message
    )

    return {
        "answer": _trim_answer_boilerplate(answer),
        "sql": sql_result.sql,
        "row_count": sql_result.row_count,
        "preview": sql_result.preview,
        "mode": "data",
        "error": sql_result.error if not sql_result.ok else None,
    }
