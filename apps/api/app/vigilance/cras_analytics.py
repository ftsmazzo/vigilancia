"""Indicadores do CADU agrupados por unidade territorial (CRAS)."""

from __future__ import annotations

import re

from sqlalchemy import text
from sqlalchemy.engine import Connection

from .cadu_classificacao import (
    cadu_sim,
    classificacao_deficiencia_sql,
    classificacao_escolaridade_sql,
    classificacao_idade_sql,
    classificacao_raca_sql,
    tem_deficiencia_expr,
)
from .cadu_params import SM_METADE
from .familia_mview import _table_exists

SISC_MVIEW = "mvw_sisc_qualificado"
PAINEL_CRAS_VERSAO = 2

SEXO_MASC = "UPPER(COALESCE(pes.cod_sexo, '')) IN ('1', '01', 'M', 'MASCULINO')"
SEXO_FEM = "UPPER(COALESCE(pes.cod_sexo, '')) IN ('2', '02', 'F', 'FEMININO')"

IDADE_EXPR = classificacao_idade_sql("pes.idade")
ESCOLARIDADE_EXPR = classificacao_escolaridade_sql("pes.grau_instrucao")
RACA_EXPR = classificacao_raca_sql("pes.cod_raca_cor")
DEFICIENCIA_EXPR = classificacao_deficiencia_sql("pes")
TEM_DEFICIENCIA = tem_deficiencia_expr("pes")


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


def _cras_numero_ordem(cras_cod: str, cras_nome: str) -> int:
    """
    Ordem de exibição: número após 'CRAS' no nome; Bonfim sem código → 9 (referência local).
  """
    nome = cras_nome or ""
    nome_u = nome.upper()
    if "BONFIM" in nome_u:
        return 9
    m = re.search(r"CRAS\s*(\d+)", nome, flags=re.I)
    if m:
        return int(m.group(1))
    return 999


def _sort_cras_items(items: list[dict]) -> list[dict]:
    sem = [x for x in items if x.get("cras_cod") == "__sem_cras__"]
    rest = [x for x in items if x.get("cras_cod") != "__sem_cras__"]
    rest.sort(
        key=lambda x: (
            _cras_numero_ordem(str(x.get("cras_cod") or ""), str(x.get("cras_nome") or "")),
            str(x.get("cras_nome") or "").upper(),
        )
    )
    return rest + sem


def bairros_por_cras_from_views(conn: Connection, cras_cod: str) -> list[dict]:
    """Bairros distintos vinculados a um CRAS territorial (vig.mvw_familia)."""
    _require_views(conn)
    cod = (cras_cod or "").strip()
    if not cod or cod in ("__todos__", "__sem_cras__"):
        return []

    rows = conn.execute(
        text(
            """
            SELECT
              btrim(f.bairro::text) AS bairro,
              COUNT(DISTINCT f.codigo_familiar)::bigint AS familias
            FROM vig.mvw_familia f
            WHERE btrim(f.num_cras::text) = :cras_cod
              AND f.bairro IS NOT NULL
              AND btrim(f.bairro::text) <> ''
            GROUP BY 1
            ORDER BY familias DESC, bairro ASC
            """
        ),
        {"cras_cod": cod},
    ).mappings().all()

    return [
        {
            "bairro": str(r["bairro"] or ""),
            "familias": int(r["familias"] or 0),
        }
        for r in rows
        if r.get("bairro")
    ]


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
            """
        )
    ).mappings().all()
    out: list[dict] = []
    for r in rows:
        cod = (r["cras_cod"] or "").strip()
        nome = str(r["cras_nome"] or "")
        num_ordem = _cras_numero_ordem(cod, nome)
        rotulo = (
            f"CRAS {num_ordem} — {nome}"
            if num_ordem < 999
            else nome
        )
        out.append(
            {
                "cras_cod": cod if cod else "__sem_cras__",
                "cras_codigo_exibicao": cod if cod else "—",
                "cras_nome": nome,
                "cras_numero_ordem": num_ordem if num_ordem < 999 else None,
                "rotulo_ordenado": rotulo,
                "familias": int(r["familias"] or 0),
                "pessoas": int(r["pessoas"] or 0),
                "homens": int(r["homens"] or 0),
                "mulheres": int(r["mulheres"] or 0),
                "familias_pbf": int(r["familias_pbf"] or 0),
                "familias_renda_ate_218": int(r["familias_renda_ate_218"] or 0),
            }
        )
    return _sort_cras_items(out)


def _fam_pes_cte(where_extra: str) -> str:
    return f"""
    WITH fam AS (
      SELECT f.* FROM vig.mvw_familia f WHERE TRUE {where_extra}
    ),
    pes AS (
      SELECT p.* FROM vig.mvw_pessoas p
      INNER JOIN fam ON fam.codigo_familiar = p.codigo_familiar
    )
    """


def _pessoas_bucket(
    conn: Connection,
    where_extra: str,
    params: dict,
    group_expr: str,
    limit: int = 12,
) -> list[dict]:
    sql = f"""
    {_fam_pes_cte(where_extra)}
    SELECT
      bucket AS rotulo,
      COUNT(*)::bigint AS total,
      ROUND(100.0 * COUNT(*) / NULLIF((SELECT COUNT(*) FROM pes), 0), 2) AS pct
    FROM (
      SELECT ({group_expr}) AS bucket FROM pes
    ) sub
    GROUP BY 1
    ORDER BY total DESC
    LIMIT :lim
    """
    return _bucket(conn, sql, params, limit)


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


def _sisc_disponivel(conn: Connection) -> bool:
    return _table_exists(conn, "vig", SISC_MVIEW)


def _sisc_filter_clause(cras_sel: str) -> tuple[str, dict]:
    if cras_sel in ("", "__todos__"):
        return "", {}
    if cras_sel == "__sem_cras__":
        return " AND (cras_codigo IS NULL OR btrim(cras_codigo::text) = '') ", {}
    return " AND btrim(cras_codigo::text) = :sisc_cras_cod ", {"sisc_cras_cod": cras_sel}


def _sisc_painel(conn: Connection, cras_sel: str) -> dict:
    if not _sisc_disponivel(conn):
        return {
            "disponivel": False,
            "mensagem": (
                "Qualificação SISC não gerada. Em Convivência, clique em «Qualificar atendidos» "
                "após ingerir o SISC.csv."
            ),
        }

    where_sisc, params = _sisc_filter_clause(cras_sel)

    if cras_sel in ("", "__todos__"):
        rows = conn.execute(
            text(
                f"""
                SELECT
                  COALESCE(NULLIF(btrim(cras_codigo::text), ''), '__sem_codigo__') AS cras_cod,
                  MAX(cras_nome) AS cras_nome,
                  COUNT(*)::bigint AS atendimentos,
                  COUNT(DISTINCT nis_norm)::bigint AS nis_distintos,
                  COUNT(*) FILTER (WHERE classificacao_vinculo = 'vinculado_cadu')::bigint AS vinculados_cadu,
                  COUNT(*) FILTER (WHERE classificacao_atendimento = 'prioritario')::bigint AS prioritarios,
                  COUNT(*) FILTER (WHERE tem_deficiencia)::bigint AS com_deficiencia
                FROM vig.{SISC_MVIEW}
                GROUP BY 1
                ORDER BY atendimentos DESC
                """
            )
        ).mappings().all()
        return {
            "disponivel": True,
            "modo": "municipal",
            "tabela_por_cras": [
                {
                    "cras_cod": r["cras_cod"],
                    "cras_nome": r["cras_nome"],
                    "atendimentos": int(r["atendimentos"] or 0),
                    "nis_distintos": int(r["nis_distintos"] or 0),
                    "vinculados_cadu": int(r["vinculados_cadu"] or 0),
                    "prioritarios": int(r["prioritarios"] or 0),
                    "com_deficiencia": int(r["com_deficiencia"] or 0),
                }
                for r in rows
            ],
        }

    resumo = conn.execute(
        text(
            f"""
            SELECT
              COUNT(*)::bigint AS atendimentos,
              COUNT(DISTINCT nis_norm)::bigint AS nis_distintos,
              COUNT(*) FILTER (WHERE classificacao_vinculo = 'vinculado_cadu')::bigint AS vinculados_cadu,
              COUNT(*) FILTER (WHERE classificacao_atendimento = 'prioritario')::bigint AS prioritarios,
              COUNT(*) FILTER (WHERE tem_deficiencia)::bigint AS com_deficiencia,
              COUNT(*) FILTER (WHERE classificacao_vinculo = 'sem_vinculo_cadu')::bigint AS sem_vinculo_cadu
            FROM vig.{SISC_MVIEW}
            WHERE TRUE {where_sisc}
            """
        ),
        params,
    ).mappings().first()

    por_faixa_sisc = _bucket(
        conn,
        f"""
        SELECT
          COALESCE(NULLIF(btrim(faixa_etaria::text), ''), '(não informado)') AS rotulo,
          COUNT(*)::bigint AS total,
          ROUND(
            100.0 * COUNT(*) / NULLIF((SELECT COUNT(*) FROM vig.{SISC_MVIEW} WHERE TRUE {where_sisc}), 0),
            2
          ) AS pct
        FROM vig.{SISC_MVIEW}
        WHERE TRUE {where_sisc}
        GROUP BY 1
        ORDER BY total DESC
        LIMIT :lim
        """,
        params,
        10,
    )

    por_grupo_sisc = _bucket(
        conn,
        f"""
        SELECT
          COALESCE(NULLIF(btrim(grupo::text), ''), '(sem grupo)') AS rotulo,
          COUNT(*)::bigint AS total,
          ROUND(
            100.0 * COUNT(*) / NULLIF((SELECT COUNT(*) FROM vig.{SISC_MVIEW} WHERE TRUE {where_sisc}), 0),
            2
          ) AS pct
        FROM vig.{SISC_MVIEW}
        WHERE TRUE {where_sisc}
        GROUP BY 1
        ORDER BY total DESC
        LIMIT :lim
        """,
        params,
        8,
    )

    r = resumo or {}
    atend = int(r.get("atendimentos") or 0)
    vinc = int(r.get("vinculados_cadu") or 0)
    return {
        "disponivel": True,
        "modo": "unidade",
        "resumo": {
            "atendimentos": atend,
            "nis_distintos": int(r.get("nis_distintos") or 0),
            "vinculados_cadu": vinc,
            "pct_vinculados_cadu": round(100.0 * vinc / atend, 2) if atend else 0.0,
            "prioritarios": int(r.get("prioritarios") or 0),
            "com_deficiencia": int(r.get("com_deficiencia") or 0),
            "sem_vinculo_cadu": int(r.get("sem_vinculo_cadu") or 0),
        },
        "por_faixa_etaria": por_faixa_sisc,
        "por_grupo": por_grupo_sisc,
    }


def cras_painel_from_views(conn: Connection, cras_cod: str | None = None) -> dict:
    _require_views(conn)
    where_extra, params = _cras_filter_clause(cras_cod)
    ck = _cras_key_sql("fam")
    cn = _cras_nome_sql("fam")

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
                  AND fam.renda_per_capita <= {SM_METADE}
              )::bigint AS familias_renda_219_706,
              COUNT(DISTINCT fam.codigo_familiar) FILTER (
                WHERE fam.meses_desatualizado IS NOT NULL AND fam.meses_desatualizado <= 24
              )::bigint AS familias_tac_24m,
              COUNT(pes.cadu_row_id) FILTER (WHERE {TEM_DEFICIENCIA})::bigint AS pessoas_com_deficiencia,
              COUNT(pes.cadu_row_id) FILTER (WHERE {cadu_sim('pes.marc_sit_rua')})::bigint AS pessoas_situacao_rua,
              COUNT(pes.cadu_row_id) FILTER (WHERE {cadu_sim('pes.ind_atend_cras')})::bigint AS pessoas_atendidas_cras,
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
        titulo = "Famílias sem CRAS territorial na geo (CEP sem match ou sem cras)"
        cod_exib = "__sem_cras__"
    else:
        titulo = base.get("cras_nome") or cras_sel
        cod_exib = cras_sel

    denom_fam = familias or 1
    pessoas_def = int(base.get("pessoas_com_deficiencia") or 0)
    payload: dict = {
        "disponivel": True,
        "painel_versao": PAINEL_CRAS_VERSAO,
        "cras_selecionado": cod_exib,
        "cras_titulo": titulo,
        "dicionario": {
            "codigo_campo": "raw.geo__tbl_geo.cras → vig.mvw_familia.num_cras (via CEP)",
            "nome_campo": "derivado: 'CRAS ' || num_cras",
            "fonte": "Cadastro Único + territorialização geo (CEP × tbl_geo)",
            "campos_pessoa": (
                "p.dta_nasc_pessoa/idade, p.cod_sexo_pessoa, p.cod_raca_cor_pessoa, "
                "p.grau_instrucao, p.cod_deficiencia_memb, p.ind_atend_cras_memb, p.marc_sit_rua"
            ),
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
            "pessoas_com_deficiencia": pessoas_def,
            "pct_pessoas_deficiencia": round(100.0 * pessoas_def / pessoas, 2) if pessoas else 0.0,
            "pessoas_situacao_rua": int(base.get("pessoas_situacao_rua") or 0),
            "pessoas_atendidas_cras": int(base.get("pessoas_atendidas_cras") or 0),
        },
        "por_faixa_idade": _pessoas_bucket(conn, where_extra, params, IDADE_EXPR, 8),
        "sisc": _sisc_painel(conn, cras_sel),
    }

    if cras_sel in ("", "__todos__"):
        payload["tabela_cras"] = cras_catalog_from_views(conn)
    else:
        payload["por_escolaridade"] = _pessoas_bucket(conn, where_extra, params, ESCOLARIDADE_EXPR, 10)
        payload["por_deficiencia"] = _pessoas_bucket(conn, where_extra, params, DEFICIENCIA_EXPR, 10)
        payload["por_raca"] = _pessoas_bucket(conn, where_extra, params, RACA_EXPR, 8)
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
