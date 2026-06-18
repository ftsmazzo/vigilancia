"""VigIA — orquestrador multi-especialista.

Pipeline autônomo (sem LangChain/CrewAI):
  1. Reformulador → QueryTaskSpec (intenção tipada)
  2. Maestro → roteamento por especialista
  3. Executor composicional / canônico / AgenteSQL (com verificador)
  4. Síntese analítica — só quando response_mode exige interpretação

Especialistas:
  - Políticas, Município, Vigilância (CADU + camadas), Síntese
"""

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
from .cadu_pessoas_metrics import try_cadu_pessoas_recorte_metric
from .cadu_spec_executor import try_execute_cadu_spec
from .answer_trim import trim_answer_boilerplate
from .analyst_agent import interpret_evidence
from .canonical_metrics import try_canonical_metric
from .conversation_intent import (
    build_thread_brief,
    is_planning_coverage_followup,
    planning_thread_active,
)
from .evidence import pack_from_canonical, pack_from_sql
from .kb_client import query_knowledge_base
from .llm import chat_completion
from .maestro_router import resolve_turn_route
from .municipio_agent import run_municipio_agent
from .planning_metrics import try_planning_demand_metric
from .policy_agent import run_policy_agent
from .query_task_spec import (
    MetricKind,
    extract_task_spec,
    legacy_cadu_recorte_covers_spec,
    merge_task_spec_with_session,
    verify_sql_covers_spec,
)
from .session_context import SessionContext, resolve_effective_question
from .sql_agent import SqlAgentResult, run_sql_agent

ORCHESTRATOR_PLAN_SYSTEM = """Você é VigIA, orquestrador do assistente de vigilância socioassistencial municipal.

Especialistas (você roteia; SIBEC/IVS/SISC são camadas de Vigilância no tronco CADU, não agentes):
- **Políticas e Normativas** — conceitos SUAS, regras de programas, legislação
- **Dados do Município** — rede local cadastrada, caracterização institucional
- **Dados de Vigilância** — números do CADU e camadas por codigo_familiar/CPF/NIS (SISC, IVS, SIBEC, geo)

Analise a mensagem atual e o histórico da conversa.

**mode = "chat"** quando:
- Cumprimentos, agradecimentos, conversa geral
- Dúvidas sobre políticas, conceitos SUAS, orientações (use contexto RAG se fornecido)
- Não há pedido de número, total, percentual ou cruzamento de dados

**mode = "data"** quando:
- O usuário pede quantidade, total, percentual, listagem agregada
- Perguntas sobre CADU, PBF, SISC, CRAS, famílias, pessoas, renda, deficiência, **IVS/IVCAD**, **manutenções SIBEC**, etc.
- **Follow-up curto** ("e no 5?", "e no CRAS 3") — use o histórico: mantenha assunto e filtros (ex.: mulheres) e troque só CRAS/bairro
- **Planejamento** (implantar novo serviço) — use CADU territorial, NÃO matrícula SISC existente
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
    return trim_answer_boilerplate(answer)


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


def _answer_via_analyst(
    message: str,
    result: dict[str, Any],
    *,
    conn: Connection,
    db: Session,
    transcript: list[dict[str, str]],
    user_first_name: str = "",
    thread_brief: str = "",
    municipio_block: str = "",
    rag_block: str = "",
) -> str:
    if not result.get("use_analyst") and result.get("answer", "").strip():
        return result["answer"]
    brief = thread_brief or build_thread_brief(message, transcript)
    pack = pack_from_canonical(message, result, thread_brief=brief)
    return interpret_evidence(
        pack,
        user_first_name=user_first_name,
        conn=conn,
        db=db,
        municipio_block=municipio_block,
        rag_block=rag_block,
    )


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
    *,
    session_id: str | None = None,
    session_context: SessionContext | None = None,
) -> dict[str, Any]:
    """
    Pipeline VigIA:
    Maestro → Políticas | Município | Vigilância (CADU + camadas) → Síntese analítica
    """
    effective_message, merged_ctx = resolve_effective_question(
        message,
        transcript,
        session_context,
    )
    task_spec = merge_task_spec_with_session(
        extract_task_spec(effective_message, transcript, session_context=merged_ctx),
        merged_ctx,
        transcript,
    )
    municipio_block = load_context_prompt(db)
    user_block = _user_context_block(user, municipio_block)
    rag_block = query_knowledge_base(effective_message)
    first_name = _first_name(user.name)
    route = resolve_turn_route(
        message,
        transcript,
        session_context=merged_ctx,
        effective_message=effective_message,
    )
    data_message = route.effective_message or effective_message

    if route.primary == "planning":
        policy_rag = query_knowledge_base(
            f"{data_message} SCFV SUAS tipificação serviço convivência PAIF atualização cadastral"
        )
        if policy_rag:
            rag_block = (
                f"{rag_block}\n\n---\n\n{policy_rag[:4000]}"
                if rag_block
                else policy_rag[:6000]
            )
        planning = try_planning_demand_metric(
            conn, data_message, transcript, db=db, user_first_name=first_name
        )
        if planning:
            answer = _answer_via_analyst(
                data_message,
                planning,
                conn=conn,
                db=db,
                transcript=transcript,
                user_first_name=first_name,
                thread_brief=route.thread_brief,
                municipio_block=municipio_block,
                rag_block=rag_block,
            )
            return {
                **planning,
                "answer": _trim_answer_boilerplate(answer),
                "effective_message": effective_message,
            }
        sql_result = run_sql_agent(
            conn, db, data_message, thread_brief=route.thread_brief
        )
        if sql_result.ok:
            pack = pack_from_sql(data_message, sql_result, thread_brief=route.thread_brief)
            answer = interpret_evidence(
                pack,
                user_first_name=first_name,
                conn=conn,
                db=db,
                municipio_block=municipio_block,
                rag_block=rag_block,
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

    cadu_spec = try_execute_cadu_spec(
        conn, task_spec, data_message, user_first_name=first_name
    )
    if cadu_spec:
        if cadu_spec.get("mode") == "disambiguation":
            return {
                **cadu_spec,
                "answer": _trim_answer_boilerplate(cadu_spec["answer"]),
                "effective_message": effective_message,
                "task_spec": task_spec.to_dict(),
            }
        if cadu_spec.get("use_analyst"):
            answer = _answer_via_analyst(
                message,
                cadu_spec,
                conn=conn,
                db=db,
                transcript=transcript,
                user_first_name=first_name,
                thread_brief=route.thread_brief,
                municipio_block=municipio_block,
                rag_block=rag_block,
            )
        else:
            answer = cadu_spec["answer"]
        return {
            "answer": _trim_answer_boilerplate(answer),
            "sql": cadu_spec.get("sql"),
            "row_count": cadu_spec.get("row_count", 0),
            "preview": cadu_spec.get("preview") or [],
            "mode": cadu_spec.get("mode", "canonical"),
            "effective_message": effective_message,
            "task_spec": task_spec.to_dict(),
            "filters_applied": cadu_spec.get("filters_applied"),
        }

    if not task_spec.person_recorte and not task_spec.age_range:
        pessoas_bairro = try_pessoas_bairro_metric(conn, data_message, first_name)
        if pessoas_bairro:
            return {
                **pessoas_bairro,
                "answer": _trim_answer_boilerplate(pessoas_bairro["answer"]),
                "task_spec": task_spec.to_dict(),
            }

    cadu_pessoas = None
    if legacy_cadu_recorte_covers_spec(task_spec):
        cadu_pessoas = try_cadu_pessoas_recorte_metric(
            conn, data_message, user_first_name=first_name
        )
    if cadu_pessoas:
        return {
            **cadu_pessoas,
            "answer": _trim_answer_boilerplate(cadu_pessoas["answer"]),
        }

    if route.primary == "policy":
        policy = run_policy_agent(
            message,
            transcript,
            user_first_name=first_name,
            municipio_block=municipio_block,
        )
        return {
            "answer": _trim_answer_boilerplate(policy.answer),
            "sql": None,
            "row_count": 0,
            "preview": [],
            "mode": "policy",
            "agent": "policy",
        }

    if route.primary == "municipio":
        municipio = run_municipio_agent(
            conn,
            db,
            message,
            transcript,
            user_first_name=first_name,
        )
        return {
            "answer": _trim_answer_boilerplate(municipio.answer),
            "sql": None,
            "row_count": 0,
            "preview": [],
            "mode": "municipio",
            "agent": "municipio",
        }

    # Métricas canônicas (SISC×CADU, CRAS, PBF) têm prioridade — sempre com SQL explícito
    canonical = try_canonical_metric(
        conn,
        data_message,
        transcript,
        db=db,
        user_first_name=first_name,
        block_sisc=route.block_sisc,
    )
    if canonical:
        answer = _answer_via_analyst(
            message,
            canonical,
            conn=conn,
            db=db,
            transcript=transcript,
            user_first_name=first_name,
            thread_brief=route.thread_brief,
            municipio_block=municipio_block,
            rag_block=rag_block,
        )
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
            "effective_message": effective_message,
        }

    plan = _plan_turn(data_message, transcript, rag_block, user_block)

    if plan["mode"] == "chat" and (
        planning_thread_active(transcript)
        or is_planning_coverage_followup(data_message, transcript)
    ):
        retry = try_canonical_metric(
            conn,
            data_message,
            transcript,
            db=db,
            user_first_name=first_name,
            block_sisc=False,
        )
        if retry:
            answer = _answer_via_analyst(
                message,
                retry,
                conn=conn,
                db=db,
                transcript=transcript,
                user_first_name=first_name,
                thread_brief=route.thread_brief,
                municipio_block=municipio_block,
                rag_block=rag_block,
            )
            return {
                "answer": _trim_answer_boilerplate(answer),
                "sql": retry.get("sql"),
                "row_count": retry.get("row_count", 0),
                "preview": retry.get("preview") or [],
                "mode": retry.get("mode", "canonical"),
            }

    if plan["mode"] == "chat":
        answer = _chat_reply(message, transcript, rag_block, user_block)
        return {
            "answer": _trim_answer_boilerplate(answer),
            "sql": None,
            "row_count": 0,
            "preview": [],
            "mode": "chat",
        }

    sql_question = plan.get("sql_question") or data_message.strip()
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

    task_spec_block = task_spec.to_sql_agent_block()
    sql_result = run_sql_agent(
        conn,
        db,
        sql_question,
        thread_brief=route.thread_brief,
        task_spec_block=task_spec_block,
    )
    if sql_result.ok and sql_result.sql:
        verified, missing = verify_sql_covers_spec(sql_result.sql, task_spec)
        if not verified and missing:
            retry_block = (
                f"{task_spec_block}\n\n"
                f"### Correção obrigatória\n"
                f"A consulta anterior OMITIU: {', '.join(missing)}. "
                f"Inclua TODOS os filtros da especificação."
            )
            sql_result = run_sql_agent(
                conn,
                db,
                sql_question,
                thread_brief=route.thread_brief,
                task_spec_block=retry_block,
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
        if sql_result.ok:
            pack = pack_from_sql(message, sql_result, thread_brief=route.thread_brief)
            if task_spec.is_simple_data_response():
                answer = _finalize_data_reply(
                    message, transcript, sql_question, sql_result, user_block
                )
            else:
                answer = interpret_evidence(
                    pack,
                    user_first_name=first_name,
                    conn=conn,
                    db=db,
                    municipio_block=municipio_block,
                    rag_block=rag_block,
                )
        else:
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
        "effective_message": effective_message,
        "task_spec": task_spec.to_dict(),
    }
