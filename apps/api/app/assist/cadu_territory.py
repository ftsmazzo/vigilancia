"""Resolução territorial compartilhada — bairro/CRAS para métricas CADU primárias."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from sqlalchemy.engine import Connection

from .bairro_resolver import (
    extract_location_term,
    format_bairro_disambiguation,
    resolve_bairro,
    should_resolve_bairro,
)
from .geo_territorial import _CRAS_NUM


@dataclass(frozen=True)
class CaduTerritory:
    bairro: str | None = None
    num_cras: str | None = None

    @property
    def label(self) -> str:
        if self.bairro:
            return f"**{self.bairro}**"
        if self.num_cras:
            return f"**CRAS {self.num_cras}**"
        return "o **município**"


def parse_cras_from_message(message: str) -> str | None:
    m = _CRAS_NUM.search(message or "")
    if not m:
        return None
    raw = m.group(1)
    return raw.lstrip("0") or raw


def resolve_cadu_territory(
    conn: Connection,
    message: str,
    *,
    user_first_name: str = "",
    allow_municipio: bool = False,
) -> CaduTerritory | dict[str, Any] | None:
    """
    Resolve bairro ou CRAS. Retorna dict (disambiguation) ou None se sem recorte.
    """
    text_msg = (message or "").strip()
    num_cras = parse_cras_from_message(text_msg)
    if num_cras:
        return CaduTerritory(num_cras=num_cras)

    term = extract_location_term(text_msg)
    if term and should_resolve_bairro(text_msg, term):
        resolution = resolve_bairro(conn, term)
        if resolution.status == "multiple":
            return {
                "answer": format_bairro_disambiguation(resolution, user_first_name),
                "sql": None,
                "row_count": 0,
                "preview": resolution.matches,
                "mode": "disambiguation",
                "metric": "bairro_disambiguation",
            }
        if resolution.canonical:
            return CaduTerritory(bairro=resolution.canonical)

    if allow_municipio:
        return CaduTerritory()

    return None


def territory_sql_where(
    terr: CaduTerritory,
    *,
    fam_alias: str = "f",
) -> tuple[str, dict[str, Any]]:
    clauses: list[str] = []
    params: dict[str, Any] = {}
    if terr.bairro:
        clauses.append(f"lower(btrim({fam_alias}.bairro::text)) = lower(:bairro)")
        params["bairro"] = terr.bairro.strip()
    elif terr.num_cras:
        clauses.append(f"btrim({fam_alias}.num_cras::text) = :num_cras")
        params["num_cras"] = terr.num_cras.strip()
    return (" AND ".join(clauses) if clauses else "TRUE"), params
