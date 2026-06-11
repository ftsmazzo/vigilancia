"""Maestro VigIA — roteamento explícito antes de bairro/SISC/SQL."""

from __future__ import annotations

from dataclasses import dataclass

from .conversation_intent import (
    build_thread_brief,
    is_planning_followup,
    is_planning_turn,
)


@dataclass(frozen=True)
class TurnRoute:
    primary: str  # planning | ivs | sisc | canonical | sql | chat
    skip_bairro_preprocess: bool
    block_sisc: bool
    thread_brief: str


def resolve_turn_route(
    message: str,
    transcript: list[dict[str, str]] | None,
) -> TurnRoute:
    brief = build_thread_brief(message, transcript)
    planning = is_planning_turn(message, transcript)
    followup = is_planning_followup(message, transcript)

    if planning or followup:
        return TurnRoute(
            primary="planning",
            skip_bairro_preprocess=True,
            block_sisc=True,
            thread_brief=brief,
        )

    return TurnRoute(
        primary="sql",
        skip_bairro_preprocess=False,
        block_sisc=False,
        thread_brief=brief,
    )
