#!/usr/bin/env python3
"""Bootstrap RMA local a partir de DadosBrutos (dev). Produção: use Ingestão → RMA na UI."""

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
from app.vigilance.rma_pipeline import refresh_rma_pipeline


def main() -> int:
    url = settings.database_url
    if "@postgres:" in url:
        url = url.replace("@postgres:", "@127.0.0.1:")
    engine = create_engine(url)
    with engine.connect() as conn:
        bootstrap_rma_from_dados_brutos(conn)
        result = refresh_rma_pipeline(conn)
        report = auditar_rma_integridade(conn)
        conn.commit()

    print("FATO:", result.fato)
    print("MV:", result.resumo_mview)
    print("INTEGRIDADE ok=", report.ok)
    for e in report.erros:
        print(" ERRO:", e)
    return 0 if report.ok else 1


if __name__ == "__main__":
    raise SystemExit(main())
