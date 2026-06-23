"""Pipeline RMA após ingestão RAW (sem depender de pasta no servidor)."""

from __future__ import annotations

from dataclasses import dataclass

from sqlalchemy.engine import Connection

from .rma_catalogo import refresh_catalogo_from_dicionarios
from .rma_equipamento import refresh_dim_from_raw_rma
from .rma_integridade import auditar_rma_integridade
from .rma_loader import refresh_fato_rma_mensal
from .rma_mview import refresh_rma_resumo_mview


@dataclass
class RmaPipelineResult:
    catalogo: dict
    dim: dict
    fato: dict
    resumo_mview: dict
    integridade: dict


def refresh_rma_pipeline(conn: Connection) -> RmaPipelineResult:
    cat = refresh_catalogo_from_dicionarios(conn)
    dim = refresh_dim_from_raw_rma(conn)
    fato = refresh_fato_rma_mensal(conn)
    mv = refresh_rma_resumo_mview(conn)
    report = auditar_rma_integridade(conn)
    return RmaPipelineResult(
        catalogo={"inserted": cat.inserted, "by_tipo": cat.by_tipo},
        dim={"upserted": dim.upserted, "total": dim.total},
        fato=fato,
        resumo_mview={"row_count": mv.row_count},
        integridade={
            "ok": report.ok,
            "erros": report.erros,
            "avisos": report.avisos,
            "fato_rows": report.fato_rows,
            "resumo_rows": report.resumo_rows,
        },
    )
