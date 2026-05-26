"""API — caracterização do município (contexto do assistente)."""

from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel, Field
from sqlalchemy.orm import Session

from ..db import get_db
from ..deps import get_current_user
from ..municipio_context import get_or_create_context, update_context
from ..models import User, UserRole

router = APIRouter(prefix="/municipio", tags=["municipio"])

_EDIT_ROLES = {UserRole.SUPERADMIN, UserRole.GESTOR, UserRole.ADMIN_LOCAL}


class ServicoItem(BaseModel):
    nome: str = Field(..., min_length=1, max_length=200)
    tipo: str = Field("", max_length=80)
    publico: str = Field("", max_length=300)
    observacao: str = Field("", max_length=500)


class MunicipioContextBody(BaseModel):
    nome_municipio: str = Field("", max_length=120)
    uf: str = Field("", max_length=2)
    codigo_ibge: str | None = Field(None, max_length=10)
    caracterizacao: dict = Field(default_factory=dict)
    servicos: list[ServicoItem] = Field(default_factory=list)


class MunicipioContextResponse(BaseModel):
    nome_municipio: str
    uf: str
    codigo_ibge: str | None
    caracterizacao: dict
    servicos: list[dict]
    updated_at: str | None
    updated_by_email: str | None


@router.get("/context", response_model=MunicipioContextResponse)
def get_municipio_context(
    db: Session = Depends(get_db),
    _: User = Depends(get_current_user),
):
    row = get_or_create_context(db)
    return MunicipioContextResponse(
        nome_municipio=row.nome_municipio,
        uf=row.uf,
        codigo_ibge=row.codigo_ibge,
        caracterizacao=row.caracterizacao or {},
        servicos=row.servicos or [],
        updated_at=row.updated_at.isoformat() if row.updated_at else None,
        updated_by_email=row.updated_by_email,
    )


@router.put("/context", response_model=MunicipioContextResponse)
def put_municipio_context(
    body: MunicipioContextBody,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
):
    if user.role not in _EDIT_ROLES:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Apenas gestor, admin local ou superadmin podem editar a caracterização.",
        )
    servicos = [s.model_dump() for s in body.servicos]
    row = update_context(
        db,
        user,
        nome_municipio=body.nome_municipio,
        uf=body.uf,
        codigo_ibge=body.codigo_ibge,
        caracterizacao=body.caracterizacao,
        servicos=servicos,
    )
    return MunicipioContextResponse(
        nome_municipio=row.nome_municipio,
        uf=row.uf,
        codigo_ibge=row.codigo_ibge,
        caracterizacao=row.caracterizacao or {},
        servicos=row.servicos or [],
        updated_at=row.updated_at.isoformat() if row.updated_at else None,
        updated_by_email=row.updated_by_email,
    )
