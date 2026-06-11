"""Playbook de raciocínio — reexporta a estrutura reflexiva (v2)."""

from __future__ import annotations

from .analyst_reflexion import (
    REFLEXION_VERSION,
    build_planning_playbook,
    build_playbook_for_pack,
    build_reflexion_playbook,
    is_planning_decision_context,
)

PLAYBOOK_VERSION = REFLEXION_VERSION

__all__ = [
    "PLAYBOOK_VERSION",
    "build_planning_playbook",
    "build_playbook_for_pack",
    "build_reflexion_playbook",
    "is_planning_decision_context",
]
