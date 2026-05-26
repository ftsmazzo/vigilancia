"""API — assistente de vigilância (chat NL → SQL)."""

from __future__ import annotations

import logging

from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel, Field
from sqlalchemy.orm import Session

from ..assist.llm import AssistLlmError, AssistNotConfiguredError
from ..assist.service import chat_turn
from ..db import get_db
from ..deps import get_current_user
from ..models import User

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/assist", tags=["assist"])


class ChatRequest(BaseModel):
    message: str = Field(..., min_length=1, max_length=4000)
    session_id: str | None = Field(None, max_length=36)


@router.post("/chat")
def post_chat(
    body: ChatRequest,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
):
    """Pergunta em linguagem natural; retorna resposta técnica e SQL (se gerada)."""
    try:
        return chat_turn(db, user, body.message, body.session_id)
    except AssistNotConfiguredError as exc:
        raise HTTPException(status_code=status.HTTP_503_SERVICE_UNAVAILABLE, detail=str(exc)) from exc
    except AssistLlmError as exc:
        raise HTTPException(status_code=status.HTTP_502_BAD_GATEWAY, detail=str(exc)) from exc
    except ValueError as exc:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc)) from exc
    except Exception as exc:
        logger.exception("assist/chat falhou")
        msg = str(exc).strip() or f"{type(exc).__name__}"
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Falha no assistente: {msg}",
        ) from exc
