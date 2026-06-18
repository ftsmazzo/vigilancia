"""Contexto estruturado da sessão — follow-ups (CRAS, filtros, assunto)."""

from __future__ import annotations

import re
from dataclasses import asdict, dataclass, field
from typing import Any

_DATA_Q = re.compile(r"quantas?|quantos?|total|n[uú]mero", re.I)
_FOLLOWUP_CRAS = re.compile(
    r"^(?:e\s+)?(?:no|na|em)\s+(?:cras\s*)?(\d{1,2})\s*\??\.?$",
    re.I,
)
_FOLLOWUP_AND = re.compile(
    r"^(?:e\s+)(?:no|na|em)\s+(?:cras\s*)?(\d{1,2})",
    re.I,
)
_CRAS_NUM = re.compile(r"\bcras\s*(\d{1,2})\b", re.I)
_WOMEN = re.compile(r"mulher|feminino", re.I)
_MEN = re.compile(r"homem|masculino", re.I)
_CHILD = re.compile(r"crian[cç]", re.I)
_FAMILIA = re.compile(r"fam[ií]lia", re.I)
_BLOQUEIO = re.compile(r"bloque", re.I)
_CANCEL = re.compile(r"cancel", re.I)
_SIBEC = re.compile(r"manuten[cç]|sibec|pbf", re.I)


@dataclass
class SessionContext:
    """Slots da conversa de dados — persistidos no Redis por sessão."""

    subject: str = ""
    entity: str = ""
    filters: list[str] = field(default_factory=list)
    last_cras: str = ""
    last_bairro: str = ""
    last_competencia: str = ""
    question_stem: str = ""

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)

    @classmethod
    def from_dict(cls, data: dict[str, Any] | None) -> SessionContext:
        if not data:
            return cls()
        return cls(
            subject=str(data.get("subject") or ""),
            entity=str(data.get("entity") or ""),
            filters=list(data.get("filters") or []),
            last_cras=str(data.get("last_cras") or ""),
            last_bairro=str(data.get("last_bairro") or ""),
            last_competencia=str(data.get("last_competencia") or ""),
            question_stem=str(data.get("question_stem") or ""),
        )

    def has_data_thread(self) -> bool:
        return bool(self.question_stem or self.subject or self.entity)

    def to_brief(self) -> str:
        if not self.has_data_thread():
            return ""
        lines = ["- **Memória da sessão (mantenha filtros do turno anterior):**"]
        if self.question_stem:
            lines.append(f"  - Pergunta-base: {self.question_stem}")
        if self.subject:
            lines.append(f"  - Assunto: {self.subject}")
        if self.entity:
            lines.append(f"  - Entidade: {self.entity}")
        if self.filters:
            lines.append(f"  - Filtros ativos: {', '.join(self.filters)}")
        if self.last_cras:
            lines.append(f"  - CRAS anterior: {self.last_cras}")
        if self.last_bairro:
            lines.append(f"  - Bairro anterior: {self.last_bairro}")
        if self.last_competencia:
            lines.append(f"  - Competência anterior: {self.last_competencia}")
        return "\n".join(lines)


def _cras_from_text(text: str) -> str:
    m = _CRAS_NUM.search(text or "")
    if not m:
        return ""
    raw = m.group(1)
    return raw.lstrip("0") or raw


def _parse_user_data_question(text: str) -> SessionContext | None:
    if not text or not text.strip():
        return None
    if not _DATA_Q.search(text):
        return None

    ctx = SessionContext()
    low = text.lower()

    if _WOMEN.search(low):
        ctx.subject = "mulheres"
        ctx.entity = "pessoas"
        ctx.filters.append("cod_sexo = '2' (mulher)")
    elif _MEN.search(low):
        ctx.subject = "homens"
        ctx.entity = "pessoas"
        ctx.filters.append("cod_sexo = '1' (homem)")
    elif _CHILD.search(low):
        ctx.subject = "crianças"
        ctx.entity = "pessoas"
    elif _BLOQUEIO.search(low):
        ctx.subject = "bloqueio PBF"
        ctx.entity = "famílias (manutenção SIBEC)"
        ctx.filters.append("teve_bloqueio")
    elif _CANCEL.search(low):
        ctx.subject = "cancelamento PBF"
        ctx.entity = "famílias (manutenção SIBEC)"
        ctx.filters.append("teve_cancelamento")
    elif _FAMILIA.search(low):
        ctx.subject = "famílias"
        ctx.entity = "famílias"
    else:
        ctx.subject = "consulta de dados"
        ctx.entity = "CADU/Vigilância"

    cras = _cras_from_text(text)
    if cras:
        ctx.last_cras = cras

    age = re.search(r"(\d{1,2})\s*(?:a|-|á)\s*(\d{1,2})\s*(?:anos)?", low)
    if age:
        ctx.filters.append(f"idade {age.group(1)} a {age.group(2)} anos")

    comp = re.search(r"\b(20\d{4})\b", text)
    if comp:
        ctx.last_competencia = comp.group(1)
    else:
        for nome in ("janeiro", "fevereiro", "março", "marco", "abril", "maio", "junho",
                     "julho", "agosto", "setembro", "outubro", "novembro", "dezembro"):
            if re.search(rf"\b{nome}\b", low):
                ym = re.search(r"\b(20\d{2})\b", text)
                if ym:
                    ctx.last_competencia = f"{nome}/{ym.group(1)}"
                break

    stem = text.strip().rstrip("?.!")
    ctx.question_stem = stem
    return ctx


def _last_user_data_question(transcript: list[dict[str, str]] | None) -> str:
    if not transcript:
        return ""
    for msg in reversed(transcript):
        if msg.get("role") != "user":
            continue
        content = msg.get("content", "")
        if _DATA_Q.search(content) and not _is_cras_followup_only(content):
            return content
    return ""


def _is_cras_followup_only(message: str) -> bool:
    text = message.strip()
    if _FOLLOWUP_CRAS.match(text):
        return True
    if _FOLLOWUP_AND.search(text) and not _DATA_Q.search(text):
        return True
    return False


def parse_cras_followup(message: str) -> str | None:
    text = message.strip()
    m = _FOLLOWUP_CRAS.match(text) or _FOLLOWUP_AND.search(text)
    if not m:
        return None
    raw = m.group(1)
    return raw.lstrip("0") or raw


def extract_context_from_transcript(
    transcript: list[dict[str, str]] | None,
) -> SessionContext:
    """Reconstrói contexto a partir do histórico (fallback se Redis vazio)."""
    from .bairro_resolver import extract_location_term
    from .followup_enrichment import bairro_from_transcript

    ctx = SessionContext()
    last_q = _last_user_data_question(transcript)
    if last_q:
        parsed = _parse_user_data_question(last_q)
        if parsed:
            ctx = parsed

    if transcript:
        for msg in reversed(transcript):
            if msg.get("role") != "assistant":
                continue
            content = msg.get("content", "")
            cras = _cras_from_text(content)
            if cras:
                ctx.last_cras = cras
                break

    bairro = bairro_from_transcript(transcript)
    if not bairro and last_q:
        bairro = extract_location_term(last_q)
    if bairro:
        ctx.last_bairro = bairro

    return ctx


def merge_context(stored: SessionContext, extracted: SessionContext) -> SessionContext:
    """Redis prevalece; transcript preenche lacunas."""
    if not stored.has_data_thread():
        return extracted
    if not extracted.has_data_thread():
        return stored
    return SessionContext(
        subject=stored.subject or extracted.subject,
        entity=stored.entity or extracted.entity,
        filters=_merge_filter_lists(stored.filters, extracted.filters),
        last_cras=extracted.last_cras or stored.last_cras,
        last_bairro=stored.last_bairro or extracted.last_bairro,
        last_competencia=stored.last_competencia or extracted.last_competencia,
        question_stem=stored.question_stem or extracted.question_stem,
    )


def _merge_filter_lists(stored: list[str], extracted: list[str]) -> list[str]:
    merged = list(stored)
    for item in extracted:
        if item not in merged:
            merged.append(item)
    return merged


def reformulate_followup(
    message: str,
    ctx: SessionContext,
) -> str | None:
    """
    'e no 5?' após 'quantas mulheres no CRAS 12' →
    'Quantas mulheres no CRAS 5'
    """
    new_cras = parse_cras_followup(message)
    if not new_cras or not ctx.has_data_thread():
        return None

    if ctx.question_stem and ctx.last_cras:
        stem = re.sub(
            rf"\bcras\s*{re.escape(ctx.last_cras)}\b",
            f"CRAS {new_cras}",
            ctx.question_stem,
            flags=re.I,
        )
        if stem.lower() != ctx.question_stem.lower():
            return stem.rstrip("?.!")

    if ctx.question_stem and re.search(r"\bcras\b", ctx.question_stem, re.I):
        stem = re.sub(
            r"\bcras\s*\d{1,2}\b",
            f"CRAS {new_cras}",
            ctx.question_stem,
            count=1,
            flags=re.I,
        )
        return stem.rstrip("?.!")

    parts = ["Quantas"]
    if ctx.subject == "mulheres":
        parts.append("mulheres")
    elif ctx.subject == "homens":
        parts.append("homens")
    elif ctx.subject == "crianças":
        parts.append("crianças")
    elif ctx.subject:
        parts.append(ctx.subject)
    else:
        parts.append("pessoas")
    parts.append(f"no CRAS {new_cras}")
    return " ".join(parts)


def resolve_effective_question(
    message: str,
    transcript: list[dict[str, str]] | None,
    stored: SessionContext | None,
) -> tuple[str, SessionContext]:
    from .followup_enrichment import enrich_effective_question

    extracted = extract_context_from_transcript(transcript)
    ctx = merge_context(stored or SessionContext(), extracted)

    working = message
    reformulated = reformulate_followup(message, ctx)
    if reformulated:
        working = reformulated

    effective, ctx = enrich_effective_question(working, ctx, transcript)

    parsed = _parse_user_data_question(effective)
    if parsed and not _is_cras_followup_only(message):
        ctx = merge_context(ctx, parsed)
    return effective, ctx


def context_after_turn(
    message: str,
    effective_message: str,
    answer: str,
    prior: SessionContext,
    *,
    mode: str = "",
) -> SessionContext:
    """Atualiza slots após resposta de dados."""
    if mode in ("chat", "policy", "municipio", "disambiguation"):
        return prior

    from .bairro_resolver import extract_location_term
    from .followup_enrichment import bairro_from_transcript, territorial_term_from_message

    parsed = _parse_user_data_question(effective_message)
    if parsed and not _is_cras_followup_only(message):
        ctx = parsed
    else:
        ctx = SessionContext(
            subject=prior.subject,
            entity=prior.entity,
            filters=list(prior.filters),
            last_cras=prior.last_cras,
            last_bairro=prior.last_bairro,
            last_competencia=prior.last_competencia,
            question_stem=prior.question_stem,
        )

    cras = _cras_from_text(answer) or _cras_from_text(effective_message) or parse_cras_followup(message)
    if cras:
        ctx.last_cras = cras

    bairro = (
        territorial_term_from_message(effective_message)
        or territorial_term_from_message(message)
        or extract_location_term(effective_message)
        or extract_location_term(message)
    )
    if bairro:
        ctx.last_bairro = bairro
    else:
        from_transcript = bairro_from_transcript(
            [{"role": "assistant", "content": answer}] if answer else None
        )
        if from_transcript:
            ctx.last_bairro = from_transcript

    if not ctx.question_stem and effective_message:
        ctx.question_stem = effective_message.strip().rstrip("?.!")

    return ctx
