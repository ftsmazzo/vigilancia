"""Fase 1 — Maestro de especificação: LLM interpreta turno, heurística valida depois.

Substitui cascata de reformuladores regex para follow-ups ambíguos.
Determinístico só onde a confiança é alta (ex.: «e no CRAS 5?» em session_context).
"""

from __future__ import annotations

import json
import re
from typing import Any

from .llm import AssistNotConfiguredError, chat_completion
from .session_context import SessionContext

_SHORT = 100
_COHORT = re.compile(
    r"nessa\s+faixa|faixa\s+et[aá]ria|dess[aeo]s|dest[aeo]s|entre\s+(?:eles|elas)|"
    r"por\s+cada|e\s+idosos|e\s+crian|e\s+mulher|e\s+homem",
    re.I,
)
_EXPLICIT_AGE = re.compile(r"\d{1,3}\s*(?:a|-|á)\s*\d{1,3}\s*(?:anos)?", re.I)

PLANNER_SYSTEM = """Você é o planejador de consultas do VigIA (vigilância socioassistencial municipal).

Recebe a mensagem atual, memória da sessão e histórico. Produza UM pedido de dado claro.

Regras:
- Follow-ups curtos recombinam memória + intenção nova (ex.: após crianças 7–15 por CRAS, «E idosos?» → idosos ≥60 por CRAS, SEM herdar 7–15).
- Coorte («nessa faixa etária», «desses homens») HERDA faixa/filtros da sessão.
- «por CRAS», «distribuição», «qual CRAS tem mais» → breakdown = cras.
- Famílias recebendo Bolsa Família / PBF (folha marc_pbf) → requires_pbf true.
- **SIBEC bloqueio/cancelamento/manutenção** → NÃO é PBF folha; requires_pbf false; mencione SIBEC na pergunta reformulada.
- **Raça/cor/etnia** → incluir na pergunta reformulada (cod_raca_cor_pessoa).
- NÃO invente números. NÃO escreva SQL.

Responda APENAS JSON:
{
  "effective_question": "pergunta completa em português",
  "subject": "crianças|idosos|mulheres|homens|famílias|",
  "entity": "pessoa|familia",
  "age_min": null,
  "age_max": null,
  "breakdown": "cras|none",
  "requires_pbf": false,
  "cohort_followup": false
}
"""


def needs_llm_planner(
    message: str,
    ctx: SessionContext,
    transcript: list[dict[str, str]] | None,
) -> bool:
    """Turnos ambíguos vão ao LLM; perguntas explícitas ficam na heurística."""
    text = (message or "").strip()
    if not text:
        return False
    if _COHORT.search(text):
        return True
    if ctx.has_data_thread() and len(text) <= _SHORT:
        return True
    if ctx.has_data_thread() and not _EXPLICIT_AGE.search(text) and len(text) < 140:
        if re.search(r"\?\.?\s*$", text) and not re.search(
            r"quantas?|quantos?|qual\s+o\s+total|distribu", text, re.I
        ):
            return True
    return False


def _transcript_snippet(transcript: list[dict[str, str]] | None, limit: int = 6) -> str:
    if not transcript:
        return ""
    lines: list[str] = []
    for msg in transcript[-limit:]:
        role = msg.get("role", "user")
        content = (msg.get("content") or "").strip()[:400]
        if content:
            lines.append(f"{role}: {content}")
    return "\n".join(lines)


def _parse_planner_json(raw: str) -> dict[str, Any]:
    text = (raw or "").strip()
    try:
        if text.startswith("{"):
            return json.loads(text)
    except json.JSONDecodeError:
        pass
    m = re.search(r"\{[\s\S]*\}", text)
    if m:
        try:
            return json.loads(m.group(0))
        except json.JSONDecodeError:
            pass
    return {}


def _apply_planner_to_context(ctx: SessionContext, plan: dict[str, Any]) -> SessionContext:
    subject = str(plan.get("subject") or "").strip()
    age_min = plan.get("age_min")
    age_max = plan.get("age_max")
    requires_pbf = bool(plan.get("requires_pbf"))

    filters = list(ctx.filters)
    if subject and subject != ctx.subject:
        filters = [f for f in filters if not f.startswith("idade ") and not f.startswith("crianças de ")]

    last_age_min = ctx.last_age_min
    last_age_max = ctx.last_age_max
    if age_min is not None and age_max is not None:
        last_age_min = int(age_min)
        last_age_max = int(age_max)
        label = f"idade {age_min} a {age_max} anos"
        if subject == "crianças":
            label = f"crianças de {age_min} a {age_max} anos"
        if label not in filters:
            filters.append(label)
    elif subject and subject != ctx.subject:
        last_age_min = None
        last_age_max = None

    if requires_pbf and "família na folha PBF" not in filters:
        filters.append("família na folha PBF")

    eq = str(plan.get("effective_question") or "").strip()
    return SessionContext(
        subject=subject or ctx.subject,
        entity="famílias" if plan.get("entity") == "familia" else (ctx.entity or "pessoas"),
        filters=filters,
        last_cras=ctx.last_cras,
        last_bairro=ctx.last_bairro,
        last_competencia=ctx.last_competencia,
        question_stem=eq.rstrip("?.!") if eq else ctx.question_stem,
        last_age_min=last_age_min,
        last_age_max=last_age_max,
        requires_pbf=requires_pbf or ctx.requires_pbf,
    )


def plan_task_turn(
    message: str,
    ctx: SessionContext,
    transcript: list[dict[str, str]] | None,
) -> tuple[str, SessionContext]:
    """
    Fase 1: LLM produz effective_question + slots.
    Fallback silencioso para mensagem original se LLM indisponível.
    """
    text = (message or "").strip()
    if not needs_llm_planner(text, ctx, transcript):
        return text, ctx

    user_parts = [f"Mensagem atual: {text}"]
    if ctx.has_data_thread():
        user_parts.append(f"\nMemória da sessão:\n{ctx.to_brief()}")
    snippet = _transcript_snippet(transcript)
    if snippet:
        user_parts.append(f"\nHistórico recente:\n{snippet}")

    try:
        raw = chat_completion(
            [
                {"role": "system", "content": PLANNER_SYSTEM},
                {"role": "user", "content": "\n".join(user_parts)},
            ],
            json_mode=True,
            temperature=0.15,
            role="orch",
        )
        plan = _parse_planner_json(raw)
    except (AssistNotConfiguredError, Exception):
        return text, ctx

    eq = str(plan.get("effective_question") or "").strip()
    if not eq:
        return text, ctx

    updated = _apply_planner_to_context(ctx, plan)
    return eq.rstrip("?.!") + "?", updated
