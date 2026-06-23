#!/usr/bin/env python3
"""Bootstrap RMA local (sem subir a API). Uso: python scripts/bootstrap_rma.py"""

from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
API_DIR = ROOT / "apps" / "api"
sys.path.insert(0, str(API_DIR))

from sqlalchemy import create_engine

from app.config import settings
from app.vigilance.rma_integridade import auditar_rma_integridade
from app.vigilance.rma_loader import bootstrap_rma_from_dados_brutos
from app.vigilance.rma_mview import refresh_rma_resumo_mview


def main() -> int:
    url = settings.database_url
    if "@postgres:" in url:
        url = url.replace("@postgres:", "@127.0.0.1:")
    engine = create_engine(url)
    with engine.connect() as conn:
        result = bootstrap_rma_from_dados_brutos(conn)
        mv = refresh_rma_resumo_mview(conn)
        report = auditar_rma_integridade(conn)
        conn.commit()

    print("RAW:", [(r.table, r.rows) for r in result.raw])
    print("DIM:", result.dim)
    print("FATO:", result.fato)
    print("MV:", mv.row_count)
    print("INTEGRIDADE ok=", report.ok)
    for e in report.erros:
        print(" ERRO:", e)
    for a in report.avisos:
        print(" AVISO:", a)
    return 0 if report.ok else 1


if __name__ == "__main__":
    raise SystemExit(main())
