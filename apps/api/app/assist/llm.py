"""Cliente OpenAI-compatível (httpx)."""

from __future__ import annotations

import httpx

from ..config import settings


class AssistLlmError(RuntimeError):
    pass


class AssistNotConfiguredError(AssistLlmError):
    pass


def _ensure_configured() -> None:
    if not settings.assist_llm_api_key:
        raise AssistNotConfiguredError(
            "Assistente não configurado: defina ASSIST_LLM_API_KEY no ambiente da API."
        )


def resolve_model(role: str | None = None) -> str:
    if role == "orch" and settings.assist_orch_model:
        return settings.assist_orch_model
    if role == "sql" and settings.assist_sql_model:
        return settings.assist_sql_model
    return settings.assist_llm_model


def chat_completion(
    messages: list[dict[str, str]],
    *,
    json_mode: bool = False,
    temperature: float = 0.1,
    model: str | None = None,
    role: str | None = None,
) -> str:
    _ensure_configured()
    url = f"{settings.assist_llm_base_url.rstrip('/')}/chat/completions"
    body: dict = {
        "model": model or resolve_model(role),
        "messages": messages,
        "temperature": temperature,
    }
    if json_mode:
        body["response_format"] = {"type": "json_object"}

    try:
        with httpx.Client(timeout=90.0) as client:
            response = client.post(
                url,
                headers={
                    "Authorization": f"Bearer {settings.assist_llm_api_key}",
                    "Content-Type": "application/json",
                },
                json=body,
            )
            response.raise_for_status()
            data = response.json()
    except httpx.HTTPStatusError as exc:
        detail = exc.response.text[:500] if exc.response is not None else str(exc)
        raise AssistLlmError(f"Erro na API do modelo: {detail}") from exc
    except httpx.HTTPError as exc:
        raise AssistLlmError(f"Falha de rede ao chamar o modelo: {exc}") from exc

    try:
        return data["choices"][0]["message"]["content"]
    except (KeyError, IndexError, TypeError) as exc:
        raise AssistLlmError("Resposta inesperada do provedor de LLM.") from exc
