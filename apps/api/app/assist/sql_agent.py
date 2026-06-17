"""AgenteSQL — especialista NL→SQL (schema vig.mvw_*, execução com retry)."""

from __future__ import annotations

import json
import re
from dataclasses import dataclass, field
from datetime import date, datetime
from decimal import Decimal
from typing import Any

from sqlalchemy import text
from sqlalchemy.engine import Connection
from sqlalchemy.orm import Session

from .cras_breakdown import format_cras_breakdown_answer, format_cras_breakdown_summary, is_cras_breakdown
from ..vigilance.cadu_classificacao import tem_deficiencia_expr
from .llm import AssistLlmError, chat_completion
from .dictionary import build_dictionary_prompt
from .data_joins import build_data_agent_context
from .schema_context import CATALOG_STATIC
from .schema_introspection import build_live_schema_markdown
from .sql_guard import SqlGuardError, wrap_limit
from .sql_sanitize import sanitize_llm_sql

SQL_AGENT_SYSTEM = """Você é o **Especialista em Dados de Vigilância** (AgenteSQL) — gera SQL PostgreSQL somente leitura.

## Tronco CADU (obrigatório entender antes de qualquer JOIN)
- vig.mvw_familia f — 1 linha/família; chave codigo_familiar; território (num_cras, bairro, geo)
- vig.mvw_pessoas p — 1 linha/pessoa; chaves codigo_familiar, num_nis, num_cpf
- Toda camada de Vigilância (SISC, IVS, SIBEC manutenções, domicílio) liga ao CADU por codigo_familiar
- Pessoa individual: p → f via codigo_familiar; ou localizar por num_cpf / num_nis

## Visões de Vigilância (schema vig e core)
- vig.mvw_familia (f) — famílias CADU + territorialização
- vig.mvw_pessoas (p) — pessoas CADU
- vig.mvw_familia_domicilio (d) — moradia/vulnerabilidades; d.codigo_familiar = f.codigo_familiar
- vig.mvw_sisc_qualificado (s) — SISC × CADU; s.codigo_familiar ou s.nis_norm = p.num_nis
- vig.mvw_sibec_manut_familia_mes (m) — manutenções PBF (bloqueio/cancelamento/reversão); m.codigo_familiar; competencia AAAAMM; teve_bloqueio, teve_cancelamento, teve_reversao
- core.mvw_ivs_familia (i) — IVS/IVCAD; i.codigo_familiar = f.codigo_familiar

Regras obrigatórias:
- Apenas SELECT; uma instrução; sem ponto e vírgula no final.
- IVS/IVCAD: filtre i.elegivel_ivs; território via f.bairro e f.num_cras; dimensões idx_nc, idx_dpi, idx_dca, idx_tqa, idx_dr, idx_ch; composto i.ivs.
- Contagem de famílias: COUNT(DISTINCT f.codigo_familiar) ou COUNT(*) em mvw_sibec_manut_familia_mes (já 1 linha/família/mês).
- Contagem de pessoas: COUNT(p.cadu_row_id) ou COUNT(*).
- Mulher: p.cod_sexo = '2'. Homem: p.cod_sexo = '1'.
- **Pessoa com deficiência (PCD)**: {tem_deficiencia_expr("p")} — campos p.cod_deficiencia e p.ind_def_* (texto '1'/'0', ver dicionário p.cod_deficiencia_memb).
- Criança até 6 anos: p.idade <= 6 AND p.idade IS NOT NULL.
- Folha PBF (KPI painel): COALESCE(f.marc_pbf, false) = true.
- Marcador PBF no CADU (≠ folha): btrim(COALESCE(f.marc_pbf_cadu::text,'')) IN ('1','01','sim','s','true').
- SIBEC manutenções ≠ folha PBF — use m.teve_* e m.competencia, não marc_pbf.
- Campos ind_* / marc_* em pessoas são texto ('1'/'0') — NUNCA = true/false.
- SISC / convivência: vig.mvw_sisc_qualificado (s), NÃO p.ind_atend_cras.
- SISC vinculado ao CADU: s.classificacao_vinculo = 'vinculado_cadu'.
- CRAS territorial CADU: f.num_cras, f.nom_cras. CRAS do SISC: s.cras_codigo, s.cras_nome.
- **Bairro territorial (geo)**: f.bairro via CEP × raw.geo__tbl_geo (f.tem_geo). NUNCA filtre f.bairro_cadu salvo pedido explícito de "bairro no CADU".
- Filtro por bairro: btrim(f.bairro::text) ILIKE '%termo%' (parcial, case-insensitive).
- Filtro por CRAS territorial: btrim(f.num_cras::text) = '1' (texto '1' a '12').
- Desdobramento por CRAS (CADU): GROUP BY f.num_cras, f.nom_cras; ORDER BY num_cras numérico 1→12 (NULL por último).
- CRAS 1 = Central (Centro) — matrícula SISC "CRAS Centro" equivale ao CRAS 1 territorial.
- CRAS 9 = Bonfim Paulista. Famílias com num_cras vazio/null = sem referência territorial (informe aparte).
- **Planejamento SCFV (implantar novo serviço)**: p JOIN f — demanda por f.num_cras. PROIBIDO usar mvw_sisc_qualificado.
- **Matrícula SISC existente**: somente quando o usuário pergunta quem já está atendido/matriculado.
- Sempre que cruzar território com pessoa/família/IVS/SIBEC: JOIN via codigo_familiar conforme catálogo abaixo.
- Se não houver dados suficientes para montar a query, retorne sql vazio e justificativa clara.

Responda APENAS JSON válido: {"sql": "SELECT ...", "justificativa": "..."}
"""

MAX_SQL_ATTEMPTS = 3


@dataclass
class SqlAgentResult:
    ok: bool
    sql: str | None = None
    rows: list[dict[str, Any]] = field(default_factory=list)
    summary: str = ""
    row_count: int = 0
    preview: list[dict[str, Any]] = field(default_factory=list)
    error: str | None = None
    formatted_answer: str | None = None


def _json_safe(value: Any) -> Any:
    if isinstance(value, Decimal):
        return float(value)
    if isinstance(value, (datetime, date)):
        return value.isoformat()
    return value


def _rows_to_preview(rows: list[dict[str, Any]], max_rows: int = 8) -> list[dict[str, Any]]:
    return [{k: _json_safe(v) for k, v in row.items()} for row in rows[:max_rows]]


def _execute_query(conn: Connection, sql: str) -> list[dict[str, Any]]:
    conn.execute(text("SET LOCAL statement_timeout = '20000'"))
    result = conn.execute(text(sql))
    return [dict(row._mapping) for row in result]


def _extract_sql_payload(llm_content: str) -> tuple[str, str]:
    content = llm_content.strip()
    sql = ""
    justificativa = ""
    if content.startswith("{"):
        try:
            payload = json.loads(content)
            sql = (payload.get("sql") or payload.get("query") or "").strip()
            justificativa = (payload.get("justificativa") or payload.get("nota") or "").strip()
        except json.JSONDecodeError:
            pass
    if not sql:
        m = re.search(r"```(?:sql)?\s*(select[\s\S]+?)```", content, re.I)
        if m:
            sql = m.group(1).strip()
        elif re.match(r"^select\b", content, re.I):
            sql = content
    if not sql and not justificativa:
        raise AssistLlmError("AgenteSQL não retornou SQL válido.")
    return sql, justificativa


def _summarize_rows(rows: list[dict[str, Any]]) -> str:
    if not rows:
        return "Nenhum resultado (0 linhas)."
    if is_cras_breakdown(rows):
        return format_cras_breakdown_summary(rows)
    if len(rows) == 1 and len(rows[0]) == 1:
        key, val = next(iter(rows[0].items()))
        return f"{key} = {val}"
    preview = _rows_to_preview(rows, max_rows=50)
    return json.dumps(preview, ensure_ascii=False, default=str)


def _build_sql_context(conn: Connection, db: Session | None, *, thread_brief: str = "") -> str:
    parts = [
        CATALOG_STATIC.strip(),
        build_live_schema_markdown(conn),
        build_data_agent_context(conn, thread_brief=thread_brief),
    ]
    try:
        block = build_dictionary_prompt()
        if block:
            parts.append(block)
    except Exception:
        pass
    return "\n\n".join(parts)


def run_sql_agent(
    conn: Connection,
    db: Session | None,
    question: str,
    *,
    thread_brief: str = "",
) -> SqlAgentResult:
    """Recebe pergunta limpa do Orquestrador; devolve número/resultado ou erro."""
    context = _build_sql_context(conn, db, thread_brief=thread_brief)
    user_content = question.strip()
    if thread_brief.strip():
        user_content = f"{user_content}\n\n### Contexto da conversa\n{thread_brief.strip()}"

    messages: list[dict[str, str]] = [
        {"role": "system", "content": SQL_AGENT_SYSTEM + "\n\n" + context},
        {"role": "user", "content": user_content},
    ]

    last_error: str | None = None
    last_sql: str | None = None

    for _attempt in range(MAX_SQL_ATTEMPTS):
        raw = chat_completion(messages, json_mode=True, temperature=0.05, role="sql")
        try:
            raw_sql, justificativa = _extract_sql_payload(raw)
        except AssistLlmError as exc:
            last_error = str(exc)
            messages.append({"role": "assistant", "content": raw})
            messages.append(
                {
                    "role": "user",
                    "content": f"Resposta inválida: {exc}. Retorne JSON com sql SELECT válido.",
                }
            )
            continue

        if not raw_sql:
            return SqlAgentResult(
                ok=False,
                error=justificativa or "AgenteSQL não gerou consulta para esta pergunta.",
            )

        try:
            safe_sql = wrap_limit(sanitize_llm_sql(raw_sql), limit=500)
            rows = _execute_query(conn, safe_sql)
            preview = _rows_to_preview(rows)
            formatted = None
            if is_cras_breakdown(rows):
                formatted = format_cras_breakdown_answer(rows)
            return SqlAgentResult(
                ok=True,
                sql=safe_sql,
                rows=rows,
                summary=_summarize_rows(rows),
                row_count=len(rows),
                preview=preview,
                formatted_answer=formatted,
            )
        except (SqlGuardError, Exception) as exc:
            last_error = str(exc)
            last_sql = raw_sql
            messages.append({"role": "assistant", "content": raw})
            messages.append(
                {
                    "role": "user",
                    "content": (
                        f"A consulta falhou na validação ou execução: {exc}\n"
                        "Corrija o SQL (somente vig.mvw_*) e retorne JSON com sql corrigido."
                    ),
                }
            )

    return SqlAgentResult(
        ok=False,
        sql=last_sql,
        error=last_error or "Não foi possível executar a consulta após várias tentativas.",
    )
