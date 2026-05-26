"""Histórico de conversa por sessão (PostgreSQL)."""

from __future__ import annotations

import uuid
from datetime import datetime

from sqlalchemy import select
from sqlalchemy.orm import Session

from ..models import AssistMessage, AssistSession, User

MAX_HISTORY_MESSAGES = 20


def get_or_create_session(db: Session, user: User, session_id: str | None) -> AssistSession:
    if session_id:
        session = db.get(AssistSession, session_id)
        if session and session.user_id == user.id:
            session.updated_at = datetime.utcnow()
            db.commit()
            return session
    new_id = str(uuid.uuid4())
    session = AssistSession(id=new_id, user_id=user.id)
    db.add(session)
    db.commit()
    db.refresh(session)
    return session


def load_history(db: Session, session_id: str) -> list[dict[str, str]]:
    rows = db.scalars(
        select(AssistMessage)
        .where(AssistMessage.session_id == session_id)
        .order_by(AssistMessage.created_at.asc())
        .limit(MAX_HISTORY_MESSAGES)
    ).all()
    return [{"role": row.role, "content": row.content} for row in rows]


def append_message(
    db: Session,
    session_id: str,
    role: str,
    content: str,
    sql_executed: str | None = None,
) -> None:
    db.add(
        AssistMessage(
            session_id=session_id,
            role=role,
            content=content,
            sql_executed=sql_executed,
        )
    )
    db.commit()
