"""Cliente opcional — workflow VigIA no n8n (orquestrador LLM + webhook).

Quando ASSIST_N8N_VIGIA_URL está definido, o frontend pode rotear pelo n8n
em vez do orquestrador nativo. O workflow n8n chama de volta /api/v1/assist/chat
para dados verificados (Especialista Vigilância).
"""

from __future__ import annotations

import logging
from typing import Any

import httpx

from ..config import settings

logger = logging.getLogger(__name__)


class N8nAssistError(RuntimeError):
    pass


def n8n_vigia_enabled() -> bool:
    return bool((settings.assist_n8n_vigia_url or "").strip())


def chat_via_n8n(
    *,
    message: str,
    session_id: str | None,
    user: dict[str, Any],
    session_context: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """POST no webhook VigIA do n8n — POST /vigia/chat."""
    url = (settings.assist_n8n_vigia_url or "").strip().rstrip("/")
    if not url:
        raise N8nAssistError("ASSIST_N8N_VIGIA_URL não configurado.")

    payload = {
        "message": message,
        "session_id": session_id,
        "user": user,
        "session_context": session_context or {},
    }
    headers: dict[str, str] = {"Content-Type": "application/json"}
    if settings.assist_n8n_vigia_token:
        headers["Authorization"] = f"Bearer {settings.assist_n8n_vigia_token}"

    try:
        with httpx.Client(timeout=float(settings.assist_n8n_timeout_seconds)) as client:
            response = client.post(url, json=payload, headers=headers)
            response.raise_for_status()
            data = response.json()
    except httpx.HTTPStatusError as exc:
        detail = exc.response.text[:500] if exc.response is not None else str(exc)
        raise N8nAssistError(f"n8n VigIA HTTP {exc.response.status_code}: {detail}") from exc
    except httpx.HTTPError as exc:
        raise N8nAssistError(f"Falha ao chamar n8n VigIA: {exc}") from exc

    if isinstance(data, dict) and "body" in data and isinstance(data["body"], dict):
        data = data["body"]

    answer = str(data.get("answer") or "").strip()
    if not answer:
        raise N8nAssistError("n8n VigIA retornou resposta vazia.")

    return {
        "session_id": data.get("session_id") or session_id,
        "answer": answer,
        "sql": data.get("sql"),
        "row_count": int(data.get("row_count") or 0),
        "preview": data.get("preview") or [],
        "mode": data.get("mode") or data.get("agent") or "data",
        "routing": data.get("routing"),
    }
