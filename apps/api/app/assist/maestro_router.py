"""Maestro VigIA — roteamento explícito antes de bairro/SISC/SQL."""

from __future__ import annotations

from dataclasses import dataclass

from .conversation_intent import (
    build_thread_brief,
    is_planning_coverage_followup,
    is_planning_followup,
    is_planning_turn,
)
from .municipio_agent import is_municipio_turn
from .policy_agent import is_policy_turn
from .multi_bairro_metrics import is_simple_territorial_count
from .session_context import SessionContext


@dataclass(frozen=True)
class TurnRoute:
    primary: str  # planning | policy | municipio | data | chat
    skip_bairro_preprocess: bool
    block_sisc: bool
    thread_brief: str
    effective_message: str = ""


def resolve_turn_route(
    message: str,
    transcript: list[dict[str, str]] | None,
    *,
    session_context: SessionContext | None = None,
    effective_message: str = "",
) -> TurnRoute:
    eff = (effective_message or message).strip()
    brief = build_thread_brief(eff, transcript, session_context=session_context)

    if is_simple_territorial_count(message, transcript) or is_simple_territorial_count(eff, transcript):
        return TurnRoute(
            primary="data",
            skip_bairro_preprocess=False,
            block_sisc=False,
            thread_brief=brief,
            effective_message=eff,
        )

    coverage = is_planning_coverage_followup(message, transcript)
    planning = is_planning_turn(message, transcript) or coverage
    followup = is_planning_followup(message, transcript)

    if planning or followup:
        return TurnRoute(
            primary="planning",
            skip_bairro_preprocess=True,
            block_sisc=True,
            thread_brief=brief,
            effective_message=eff,
        )

    if is_policy_turn(message):
        return TurnRoute(
            primary="policy",
            skip_bairro_preprocess=True,
            block_sisc=False,
            thread_brief=brief,
            effective_message=eff,
        )

    if is_municipio_turn(message):
        return TurnRoute(
            primary="municipio",
            skip_bairro_preprocess=True,
            block_sisc=False,
            thread_brief=brief,
            effective_message=eff,
        )

    return TurnRoute(
        primary="data",
        skip_bairro_preprocess=False,
        block_sisc=False,
        thread_brief=brief,
        effective_message=eff,
    )
