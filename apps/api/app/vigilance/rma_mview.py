"""Materialized view vig.mvw_rma_resumo_mes — KPIs mensais por equipamento (produção consolidada)."""

from __future__ import annotations

from dataclasses import dataclass

from sqlalchemy import text
from sqlalchemy.engine import Connection

from .familia_mview import _table_exists, ensure_vig_functions
from .rma_loader import FATO_TABLE

RESUMO_MVIEW = "mvw_rma_resumo_mes"


def _qi(ident: str) -> str:
    return '"' + ident.replace('"', '""') + '"'


def build_rma_resumo_mview_sql() -> str:
    """Pivota indicadores-chave; PSR usa Centro POP (CREAS POP excluído no fato)."""
    return f"""
    SELECT
      f.competencia,
      f.id_equipamento,
      d.tipo_equipamento,
      d.nome_oficial,
      d.cras_num_territorial,
      d.creas_num_territorial,
      d.grupo_psr_id,
      MAX(CASE WHEN f.tipo_formulario = 'CRAS' AND f.codigo_indicador = 'a1' THEN f.valor END)
        AS cras_familias_paif,
      MAX(CASE WHEN f.tipo_formulario = 'CRAS' AND f.codigo_indicador = 'a2' THEN f.valor END)
        AS cras_novas_familias_paif,
      MAX(CASE WHEN f.tipo_formulario = 'CRAS' AND f.codigo_indicador = 'c1' THEN f.valor END)
        AS cras_atend_individual,
      MAX(CASE WHEN f.tipo_formulario = 'CRAS' AND f.codigo_indicador = 'c6' THEN f.valor END)
        AS cras_visitas_domiciliares,
      MAX(CASE WHEN f.tipo_formulario = 'CREAS' AND f.codigo_indicador = 'a1' THEN f.valor END)
        AS creas_casos_paefi,
      MAX(CASE WHEN f.tipo_formulario = 'CREAS' AND f.codigo_indicador = 'a2' THEN f.valor END)
        AS creas_novos_casos_paefi,
      MAX(CASE WHEN f.tipo_formulario = 'CREAS' AND f.codigo_indicador = 'm1' THEN f.valor END)
        AS creas_atend_individual,
      MAX(CASE WHEN f.tipo_formulario = 'CREAS' AND f.codigo_indicador = 'm4' THEN f.valor END)
        AS creas_visitas_domiciliares,
      MAX(CASE WHEN f.tipo_formulario = 'CENTRO_POP' AND f.codigo_indicador = 'a1' THEN f.valor END)
        AS pop_pessoas_situacao_rua,
      MAX(CASE WHEN f.tipo_formulario = 'CENTRO_POP' AND f.codigo_indicador = 'd1' THEN f.valor END)
        AS pop_atendimentos_mes,
      MAX(CASE WHEN f.tipo_formulario = 'CENTRO_POP' AND f.codigo_indicador = 'e1' THEN f.valor END)
        AS pop_abordagens_pessoas,
      MAX(CASE WHEN f.tipo_formulario = 'CENTRO_POP' AND f.codigo_indicador = 'f1' THEN f.valor END)
        AS pop_total_abordagens
    FROM vig.{_qi(FATO_TABLE)} f
    LEFT JOIN vig.{_qi("dim_equipamento_suas")} d
      ON d.id_equipamento = f.id_equipamento
    WHERE f.incluir_analitico IS TRUE
    GROUP BY
      f.competencia,
      f.id_equipamento,
      d.tipo_equipamento,
      d.nome_oficial,
      d.cras_num_territorial,
      d.creas_num_territorial,
      d.grupo_psr_id
    """


@dataclass
class RmaResumoRefreshResult:
    row_count: int


def refresh_rma_resumo_mview(conn: Connection) -> RmaResumoRefreshResult:
    if not _table_exists(conn, "vig", FATO_TABLE):
        raise ValueError(f"Tabela vig.{FATO_TABLE} não encontrada. Execute bootstrap/refresh do fato antes.")

    ensure_vig_functions(conn)
    conn.execute(text("CREATE SCHEMA IF NOT EXISTS vig"))
    body = build_rma_resumo_mview_sql()
    conn.execute(text(f"DROP MATERIALIZED VIEW IF EXISTS vig.{_qi(RESUMO_MVIEW)}"))
    conn.execute(
        text(
            f"""
            CREATE MATERIALIZED VIEW vig.{_qi(RESUMO_MVIEW)} AS
            {body}
            """
        )
    )
    conn.execute(
        text(
            f"""
            CREATE UNIQUE INDEX IF NOT EXISTS idx_mvw_rma_resumo_pk
              ON vig.{_qi(RESUMO_MVIEW)} (competencia, id_equipamento)
            """
        )
    )
    conn.execute(
        text(
            f"""
            CREATE INDEX IF NOT EXISTS idx_mvw_rma_resumo_tipo
              ON vig.{_qi(RESUMO_MVIEW)} (tipo_equipamento, competencia)
            """
        )
    )
    count = conn.execute(text(f"SELECT COUNT(*) FROM vig.{_qi(RESUMO_MVIEW)}")).scalar() or 0
    return RmaResumoRefreshResult(row_count=int(count))
