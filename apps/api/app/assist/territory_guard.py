"""Guardião territorial — impede tratar entidades de dados (família, PBF) como bairro."""

from __future__ import annotations

import re
import unicodedata

_NON_GEO_TERMS = frozenset({
    "familia", "familias", "família", "famílias",
    "cadastro", "cadastro unico", "cadastro único", "cadu",
    "pbf", "bolsa", "beneficio", "benefício", "beneficios", "benefícios",
    "programa", "renda", "cras", "sisc", "sibec", "ivs", "ivcad",
    "municipio", "município", "territorio", "território",
    "homens", "homem", "mulheres", "mulher", "pessoas", "pessoa",
    "criancas", "crianças", "crianca", "criança", "idosos", "idoso",
    "adolescentes", "adolescente", "deficiencia", "deficiência",
    "recebem", "recebe", "beneficiarios", "beneficiários",
})

_FAMILIA_AS_ENTITY = re.compile(
    r"\b(?:nos|no|na|em|de|da|do)\s+fam[ií]lias?\b(?:\s+(?:que|com|do|da|de|recebe|benefici))",
    re.I,
)
_COHORT_FOLLOWUP = re.compile(
    r"\b(?:dess[aeo]s?|dest[aeo]s?|dessas?|desses?|"
    r"entre\s+(?:eles|elas|ess[aeo]s?)|"
    r"d[oa]s?\s+(?:homens|mulheres|pessoas|crian[cç]as?|idosos?))\b",
    re.I,
)
_PBF_CONTEXT = re.compile(
    r"\b(?:pbf|bolsa\s+fam[ií]lia|programa\s+bolsa|"
    r"recebe[m]?\s+(?:o\s+)?(?:pbf|bolsa|benef[ií]cio)|"
    r"benef[ií]cio\s+bolsa)\b",
    re.I,
)
_BENEFIT_CROSS = re.compile(
    r"\bfam[ií]lias?\s+(?:que\s+)?(?:recebe|receb|benefici|est[aá]o\s+no)\b",
    re.I,
)


def _fold(text: str) -> str:
    normalized = unicodedata.normalize("NFKD", text or "")
    stripped = "".join(c for c in normalized if not unicodedata.combining(c))
    return re.sub(r"\s+", " ", stripped.lower().strip())


def _clean_term(term: str) -> str:
    cleaned = (term or "").strip().strip("\"'")
    return re.sub(
        r"\s+(?:com|sem|que|do|da|de|no|na|em|cadastro|cadu).*$",
        "",
        cleaned,
        flags=re.I,
    ).strip()


def is_non_geographic_term(term: str) -> bool:
    cleaned = _clean_term(term)
    if not cleaned:
        return True
    folded = _fold(cleaned)
    if folded in _NON_GEO_TERMS:
        return True
    first = folded.split()[0] if folded else ""
    if first in _NON_GEO_TERMS:
        return True
    if re.match(r"^fam[ií]lias?\b", folded):
        return True
    if re.match(r"^fam[ií]lias?\s+que\b", folded):
        return True
    return False


def familia_as_data_entity(message: str) -> bool:
    """'em famílias que recebem PBF' — família como cruzamento, não bairro."""
    text_msg = (message or "").strip()
    if not text_msg:
        return False
    return bool(_FAMILIA_AS_ENTITY.search(text_msg) or _BENEFIT_CROSS.search(text_msg))


def is_cohort_followup(message: str) -> bool:
    text_msg = (message or "").strip()
    return bool(_COHORT_FOLLOWUP.search(text_msg))


def has_pbf_cross_filter(message: str) -> bool:
    return bool(_PBF_CONTEXT.search(message or ""))


def should_skip_bairro_resolution(
    message: str,
    transcript: list[dict[str, str]] | None = None,
) -> bool:
    text_msg = (message or "").strip()
    if not text_msg:
        return False

    if familia_as_data_entity(text_msg) or has_pbf_cross_filter(text_msg):
        if not re.search(r"\bbairro\s+(?!desse|nesse|deste|dese\b)", text_msg, re.I):
            return True

    if is_cohort_followup(text_msg) and not re.search(r"\bbairro\b", text_msg, re.I):
        if has_pbf_cross_filter(text_msg) or familia_as_data_entity(text_msg):
            return True
        if transcript and _session_has_territory(transcript):
            return True

    return False


def _session_has_territory(transcript: list[dict[str, str]] | None) -> bool:
    if not transcript:
        return False
    for msg in reversed(transcript):
        content = msg.get("content", "")
        if re.search(r"\bbairro\b", content, re.I):
            return True
        if re.search(r"(?:Em|No recorte)\s+\*\*[^*]{4,}\*\*", content, re.I):
            return True
    return False
