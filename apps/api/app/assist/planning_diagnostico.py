"""Diagnóstico territorial — delega à estrutura reflexiva multi-eixo."""

from __future__ import annotations

from typing import Any

from sqlalchemy.engine import Connection
from sqlalchemy.orm import Session

from .analyst_reflexion import (
    TerritorialReflexion,
    build_bairro_diagnostico_facts,
    collect_reflexion_result,
    collect_territorial_reflexion,
)

__all__ = [
    "TerritorialReflexion",
    "build_bairro_diagnostico_facts",
    "collect_reflexion_result",
    "collect_territorial_reflexion",
]
