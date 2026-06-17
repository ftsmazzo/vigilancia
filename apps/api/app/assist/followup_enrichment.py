"""Reformulação de follow-ups — território, assunto e pergunta sim/não.

Evita travar em variações de phrasing; recompõe a pergunta completa a partir
do histórico antes das métricas canônicas ou do AgenteSQL.
"""

from __future__ import annotations

import re

from .bairro_resolver import extract_location_term, should_resolve_bairro
from .session_context import SessionContext

_YESNO_SIBEC = re.compile(
    r"(?:tem|h[aá]|existem|possui|apresenta|registr)"
    r".*(?:bloque|cancel|manuten[cç]|sibec|bolsa\s+fam)",
    re.I,
)
_YESNO_SIBEC_REV = re.compile(
    r"(?:bloque|cancel|manuten[cç]|sibec|bolsa\s+fam)"
    r".*(?:tem|h[aá]|existem|possui|apresenta|registr)",
    re.I,
)
_QUANT = re.compile(r"quantas?|quantos?|total|n[uú]mero|qtd|conte", re.I)
_TERR_SHORT = re.compile(
    r"^(?:"
    r"(?:no|na|nos|em)\s+(?:bairro\s+)?(.+?)|"
    r"(?:no\s+)?bairro\s+(.+?)|"
    r"e\s+(?:no|na|nos|em)\s+(?:bairro\s+)?(.+?)"
    r")\??\.?$",
    re.I,
)
_BAIRRO_IN_TEXT = re.compile(r"\bbairro\b", re.I)
_MANUT = re.compile(
    r"manuten[cç]|sibec|bloque|cancel|bolsa\s+fam|pbf",
    re.I,
)
_BLOQUEIO = re.compile(r"bloque", re.I)
_CANCEL = re.compile(r"cancel", re.I)


def _clean_term(term: str) -> str:
    return term.strip().strip("?.!,")


def territorial_term_from_message(message: str) -> str | None:
    """Extrai nome de bairro/território da mensagem curta ou longa."""
    text_msg = (message or "").strip()
    if not text_msg:
        return None

    m = _TERR_SHORT.match(text_msg)
    if m:
        for g in m.groups():
            if g:
                t = _clean_term(g)
                if len(t) >= 3:
                    return t

    if extract_location_term(text_msg):
        return extract_location_term(text_msg)

    if _BAIRRO_IN_TEXT.search(text_msg):
        term = extract_location_term(text_msg)
        if term:
            return term

    return None


def bairro_from_transcript(transcript: list[dict[str, str]] | None) -> str | None:
    """Último bairro citado no fio (usuário ou resposta com **bairro**)."""
    if not transcript:
        return None
    for msg in reversed(transcript):
        content = msg.get("content", "")
        term = extract_location_term(content)
        if term and (should_resolve_bairro(content, term) or _BAIRRO_IN_TEXT.search(content)):
            return term
        m = re.search(
            r"(?:Em|No recorte|territ[oó]rio do|bairro)\s+\*\*([^*]{3,})\*\*",
            content,
            re.I,
        )
        if m:
            return m.group(1).strip()
    return None


def is_territorial_clarification(message: str) -> bool:
    text_msg = (message or "").strip()
    if not text_msg or len(text_msg) > 120:
        return False
    if _QUANT.search(text_msg):
        return False
    return bool(_TERR_SHORT.match(text_msg) or (_BAIRRO_IN_TEXT.search(text_msg) and len(text_msg) < 80))


def is_sibec_yesno_question(message: str, transcript: list[dict[str, str]] | None = None) -> bool:
    text_msg = (message or "").strip()
    if _QUANT.search(text_msg):
        return False
    if _YESNO_SIBEC.search(text_msg) or _YESNO_SIBEC_REV.search(text_msg):
        return True
    return bool(_MANUT.search(text_msg) and (_YESNO_SIBEC.search(text_msg) or "?" in text_msg))


def _action_phrase(ctx: SessionContext, message: str) -> str:
    blob = f"{ctx.subject} {message}".lower()
    if _CANCEL.search(blob):
        return "cancelamentos do Bolsa Família"
    if _BLOQUEIO.search(blob) or ctx.subject == "bloqueio PBF":
        return "bloqueios do Bolsa Família"
    if _MANUT.search(blob):
        return "manutenções do Bolsa Família (SIBEC)"
    return "bloqueios do Bolsa Família"


def _inject_bairro(stem: str, bairro: str) -> str:
    """Garante bairro explícito na pergunta reformulada."""
    if not bairro:
        return stem
    b_fold = bairro.lower()
    if b_fold in stem.lower():
        if not _BAIRRO_IN_TEXT.search(stem):
            replaced = re.sub(
                rf"\b(?:no|na|nos|em)\s+{re.escape(bairro)}\b",
                f"no bairro {bairro}",
                stem,
                flags=re.I,
                count=1,
            )
            if replaced != stem:
                return replaced
        return stem
    return f"{stem.rstrip('?.!')} no bairro {bairro}"


def reformulate_territorial_followup(
    message: str,
    ctx: SessionContext,
    transcript: list[dict[str, str]] | None,
) -> str | None:
    """'no Bairro Campos Elíseos?' → recompõe pergunta anterior com território."""
    if not is_territorial_clarification(message):
        return None

    bairro = territorial_term_from_message(message) or ctx.last_bairro or bairro_from_transcript(transcript)
    if not bairro:
        return None

    if ctx.question_stem:
        return _inject_bairro(ctx.question_stem, bairro)

    action = _action_phrase(ctx, message)
    if ctx.subject or _MANUT.search(message):
        return f"Quantos {action} no bairro {bairro}"

    return f"Quantas pessoas no bairro {bairro}"


def reformulate_sibec_yesno(
    message: str,
    ctx: SessionContext,
    transcript: list[dict[str, str]] | None,
) -> str | None:
    """'Tem bloqueios no Campos Elíseos?' → pergunta quantitativa canônica."""
    if not is_sibec_yesno_question(message, transcript):
        return None

    bairro = (
        territorial_term_from_message(message)
        or ctx.last_bairro
        or bairro_from_transcript(transcript)
    )
    action = _action_phrase(ctx, message)
    if bairro:
        return f"Quantos {action} no bairro {bairro}"
    return f"Quantos {action} no município"


def enrich_effective_question(
    message: str,
    ctx: SessionContext,
    transcript: list[dict[str, str]] | None,
) -> tuple[str, SessionContext]:
    """Aplica reformulações territoriais e sim/não antes do roteamento."""
    updated = ctx

    term = territorial_term_from_message(message)
    if term:
        updated = SessionContext(
            subject=ctx.subject,
            entity=ctx.entity,
            filters=list(ctx.filters),
            last_cras=ctx.last_cras,
            last_bairro=term,
            last_competencia=ctx.last_competencia,
            question_stem=ctx.question_stem,
        )

    for reformulator in (reformulate_territorial_followup, reformulate_sibec_yesno):
        rebuilt = reformulator(message, updated, transcript)
        if rebuilt:
            return rebuilt.rstrip("?.!") + "?", updated

    return message, updated
