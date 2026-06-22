"""API — painel CADU por CRAS (unidade territorial)."""

from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy.orm import Session

from ..db import get_db
from ..deps import get_current_user
from ..models import User
from ..vigilance.cras_analytics import bairros_por_cras_from_views, cras_catalog_from_views, cras_painel_from_views

router = APIRouter(prefix="/cras", tags=["cras"])


@router.get("/catalog")
def get_cras_catalog(
    db: Session = Depends(get_db),
    _: User = Depends(get_current_user),
):
    """Lista CRAS distintos no CADU com totais de famílias e pessoas."""
    try:
        with db.bind.connect() as conn:
            items = cras_catalog_from_views(conn)
    except ValueError as exc:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc)) from exc
    except Exception as exc:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Falha ao listar CRAS: {exc}",
        ) from exc
    return {"total_unidades": len(items), "items": items}


@router.get("/bairros")
def get_bairros_por_cras(
    num_cras: str = Query(..., description="Código CRAS (num_cras territorial)"),
    db: Session = Depends(get_db),
    _: User = Depends(get_current_user),
):
    """Lista bairros distintos de um CRAS (geo × CEP na visão família)."""
    try:
        with db.bind.connect() as conn:
            items = bairros_por_cras_from_views(conn, num_cras)
    except ValueError as exc:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc)) from exc
    except Exception as exc:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Falha ao listar bairros: {exc}",
        ) from exc
    return {"num_cras": num_cras.strip(), "total": len(items), "items": items}


@router.get("/painel")
def get_cras_painel(
    cras_cod: str | None = Query(
        None,
        description="Código CRAS (num_cras) ou __todos__ / __sem_cras__",
    ),
    creas_cod: str | None = Query(
        None,
        description="Código CREAS (num_creas) ou __todos__ / __sem_creas__",
    ),
    db: Session = Depends(get_db),
    _: User = Depends(get_current_user),
):
    """
  Indicadores quantitativos do CADU filtrados por CRAS.
  Sem parâmetro ou `__todos__`: visão municipal + tabela comparativa.
  """
    try:
        with db.bind.connect() as conn:
            return cras_painel_from_views(conn, cras_cod, creas_cod)
    except ValueError as exc:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc)) from exc
    except Exception as exc:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Falha no painel CRAS: {exc}",
        ) from exc
