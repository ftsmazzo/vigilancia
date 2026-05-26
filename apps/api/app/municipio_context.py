"""Leitura/gravação do contexto municipal (singleton id=1)."""

from __future__ import annotations

from datetime import datetime

from sqlalchemy import select
from sqlalchemy.orm import Session

from .models import MunicipioContext, User


def get_or_create_context(db: Session) -> MunicipioContext:
    row = db.get(MunicipioContext, 1)
    if row:
        return row
    row = MunicipioContext(id=1)
    db.add(row)
    db.commit()
    db.refresh(row)
    return row


def context_to_prompt_block(ctx: MunicipioContext) -> str:
    parts = ["## Contexto do município (cadastro local VigSocial)"]
    if ctx.nome_municipio:
        ibge = f", IBGE {ctx.codigo_ibge}" if ctx.codigo_ibge else ""
        parts.append(f"Município: **{ctx.nome_municipio}** / {ctx.uf or '—'}{ibge}.")

    car = ctx.caracterizacao or {}
    if isinstance(car, dict):
        for key, val in car.items():
            if val and str(val).strip():
                label = key.replace("_", " ").strip()
                parts.append(f"- {label}: {val}")

    servicos = ctx.servicos or []
    if isinstance(servicos, list) and servicos:
        parts.append("\n### Rede de serviços cadastrada")
        for i, s in enumerate(servicos[:40], 1):
            if not isinstance(s, dict):
                continue
            nome = s.get("nome") or s.get("titulo") or f"Serviço {i}"
            tipo = s.get("tipo") or ""
            pub = s.get("publico") or ""
            obs = s.get("observacao") or ""
            line = f"- {nome}"
            if tipo:
                line += f" ({tipo})"
            if pub:
                line += f" — público: {pub}"
            if obs:
                line += f". {obs}"
            parts.append(line)

    if len(parts) <= 1:
        return ""
    parts.append(
        "\nUse este contexto para situar respostas (território, rede local, prioridades), "
        "sem substituir números vindos do SQL."
    )
    return "\n".join(parts)


def update_context(
    db: Session,
    user: User,
    *,
    nome_municipio: str,
    uf: str,
    codigo_ibge: str | None,
    caracterizacao: dict,
    servicos: list,
) -> MunicipioContext:
    row = get_or_create_context(db)
    row.nome_municipio = nome_municipio.strip()
    row.uf = uf.strip().upper()[:2]
    row.codigo_ibge = (codigo_ibge or "").strip() or None
    row.caracterizacao = caracterizacao if isinstance(caracterizacao, dict) else {}
    row.servicos = servicos if isinstance(servicos, list) else []
    row.updated_at = datetime.utcnow()
    row.updated_by_email = user.email
    db.commit()
    db.refresh(row)
    return row


def load_context_prompt(db: Session) -> str:
    row = db.get(MunicipioContext, 1)
    if not row:
        return ""
    return context_to_prompt_block(row)
