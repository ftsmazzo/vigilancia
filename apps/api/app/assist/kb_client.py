"""Cliente HTTP para base de conhecimento (políticas SUAS) — nativo na API."""

from __future__ import annotations

import logging
from typing import Any

import httpx

from ..config import settings

logger = logging.getLogger(__name__)


def query_knowledge_base(question: str) -> str:
    """
    Consulta a API de KB (ex.: POST /api/kb/5/query).
    Retorna texto concatenado dos trechos ou string vazia se não configurado / falhar.
    """
    url = (settings.kb_api_url or "").strip()
    key = (settings.kb_api_key or "").strip()
    if not url or not key:
        return ""

    body: dict[str, Any] = {
        "query": question.strip(),
        "topK": settings.kb_top_k,
    }

    try:
        with httpx.Client(timeout=20.0) as client:
            response = client.post(
                url,
                headers={
                    "Authorization": f"Bearer {key}",
                    "Content-Type": "application/json",
                },
                json=body,
            )
            response.raise_for_status()
            data = response.json()
    except httpx.HTTPError as exc:
        logger.warning("KB query falhou: %s", exc)
        return ""

    return _extract_snippets(data)


def _extract_snippets(data: Any) -> str:
    """Aceita formatos comuns: results[], chunks[], data[]."""
    if not isinstance(data, dict):
        return ""

    candidates = data.get("results") or data.get("chunks") or data.get("data") or []
    if not isinstance(candidates, list):
        return ""

    parts: list[str] = []
    for item in candidates[: settings.kb_top_k]:
        if isinstance(item, str) and item.strip():
            parts.append(item.strip())
            continue
        if not isinstance(item, dict):
            continue
        text = (
            item.get("content")
            or item.get("text")
            or item.get("snippet")
            or item.get("pageContent")
        )
        if text and str(text).strip():
            parts.append(str(text).strip())

    return "\n\n---\n\n".join(parts)
