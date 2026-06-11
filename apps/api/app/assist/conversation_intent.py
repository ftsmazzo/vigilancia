"""Intenção conversacional — evita follow-up cego e rotas conflitantes."""

from __future__ import annotations

import re

_PLANNING = re.compile(
    r"implantar|implementar|novo\s+serv|abrir|criar|expandir|"
    r"suger|indic|recomend|onde\s+(?:abrir|implantar|criar)|"
    r"maior\s+demanda|potencial\s+(?:de\s+)?demanda|"
    r"preciso\s+(?:de\s+)?(?:um|uma)\s+(?:novo|nova)|"
    r"scfv|servi[cç]o\s+de\s+conviv",
    re.I,
)
_SCFV = re.compile(r"\bscfv\b|servi[cç]o\s+de\s+conviv", re.I)
_FAIXA = re.compile(r"crianç|crianc|adolesc|menor|\d{1,2}\s*(?:a|-|á)\s*\d{1,2}", re.I)
_BAIRRO_FOLLOWUP = re.compile(
    r"\bbairro\b.*(?:desse|nesse|deste|dese)\s+cras|"
    r"(?:desse|nesse|deste|dese)\s+cras.*\bbairro\b|"
    r"qual\s+bairro|em\s+que\s+bairro|bairro\s+(?:mais|indicad)",
    re.I,
)
_PLANNING_ANSWER = re.compile(
    r"mais indicado|demanda potencial|eu indicaria|maior demanda|reúne a maior demanda",
    re.I,
)
_SISC = re.compile(r"\bsisc\b|matriculad|atendid[oa]s?\s+(?:no|em)\s+(?:sisc|conviv)", re.I)
_LIST_OTHERS = re.compile(
    r"outros\s+cras|demais\s+cras|liste|listar|ranking|comparar|todos\s+os\s+cras",
    re.I,
)
_COVERAGE = re.compile(
    r"car[eê]ncia|j[aá]\s+(?:possui|tem|existe)|possui\s+(?:algum|alguma)\s+serv|"
    r"servi[cç]o\s+(?:para|nesse|neste|no\s+bairro)|tem\s+car[eê]ncia|"
    r"oferta\s+(?:real|existente)|vulnerabilidade\s+social|"
    r"considerou\s+como\s+vulnerabilidade|o\s*que\s+considerou",
    re.I,
)
_SHORT_ACK = re.compile(
    r"^(?:se\s+puder\s+)?(?:agrade[cç]o|obrigad|por\s+favor|sim\s*,?\s*por\s+favor)\.?$",
    re.I,
)


def user_messages_blob(transcript: list[dict[str, str]] | None, message: str = "") -> str:
    parts = [
        m.get("content", "")
        for m in (transcript or [])
        if m.get("role") == "user"
    ]
    if message:
        parts.append(message)
    return " ".join(parts)


def planning_thread_active(transcript: list[dict[str, str]] | None) -> bool:
    if not transcript:
        return False
    for msg in reversed(transcript):
        role = msg.get("role")
        content = msg.get("content", "")
        if role == "assistant" and _PLANNING_ANSWER.search(content):
            return True
        if role == "user" and (_PLANNING.search(content) or _SCFV.search(content)) and _FAIXA.search(content):
            return True
    return False


def is_planning_followup(message: str, transcript: list[dict[str, str]] | None) -> bool:
    text_msg = message.strip()
    if not text_msg or not transcript:
        return False
    if not planning_thread_active(transcript):
        return False
    return bool(_BAIRRO_FOLLOWUP.search(text_msg))


def is_planning_turn(message: str, transcript: list[dict[str, str]] | None) -> bool:
    text_msg = message.strip()
    if not text_msg:
        return False
    if is_planning_followup(text_msg, transcript):
        return True
    if not _PLANNING.search(text_msg):
        return False
    blob = user_messages_blob(transcript, text_msg)
    return bool(_FAIXA.search(text_msg) or _FAIXA.search(blob))


def user_asks_sisc_existing(message: str, transcript: list[dict[str, str]] | None) -> bool:
    """Matrícula/atendimento existente no SISC — não confundir com planejamento."""
    text_msg = message.strip()
    if is_planning_turn(text_msg, transcript):
        return False
    if _SISC.search(text_msg) and re.search(
        r"matriculad|atendid|quantos?\s+(?:atendid|matricul)|j[aá]\s+(?:exist|tem)",
        text_msg,
        re.I,
    ):
        return True
    return bool(_SISC.search(text_msg) and not _PLANNING.search(text_msg))


def skips_bairro_preprocess(message: str, transcript: list[dict[str, str]] | None) -> bool:
    """Não resolver bairro em planejamento municipal/CRAS sem nome de bairro."""
    text_msg = message.strip()
    if is_planning_turn(text_msg, transcript) and not re.search(
        r"\bbairro\s+(?!desse|nesse|deste|dese\b)",
        text_msg,
        re.I,
    ):
        return True
    if re.search(r"\b(?:scfv|implantar|munic[ií]pio)\b", text_msg, re.I) and not re.search(
        r"\bbairro\b", text_msg, re.I
    ):
        return True
    return False


def wants_planning_ranking(message: str) -> bool:
    return bool(_LIST_OTHERS.search(message))


def pending_coverage_in_thread(transcript: list[dict[str, str]] | None) -> bool:
    """Usuário pediu carência/oferta e o assistente ainda não respondeu com dados."""
    if not transcript:
        return False
    asked = False
    for msg in transcript:
        if msg.get("role") == "user" and _COVERAGE.search(msg.get("content", "")):
            asked = True
        if msg.get("role") == "assistant" and asked:
            content = msg.get("content", "").lower()
            if any(
                x in content
                for x in (
                    "não tenho informação",
                    "formule uma pergunta",
                    "não consegui reunir",
                )
            ):
                return True
            if re.search(r"\d+.*(?:sisc|cadu|matricul|demanda|carência)", content, re.I):
                return False
    return asked


def is_planning_coverage_followup(
    message: str,
    transcript: list[dict[str, str]] | None,
) -> bool:
    text_msg = message.strip()
    if not transcript or not planning_thread_active(transcript):
        return False
    if _COVERAGE.search(text_msg):
        return True
    if _SHORT_ACK.search(text_msg) and pending_coverage_in_thread(transcript):
        return True
    return False


def build_thread_brief(message: str, transcript: list[dict[str, str]] | None) -> str:
    """Resumo estruturado para o AgenteSQL — evita perder o fio da conversa."""
    lines: list[str] = []
    if is_planning_turn(message, transcript):
        lines.append("- Assunto: planejamento de **novo SCFV** (demanda potencial no CADU territorial).")
        lines.append("- **NÃO** usar vig.mvw_sisc_qualificado salvo pedido explícito de matrícula existente.")
    if is_planning_followup(message, transcript):
        lines.append("- Follow-up: detalhar **bairro dentro do CRAS** indicado na resposta anterior.")
    if is_planning_coverage_followup(message, transcript):
        lines.append(
            "- Follow-up: **carência de SCFV** — cruzar demanda CADU (p×f territorial) "
            "com matrícula SISC no bairro/faixa etária da conversa."
        )
    if planning_thread_active(transcript):
        for msg in reversed(transcript or []):
            if msg.get("role") != "assistant":
                continue
            content = msg.get("content", "")
            m = re.search(r"\bCRAS\s*(\d{1,2})\b", content, re.I)
            if m and re.search(r"indic|suger|demanda|scfv", content, re.I):
                lines.append(f"- CRAS indicado no histórico: **CRAS {m.group(1)}**.")
                break
    blob = user_messages_blob(transcript, message)
    age = re.search(r"(\d{1,2})\s*(?:a|-|á)\s*(\d{1,2})\s*(?:anos)?", blob, re.I)
    if age:
        lines.append(f"- Faixa etária em discussão: **{age.group(1)} a {age.group(2)} anos**.")
    if not lines:
        return ""
    return "\n".join(lines)
