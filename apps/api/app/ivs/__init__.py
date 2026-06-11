"""IVS — Índice de Vulnerabilidade Social (metodologia IVCAD MDS v1.0.5)."""

from .ivs_familia import IvsRefreshResult, refresh_ivs_familia

__all__ = ["IvsRefreshResult", "refresh_ivs_familia"]
