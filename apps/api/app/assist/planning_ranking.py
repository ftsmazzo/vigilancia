"""Ranking territorial reutilizável — priorização municipal para qualquer ação/implantação."""

from __future__ import annotations

import re
from collections.abc import Callable
from typing import Any

from .conversation_intent import wants_planning_ranking


def planning_rank_limit(message: str, *, default: int = 5, explicit_max: int = 12) -> int:
    """Quantos itens incluir no ranking (pedido explícito ou snapshot padrão)."""
    text = (message or "").strip()
    m = re.search(
        r"\b(\d{1,2})\s*(?:primeir[oa]s?|bairros?|cras|unidades?|posi[cç][õo]es?)\b",
        text,
        re.I,
    )
    if m:
        return max(2, min(int(m.group(1)), explicit_max))
    if re.search(r"\bcinco\b|\btop\s*5\b", text, re.I):
        return 5
    if wants_planning_ranking(text):
        return 8
    return default


def _fmt_int(n: int) -> str:
    return f"{n:,}".replace(",", ".")


def format_bairro_ranking_lines(
    rows: list[dict[str, Any]],
    *,
    value_key: str,
    limit: int,
    bairro_key: str = "bairro",
    cras_key: str = "num_cras",
    suffix_fn: Callable[[dict[str, Any]], str] | None = None,
) -> str:
    parts: list[str] = []
    for i, row in enumerate(rows[:limit], 1):
        bairro = str(row.get(bairro_key) or "").strip()
        val = int(row.get(value_key) or 0)
        cras = str(row.get(cras_key) or "").strip()
        cras_part = f" (CRAS {cras})" if cras else ""
        suffix = suffix_fn(row) if suffix_fn else ""
        parts.append(f"{i}. **{bairro}**{cras_part}: {_fmt_int(val)}{suffix}")
    return "; ".join(parts)


def build_bairro_ranking_fact(
    rows: list[dict[str, Any]],
    *,
    title: str,
    value_key: str,
    source: str,
    detail: str,
    message: str,
    limit: int | None = None,
    suffix_fn: Callable[[dict[str, Any]], str] | None = None,
) -> dict[str, Any] | None:
    """Fato eixo H — ranking municipal para a síntese analítica."""
    if not rows:
        return None
    lim = limit if limit is not None else planning_rank_limit(message)
    lim = min(lim, len(rows))
    list_mode = wants_planning_ranking(message)
    body = format_bairro_ranking_lines(
        rows,
        value_key=value_key,
        limit=lim,
        suffix_fn=suffix_fn,
    )
    return {
        "axis": "H",
        "label": title,
        "value": body,
        "source": source,
        "detail": detail,
        "signal": "reforça_prioridade" if list_mode else "neutro",
    }


def attach_territorial_ranking(
    reflex: dict[str, Any],
    rows: list[dict[str, Any]],
    *,
    message: str,
    title: str,
    value_key: str,
    source: str,
    detail: str,
    limit: int | None = None,
    suffix_fn: Callable[[dict[str, Any]], str] | None = None,
) -> dict[str, Any]:
    """Anexa ranking municipal ao pacote reflexivo (replicável em qualquer métrica de planejamento)."""
    fact = build_bairro_ranking_fact(
        rows,
        title=title,
        value_key=value_key,
        source=source,
        detail=detail,
        message=message,
        limit=limit,
        suffix_fn=suffix_fn,
    )
    if not fact:
        return reflex

    preview = list(reflex.get("preview") or [])
    preview.append(fact)
    axes = set(reflex.get("reflexion_axes") or [])
    axes.add("H")
    guide = str(reflex.get("reflexion_guide") or "")
    if wants_planning_ranking(message):
        guide += (
            " Gestor pediu **lista/ranking** — apresente o ranking municipal (eixo H) "
            "de forma objetiva após a recomendação do #1."
        )
    else:
        guide += (
            " Ranking municipal nos fatos (eixo H) — cite 2–3 bairros seguintes "
            "somente se enriquecer a decisão; não despeje lista inteira."
        )
    return {
        **reflex,
        "preview": preview,
        "reflexion_guide": guide.strip(),
        "reflexion_axes": sorted(axes),
    }
