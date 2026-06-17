"""Histórico de conversa: Redis (memória quente) + PostgreSQL (persistência)."""

from __future__ import annotations

import json
import logging
import uuid
from datetime import datetime
from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session

from ..config import settings
from ..models import AssistMessage, AssistSession, User

logger = logging.getLogger(__name__)

MAX_HISTORY_MESSAGES = 20
REDIS_KEY_PREFIX = "vigsocial:assist:session:"
REDIS_CTX_SUFFIX = ":context"
_redis_client: Any | None = None
_redis_unavailable = False


def _session_context_key(session_id: str) -> str:
    return f"{REDIS_KEY_PREFIX}{session_id}{REDIS_CTX_SUFFIX}"


def load_session_context(session_id: str) -> dict[str, Any]:
    """Slots estruturados da sessão (follow-up CRAS, filtros, assunto)."""
    client = _redis()
    if not client:
        return {}
    try:
        raw = client.get(_session_context_key(session_id))
        if not raw:
            return {}
        data = json.loads(raw)
        return data if isinstance(data, dict) else {}
    except Exception as exc:
        logger.warning("Falha ao ler contexto Redis (sessão %s): %s", session_id, exc)
        return {}


def save_session_context(session_id: str, context: dict[str, Any]) -> None:
    client = _redis()
    if not client:
        return
    try:
        client.set(
            _session_context_key(session_id),
            json.dumps(context, ensure_ascii=False),
            ex=_ttl_seconds(),
        )
    except Exception as exc:
        logger.warning("Falha ao gravar contexto Redis (sessão %s): %s", session_id, exc)


def _session_messages_key(session_id: str) -> str:
    return f"{REDIS_KEY_PREFIX}{session_id}:messages"


def _redis() -> Any | None:
    global _redis_client, _redis_unavailable
    if _redis_unavailable:
        return None
    if _redis_client is not None:
        return _redis_client
    url = (settings.redis_url or "").strip()
    if not url:
        _redis_unavailable = True
        return None
    try:
        import redis

        client = redis.from_url(url, decode_responses=True, socket_connect_timeout=2)
        client.ping()
        _redis_client = client
        logger.info("Memória do assistente: Redis ativo (%s)", url.split("@")[-1])
        return _redis_client
    except Exception as exc:
        logger.warning("Redis indisponível para assistente, usando PostgreSQL: %s", exc)
        _redis_unavailable = True
        return None


def _ttl_seconds() -> int:
    return max(3600, settings.assist_session_ttl_hours * 3600)


def _redis_load(session_id: str) -> list[dict[str, str]] | None:
    client = _redis()
    if not client:
        return None
    try:
        key = _session_messages_key(session_id)
        if not client.exists(key):
            return None
        raw = client.lrange(key, 0, -1)
        out: list[dict[str, str]] = []
        for item in raw[-MAX_HISTORY_MESSAGES:]:
            row = json.loads(item)
            out.append({"role": row["role"], "content": row["content"]})
        return out
    except Exception as exc:
        logger.warning("Falha ao ler histórico Redis (sessão %s): %s", session_id, exc)
        return None


def _redis_append(
    session_id: str,
    role: str,
    content: str,
    sql_executed: str | None = None,
) -> None:
    client = _redis()
    if not client:
        return
    try:
        key = _session_messages_key(session_id)
        payload = json.dumps(
            {"role": role, "content": content, "sql": sql_executed},
            ensure_ascii=False,
        )
        client.rpush(key, payload)
        client.ltrim(key, -MAX_HISTORY_MESSAGES, -1)
        client.expire(key, _ttl_seconds())
    except Exception as exc:
        logger.warning("Falha ao gravar histórico Redis (sessão %s): %s", session_id, exc)


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
    cached = _redis_load(session_id)
    if cached is not None:
        return cached

    rows = db.scalars(
        select(AssistMessage)
        .where(AssistMessage.session_id == session_id)
        .order_by(AssistMessage.created_at.asc())
        .limit(MAX_HISTORY_MESSAGES)
    ).all()
    history = [{"role": row.role, "content": row.content} for row in rows]

    if history and _redis():
        for row in rows:
            _redis_append(session_id, row.role, row.content, row.sql_executed)

    return history


def append_message(
    db: Session,
    session_id: str,
    role: str,
    content: str,
    sql_executed: str | None = None,
) -> None:
    _redis_append(session_id, role, content, sql_executed)
    db.add(
        AssistMessage(
            session_id=session_id,
            role=role,
            content=content,
            sql_executed=sql_executed,
        )
    )
    db.commit()
