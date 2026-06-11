"""Materialized view vig.mvw_familia_domicilio: moradia, riscos e GPTE por código familiar (só CADU)."""

from __future__ import annotations

import re
from dataclasses import dataclass

from sqlalchemy import text
from sqlalchemy.engine import Connection

from .familia_mview import CADU_TABLE, _columns, _qi, _table_exists, ensure_vig_functions

# Colunas d.* esperadas após normalização da ingestão (layout tudo CADU).
_DOM_COLS: dict[str, str] = {
    "cod": "d_cod_familiar_fam",
    "atual": "d_dat_atual_fam",
    "cad": "d_dat_cadastramento_fam",
    "local_domic": "d_cod_local_domic_fam",
    "especie_domic": "d_cod_especie_domic_fam",
    "qtd_comodos": "d_qtd_comodos_domic_fam",
    "qtd_dorm": "d_qtd_comodos_dormitorio_fam",
    "mat_piso": "d_cod_material_piso_fam",
    "mat_domic": "d_cod_material_domic_fam",
    "agua_canal": "d_cod_agua_canalizada_fam",
    "abast_agua": "d_cod_abaste_agua_domic_fam",
    "banheiro": "d_cod_banheiro_domic_fam",
    "escoamento": "d_cod_escoa_sanitario_domic_fam",
    "lixo": "d_cod_destino_lixo_domic_fam",
    "iluminacao": "d_cod_iluminacao_domic_fam",
    "calcamento": "d_cod_calcamento_domic_fam",
    "indigena_reside": "d_cod_indigena_reside_fam",
    "quilombola": "d_ind_familia_quilombola_fam",
    "familias_domic": "d_qtd_familias_domic_fam",
    "qtd_pessoas_domic": "d_qtd_pessoas_domic_fam",
    "desp_aluguel": "d_val_desp_aluguel_fam",
    "cod_cras": "d_cod_centro_assist_fam",
    "risco_viol": "d_ind_risco_scl_vlco_drts",
    "risco_alim": "d_ind_risco_scl_inseg_alim",
    "gpte": "d_ind_parc_mds_fam",
}

CPF_PESSOA_COL = "p_num_cpf_pessoa"


def _col_expr(cols: set[str], phys: str) -> str:
    if phys in cols:
        return _qi(phys)
    return "NULL"


def _validate_domicilio_columns(cols: set[str]) -> list[str]:
    """Retorna colunas físicas ausentes (exceto opcionais e CPF pessoa)."""
    optional = frozenset(
        {
            "d_qtd_pessoas_domic_fam",
            "d_val_desp_aluguel_fam",
        }
    )
    missing: list[str] = []
    for _k, phys in _DOM_COLS.items():
        if phys not in cols and phys not in optional:
            missing.append(phys)
    return missing


def build_domicilio_mview_sql(*, cadu_cols: set[str], has_cpf_col: bool) -> str:
    def q(phys: str) -> str:
        return f"{_col_expr(cadu_cols, phys)}::text"

    # CPF: mesmo critério da mvw_pessoas (só dígitos, lpad 11 se exportação cortou zeros à esquerda).
    if has_cpf_col:
        cpf_sql = f"""
        cpf_por_familia AS (
          SELECT
            vig.norm_familia_cod({q("d_cod_familiar_fam")}) AS codigo_familiar,
            COUNT(
              DISTINCT CASE
                WHEN vig.only_digits({_qi(CPF_PESSOA_COL)}::text) IS NOT NULL
                  AND btrim(vig.only_digits({_qi(CPF_PESSOA_COL)}::text)) <> ''
                  AND length(vig.only_digits({_qi(CPF_PESSOA_COL)}::text)) <= 11
                THEN lpad(vig.only_digits({_qi(CPF_PESSOA_COL)}::text), 11, '0')
              END
            )::bigint AS total_pessoas
          FROM raw.{_qi(CADU_TABLE)}
          WHERE vig.norm_familia_cod({q("d_cod_familiar_fam")}) IS NOT NULL
          GROUP BY 1
        )
        """
    else:
        cpf_sql = """
        cpf_por_familia AS (
          SELECT NULL::text AS codigo_familiar, NULL::bigint AS total_pessoas WHERE false
        )
        """

    sql = f"""
    CREATE MATERIALIZED VIEW vig.mvw_familia_domicilio AS
    WITH {cpf_sql},
    cadu_domic AS (
      SELECT
        vig.norm_familia_cod({q("d_cod_familiar_fam")}) AS codigo_familiar,
        vig.parse_cadu_date({q("d_dat_atual_fam")}) AS data_atualizacao,
        vig.parse_cadu_date({q("d_dat_cadastramento_fam")}) AS data_cadastro,
        vig.ltrim_zeros_text({q("d_cod_local_domic_fam")}) AS situacao_domicilio,
        vig.ltrim_zeros_text({q("d_cod_especie_domic_fam")}) AS especie_domicilio,
        vig.ltrim_zeros_text({q("d_qtd_comodos_domic_fam")}) AS qtd_comodos,
        vig.ltrim_zeros_text({q("d_qtd_comodos_dormitorio_fam")}) AS total_dormitorios,
        vig.ltrim_zeros_text({q("d_cod_material_piso_fam")}) AS tipo_piso,
        vig.ltrim_zeros_text({q("d_cod_material_domic_fam")}) AS tipo_parede,
        vig.ltrim_zeros_text({q("d_cod_agua_canalizada_fam")}) AS agua_canalizada,
        vig.ltrim_zeros_text({q("d_cod_abaste_agua_domic_fam")}) AS abastecimento_agua,
        vig.ltrim_zeros_text({q("d_cod_banheiro_domic_fam")}) AS existencia_banheiro,
        vig.ltrim_zeros_text({q("d_cod_escoa_sanitario_domic_fam")}) AS escoamento_sanitario,
        vig.ltrim_zeros_text({q("d_cod_destino_lixo_domic_fam")}) AS coleta_lixo,
        vig.ltrim_zeros_text({q("d_cod_iluminacao_domic_fam")}) AS tipo_iluminacao,
        vig.ltrim_zeros_text({q("d_cod_calcamento_domic_fam")}) AS tipo_calcamento,
        vig.ltrim_zeros_text({q("d_cod_indigena_reside_fam")}) AS familia_indigena,
        vig.ltrim_zeros_text({q("d_ind_familia_quilombola_fam")}) AS familia_quilombola,
        vig.ltrim_zeros_text({q("d_qtd_familias_domic_fam")}) AS familias_domicilio,
        vig.parse_money_br({q("d_val_desp_aluguel_fam")}::text) AS desp_aluguel,
        NULLIF(regexp_replace(COALESCE({q("d_qtd_pessoas_domic_fam")}::text, ''), '[^0-9]', '', 'g'), '')::integer AS qtd_pessoas_domic,
        vig.ltrim_zeros_text({q("d_cod_centro_assist_fam")}) AS codigo_cras,
        vig.ltrim_zeros_text({q("d_ind_risco_scl_vlco_drts")}) AS risco_violacao_direitos,
        vig.ltrim_zeros_text({q("d_ind_risco_scl_inseg_alim")}) AS inseguranca_alimentar,
        vig.ltrim_zeros_text({q("d_ind_parc_mds_fam")}) AS gpte
      FROM raw.{_qi(CADU_TABLE)}
      WHERE vig.norm_familia_cod({q("d_cod_familiar_fam")}) IS NOT NULL
    ),
    dom_dedup AS (
      SELECT DISTINCT ON (codigo_familiar)
        codigo_familiar,
        situacao_domicilio,
        especie_domicilio,
        qtd_comodos,
        total_dormitorios,
        tipo_piso,
        tipo_parede,
        agua_canalizada,
        abastecimento_agua,
        existencia_banheiro,
        escoamento_sanitario,
        coleta_lixo,
        tipo_iluminacao,
        tipo_calcamento,
        familia_indigena,
        familia_quilombola,
        familias_domicilio,
        desp_aluguel,
        qtd_pessoas_domic,
        codigo_cras,
        risco_violacao_direitos,
        inseguranca_alimentar,
        gpte
      FROM cadu_domic
      ORDER BY
        codigo_familiar,
        data_atualizacao DESC NULLS LAST,
        data_cadastro DESC NULLS LAST
    )
    SELECT
      d.codigo_familiar,
      d.situacao_domicilio,
      d.especie_domicilio,
      d.qtd_comodos,
      d.total_dormitorios,
      d.tipo_piso,
      d.tipo_parede,
      d.agua_canalizada,
      d.abastecimento_agua,
      d.existencia_banheiro,
      d.escoamento_sanitario,
      d.coleta_lixo,
      d.tipo_iluminacao,
      d.tipo_calcamento,
      d.familia_indigena,
      d.familia_quilombola,
      COALESCE(c.total_pessoas, 0)::bigint AS total_pessoas,
      d.familias_domicilio,
      d.desp_aluguel,
      COALESCE(d.qtd_pessoas_domic, c.total_pessoas::integer) AS qtd_pessoas_domic,
      d.codigo_cras,
      d.risco_violacao_direitos,
      d.inseguranca_alimentar,
      d.gpte
    FROM dom_dedup d
    LEFT JOIN cpf_por_familia c ON c.codigo_familiar = d.codigo_familiar
    """
    return re.sub(r"\s+", " ", sql).strip()


@dataclass
class DomicilioRefreshResult:
    row_count: int
    warnings: list[str]


def refresh_domicilio_mview(conn: Connection) -> DomicilioRefreshResult:
    warnings: list[str] = []
    ensure_vig_functions(conn)

    if not _table_exists(conn, "raw", CADU_TABLE):
        raise ValueError("Tabela raw.cecad__cadu não encontrada. Ingeste o CADU antes.")

    cadu_cols = _columns(conn, "raw", CADU_TABLE)
    missing = _validate_domicilio_columns(cadu_cols)
    if missing:
        raise ValueError(
            "Tabela raw.cecad__cadu sem colunas do bloco domicílio: "
            + ", ".join(missing)
            + ". Use o layout CADU (família + domicílio)."
        )

    has_cpf = CPF_PESSOA_COL in cadu_cols
    if not has_cpf:
        warnings.append(
            f"Coluna {CPF_PESSOA_COL} ausente; total_pessoas ficará 0. Confirme ingestão do arquivo 'tudo' com bloco p.*."
        )

    mview_sql = build_domicilio_mview_sql(cadu_cols=cadu_cols, has_cpf_col=has_cpf)

    conn.execute(text("DROP MATERIALIZED VIEW IF EXISTS vig.mvw_familia_domicilio CASCADE"))
    conn.execute(text(mview_sql))
    conn.execute(
        text(
            "CREATE UNIQUE INDEX IF NOT EXISTS mvw_familia_domicilio_cod_uq "
            "ON vig.mvw_familia_domicilio (codigo_familiar)"
        )
    )

    row_count = conn.execute(text("SELECT COUNT(*) FROM vig.mvw_familia_domicilio")).scalar() or 0

    return DomicilioRefreshResult(row_count=int(row_count), warnings=warnings)
