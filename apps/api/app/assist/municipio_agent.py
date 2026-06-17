"""Especialista Dados do Município — rede local, caracterização e contexto territorial cadastrado."""

from __future__ import annotations

import re
from dataclasses import dataclass

from sqlalchemy import text
from sqlalchemy.engine import Connection
from sqlalchemy.orm import Session

from .answer_trim import trim_answer_boilerplate
from .llm import chat_completion
from ..municipio_context import load_context_prompt

MUNICIPIO_AGENT_SYSTEM = """Você é o **Especialista em Dados do Município** do VigIA — socioassistencial municipal.

Missão:
- Responder sobre a rede de serviços cadastrada, caracterização local e território institucional.
- Situar decisões com o cadastro municipal e o panorama CRAS (quando disponível).
- Números de famílias/pessoas/manutenções vêm do tronco **CADU/Vigilância** — encaminhe com naturalidade quando pedirem totais.

Tom: cordial, técnico, útil para gestão local.
"""

_MUNICIPIO_INTENT = re.compile(
    r"rede\s+(?:local|municipal)|servi[cç]os?\s+cadastrad|"
    r"caracteriza[cç][ãa]o\s+(?:do\s+)?munic[ií]pio|"
    r"unidades?\s+(?:do\s+)?munic[ií]pio|"
    r"quais?\s+(?:s[aã]o\s+)?(?:os\s+)?servi[cç]os|"
    r"onde\s+fica\s+(?:o\s+)?cras|endere[cç]o\s+(?:do\s+)?cras|"
    r"territ[oó]rio\s+(?:do\s+)?munic[ií]pio|"
    r"prioridades?\s+(?:locais|municipais)|"
    r"nossa\s+rede|nosso\s+munic[ií]pio|"
    r"cras\s+(?:da\s+cidade|do\s+munic[ií]pio)",
    re.I,
)

_DATA_OVERRIDE = re.compile(
    r"quantas?|quantos?|total|n[uú]mero|percentual|%|"
    r"bloqueio|cancelamento|manuten[cç][ãa]o|"
    r"fam[ií]lia|pessoa|renda|ivs|ivcad",
    re.I,
)


@dataclass(frozen=True)
class MunicipioAgentResult:
    ok: bool
    answer: str
    has_local_context: bool


def is_municipio_turn(message: str) -> bool:
    text = message.strip()
    if not text:
        return False
    if _DATA_OVERRIDE.search(text):
        return False
    return bool(_MUNICIPIO_INTENT.search(text))


def _territorial_panorama(conn: Connection) -> str:
    try:
        rows = conn.execute(
            text(
                """
                SELECT
                  btrim(COALESCE(num_cras::text, '')) AS num_cras,
                  btrim(COALESCE(nom_cras::text, '')) AS nom_cras,
                  COUNT(DISTINCT btrim(bairro::text)) FILTER (
                    WHERE btrim(COALESCE(bairro::text, '')) <> ''
                  )::int AS bairros
                FROM vig.mvw_familia
                WHERE btrim(COALESCE(num_cras::text, '')) <> ''
                GROUP BY num_cras, nom_cras
                ORDER BY NULLIF(
                  regexp_replace(btrim(num_cras::text), '[^0-9]', '', 'g'), ''
                )::int NULLS LAST
                LIMIT 20
                """
            )
        ).mappings().all()
    except Exception:
        return ""
    if not rows:
        return ""
    lines = ["### Panorama territorial (CADU × CRAS)"]
    for r in rows:
        num = r.get("num_cras") or "?"
        nome = r.get("nom_cras") or ""
        bairros = int(r.get("bairros") or 0)
        label = f"CRAS {num}"
        if nome:
            label += f" — {nome}"
        lines.append(f"- {label}: {bairros} bairro(s) referenciado(s)")
    return "\n".join(lines)


def run_municipio_agent(
    conn: Connection,
    db: Session,
    message: str,
    transcript: list[dict[str, str]] | None,
    *,
    user_first_name: str = "",
) -> MunicipioAgentResult:
    municipio_block = load_context_prompt(db)
    panorama = _territorial_panorama(conn)

    system = MUNICIPIO_AGENT_SYSTEM
    if municipio_block:
        system += f"\n\n{municipio_block[:6000]}"
    else:
        system += (
            "\n\n### Cadastro municipal\n"
            "Ainda não há caracterização cadastrada em **Município**. "
            "Oriente o usuário a preencher em Configurações → Município."
        )
    if panorama:
        system += f"\n\n{panorama[:4000]}"

    messages: list[dict[str, str]] = [
        {"role": "system", "content": system},
        *(transcript or []),
    ]
    raw = chat_completion(messages, temperature=0.35, role="municipio").strip()
    answer = trim_answer_boilerplate(raw)
    if user_first_name and answer and not answer.lower().startswith(user_first_name.lower()):
        answer = f"{user_first_name}, {answer[0].lower()}{answer[1:]}"
    return MunicipioAgentResult(
        ok=True,
        answer=answer,
        has_local_context=bool(municipio_block),
    )
