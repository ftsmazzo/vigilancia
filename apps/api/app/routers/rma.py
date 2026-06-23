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
    resumo_serie,
)
from ..vigilance.rma_catalogo import refresh_catalogo_from_dicionarios
from ..vigilance.rma_equipamento import refresh_dim_from_raw_rma
from ..vigilance.rma_loader import (
    bootstrap_rma_from_dados_brutos,
    refresh_fato_rma_mensal,
)
from ..vigilance.rma_integridade import auditar_rma_integridade
from ..vigilance.rma_mview import refresh_rma_resumo_mview

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
        "data_dir": report.data_dir,
    }


@router.post("/bootstrap")
def bootstrap_rma(
    db: Session = Depends(get_db),
    _: User = Depends(get_current_user),
):
    """
    Carga inicial: CSVs em DadosBrutos/RMA → raw → catálogo → dim equipamento → fato → MV resumo.
    """
    try:
        with db.bind.connect() as conn:
            result = bootstrap_rma_from_dados_brutos(conn)
            mv = refresh_rma_resumo_mview(conn)
            integridade = auditar_rma_integridade(conn)
            conn.commit()
    except Exception as exc:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Falha no bootstrap RMA: {exc}",
        ) from exc

    return {
        "raw": [{"table": r.table, "rows": r.rows} for r in result.raw],
        "catalogo": result.catalogo,
        "dim_equipamento": result.dim,
        "fato": result.fato,
        "resumo_mview": {"row_count": mv.row_count},
        "integridade": _integridade_dict(integridade),
    }


@router.post("/refresh")
def refresh_rma(
    db: Session = Depends(get_db),
    _: User = Depends(get_current_user),
):
    """Reprocessa dim, fato e MV a partir das tabelas raw já ingeridas."""
    try:
        with db.bind.connect() as conn:
            refresh_catalogo_from_dicionarios(conn)
            dim = refresh_dim_from_raw_rma(conn)
            fato = refresh_fato_rma_mensal(conn)
            mv = refresh_rma_resumo_mview(conn)
            integridade = auditar_rma_integridade(conn)
            conn.commit()
    except Exception as exc:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Falha ao atualizar RMA: {exc}",
        ) from exc

    return {
        "dim_equipamento": {"upserted": dim.upserted, "total": dim.total},
        "fato": fato,
        "resumo_mview": {"row_count": mv.row_count},
        "integridade": _integridade_dict(integridade),
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
