"""API — RMA (produção mensal SUAS) e dimensão de equipamentos oficiais."""

from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy.orm import Session

from ..db import get_db
from ..deps import get_current_user
from ..models import User
from ..vigilance.rma_analytics import (
    comparativo_cras_carga_demanda,
    equipamento_catalog,
    list_competencias,
    painel_rma,
    resumo_serie,
    serie_rma,
)
from ..vigilance.rma_integridade import auditar_rma_integridade
from ..vigilance.rma_pipeline import refresh_rma_pipeline

router = APIRouter(prefix="/rma", tags=["rma"])


def _integridade_dict(report) -> dict:
    return {
        "ok": report.ok,
        "erros": report.erros,
        "avisos": report.avisos,
        "raw": report.raw,
        "dim_equipamentos": report.dim_equipamentos,
        "ponte_cras": report.ponte_cras,
        "ponte_creas": report.ponte_creas,
        "geo_map_cras_nums": report.geo_map_cras_nums,
        "geo_map_creas_nums": report.geo_map_creas_nums,
        "fato_rows": report.fato_rows,
        "fato_psr_excluidos": report.fato_psr_excluidos,
        "resumo_rows": report.resumo_rows,
        "familia_mview": report.familia_mview,
    }


@router.post("/refresh")
def refresh_rma(
    db: Session = Depends(get_db),
    _: User = Depends(get_current_user),
):
    """
    Gera visão RMA a partir das tabelas raw já ingeridas pela UI
    (source=rma → rma__cras, rma__creas, rma__centro_pop).
    """
    try:
        with db.bind.connect() as conn:
            result = refresh_rma_pipeline(conn)
            conn.commit()
    except Exception as exc:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Falha ao gerar visão RMA: {exc}",
        ) from exc

    return {
        "catalogo": result.catalogo,
        "dim_equipamento": result.dim,
        "fato": result.fato,
        "resumo_mview": result.resumo_mview,
        "integridade": result.integridade,
    }


@router.get("/integridade")
def get_rma_integridade(
    db: Session = Depends(get_db),
    _: User = Depends(get_current_user),
):
    """Auditoria: ponte territorial, geo, fato, MV e gaps."""
    with db.bind.connect() as conn:
        report = auditar_rma_integridade(conn)
    return _integridade_dict(report)


@router.get("/competencias")
def get_competencias(
    db: Session = Depends(get_db),
    _: User = Depends(get_current_user),
):
    with db.bind.connect() as conn:
        items = list_competencias(conn)
    return {"total": len(items), "items": items}


@router.get("/painel")
def get_painel_rma(
    competencia: str = Query(..., description="Primeiro dia do mês, ex. 2025-01-01"),
    tipo_equipamento: str = Query("CRAS", description="CRAS | CREAS | CENTRO_POP"),
    id_equipamento: str | None = Query(None, description="Id oficial SUAS (opcional)"),
    db: Session = Depends(get_db),
    _: User = Depends(get_current_user),
):
    try:
        with db.bind.connect() as conn:
            return painel_rma(
                conn,
                competencia=competencia,
                tipo_equipamento=tipo_equipamento,
                id_equipamento=id_equipamento,
            )
    except Exception as exc:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Falha ao montar painel RMA: {exc}",
        ) from exc


@router.get("/serie")
def get_serie_rma(
    tipo_equipamento: str = Query("CRAS", description="CRAS | CREAS | CENTRO_POP"),
    id_equipamento: str | None = Query(None),
    meses: int = Query(24, ge=1, le=120),
    db: Session = Depends(get_db),
    _: User = Depends(get_current_user),
):
    try:
        with db.bind.connect() as conn:
            items = serie_rma(
                conn,
                tipo_equipamento=tipo_equipamento,
                id_equipamento=id_equipamento,
                meses=meses,
            )
    except ValueError as exc:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc)) from exc
    return {"total": len(items), "items": items}


@router.get("/equipamentos")
def list_equipamentos(
    db: Session = Depends(get_db),
    _: User = Depends(get_current_user),
):
    """Catálogo de equipamentos com id oficial SUAS e ponte territorial."""
    with db.bind.connect() as conn:
        items = equipamento_catalog(conn)
    return {"total": len(items), "items": items}


@router.get("/resumo")
def get_resumo_serie(
    id_equipamento: str | None = Query(None, description="Id oficial SUAS"),
    tipo_equipamento: str | None = Query(None, description="CRAS | CREAS | CENTRO_POP"),
    desde: str | None = Query(None, description="YYYY-MM-DD"),
    ate: str | None = Query(None, description="YYYY-MM-DD"),
    db: Session = Depends(get_db),
    _: User = Depends(get_current_user),
):
    try:
        with db.bind.connect() as conn:
            items = resumo_serie(
                conn,
                id_equipamento=id_equipamento,
                tipo_equipamento=tipo_equipamento,
                desde=desde,
                ate=ate,
            )
    except ValueError as exc:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc)) from exc
    return {"total": len(items), "items": items}


@router.get("/comparativo/cras-demanda")
def get_comparativo_cras_demanda(
    competencia: str = Query(..., description="Primeiro dia do mês, ex. 2025-01-01"),
    db: Session = Depends(get_db),
    _: User = Depends(get_current_user),
):
    """
    Produção RMA × estoque CADU por CRAS territorial — base para redimensionamento.
    """
    try:
        with db.bind.connect() as conn:
            items = comparativo_cras_carga_demanda(conn, competencia=competencia)
    except ValueError as exc:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc)) from exc
    return {"competencia": competencia, "total": len(items), "items": items}
