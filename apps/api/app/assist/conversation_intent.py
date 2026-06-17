"""Intenção conversacional — evita follow-up cego e rotas conflitantes."""

from __future__ import annotations

import re

from .session_context import SessionContext

_PLANNING = re.compile(
    r"implantar|implementar|novo\s+serv|abrir|criar|expandir|"
    r"suger|indic|recomend|onde\s+(?:abrir|implantar|criar|ir|priorizar)|"
    r"maior\s+demanda|potencial\s+(?:de\s+)?demanda|"
    r"preciso\s+(?:de\s+)?(?:um|uma)\s+(?:novo|nova)|"
    r"scfv|servi[cç]o\s+de\s+conviv|"
    r"repasse|recurso\s+(?:estadual|federa|extra)|"
    r"pol[ií]tica\s+p[uú]blica|executar\s+pol",
    re.I,
)
_SCFV = re.compile(r"\bscfv\b|servi[cç]o\s+de\s+conviv", re.I)
_FAIXA = re.compile(r"crianç|crianc|adolesc|menor|\d{1,2}\s*(?:a|-|á)\s*\d{1,2}", re.I)
_IDOSO = re.compile(
    r"idos|terceira\s+idade|melhor\s+idade|pessoa\s+idosa|"
    r"60\s*\+|65\s*\+|\b60\s*a\s*\d",
    re.I,
)
_BAIRRO_SUGGEST = re.compile(
    r"qual\s+bairro|bairro\s+(?:suger|indic|prioriz|deveria|recomend)|"
    r"onde\s+(?:devo|deveria|priorizar|ir|atuar)",
    re.I,
)
_CADU_ACAO = re.compile(
    r"atualiza[cç][ãa]o\s+cadastral|atualizar\s+(?:o\s+)?cadu|"
    r"a[cç][ãa]o.*cadu|cadu.*a[cç][ãa]o|"
    r"cadastro\s+[úu]nico.*territ[oó]rio|territ[oó]rio.*cadastro|"
    r"recadastramento|busca\s+ativa|"
    r"atualiza[cç][ãa]o.*territ[oó]rio|territ[oó]rio.*atualiza",
    re.I,
)
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
        if role == "user" and (
            _PLANNING.search(content)
            or _SCFV.search(content)
            or _CADU_ACAO.search(content)
        ) and (
            _FAIXA.search(content)
            or _IDOSO.search(content)
            or _BAIRRO_SUGGEST.search(content)
            or _CADU_ACAO.search(content)
        ):
            return True
    return False


def is_planning_followup(message: str, transcript: list[dict[str, str]] | None) -> bool:
    text_msg = message.strip()
    if not text_msg or not transcript:
        return False
    if not planning_thread_active(transcript):
        return False
    return bool(_BAIRRO_FOLLOWUP.search(text_msg))


def is_cadu_acao_turn(message: str, transcript: list[dict[str, str]] | None) -> bool:
    """Ação de atualização cadastral / busca ativa no território."""
    text_msg = message.strip()
    if not text_msg:
        return False
    if _CADU_ACAO.search(text_msg):
        return True
    blob = user_messages_blob(transcript, text_msg)
    return bool(_CADU_ACAO.search(blob) and _BAIRRO_SUGGEST.search(text_msg))


def is_planning_turn(message: str, transcript: list[dict[str, str]] | None) -> bool:
    text_msg = message.strip()
    if not text_msg:
        return False
    if is_planning_followup(text_msg, transcript):
        return True
    if is_cadu_acao_turn(text_msg, transcript):
        return True
    if not _PLANNING.search(text_msg):
        return False
    blob = user_messages_blob(transcript, text_msg)
    return bool(
        _FAIXA.search(text_msg)
        or _FAIXA.search(blob)
        or _IDOSO.search(text_msg)
        or _IDOSO.search(blob)
        or _BAIRRO_SUGGEST.search(text_msg)
    )


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


def build_thread_brief(
    message: str,
    transcript: list[dict[str, str]] | None,
    *,
    session_context: SessionContext | None = None,
) -> str:
    """Resumo estruturado para o AgenteSQL — evita perder o fio da conversa."""
    lines: list[str] = []
    if session_context and session_context.has_data_thread():
        brief = session_context.to_brief()
        if brief:
            lines.append(brief)
    if is_planning_turn(message, transcript):
        if is_cadu_acao_turn(message, transcript):
            lines.append(
                "- Assunto: **ação de atualização cadastral** no território "
                "(priorizar bairros com CADU desatualizado — eixo C/TAC)."
            )
        else:
            lines.append("- Assunto: planejamento territorial / **SCFV** (demanda potencial no CADU).")
        lines.append("- **NÃO** usar vig.mvw_sisc_qualificado salvo pedido explícito de matrícula existente.")
        lines.append("- Cruze demanda (A), carência SISC (B), IVS/NC (D) e TAC (C) na síntese.")
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
