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
    data        — 1–2 frases, só o número/resposta pedida.
    ranking     — lista objetiva pedida, sem comentário extra.
    interpret   — síntese breve (2–4 frases), só eixos pertinentes.
    balanced    — padrão: curto, sem enrolação.
    """
    q = (question or "").strip()
    m = metric or ""

    if _INTERPRET.search(q) or m in ("planning_carencia",):
        return "interpret"

    if _RANKING.search(q) or m in ("ivs_cras_compare", "planning_cras_demanda"):
        return "ranking"

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
        "**Modo DADO** — Responda em **1–2 frases** apenas o que foi perguntado. "
        "Número principal + recorte mínimo (bairro/CRAS/faixa). "
        "Sem metodologia, sem outros eixos, sem conclusão extra."
    ),
    "ranking": (
        "**Modo LISTA/RANKING** — Entregue o ranking ou comparativo pedido de forma objetiva. "
        "Uma frase introdutória no máximo; depois os itens. Sem interpretação não solicitada."
    ),
    "interpret": (
        "**Modo INTERPRETAÇÃO** — Sintetize em **2–4 frases** só os eixos **pertinentes** "
        "à pergunta (ex.: carência → A+B; renda → C). Não percorra todos os eixos coletados. "
        "Conclusão clara em uma frase."
    ),
    "balanced": (
        "**Modo OBJETIVO** — Resposta **curta**: 1–3 frases. "
        "Responda ao que foi pedido; reflexão só se agregar valor direto."
    ),
}


def response_mode_hint(question: str, metric: str = "") -> str:
    mode = infer_response_mode(question, metric)
    return RESPONSE_MODE_HINTS.get(mode, RESPONSE_MODE_HINTS["balanced"])
