"""API — caracterização sociodemográfica (CADU)."""

from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy.orm import Session

from ..db import get_db
from ..deps import get_current_user
from ..models import User
from ..vigilance.caracterizacao import caracterizacao_painel_from_views

router = APIRouter(prefix="/caracterizacao", tags=["caracterizacao"])


@router.get("/painel")
def get_caracterizacao_painel(
    cras_cod: str | None = Query(
        None,
        description="Código CRAS (num_cras), __todos__ ou __sem_cras__",
    ),
    bairro: str | None = Query(None, description="Bairro territorial (match exato)"),
    db: Session = Depends(get_db),
    _: User = Depends(get_current_user),
):
    """Perfil de sexo, raça, escolaridade, deficiência e idade no CADU."""
    try:
        with db.bind.connect() as conn:
            return caracterizacao_painel_from_views(conn, cras_cod, bairro)
    except ValueError as exc:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc)) from exc
    except Exception as exc:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Falha ao carregar caracterização: {exc}",
        ) from exc
