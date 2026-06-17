"""Inferência de modo de resposta — proporcional ao que o gestor pediu."""

from __future__ import annotations

import re

_DATA = re.compile(
    r"^(?:qual|quantos?|quantas?|quanto|tem\s+algum|liste|listar|"
    r"me\s+(?:d[eê]|passa)|informe)\b",
    re.I,
)
_INTERPRET = re.compile(
    r"car[eê]ncia|implantar|recomend|indic|prioriz|analise|diagn[oó]stic|"
    r"vale\s+a\s+pena|faz\s+sentido|devo|justific|por\s+que|como\s+pens|"
    r"o\s+que\s+consider|servi[cç]o\s+(?:para|nesse)|j[aá]\s+(?:tem|possui|existe)|"
    r"tem\s+car[eê]ncia|interpret",
    re.I,
)
_RANKING = re.compile(
    r"ranking|compar|maior|menor|superior|acima|demais|outros\s+cras|liste",
    re.I,
)


def infer_response_mode(question: str, metric: str = "") -> str:
    """
    data        — número direto, recorte mínimo.
    decision    — comparativo/variação: fato + leitura técnica breve para decisão.
    ranking     — lista ou ranking objetivo.
    interpret   — síntese para planejamento/carência.
    balanced    — padrão objetivo com valor agregado quando couber.
    """
    q = (question or "").strip()
    m = metric or ""

    if m.startswith("sibec_manut_compare") or m == "sibec_manut_compare_pair":
        return "decision"

    if m.startswith("planning_"):
        return "interpret"

    if _INTERPRET.search(q) or m in ("planning_carencia",):
        return "interpret"

    if _RANKING.search(q) or m in ("ivs_cras_compare", "planning_cras_demanda"):
        return "decision" if m.startswith("sibec") else "ranking"

    if _DATA.search(q) or re.search(
        r"\b(?:índice|indice|ivs|nc|total|n[uú]mero)\b", q, re.I
    ) and not _INTERPRET.search(q):
        return "data"

    if m in ("planning_bairro_em_cras",):
        if _INTERPRET.search(q):
            return "interpret"
        return "balanced"

    return "balanced"


RESPONSE_MODE_HINTS: dict[str, str] = {
    "data": (
        "**Modo DADO** — Resposta direta em 1–2 frases: número + recorte (CRAS/bairro/competência). "
        "Tom técnico e cordial; sem jargão de banco."
    ),
    "decision": (
        "**Modo DECISÃO** — Apresente os números verificados e, em seguida, **1 frase** de leitura "
        "técnica útil (ex.: magnitude da variação, possível eixo de acompanhamento no território). "
        "Cruze com RAG/rede só se agregar valor. Não seja seco nem prolixo."
    ),
    "ranking": (
        "**Modo LISTA/RANKING** — Entregue o ranking pedido de forma objetiva. "
        "Intro mínima; depois os itens."
    ),
    "interpret": (
        "**Modo INTERPRETAÇÃO** — Sintetize em 2–4 frases os eixos pertinentes à pergunta. "
        "Conclusão clara orientada à decisão."
    ),
    "balanced": (
        "**Modo OBJETIVO** — 1–3 frases: resposta + leitura breve se agregar valor."
    ),
}


def response_mode_hint(question: str, metric: str = "") -> str:
    mode = infer_response_mode(question, metric)
    return RESPONSE_MODE_HINTS.get(mode, RESPONSE_MODE_HINTS["balanced"])
