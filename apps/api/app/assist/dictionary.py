"""Carrega dicionariotudo.csv e monta trecho de prompt para o LLM."""

from __future__ import annotations

import csv
from functools import lru_cache
from pathlib import Path

from ..config import settings
from .column_map import VIEW_COLUMN_MAP

_CACHE_MAX_CHARS = 12_000


def _dictionary_candidates() -> list[Path]:
    """Caminhos possíveis (dev monorepo, Docker /app, env explícito)."""
    here = Path(__file__).resolve()
    out: list[Path] = []
    if settings.cadu_dictionary_path:
        out.append(Path(settings.cadu_dictionary_path))
    # Copiado pelo backend/Dockerfile em produção
    out.append(here.parent / "data" / "dicionariotudo.csv")
    for parent in here.parents:
        out.append(parent / "DadosBrutos" / "CECAD" / "dicionariotudo.csv")
    return out


def _resolve_csv_path() -> Path | None:
    for candidate in _dictionary_candidates():
        if candidate.is_file():
            return candidate
    return None


@lru_cache(maxsize=1)
def load_dictionary() -> dict[str, dict[str, str]]:
    """campo_cadu → {descricao, resposta}."""
    path = _resolve_csv_path()
    if not path:
        return {}
    out: dict[str, dict[str, str]] = {}
    with path.open(encoding="utf-8-sig", newline="") as fh:
        reader = csv.DictReader(fh, delimiter=";")
        for row in reader:
            campo = (row.get("campo") or "").strip().strip('"').lower()
            if not campo:
                continue
            out[campo] = {
                "descricao": (row.get("descricao") or "").strip().strip('"'),
                "resposta": (row.get("resposta") or "").strip().strip('"'),
            }
    return out


def build_dictionary_prompt(max_chars: int = _CACHE_MAX_CHARS) -> str:
    """Texto semântico: colunas das views + significado + domínios de resposta."""
    dicionario = load_dictionary()
    if not dicionario:
        return ""

    lines = [
        "## Dicionário de dados (CADU → colunas usadas nas views)",
        "Use os códigos e domínios abaixo ao montar filtros WHERE e ao interpretar resultados.",
        "",
    ]

    for view, columns in VIEW_COLUMN_MAP.items():
        lines.append(f"### {view}")
        for col_view, campos_cadu in columns.items():
            if not campos_cadu:
                lines.append(f"- **{col_view}**: coluna derivada/classificada na visão VigSocial.")
                continue
            for campo in campos_cadu:
                key = campo.lower()
                meta = dicionario.get(key)
                if not meta:
                    lines.append(f"- **{col_view}** (origem `{campo}`): sem entrada no dicionário.")
                    continue
                desc = meta["descricao"] or "—"
                dom = meta["resposta"]
                if dom:
                    lines.append(f"- **{col_view}** ← `{campo}`: {desc}. Valores: {dom}")
                else:
                    lines.append(f"- **{col_view}** ← `{campo}`: {desc}.")
        lines.append("")

    text = "\n".join(lines)
    if len(text) > max_chars:
        return text[: max_chars - 80] + "\n\n… (dicionário truncado; priorize colunas listadas acima)"
    return text
