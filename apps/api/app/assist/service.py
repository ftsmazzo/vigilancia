"""Ponto de entrada do assistente VigIA (nativo — sem N8N)."""

from __future__ import annotations

from typing import Any

from sqlalchemy.orm import Session

from ..models import User
from .memory import (
    append_message,
    get_or_create_session,
    load_history,
    load_session_context,
    save_session_context,
)
from .orchestrator import run_orchestrator_turn
from .session_context import SessionContext, context_after_turn, resolve_effective_question


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
