"""Qualificação SISC (Serviço de Convivência) × CADU via NIS."""

from __future__ import annotations

import re
from dataclasses import dataclass

from sqlalchemy import text
from sqlalchemy.engine import Connection

from .familia_mview import _qi, _table_exists, ensure_vig_functions

SISC_TABLE = "sisc__sisc"
MVIEW_NAME = "mvw_sisc_qualificado"


def _columns(conn: Connection, schema: str, table: str) -> set[str]:
    rows = conn.execute(
        text(
            """
            SELECT column_name
            FROM information_schema.columns
            WHERE table_schema = :schema AND table_name = :table
            """
        ),
        {"schema": schema, "table": table},
    ).all()
    return {r[0] for r in rows}


def _pick(cols: set[str], candidates: tuple[str, ...]) -> str | None:
    for c in candidates:
        if c in cols:
            return c
    lower = {x.lower(): x for x in cols}
    for c in candidates:
        if c.lower() in lower:
            return lower[c.lower()]
    return None


def _col_expr(cols: set[str], candidates: tuple[str, ...], cast: str = "text") -> str:
    phys = _pick(cols, candidates)
    if not phys:
        return f"NULL::{cast}"
    return f"s.{_qi(phys)}::{cast}"


def _cadu_sim(col: str) -> str:
    return f"btrim(COALESCE({col}::text, '')) IN ('1', '01', 'sim', 's', 'true', 'yes')"


def _classificacao_sexo_sql(col: str = "p.cod_sexo") -> str:
    c = f"btrim(COALESCE({col}::text, ''))"
    return f"""CASE
      WHEN {c} IN ('1', '01') THEN 'masculino'
      WHEN {c} IN ('2', '02') THEN 'feminino'
      WHEN UPPER({c}) IN ('M', 'MASCULINO') THEN 'masculino'
      WHEN UPPER({c}) IN ('F', 'FEMININO') THEN 'feminino'
      ELSE 'nao_informado'
    END"""


def _classificacao_raca_sql(col: str = "p.cod_raca_cor") -> str:
    c = f"btrim(COALESCE({col}::text, ''))"
    return f"""CASE
      WHEN {c} IN ('1', '01') THEN 'branca'
      WHEN {c} IN ('2', '02') THEN 'preta'
      WHEN {c} IN ('3', '03') THEN 'amarela'
      WHEN {c} IN ('4', '04') THEN 'parda'
      WHEN {c} IN ('5', '05') THEN 'indigena'
      WHEN {c} <> '' THEN 'outro_codigo'
      ELSE 'nao_informado'
    END"""


def _classificacao_escolaridade_sql(col: str = "p.grau_instrucao") -> str:
    c = f"btrim(COALESCE({col}::text, ''))"
    return f"""CASE
      WHEN {c} IN ('1', '01') THEN 'analfabeto'
      WHEN {c} IN ('2', '02') THEN 'fundamental_incompleto'
      WHEN {c} IN ('3', '03') THEN 'fundamental_completo'
      WHEN {c} IN ('4', '04') THEN 'medio_incompleto'
      WHEN {c} IN ('5', '05') THEN 'medio_completo'
      WHEN {c} IN ('6', '06') THEN 'superior_incompleto'
      WHEN {c} IN ('7', '07') THEN 'superior_completo'
      WHEN {c} <> '' THEN 'outro_codigo'
      ELSE 'nao_informado'
    END"""


def _classificacao_idade_sql(col: str = "p.idade") -> str:
    return f"""CASE
      WHEN {col} IS NULL THEN 'idade_nao_informada'
      WHEN {col} < 12 THEN 'crianca_0_11'
      WHEN {col} < 18 THEN 'adolescente_12_17'
      WHEN {col} < 60 THEN 'adulto_18_59'
      ELSE 'idoso_60_mais'
    END"""


def build_sisc_qualificacao_mview_sql(sisc_cols: set[str]) -> str:
    nis_expr = f"vig.norm_nis({_col_expr(sisc_cols, ('nu_nis_pessoa', 'nis', 'num_nis'), 'text')})"
    sexo_sql = _classificacao_sexo_sql()
    raca_sql = _classificacao_raca_sql()
    esc_sql = _classificacao_escolaridade_sql()
    idade_sql = _classificacao_idade_sql()

    def_flag = " OR ".join(
        _cadu_sim(f"p.{f}")
        for f in (
            "cod_deficiencia",
            "ind_def_cegueira",
            "ind_def_baixa_visao",
            "ind_def_surdez_profunda",
            "ind_def_surdez_leve",
            "ind_def_fisica",
            "ind_def_mental",
            "ind_def_sindrome_down",
            "ind_def_transtorno_mental",
        )
    )

    n_tipos_def = " + ".join(
        f"CASE WHEN {_cadu_sim(f'p.{f}')} THEN 1 ELSE 0 END"
        for f in (
            "ind_def_cegueira",
            "ind_def_baixa_visao",
            "ind_def_surdez_profunda",
            "ind_def_surdez_leve",
            "ind_def_fisica",
            "ind_def_mental",
            "ind_def_sindrome_down",
            "ind_def_transtorno_mental",
        )
    )

    tipo_def_sql = f"""CASE
      WHEN p.num_nis IS NULL THEN 'sem_vinculo_cadu'
      WHEN NOT ({def_flag}) THEN 'sem_deficiencia'
      WHEN ({n_tipos_def}) >= 2 THEN 'deficiencia_multipla'
      WHEN {_cadu_sim('p.ind_def_fisica')} THEN 'deficiencia_fisica'
      WHEN {_cadu_sim('p.ind_def_cegueira')} OR {_cadu_sim('p.ind_def_baixa_visao')} THEN 'deficiencia_visual'
      WHEN {_cadu_sim('p.ind_def_surdez_profunda')} OR {_cadu_sim('p.ind_def_surdez_leve')} THEN 'deficiencia_auditiva'
      WHEN {_cadu_sim('p.ind_def_mental')} OR {_cadu_sim('p.ind_def_transtorno_mental')}
        OR {_cadu_sim('p.ind_def_sindrome_down')} THEN 'deficiencia_mental_cognitiva'
      WHEN {_cadu_sim('p.cod_deficiencia')} THEN 'com_deficiencia_sem_tipo'
      ELSE 'sem_deficiencia'
    END"""

    sql = f"""
    CREATE MATERIALIZED VIEW vig.{MVIEW_NAME} AS
    WITH sisc_raw AS (
      SELECT
        s.id AS sisc_row_id,
        {nis_expr} AS nis_norm,
        vig.clean_spaces({_col_expr(sisc_cols, ('no_pessoa', 'nome'), 'text')}) AS sisc_nome,
        vig.clean_spaces({_col_expr(sisc_cols, ('no_grupo', 'grupo'), 'text')}) AS grupo,
        vig.clean_spaces({_col_expr(sisc_cols, ('no_cras', 'cras_nome'), 'text')}) AS cras_nome,
        vig.clean_spaces({_col_expr(sisc_cols, ('nu_cras', 'cras_codigo'), 'text')}) AS cras_codigo,
        vig.clean_spaces({_col_expr(sisc_cols, ('co_seq_faixa_etaria', 'faixa_etaria'), 'text')}) AS faixa_etaria,
        lower(vig.clean_spaces({_col_expr(sisc_cols, ('co_situacao_prioritaria',), 'text')})) AS situacao_prioritaria,
        lower(vig.clean_spaces({_col_expr(sisc_cols, ('st_intergeracional', 'intergeracional'), 'text')})) AS intergeracional,
        vig.parse_cadu_date({_col_expr(sisc_cols, ('dt_nasc_pessoa', 'data_nascimento'), 'text')}) AS dt_nasc_sisc,
        btrim({_col_expr(sisc_cols, ('dt_relatorio',), 'text')}) AS dt_relatorio
      FROM raw.{_qi(SISC_TABLE)} AS s
      WHERE {nis_expr} IS NOT NULL
    ),
    pessoa AS (
      SELECT DISTINCT ON (num_nis)
        num_nis,
        codigo_familiar,
        cadu_row_id,
        nome,
        data_nascimento,
        idade,
        cod_sexo,
        cod_raca_cor,
        grau_instrucao,
        cod_deficiencia,
        ind_def_cegueira,
        ind_def_baixa_visao,
        ind_def_surdez_profunda,
        ind_def_surdez_leve,
        ind_def_fisica,
        ind_def_mental,
        ind_def_sindrome_down,
        ind_def_transtorno_mental,
        marc_sit_rua,
        ind_frequenta_escola
      FROM vig.mvw_pessoas
      WHERE num_nis IS NOT NULL
      ORDER BY num_nis, cadu_row_id DESC
    ),
    joined AS (
      SELECT
        sr.*,
        p.codigo_familiar,
        p.cadu_row_id,
        p.nome AS cadu_nome,
        p.idade AS cadu_idade,
        p.cod_sexo AS cadu_sexo_cod,
        p.cod_raca_cor AS cadu_raca_cod,
        p.grau_instrucao AS cadu_grau_instrucao_cod,
        f.renda_per_capita,
        f.faixa_renda,
        f.marc_pbf_cadu,
        COALESCE(f.marc_pbf, FALSE) AS familia_na_folha_pbf,
        CASE
          WHEN p.num_nis IS NOT NULL THEN 'vinculado_cadu'
          ELSE 'sem_vinculo_cadu'
        END AS classificacao_vinculo,
        CASE
          WHEN p.num_nis IS NULL THEN 'nao_localizado_cadu'
          WHEN COALESCE(f.marc_pbf, FALSE) THEN 'cadu_com_bolsa_familia'
          WHEN btrim(COALESCE(f.marc_pbf_cadu::text, '')) IN ('1', '01', 'sim', 's', 'true') THEN 'cadu_marcador_pbf'
          WHEN f.renda_per_capita IS NOT NULL AND f.renda_per_capita <= 218 THEN 'cadu_renda_ate_218'
          WHEN f.renda_per_capita IS NOT NULL AND f.renda_per_capita <= 706 THEN 'cadu_renda_219_706'
          WHEN f.renda_per_capita IS NOT NULL THEN 'cadu_renda_acima_706'
          ELSE 'cadu_sem_indicador_renda'
        END AS classificacao_social,
        CASE
          WHEN sr.situacao_prioritaria IN ('sim', 's', '1', 'true', 'yes') THEN 'prioritario'
          ELSE 'regular'
        END AS classificacao_atendimento,
        CASE
          WHEN sr.intergeracional IN ('sim', 's', '1', 'true', 'yes') THEN 'intergeracional_sim'
          WHEN sr.intergeracional IN ('nao', 'não', 'n', '0', 'false', 'no') THEN 'intergeracional_nao'
          ELSE 'intergeracional_nao_informado'
        END AS classificacao_intergeracional,
        CASE WHEN p.num_nis IS NULL THEN 'sem_vinculo_cadu' ELSE {sexo_sql} END AS classificacao_sexo,
        CASE WHEN p.num_nis IS NULL THEN 'sem_vinculo_cadu' ELSE {raca_sql} END AS classificacao_raca,
        CASE WHEN p.num_nis IS NULL THEN 'sem_vinculo_cadu' ELSE {esc_sql} END AS classificacao_escolaridade,
        CASE WHEN p.num_nis IS NULL THEN 'sem_vinculo_cadu' ELSE {idade_sql} END AS classificacao_faixa_idade,
        ({tipo_def_sql}) AS classificacao_deficiencia,
        CASE
          WHEN p.num_nis IS NULL THEN FALSE
          ELSE ({def_flag})
        END AS tem_deficiencia,
        CASE
          WHEN p.num_nis IS NULL THEN FALSE
          ELSE {_cadu_sim('p.marc_sit_rua')}
        END AS situacao_rua,
        CASE
          WHEN p.num_nis IS NULL THEN 'sem_vinculo_cadu'
          WHEN {_cadu_sim('p.ind_frequenta_escola')} THEN 'frequenta_escola_sim'
          WHEN btrim(COALESCE(p.ind_frequenta_escola::text, '')) IN ('2', '02', 'nao', 'não', 'n', '0') THEN 'frequenta_escola_nao'
          ELSE 'frequenta_escola_nao_informado'
        END AS classificacao_frequenta_escola
      FROM sisc_raw sr
      LEFT JOIN pessoa p ON p.num_nis = sr.nis_norm
      LEFT JOIN vig.mvw_familia f ON f.codigo_familiar = p.codigo_familiar
    )
    SELECT * FROM joined
    """
    return re.sub(r"\s+", " ", sql).strip()


@dataclass
class SiscRefreshResult:
    row_count: int
    nis_distintos: int
    warnings: list[str]


def refresh_sisc_qualificacao_mview(conn: Connection) -> SiscRefreshResult:
    warnings: list[str] = []
    ensure_vig_functions(conn)

    if not _table_exists(conn, "raw", SISC_TABLE):
        raise ValueError(
            f"Tabela raw.{SISC_TABLE} não encontrada. Ingeste o SISC.csv (source=sisc, dataset=sisc) antes."
        )
    if not _table_exists(conn, "vig", "mvw_pessoas"):
        raise ValueError(
            "Visão vig.mvw_pessoas ausente. Atualize a visão Pessoas na página Vigilância antes de qualificar o SISC."
        )
    if not _table_exists(conn, "vig", "mvw_familia"):
        raise ValueError(
            "Visão vig.mvw_familia ausente. Atualize a visão Família na página Vigilância antes de qualificar o SISC."
        )

    sisc_cols = _columns(conn, "raw", SISC_TABLE)
    if not _pick(sisc_cols, ("nu_nis_pessoa", "nis", "num_nis")):
        raise ValueError("SISC RAW sem coluna de NIS (esperado nu_nis_pessoa).")

    mview_sql = build_sisc_qualificacao_mview_sql(sisc_cols)
    conn.execute(text(f"DROP MATERIALIZED VIEW IF EXISTS vig.{MVIEW_NAME} CASCADE"))
    conn.execute(text(mview_sql))
    for idx_name, col in (
        ("mvw_sisc_qual_nis_idx", "nis_norm"),
        ("mvw_sisc_qual_vinculo_idx", "classificacao_vinculo"),
        ("mvw_sisc_qual_sexo_idx", "classificacao_sexo"),
    ):
        conn.execute(
            text(f"CREATE INDEX IF NOT EXISTS {idx_name} ON vig.{MVIEW_NAME} ({col})")
        )

    stats = conn.execute(
        text(
            f"""
            SELECT
              COUNT(*)::bigint AS total,
              COUNT(DISTINCT nis_norm)::bigint AS nis_distintos
            FROM vig.{MVIEW_NAME}
            """
        )
    ).mappings().first()

    return SiscRefreshResult(
        row_count=int(stats["total"] or 0) if stats else 0,
        nis_distintos=int(stats["nis_distintos"] or 0) if stats else 0,
        warnings=warnings,
    )


def _mview_exists(conn: Connection) -> bool:
    return _table_exists(conn, "vig", MVIEW_NAME)


def _count_bucket(
    conn: Connection,
    group_col: str,
    limit: int = 15,
    *,
    where_sql: str = "",
) -> list[dict]:
    where_clause = f"WHERE {where_sql}" if where_sql else ""
    rows = conn.execute(
        text(
            f"""
            SELECT
              COALESCE(NULLIF(btrim({group_col}::text), ''), '(vazio)') AS rotulo,
              COUNT(*)::bigint AS total,
              ROUND(100.0 * COUNT(*) / NULLIF((SELECT COUNT(*) FROM vig.{MVIEW_NAME} {where_clause}), 0), 2) AS pct
            FROM vig.{MVIEW_NAME}
            {where_clause}
            GROUP BY 1
            ORDER BY total DESC
            LIMIT :lim
            """
        ),
        {"lim": limit},
    ).mappings().all()
    return [dict(r) for r in rows]


_VINC = "classificacao_vinculo = 'vinculado_cadu'"


def sisc_kpis_from_mview(conn: Connection) -> dict:
    if not _mview_exists(conn):
        return {
            "disponivel": False,
            "mensagem": (
                "Qualificação ainda não gerada. Ingeste o SISC e clique em «Qualificar atendidos» no painel Convivência."
            ),
        }

    base = conn.execute(
        text(
            f"""
            SELECT
              COUNT(*)::bigint AS total_linhas,
              COUNT(DISTINCT nis_norm)::bigint AS nis_distintos,
              COUNT(*) FILTER (WHERE classificacao_vinculo = 'vinculado_cadu')::bigint AS vinculados,
              COUNT(*) FILTER (WHERE classificacao_vinculo = 'sem_vinculo_cadu')::bigint AS sem_vinculo,
              COUNT(*) FILTER (WHERE classificacao_atendimento = 'prioritario')::bigint AS prioritarios,
              COUNT(*) FILTER (WHERE familia_na_folha_pbf)::bigint AS com_bolsa_familia,
              COUNT(*) FILTER (WHERE classificacao_social = 'cadu_renda_ate_218')::bigint AS renda_ate_218,
              COUNT(*) FILTER (WHERE {_VINC} AND classificacao_sexo = 'feminino')::bigint AS mulheres,
              COUNT(*) FILTER (WHERE {_VINC} AND classificacao_sexo = 'masculino')::bigint AS homens,
              COUNT(*) FILTER (WHERE tem_deficiencia)::bigint AS com_deficiencia,
              COUNT(*) FILTER (WHERE situacao_rua)::bigint AS situacao_rua,
              COUNT(*) FILTER (WHERE {_VINC} AND classificacao_faixa_idade = 'idoso_60_mais')::bigint AS idosos_60
            FROM vig.{MVIEW_NAME}
            """
        )
    ).mappings().first()
    if not base:
        return {"disponivel": False, "mensagem": "Sem dados na qualificação SISC."}

    total = int(base["total_linhas"] or 0)
    vinc = int(base["vinculados"] or 0)
    pct_vinc = round(100.0 * vinc / total, 2) if total else 0.0
    mulheres = int(base["mulheres"] or 0)
    homens = int(base["homens"] or 0)
    denom_sexo = mulheres + homens

    return {
        "disponivel": True,
        "view": f"vig.{MVIEW_NAME}",
        "total_linhas": total,
        "nis_distintos": int(base["nis_distintos"] or 0),
        "vinculo_cadu": {
            "vinculados": vinc,
            "sem_vinculo": int(base["sem_vinculo"] or 0),
            "pct_vinculados": pct_vinc,
        },
        "prioritarios": int(base["prioritarios"] or 0),
        "com_bolsa_familia": int(base["com_bolsa_familia"] or 0),
        "renda_ate_218": int(base["renda_ate_218"] or 0),
        "mulheres": mulheres,
        "homens": homens,
        "pct_mulheres": round(100.0 * mulheres / denom_sexo, 2) if denom_sexo else 0.0,
        "pct_homens": round(100.0 * homens / denom_sexo, 2) if denom_sexo else 0.0,
        "com_deficiencia": int(base["com_deficiencia"] or 0),
        "situacao_rua": int(base["situacao_rua"] or 0),
        "idosos_60": int(base["idosos_60"] or 0),
        "por_vinculo": _count_bucket(conn, "classificacao_vinculo", 5),
        "por_classificacao_social": _count_bucket(conn, "classificacao_social", 12),
        "por_grupo": _count_bucket(conn, "grupo", 12),
        "por_cras": _count_bucket(conn, "cras_nome", 10),
        "por_faixa_etaria": _count_bucket(conn, "faixa_etaria", 10),
        "por_sexo": _count_bucket(conn, "classificacao_sexo", 6, where_sql=_VINC),
        "por_raca": _count_bucket(conn, "classificacao_raca", 8, where_sql=_VINC),
        "por_escolaridade": _count_bucket(conn, "classificacao_escolaridade", 10, where_sql=_VINC),
        "por_faixa_idade_cadu": _count_bucket(conn, "classificacao_faixa_idade", 8, where_sql=_VINC),
        "por_deficiencia": _count_bucket(conn, "classificacao_deficiencia", 10, where_sql=_VINC),
        "por_atendimento": _count_bucket(conn, "classificacao_atendimento", 5),
        "por_intergeracional": _count_bucket(conn, "classificacao_intergeracional", 5),
        "por_frequenta_escola": _count_bucket(conn, "classificacao_frequenta_escola", 5, where_sql=_VINC),
    }
