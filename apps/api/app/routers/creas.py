"""API — catálogo territorial CREAS."""

from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy.orm import Session

from ..db import get_db
from ..deps import get_current_user
from ..models import User
from ..vigilance.creas_analytics import bairros_por_creas_from_views, creas_catalog_from_views

router = APIRouter(prefix="/creas", tags=["creas"])


@router.get("/catalog")
def get_creas_catalog(
    db: Session = Depends(get_db),
    _: User = Depends(get_current_user),
):
    """Lista CREAS distintos no CADU com totais de famílias e pessoas."""
    try:
        with db.bind.connect() as conn:
            items, diagnostic = creas_catalog_from_views(conn)
    except ValueError as exc:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc)) from exc
    except Exception as exc:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Falha ao listar CREAS: {exc}",
        ) from exc
    unidades = [x for x in items if x.get("creas_cod") not in ("", "__sem_creas__")]
    return {
        "total_unidades": len(unidades),
        "items": items,
        "diagnostic": diagnostic,
    }


@router.get("/bairros")
def get_bairros_por_creas(
    num_creas: str = Query(..., description="Código CREAS (num_creas territorial)"),
    db: Session = Depends(get_db),
    _: User = Depends(get_current_user),
):
    """Lista bairros distintos de um CREAS (geo × CEP na visão família)."""
    try:
        with db.bind.connect() as conn:
            items = bairros_por_creas_from_views(conn, num_creas)
    except ValueError as exc:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc)) from exc
    except Exception as exc:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Falha ao listar bairros: {exc}",
        ) from exc
    return {"num_creas": num_creas.strip(), "total": len(items), "items": items}
