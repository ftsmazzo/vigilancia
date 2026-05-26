"""Orquestração: pergunta → SQL → execução → resposta de vigilância."""

from __future__ import annotations

import json
import re
from datetime import date, datetime
from decimal import Decimal
from typing import Any

from sqlalchemy import text
from sqlalchemy.engine import Connection
from sqlalchemy.orm import Session

from ..models import User
from .llm import AssistLlmError, AssistNotConfiguredError, chat_completion
from .memory import append_message, get_or_create_session, load_history
from .schema_context import build_schema_context
from .sql_guard import SqlGuardError, wrap_limit

SQL_SYSTEM = """Você gera SQL PostgreSQL somente leitura para vigilância socioassistencial municipal.
Responda APENAS com JSON válido: {"sql": "SELECT ...", "nota": "breve justificativa"}.
Regras:
- Apenas SELECT; uma instrução; sem ponto e vírgula no final.
- Use somente: vig.mvw_familia (alias f), vig.mvw_pessoas (p), vig.mvw_familia_domicilio (d), vig.mvw_sisc_qualificado (s).
- Contagens de famílias: COUNT(DISTINCT f.codigo_familiar).
- PBF na família: f.marc_pbf = true OR f.marc_pbf_cadu = true (confirme colunas no catálogo).
- Mulher: p.cod_sexo = '2'. Criança até 6 anos: p.idade <= 6 AND p.idade IS NOT NULL.
- Se a pergunta referir filtro anterior ("dessas", "entre elas"), aplique os mesmos filtros da conversa.
- Prefira resultados agregados (COUNT, SUM) em vez de listar linhas.
- CRAS: f.num_cras ou f.nom_cras ILIKE '%texto%'.
"""

ANSWER_SYSTEM = """Você é analista de vigilância socioassistencial (SUAS/CADU/PBF/SISC).
Com base na pergunta do usuário, na SQL executada e nos resultados, redija resposta técnica em português do Brasil:
- Informe o número principal com clareza.
- Contextualize em uma frase (o que o indicador significa operacionalmente).
- Se houver incerteza ou dados vazios, diga explicitamente.
- Não invente números que não estejam nos resultados.
- Seja conciso (2–4 parágrafos curtos no máximo)."""


def _json_safe(value: Any) -> Any:
    if isinstance(value, Decimal):
        return float(value)
    if isinstance(value, (datetime, date)):
        return value.isoformat()
    return value


def _rows_to_preview(rows: list[dict[str, Any]], max_rows: int = 8) -> list[dict[str, Any]]:
    out: list[dict[str, Any]] = []
    for row in rows[:max_rows]:
        out.append({k: _json_safe(v) for k, v in row.items()})
    return out


def _execute_query(conn: Connection, sql: str) -> list[dict[str, Any]]:
    conn.execute(text("SET LOCAL statement_timeout = '20000'"))
    result = conn.execute(text(sql))
    return [dict(row._mapping) for row in result]


def _extract_sql(llm_content: str) -> str:
    content = llm_content.strip()
    if content.startswith("{"):
        try:
            payload = json.loads(content)
            sql = payload.get("sql") or payload.get("query")
            if isinstance(sql, str) and sql.strip():
                return sql.strip()
        except json.JSONDecodeError:
            pass
    m = re.search(r"```(?:sql)?\s*(select[\s\S]+?)```", content, re.I)
    if m:
        return m.group(1).strip()
    if re.match(r"^select\b", content, re.I):
        return content
    raise AssistLlmError("O modelo não retornou SQL válido.")


def chat_turn(
    db: Session,
    user: User,
    message: str,
    session_id: str | None,
) -> dict[str, Any]:
    message = message.strip()
    if not message:
        raise ValueError("Mensagem vazia.")

    session = get_or_create_session(db, user, session_id)
    history = load_history(db, session.id)
    append_message(db, session.id, "user", message)
    transcript = history + [{"role": "user", "content": message}]

    with db.bind.connect() as conn:
        schema = build_schema_context(conn, db)

        sql_messages: list[dict[str, str]] = [
            {"role": "system", "content": SQL_SYSTEM + "\n\n" + schema},
            *transcript,
        ]

        raw_sql_response = chat_completion(sql_messages, json_mode=True)
        raw_sql = _extract_sql(raw_sql_response)

        try:
            safe_sql = wrap_limit(raw_sql, limit=500)
        except SqlGuardError as exc:
            answer = (
                f"Não consegui validar a consulta gerada: {exc}. "
                "Reformule a pergunta ou peça um indicador mais simples (ex.: total de famílias com PBF)."
            )
            append_message(db, session.id, "assistant", answer, sql_executed=raw_sql)
            return {
                "session_id": session.id,
                "answer": answer,
                "sql": raw_sql,
                "row_count": 0,
                "preview": [],
                "error": str(exc),
            }

        try:
            rows = _execute_query(conn, safe_sql)
        except Exception as exc:
            answer = (
                f"A consulta foi gerada mas falhou na execução: {exc}. "
                "Tente especificar CRAS, PBF ou faixa etária de outra forma."
            )
            append_message(db, session.id, "assistant", answer, sql_executed=safe_sql)
            return {
                "session_id": session.id,
                "answer": answer,
                "sql": safe_sql,
                "row_count": 0,
                "preview": [],
                "error": str(exc),
            }

    preview = _rows_to_preview(rows)
    results_text = json.dumps(preview, ensure_ascii=False, default=str)

    answer_messages: list[dict[str, str]] = [
        {"role": "system", "content": ANSWER_SYSTEM},
        *transcript,
        {
            "role": "user",
            "content": (
                f"Pergunta: {message}\n\nSQL:\n{safe_sql}\n\n"
                f"Resultados ({len(rows)} linha(s)):\n{results_text}"
            ),
        },
    ]
    answer = chat_completion(answer_messages, temperature=0.3).strip()
    append_message(db, session.id, "assistant", answer, sql_executed=safe_sql)

    return {
        "session_id": session.id,
        "answer": answer,
        "sql": safe_sql,
        "row_count": len(rows),
        "preview": preview,
    }
