"""Ponto de entrada do assistente VigIA."""

from __future__ import annotations

import logging
from typing import Any

from sqlalchemy.orm import Session

from ..config import settings
from ..models import User
from .memory import (
    append_message,
    get_or_create_session,
    load_history,
    load_session_context,
    save_session_context,
)
from .n8n_client import N8nAssistError, chat_via_n8n, n8n_vigia_enabled
from .orchestrator import run_orchestrator_turn
from .session_context import SessionContext, context_after_turn, resolve_effective_question

logger = logging.getLogger(__name__)


def _use_n8n_backend() -> bool:
    return (settings.assist_backend or "native").strip().lower() == "n8n" and n8n_vigia_enabled()


def chat_turn(
    db: Session,
    user: User,
    message: str,
    session_id: str | None,
) -> dict[str, Any]:
    message = message.strip()
    if not message:
        raise ValueError("Mensagem vazia.")

    session = get_or_create_session(db, user, session_id)
    history = load_history(db, session.id)
    stored_ctx = SessionContext.from_dict(load_session_context(session.id))
    append_message(db, session.id, "user", message)
    transcript = history + [{"role": "user", "content": message}]

    if _use_n8n_backend():
        try:
            result = chat_via_n8n(
                message=message,
                session_id=session.id,
                user={"name": user.name, "email": user.email, "role": getattr(user, "role", "")},
                session_context=stored_ctx.to_dict(),
            )
            result["session_id"] = session.id
            append_message(
                db,
                session.id,
                "assistant",
                result["answer"],
                sql_executed=result.get("sql"),
            )
            return result
        except N8nAssistError as exc:
            logger.warning("n8n VigIA indisponível, fallback nativo: %s", exc)

    with db.bind.connect() as conn:
        result = run_orchestrator_turn(
            conn,
            db,
            user,
            message,
            transcript,
            session_id=session.id,
            session_context=stored_ctx,
        )

    new_ctx = context_after_turn(
        message,
        result.get("effective_message") or message,
        result["answer"],
        stored_ctx,
        mode=str(result.get("mode") or ""),
        task_spec=result.get("task_spec"),
        filters_applied=str(result.get("filters_applied") or ""),
    )
    save_session_context(session.id, new_ctx.to_dict())

    append_message(
        db,
        session.id,
        "assistant",
        result["answer"],
        sql_executed=result.get("sql"),
    )

    payload: dict[str, Any] = {
        "session_id": session.id,
        "answer": result["answer"],
        "sql": result.get("sql"),
        "row_count": result.get("row_count", 0),
        "preview": result.get("preview") or [],
        "mode": result.get("mode", "data"),
    }
    if result.get("error"):
        payload["error"] = result["error"]
    return payload
