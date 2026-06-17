"""Registro municipal de CRAS — aliases SISC × territorial (Ribeirão Preto)."""

from __future__ import annotations

import re
import unicodedata
from typing import Any

# Matrícula SISC frequentemente usa nome popular; territorialização geo usa num_cras.
# CRAS 1 = unidade central (bairro Centro).
_SISC_NAME_TO_NUM: dict[str, str] = {
    "centro": "1",
    "cras centro": "1",
    "cras central": "1",
    "central": "1",
    "area do cras central": "1",
    "area do cras 1": "1",
}

_TERRITORIAL_DISPLAY: dict[str, str] = {
    "1": "CRAS 1 — Central (Centro)",
    "9": "CRAS 9 — Bonfim Paulista",
}


def _fold(text: str) -> str:
    normalized = unicodedata.normalize("NFKD", text or "")
    stripped = "".join(c for c in normalized if not unicodedata.combining(c))
    return re.sub(r"\s+", " ", stripped.lower().strip())


def normalize_cras_num(value: Any) -> str | None:
    if value is None:
        return None
    raw = str(value).strip()
    if not raw:
        return None
    m = re.match(r"^(\d+)", raw)
    if m:
        n = m.group(1).lstrip("0") or m.group(1)
        return n
    return None


def sisc_cras_to_territorial_num(*, codigo: Any = None, nome: Any = None) -> str | None:
    """Mapeia CRAS da matrícula SISC → num_cras territorial quando possível."""
    num = normalize_cras_num(codigo)
    if num:
        return num
    key = _fold(str(nome or ""))
    if key in _SISC_NAME_TO_NUM:
        return _SISC_NAME_TO_NUM[key]
    if "centro" in key and "cras" in key:
        return "1"
    if key in ("centro", "central"):
        return "1"
    return None


def territorial_cras_matches_sisc(
    terr_num: str | None,
    *,
    sisc_codigo: Any = None,
    sisc_nome: Any = None,
) -> bool:
    """True se matrícula SISC e CRAS territorial referem a mesma unidade."""
    t = normalize_cras_num(terr_num)
    if not t:
        return False
    s_num = sisc_cras_to_territorial_num(codigo=sisc_codigo, nome=sisc_nome)
    if s_num and s_num == t:
        return True
    s_fold = _fold(str(sisc_nome or ""))
    if t == "1" and ("centro" in s_fold or "central" in s_fold):
        return True
    return str(sisc_codigo or "").strip() == str(t)


def format_territorial_cras(num: Any, nome: Any = None) -> str:
    n = normalize_cras_num(num)
    if not n:
        return str(nome or "").strip() or "CRAS sem referência"
    if n in _TERRITORIAL_DISPLAY:
        return _TERRITORIAL_DISPLAY[n]
    label = f"CRAS {n}"
    nom = str(nome or "").strip()
    if nom and nom.lower() not in label.lower():
        short = nom.replace("AREA DO CRAS ", "").replace("AREA DO ", "")
        return f"{label} — {short}"
    return label


def format_sisc_cras_display(codigo: Any, nome: Any) -> str:
    nom = str(nome or "").strip() or f"cód. {codigo}"
    mapped = sisc_cras_to_territorial_num(codigo=codigo, nome=nome)
    if mapped:
        equiv = format_territorial_cras(mapped)
        if _fold(nom) not in _fold(equiv):
            return f"{nom} (equivale a **{equiv}** territorial)"
    return nom
