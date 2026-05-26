"""Indicadores do CADU agrupados por unidade territorial (CRAS)."""

from __future__ import annotations

from sqlalchemy import text
from sqlalchemy.engine import Connection

from .familia_mview import _table_exists

SEXO_MASC = "UPPER(COALESCE(pes.cod_sexo, '')) IN ('1', '01', 'M', 'MASCULINO')"
SEXO_FEM = "UPPER(COALESCE(pes.cod_sexo, '')) IN ('2', '02', 'F', 'FEMININO')"


def _require_views(conn: Connection) -> None:
    if not _table_exists(conn, "vig", "mvw_familia"):
        raise ValueError(
            "Visão vig.mvw_familia ausente. Gere a visão Família em Vigilância antes de usar o painel por CRAS."
        )
    if not _table_exists(conn, "vig", "mvw_pessoas"):
        raise ValueError(
            "Visão vig.mvw_pessoas ausente. Gere a visão Pessoas em Vigilância antes de usar o painel por CRAS."
        )


def _cras_key_sql(prefix: str = "f") -> str:
    """Chave estável: código CRAS ou marcador sem unidade."""
    p = prefix
    return f"""CASE
      WHEN {p}.num_cras IS NULL OR btrim({p}.num_cras::text) = '' THEN ''
      ELSE btrim({p}.num_cras::text)
    END"""


def _cras_nome_sql(prefix: str = "f") -> str:
    p = prefix
    return f"""CASE
      WHEN {p}.nom_cras IS NULL OR btrim({p}.nom_cras::text) = '' THEN '(sem nome no CADU)'
      ELSE btrim({p}.nom_cras::text)
    END"""


def _cras_filter_clause(cras_cod: str | None) -> tuple[str, dict]:
    if cras_cod is None or cras_cod.strip() in ("", "__todos__"):
        return "", {}
    cod = cras_cod.strip()
    if cod == "__sem_cras__":
        return " AND (f.num_cras IS NULL OR btrim(f.num_cras::text) = '') ", {}
    return " AND btrim(f.num_cras::text) = :cras_cod ", {"cras_cod": cod}


def cras_catalog_from_views(conn: Connection) -> list[dict]:
    _require_views(conn)
    ck = _cras_key_sql("f")
    cn = _cras_nome_sql("f")
    rows = conn.execute(
        text(
            f"""
            WITH fam AS (
              SELECT
                {ck} AS cras_cod,
                {cn} AS cras_nome,
                f.codigo_familiar,
                COALESCE(f.marc_pbf, FALSE) AS na_folha_pbf,
                f.renda_per_capita
              FROM vig.mvw_familia f
            ),
            pes AS (
              SELECT
                p.codigo_familiar,
                p.cadu_row_id,
                p.cod_sexo
              FROM vig.mvw_pessoas p
            )
            SELECT
              fam.cras_cod,
              MAX(fam.cras_nome) AS cras_nome,
              COUNT(DISTINCT fam.codigo_familiar)::bigint AS familias,
              COUNT(pes.cadu_row_id)::bigint AS pessoas,
              COUNT(pes.cadu_row_id) FILTER (WHERE {SEXO_MASC})::bigint AS homens,
              COUNT(pes.cadu_row_id) FILTER (WHERE {SEXO_FEM})::bigint AS mulheres,
              COUNT(DISTINCT fam.codigo_familiar) FILTER (WHERE fam.na_folha_pbf)::bigint AS familias_pbf,
              COUNT(DISTINCT fam.codigo_familiar) FILTER (
                WHERE fam.renda_per_capita IS NOT NULL AND fam.renda_per_capita <= 218
              )::bigint AS familias_renda_ate_218
            FROM fam
            LEFT JOIN pes ON pes.codigo_familiar = fam.codigo_familiar
            GROUP BY fam.cras_cod
            ORDER BY familias DESC, cras_nome
            """
        )
    ).mappings().all()
    out: list[dict] = []
    for r in rows:
        cod = (r["cras_cod"] or "").strip()
        out.append(
            {
                "cras_cod": cod if cod else "__sem_cras__",
                "cras_codigo_exibicao": cod if cod else "—",
                "cras_nome": r["cras_nome"],
                "familias": int(r["familias"] or 0),
                "pessoas": int(r["pessoas"] or 0),
                "homens": int(r["homens"] or 0),
                "mulheres": int(r["mulheres"] or 0),
                "familias_pbf": int(r["familias_pbf"] or 0),
                "familias_renda_ate_218": int(r["familias_renda_ate_218"] or 0),
            }
        )
    return out


def _bucket(
    conn: Connection,
    sql: str,
    params: dict,
    limit: int = 10,
) -> list[dict]:
    rows = conn.execute(text(sql), {**params, "lim": limit}).mappings().all()
    return [
        {
            "rotulo": r["rotulo"],
            "total": int(r["total"] or 0),
            "pct": float(r["pct"] or 0),
        }
        for r in rows
    ]


def cras_painel_from_views(conn: Connection, cras_cod: str | None = None) -> dict:
    _require_views(conn)
    where_extra, params = _cras_filter_clause(cras_cod)
    ck = _cras_key_sql("f")
    cn = _cras_nome_sql("f")

    base = conn.execute(
        text(
            f"""
            WITH fam AS (
              SELECT f.*
              FROM vig.mvw_familia f
              WHERE TRUE {where_extra}
            ),
            pes AS (
              SELECT p.*
              FROM vig.mvw_pessoas p
              INNER JOIN fam ON fam.codigo_familiar = p.codigo_familiar
            )
            SELECT
              COUNT(DISTINCT fam.codigo_familiar)::bigint AS familias,
              COUNT(pes.cadu_row_id)::bigint AS pessoas,
              COUNT(pes.cadu_row_id) FILTER (WHERE {SEXO_MASC})::bigint AS homens,
              COUNT(pes.cadu_row_id) FILTER (WHERE {SEXO_FEM})::bigint AS mulheres,
              COUNT(DISTINCT fam.codigo_familiar) FILTER (WHERE COALESCE(fam.marc_pbf, FALSE))::bigint AS familias_pbf,
              COUNT(DISTINCT fam.codigo_familiar) FILTER (
                WHERE fam.renda_per_capita IS NOT NULL AND fam.renda_per_capita <= 218
              )::bigint AS familias_renda_ate_218,
              COUNT(DISTINCT fam.codigo_familiar) FILTER (
                WHERE fam.renda_per_capita IS NOT NULL
                  AND fam.renda_per_capita > 218
                  AND fam.renda_per_capita <= 706
              )::bigint AS familias_renda_219_706,
              COUNT(DISTINCT fam.codigo_familiar) FILTER (
                WHERE fam.meses_desatualizado IS NOT NULL AND fam.meses_desatualizado <= 24
              )::bigint AS familias_tac_24m,
              MAX({cn}) AS cras_nome,
              MAX({ck}) AS cras_cod_raw
            FROM fam
            LEFT JOIN pes ON pes.codigo_familiar = fam.codigo_familiar
            """
        ),
        params,
    ).mappings().first()

    if not base:
        return {"disponivel": False, "mensagem": "Sem dados."}

    familias = int(base["familias"] or 0)
    pessoas = int(base["pessoas"] or 0)
    homens = int(base["homens"] or 0)
    mulheres = int(base["mulheres"] or 0)
    denom_sexo = homens + mulheres

    cras_sel = cras_cod.strip() if cras_cod else "__todos__"
    if cras_sel in ("", "__todos__"):
        titulo = "Município — todos os CRAS (CADU)"
        cod_exib = "__todos__"
    elif cras_sel == "__sem_cras__":
        titulo = "Famílias sem CRAS informado no CADU"
        cod_exib = "__sem_cras__"
    else:
        titulo = base.get("cras_nome") or cras_sel
        cod_exib = cras_sel

    denom_fam = familias or 1
    payload: dict = {
        "disponivel": True,
        "cras_selecionado": cod_exib,
        "cras_titulo": titulo,
        "dicionario": {
            "codigo_campo": "d.cod_unidade_territorial_fam → vig.mvw_familia.num_cras",
            "nome_campo": "d.nom_unidade_territorial_fam → vig.mvw_familia.nom_cras",
            "fonte": "Cadastro Único (visões Família + Pessoas)",
        },
        "resumo": {
            "familias": familias,
            "pessoas": pessoas,
            "homens": homens,
            "mulheres": mulheres,
            "pct_homens": round(100.0 * homens / denom_sexo, 2) if denom_sexo else 0.0,
            "pct_mulheres": round(100.0 * mulheres / denom_sexo, 2) if denom_sexo else 0.0,
            "familias_pbf": int(base["familias_pbf"] or 0),
            "pct_familias_pbf": round(100.0 * int(base["familias_pbf"] or 0) / denom_fam, 2),
            "familias_renda_ate_218": int(base["familias_renda_ate_218"] or 0),
            "familias_renda_219_706": int(base["familias_renda_219_706"] or 0),
            "familias_tac_24m": int(base["familias_tac_24m"] or 0),
            "pct_renda_ate_218": round(100.0 * int(base["familias_renda_ate_218"] or 0) / denom_fam, 2),
        },
    }

    if cras_sel in ("", "__todos__"):
        payload["tabela_cras"] = cras_catalog_from_views(conn)
    else:
        payload["por_bairro"] = _bucket(
            conn,
            f"""
            SELECT
              COALESCE(NULLIF(btrim(f.bairro::text), ''), '(sem bairro)') AS rotulo,
              COUNT(DISTINCT f.codigo_familiar)::bigint AS total,
              ROUND(
                100.0 * COUNT(DISTINCT f.codigo_familiar)
                  / NULLIF((SELECT COUNT(DISTINCT codigo_familiar) FROM vig.mvw_familia f WHERE TRUE {where_extra}), 0),
                2
              ) AS pct
            FROM vig.mvw_familia f
            WHERE TRUE {where_extra}
            GROUP BY 1
            ORDER BY total DESC
            LIMIT :lim
            """,
            params,
            12,
        )
        payload["por_faixa_renda"] = _bucket(
            conn,
            f"""
            SELECT
              COALESCE(NULLIF(btrim(f.faixa_renda::text), ''), '(sem faixa)') AS rotulo,
              COUNT(DISTINCT f.codigo_familiar)::bigint AS total,
              ROUND(
                100.0 * COUNT(DISTINCT f.codigo_familiar)
                  / NULLIF((SELECT COUNT(DISTINCT codigo_familiar) FROM vig.mvw_familia f WHERE TRUE {where_extra}), 0),
                2
              ) AS pct
            FROM vig.mvw_familia f
            WHERE TRUE {where_extra}
            GROUP BY 1
            ORDER BY total DESC
            LIMIT :lim
            """,
            params,
            10,
        )

    return payload
