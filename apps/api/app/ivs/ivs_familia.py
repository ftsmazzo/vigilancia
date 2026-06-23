"""Materialized view core.mvw_ivs_familia — IVS (IVCAD v1.0.5) por família."""

from __future__ import annotations

import re
from dataclasses import dataclass

from sqlalchemy import text
from sqlalchemy.engine import Connection

from ..vigilance.cadu_params import (
    LIMIAR_POBREZA_EXTREMA,
    SALARIO_MINIMO,
    SM_METADE,
    sql_universo_ivs_elegivel,
)
from ..vigilance.familia_mview import _columns, _pick_column, _qi, _table_exists
from .functions import ensure_ivs_functions

IVS_VERSION = "1.0.5"

IVS_PARAMS = {
    "salario_minimo": SALARIO_MINIMO,
    "sm_metade": SM_METADE,
    "limiar_pobreza": LIMIAR_POBREZA_EXTREMA,
    "teto_bpc": SALARIO_MINIMO,
}


def _build_bpc_nis_cte(conn: Connection) -> str:
    row = conn.execute(
        text(
            """
            SELECT table_name
            FROM information_schema.tables
            WHERE table_schema = 'raw'
              AND table_name LIKE '%__beneficio_prestacao_continuada'
            ORDER BY table_name
            LIMIT 1
            """
        )
    ).scalar()
    if not row:
        return "bpc_nis AS (SELECT NULL::text AS num_nis WHERE false)"
    cols = _columns(conn, "raw", row)
    nis_col = _pick_column(
        cols,
        ("num_nis", "nis", "nu_nis", "num_nis_pessoa", "num_nis_pessoa_atual"),
    )
    cpf_col = _pick_column(cols, ("num_cpf", "cpf", "num_cpf_pessoa"))
    id_col = nis_col or cpf_col
    if not id_col:
        return "bpc_nis AS (SELECT NULL::text AS num_nis WHERE false)"
    return f"""
    bpc_nis AS (
      SELECT DISTINCT lpad(vig.only_digits(b.{_qi(id_col)}::text), 11, '0') AS num_nis
      FROM raw.{_qi(row)} b
      WHERE vig.only_digits(b.{_qi(id_col)}::text) IS NOT NULL
        AND btrim(vig.only_digits(b.{_qi(id_col)}::text)) <> ''
    )
    """


def build_ivs_familia_sql(
    *,
    bpc_nis_cte: str,
    territorial_cols: frozenset[str] | None = None,
) -> str:
    sm = IVS_PARAMS["salario_minimo"]
    pobreza = IVS_PARAMS["limiar_pobreza"]
    teto_bpc = IVS_PARAMS["teto_bpc"]
    territorial = territorial_cols or frozenset()

    fam_territorial_select = ""
    flags_territorial_select = ""
    indices_territorial_select = ""
    final_territorial_select = ""
    for col in ("num_cras", "num_creas", "bairro"):
        if col in territorial:
            fam_territorial_select += f"        f.{col},\n"
            flags_territorial_select += f"        f.{col},\n"
            indices_territorial_select += f"        {col},\n"
            final_territorial_select += f"      {col},\n"

    sql = f"""
    CREATE MATERIALIZED VIEW core.mvw_ivs_familia AS
    WITH
    {bpc_nis_cte},
    fam AS (
      SELECT
        f.codigo_familiar,
{fam_territorial_select}        f.renda_per_capita,
        COALESCE(f.marc_pbf, FALSE) AS marc_pbf,
        f.marc_pbf_cadu,
        COALESCE(f.vlrtotal, 0)::numeric AS pbf_total,
        f.meses_desatualizado
      FROM vig.mvw_familia f
    ),
    dom AS (
      SELECT
        d.codigo_familiar,
        d.especie_domicilio,
        d.situacao_domicilio,
        NULLIF(regexp_replace(COALESCE(d.total_dormitorios, ''), '[^0-9]', '', 'g'), '')::numeric AS dorm_decl,
        NULLIF(regexp_replace(COALESCE(d.qtd_comodos, ''), '[^0-9]', '', 'g'), '')::numeric AS comodos,
        d.tipo_piso,
        d.tipo_parede,
        d.abastecimento_agua,
        d.existencia_banheiro,
        d.escoamento_sanitario,
        d.coleta_lixo,
        d.tipo_iluminacao,
        COALESCE(d.desp_aluguel, 0)::numeric AS desp_aluguel,
        COALESCE(
          d.qtd_pessoas_domic,
          NULLIF(d.total_pessoas, 0),
          1
        )::numeric AS qtd_pessoas
      FROM vig.mvw_familia_domicilio d
    ),
    sit_rua_fam AS (
      SELECT
        p.codigo_familiar,
        bool_or(vig.cod_sim(p.marc_sit_rua)) AS tem_sit_rua
      FROM vig.mvw_pessoas p
      GROUP BY 1
    ),
    pess AS (
      SELECT
        p.codigo_familiar,
        p.idade,
        btrim(COALESCE(p.cod_sexo, '')) AS cod_sexo,
        vig.cod_sim(p.cod_deficiencia) AS tem_def,
        btrim(COALESCE(p.ind_frequenta_escola, '')) AS freq_escola,
        btrim(COALESCE(p.cod_parentesco_rf, '')) AS parentesco,
        btrim(COALESCE(p.cod_sabe_ler_escrever, '')) AS sabe_ler,
        vig.anos_estudo_aprox(p.grau_instrucao) AS anos_estudo,
        vig.cod_sim(p.ind_trabalho_infantil) AS ti_flag,
        btrim(COALESCE(p.cod_trabalhou, '')) AS cod_trabalhou,
        btrim(COALESCE(p.cod_afastado_trab, '')) AS cod_afastado_trab,
        btrim(COALESCE(p.cod_principal_trab, '')) AS principal_trab,
        vig.pessoa_ocupado(p.cod_trabalhou, p.cod_afastado_trab) AS ocupado,
        LEAST(
          vig.fx_faixa_lb(p.fx_renda_individual_805),
          vig.fx_faixa_lb(p.fx_renda_individual_808) / 12.0
        ) AS rendimento_trab,
        vig.fx_faixa_lb(p.fx_renda_individual_809_2) AS fx_apose,
        p.num_nis
      FROM vig.mvw_pessoas p
    ),
    pess_agg AS (
      SELECT
        codigo_familiar,
        COUNT(*)::numeric AS n_membros,
        MAX(CASE WHEN idade IS NOT NULL AND idade <= 3 THEN 1 ELSE 0 END) AS nc1,
        MAX(CASE WHEN idade IS NOT NULL AND idade <= 6 THEN 1 ELSE 0 END) AS nc2,
        MAX(CASE WHEN idade IS NOT NULL AND idade <= 12 THEN 1 ELSE 0 END) AS nc3,
        MAX(CASE WHEN tem_def THEN 1 ELSE 0 END) AS nc4,
        MAX(CASE WHEN idade IS NOT NULL AND idade >= 60 THEN 1 ELSE 0 END) AS nc5,
        COUNT(*) FILTER (WHERE idade BETWEEN 18 AND 59)::numeric AS n_adultos,
        COUNT(*) FILTER (
          WHERE idade BETWEEN 18 AND 59 AND cod_sexo IN ('2', '02')
        )::numeric AS n_mulheres_adultas,
        MAX(CASE WHEN idade BETWEEN 4 AND 6 AND freq_escola IN ('3','03','4','04') THEN 1 ELSE 0 END) AS dpi1,
        MAX(CASE WHEN idade BETWEEN 0 AND 6 AND freq_escola IN ('3','03','4','04') THEN 1 ELSE 0 END) AS dpi2,
        MAX(CASE
          WHEN idade BETWEEN 0 AND 6
           AND parentesco NOT IN ('3','03','4','04')
           AND parentesco <> ''
          THEN 1 ELSE 0
        END) AS dpi3,
        MAX(CASE
          WHEN idade < 16 AND ti_flag THEN 1
          WHEN idade BETWEEN 10 AND 13 AND ocupado THEN 1
          WHEN idade BETWEEN 14 AND 15 AND ocupado
           AND principal_trab NOT IN ('10','11') THEN 1
          ELSE 0
        END) AS dca1,
        MAX(CASE WHEN idade BETWEEN 15 AND 17 AND freq_escola IN ('3','03','4','04') THEN 1 ELSE 0 END) AS dca2,
        MAX(CASE WHEN idade BETWEEN 7 AND 17 AND freq_escola IN ('3','03','4','04') THEN 1 ELSE 0 END) AS dca3,
        MAX(CASE WHEN idade BETWEEN 10 AND 17 AND sabe_ler IN ('2','02') THEN 1 ELSE 0 END) AS dca4,
        MAX(CASE
          WHEN idade BETWEEN 10 AND 17
           AND anos_estudo IS NOT NULL
           AND (idade - (7 + anos_estudo)) > 2
          THEN 1 ELSE 0
        END) AS dca5,
        MAX(CASE
          WHEN idade BETWEEN 18 AND 59
           AND (sabe_ler IN ('2','02') OR COALESCE(anos_estudo, 99) <= 3)
          THEN 1 ELSE 0
        END) AS tqa1,
        MAX(CASE WHEN idade BETWEEN 18 AND 59 AND COALESCE(anos_estudo, 99) < 8 THEN 1 ELSE 0 END) AS tqa2,
        MAX(CASE WHEN idade BETWEEN 18 AND 59 AND COALESCE(anos_estudo, 99) < 11 THEN 1 ELSE 0 END) AS tqa3,
        MAX(CASE
          WHEN idade BETWEEN 18 AND 59 AND ocupado AND rendimento_trab >= {sm}
          THEN 1 ELSE 0
        END) AS tem_ocupado_1sm,
        MAX(CASE
          WHEN idade BETWEEN 18 AND 59 AND ocupado AND rendimento_trab >= {sm * 2}
          THEN 1 ELSE 0
        END) AS tem_ocupado_2sm,
        MAX(CASE WHEN idade BETWEEN 18 AND 59 AND ocupado THEN 1 ELSE 0 END) AS tem_ocupado,
        MAX(CASE
          WHEN idade BETWEEN 18 AND 59 AND ocupado
           AND principal_trab IN ('4','04','6','06','8','08','9','09','10','11')
          THEN 1 ELSE 0
        END) AS tem_formal,
        SUM(CASE
          WHEN EXISTS (
            SELECT 1 FROM bpc_nis b WHERE b.num_nis = pess.num_nis
          ) THEN
            CASE
              WHEN COALESCE(fx_apose, 0) >= {teto_bpc} THEN {teto_bpc}
              WHEN COALESCE(fx_apose, 0) > 0 THEN fx_apose
              ELSE 0
            END
          ELSE 0
        END)::numeric AS bpc_retirar_total
      FROM pess
      GROUP BY codigo_familiar
    ),
    nc_calc AS (
      SELECT
        codigo_familiar,
        nc1, nc2, nc3, nc4, nc5,
        CASE WHEN n_membros > 0 AND (n_adultos / n_membros) <= 0.5 THEN 1 ELSE 0 END AS nc6,
        CASE
          WHEN (nc3 = 1 OR nc5 = 1 OR nc4 = 1)
           AND n_membros > 0
           AND (n_mulheres_adultas / n_membros) <= 0.5
          THEN 1 ELSE 0
        END AS nc7
      FROM pess_agg
    ),
    dom_ctx AS (
      SELECT
        f.codigo_familiar,
        COALESCE(sr.tem_sit_rua, FALSE) AS sit_rua,
        btrim(COALESCE(d.especie_domicilio, '')) AS especie,
        COALESCE(d.qtd_pessoas, pa.n_membros, 1) AS qtd_pessoas,
        COALESCE(d.dorm_decl, d.comodos - 2) AS n_dorm,
        d.desp_aluguel,
        d.tipo_piso,
        d.tipo_parede,
        d.abastecimento_agua,
        d.existencia_banheiro,
        d.escoamento_sanitario,
        d.coleta_lixo,
        d.tipo_iluminacao,
        f.renda_per_capita,
        f.pbf_total,
        pa.n_membros,
        pa.bpc_retirar_total,
        (
          COALESCE(sr.tem_sit_rua, FALSE)
          OR btrim(COALESCE(d.especie_domicilio, '')) IN ('2', '02')
        ) AS moradia_extrema
      FROM fam f
      LEFT JOIN dom d ON d.codigo_familiar = f.codigo_familiar
      LEFT JOIN sit_rua_fam sr ON sr.codigo_familiar = f.codigo_familiar
      LEFT JOIN pess_agg pa ON pa.codigo_familiar = f.codigo_familiar
    ),
    flags AS (
      SELECT
        f.codigo_familiar,
{flags_territorial_select}        {sql_universo_ivs_elegivel(alias="f")} AS elegivel_ivs,
        nc.nc1, nc.nc2, nc.nc3, nc.nc4, nc.nc5, nc.nc6, nc.nc7,
        pa.dpi1, pa.dpi2, pa.dpi3,
        pa.dca1, pa.dca2, pa.dca3, pa.dca4, pa.dca5,
        pa.tqa1, pa.tqa2, pa.tqa3,
        CASE WHEN COALESCE(pa.tem_ocupado, 0) = 0 THEN 1 ELSE 0 END AS tqa4,
        CASE WHEN COALESCE(pa.tem_formal, 0) = 0 THEN 1 ELSE 0 END AS tqa5,
        CASE WHEN COALESCE(pa.tem_ocupado_1sm, 0) = 0 THEN 1 ELSE 0 END AS tqa6,
        CASE WHEN COALESCE(pa.tem_ocupado_2sm, 0) = 0 THEN 1 ELSE 0 END AS tqa7,
        CASE
          WHEN COALESCE(f.pbf_total, 0)
             + COALESCE(f.renda_per_capita, 0) * COALESCE(pa.n_membros, 1) = 0
          THEN 1 ELSE 0
        END AS dr1,
        CASE
          WHEN (
            COALESCE(f.renda_per_capita, 0)
            + COALESCE(f.pbf_total, 0) / NULLIF(COALESCE(pa.n_membros, 1), 0)
          ) <= {pobreza}
          THEN 1 ELSE 0
        END AS dr2,
        CASE WHEN COALESCE(f.renda_per_capita, 0) <= {pobreza} THEN 1 ELSE 0 END AS dr3,
        CASE
          WHEN (
            COALESCE(f.renda_per_capita, 0)
            - COALESCE(pa.bpc_retirar_total, 0) / NULLIF(COALESCE(pa.n_membros, 1), 0)
          ) <= {pobreza}
          THEN 1 ELSE 0
        END AS dr4,
        CASE WHEN dc.moradia_extrema THEN 1 ELSE 0 END AS ch1,
        CASE
          WHEN dc.especie IN ('3', '03') THEN 0
          WHEN dc.moradia_extrema THEN 1
          WHEN dc.especie IN ('1', '01')
           AND dc.n_dorm >= 1
           AND dc.qtd_pessoas / dc.n_dorm > 3
          THEN 1 ELSE 0
        END AS ch2,
        CASE
          WHEN dc.moradia_extrema THEN 1
          WHEN dc.especie IN ('1', '01')
           AND (
             COALESCE(dc.renda_per_capita, 0) * dc.qtd_pessoas = 0
             OR dc.desp_aluguel >= 0.30 * COALESCE(dc.renda_per_capita, 0) * dc.qtd_pessoas
           )
          THEN 1 ELSE 0
        END AS ch3,
        CASE
          WHEN dc.moradia_extrema THEN 1
          WHEN dc.especie IN ('1', '01')
           AND (
             COALESCE(dc.renda_per_capita, 0) = 0
             OR COALESCE(dc.desp_aluguel, 0) > 0
           )
          THEN 1 ELSE 0
        END AS ch4,
        CASE
          WHEN dc.moradia_extrema THEN 1
          WHEN dc.especie IN ('1', '01')
           AND dc.tipo_piso IN ('1','01','3','03','7','07')
           AND dc.tipo_parede IN ('5','05','6','06','7','07','8','08')
          THEN 1 ELSE 0
        END AS ch5,
        CASE
          WHEN dc.moradia_extrema THEN 1
          WHEN dc.especie IN ('1', '01')
           AND (
             dc.tipo_piso IN ('1','01','3','03','7','07')
             OR dc.tipo_parede IN ('5','05','6','06','7','07','8','08')
           )
          THEN 1 ELSE 0
        END AS ch6,
        CASE
          WHEN dc.moradia_extrema THEN 1
          WHEN dc.especie IN ('1', '01')
           AND dc.abastecimento_agua IN ('2','02','3','03','4','04')
          THEN 1 ELSE 0
        END AS ch7,
        CASE
          WHEN dc.moradia_extrema THEN 1
          WHEN dc.especie IN ('1', '01')
           AND dc.abastecimento_agua IN ('4','04')
          THEN 1 ELSE 0
        END AS ch8,
        CASE
          WHEN dc.moradia_extrema THEN 1
          WHEN dc.especie IN ('1', '01')
           AND dc.existencia_banheiro IN ('2','02')
          THEN 1 ELSE 0
        END AS ch9,
        CASE
          WHEN dc.moradia_extrema THEN 1
          WHEN dc.especie IN ('1', '01')
           AND (
             dc.existencia_banheiro IN ('2','02')
             OR (
               dc.existencia_banheiro IN ('1','01')
               AND dc.escoamento_sanitario IN ('3','03','4','04','5','05','6','06')
             )
           )
          THEN 1 ELSE 0
        END AS ch10,
        CASE
          WHEN dc.moradia_extrema THEN 1
          WHEN dc.especie IN ('1', '01')
           AND dc.coleta_lixo IN ('2','02','3','03','4','04','5','05','6','06')
          THEN 1 ELSE 0
        END AS ch11,
        CASE
          WHEN dc.moradia_extrema THEN 1
          WHEN dc.especie IN ('1', '01')
           AND dc.coleta_lixo IN ('3','03','4','04','5','05','6','06')
          THEN 1 ELSE 0
        END AS ch12,
        CASE
          WHEN dc.moradia_extrema THEN 1
          WHEN dc.especie IN ('1', '01')
           AND dc.tipo_iluminacao IN ('3','03','4','04','5','05','6','06')
          THEN 1 ELSE 0
        END AS ch13,
        CASE
          WHEN dc.moradia_extrema THEN 1
          WHEN dc.especie IN ('1', '01')
           AND dc.tipo_iluminacao IN ('4','04','5','05','6','06')
          THEN 1 ELSE 0
        END AS ch14
      FROM fam f
      JOIN nc_calc nc ON nc.codigo_familiar = f.codigo_familiar
      JOIN pess_agg pa ON pa.codigo_familiar = f.codigo_familiar
      JOIN dom_ctx dc ON dc.codigo_familiar = f.codigo_familiar
    ),
    indices AS (
      SELECT
        codigo_familiar,
{indices_territorial_select}        elegivel_ivs,
        nc1, nc2, nc3, nc4, nc5, nc6, nc7,
        dpi1, dpi2, dpi3,
        dca1, dca2, dca3, dca4, dca5,
        tqa1, tqa2, tqa3, tqa4, tqa5, tqa6, tqa7,
        dr1, dr2, dr3, dr4,
        ch1, ch2, ch3, ch4, ch5, ch6, ch7, ch8, ch9, ch10, ch11, ch12, ch13, ch14,
        (nc1 + nc2 + nc3 + nc4 + nc5 + nc6 + nc7) / 7.0 AS idx_nc,
        (dpi1 + dpi2 + dpi3) / 3.0 AS idx_dpi,
        (dca1 + dca2 + dca3 + dca4 + dca5) / 5.0 AS idx_dca,
        (tqa1 + tqa2 + tqa3 + tqa4 + tqa5 + tqa6 + tqa7) / 7.0 AS idx_tqa,
        (dr1 + dr2 + dr3 + dr4) / 4.0 AS idx_dr,
        (ch1 + ch2 + ch3 + ch4 + ch5 + ch6 + ch7 + ch8 + ch9 + ch10 + ch11 + ch12 + ch13 + ch14) / 14.0 AS idx_ch
      FROM flags
    )
    SELECT
      codigo_familiar,
{final_territorial_select}      elegivel_ivs,
      nc1, nc2, nc3, nc4, nc5, nc6, nc7,
      dpi1, dpi2, dpi3,
      dca1, dca2, dca3, dca4, dca5,
      tqa1, tqa2, tqa3, tqa4, tqa5, tqa6, tqa7,
      dr1, dr2, dr3, dr4,
      ch1, ch2, ch3, ch4, ch5, ch6, ch7, ch8, ch9, ch10, ch11, ch12, ch13, ch14,
      idx_nc, idx_dpi, idx_dca, idx_tqa, idx_dr, idx_ch,
      CASE
        WHEN elegivel_ivs THEN
          (idx_nc + idx_dpi + idx_dca + idx_tqa + idx_dr + idx_ch) / 6.0
        ELSE NULL
      END AS ivs,
      CASE
        WHEN elegivel_ivs THEN
          (idx_nc + idx_dpi + idx_dca + idx_tqa + idx_dr + idx_ch) / 6.0
        ELSE NULL
      END AS ivcad,
      '{IVS_VERSION}'::text AS versao_metodologica,
      NOW() AS calculado_em
    FROM indices
    """
    return re.sub(r"\s+", " ", sql).strip()


@dataclass
class IvsRefreshResult:
    row_count: int
    elegivel_count: int
    warnings: list[str]


def refresh_ivs_familia(conn: Connection) -> IvsRefreshResult:
    warnings: list[str] = []
    ensure_ivs_functions(conn)

    for mv in ("vig.mvw_familia", "vig.mvw_pessoas", "vig.mvw_familia_domicilio"):
        schema, name = mv.split(".")
        if not _table_exists(conn, schema, name):
            raise ValueError(
                f"Materialized view {mv} ausente. "
                "Atualize família, pessoas e domicílio antes do IVS."
            )

    bpc_cte = _build_bpc_nis_cte(conn)
    if "WHERE false" in bpc_cte:
        warnings.append(
            "Tabela BPC (Maciça) não encontrada ou sem NIS/CPF — DR4 usa proxy por faixa aposentadoria."
        )

    mview_sql = build_ivs_familia_sql(
        bpc_nis_cte=bpc_cte,
        territorial_cols=frozenset(
            c for c in ("num_cras", "num_creas", "bairro") if c in _columns(conn, "vig", "mvw_familia")
        ),
    )

    conn.execute(text("DROP MATERIALIZED VIEW IF EXISTS core.mvw_ivs_familia CASCADE"))
    conn.execute(text(mview_sql))
    conn.execute(
        text(
            "CREATE UNIQUE INDEX IF NOT EXISTS mvw_ivs_familia_cod_uq "
            "ON core.mvw_ivs_familia (codigo_familiar)"
        )
    )
    conn.execute(
        text(
            "CREATE INDEX IF NOT EXISTS mvw_ivs_familia_elegivel_idx "
            "ON core.mvw_ivs_familia (elegivel_ivs) WHERE elegivel_ivs"
        )
    )
    ivs_cols = _columns(conn, "core", "mvw_ivs_familia")
    if "num_cras" in ivs_cols:
        conn.execute(
            text(
                "CREATE INDEX IF NOT EXISTS mvw_ivs_familia_num_cras_idx "
                "ON core.mvw_ivs_familia (num_cras)"
            )
        )
    if "num_creas" in ivs_cols:
        conn.execute(
            text(
                "CREATE INDEX IF NOT EXISTS mvw_ivs_familia_num_creas_idx "
                "ON core.mvw_ivs_familia (num_creas)"
            )
        )

    stats = conn.execute(
        text(
            """
            SELECT
              COUNT(*)::bigint AS total,
              COUNT(*) FILTER (WHERE elegivel_ivs)::bigint AS elegivel
            FROM core.mvw_ivs_familia
            """
        )
    ).mappings().first()

    return IvsRefreshResult(
        row_count=int(stats["total"] or 0),
        elegivel_count=int(stats["elegivel"] or 0),
        warnings=warnings,
    )
