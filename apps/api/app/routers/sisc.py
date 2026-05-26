"""API — SISC (Serviço de Convivência) × CADU."""

from __future__ import annotations

import time

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.orm import Session

from ..db import get_db
from ..deps import get_current_user
from ..models import User
from ..vigilance.sisc_qualificacao import refresh_sisc_qualificacao_mview, sisc_kpis_from_mview

router = APIRouter(prefix="/sisc", tags=["sisc"])


@router.get("/kpis")
def get_sisc_kpis(
    db: Session = Depends(get_db),
    _: User = Depends(get_current_user),
):
    """Indicadores e distribuições da qualificação SISC × CADU (requer visão materializada)."""
    with db.bind.connect() as conn:
        return sisc_kpis_from_mview(conn)


@router.post("/qualificacao/refresh")
def refresh_sisc_qualificacao(
    db: Session = Depends(get_db),
    _: User = Depends(get_current_user),
):
    """
    Recria `vig.mvw_sisc_qualificado`: cada atendido SISC enriquecido com pessoa/família CADU (chave NIS).
    Pré-requisitos: raw.sisc__sisc, vig.mvw_pessoas e vig.mvw_familia atualizadas.
    """
    started = time.perf_counter()
    try:
        with db.bind.begin() as conn:
            result = refresh_sisc_qualificacao_mview(conn)
    except ValueError as exc:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc)) from exc
    except Exception as exc:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Falha ao qualificar SISC: {exc}",
        ) from exc

    elapsed_ms = int((time.perf_counter() - started) * 1000)
    return {
        "status": "success",
        "view_schema": "vig",
        "view_name": "mvw_sisc_qualificado",
        "row_count": result.row_count,
        "nis_distintos": result.nis_distintos,
        "elapsed_ms": elapsed_ms,
        "warnings": result.warnings,
    }
