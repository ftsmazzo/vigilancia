"""Perfil sociodemográfico do CADU (caracterização municipal)."""

from __future__ import annotations

from sqlalchemy import text
from sqlalchemy.engine import Connection

from .cadu_classificacao import (
    classificacao_deficiencia_sql,
    classificacao_escolaridade_sql,
    classificacao_idade_sql,
    classificacao_raca_sql,
    classificacao_sexo_sql,
    tem_deficiencia_expr,
)
from .cras_analytics import (
    SEXO_FEM,
    SEXO_MASC,
    _cras_filter_clause,
    _cras_nome_sql,
    _pessoas_bucket,
    _require_views,
)
from .familia_mview import _table_exists

PAINEL_CARACTERIZACAO_VERSAO = 3

GEO_TABLE = "geo__tbl_geo"

# Faixas de renda per capita familiar (valores em R$, vig.mvw_familia.renda_per_capita).
RENDA_FAIXA_ORDER = (
    "renda_0_218",
    "renda_219_810",
    "renda_811_1621",
    "renda_1622_3242",
    "renda_acima_3242",
    "renda_nao_informada",
)

IDADE_EXPR = classificacao_idade_sql("pes.idade")
SEXO_EXPR = classificacao_sexo_sql("pes.cod_sexo")
RACA_EXPR = classificacao_raca_sql("pes.cod_raca_cor")
ESCOLARIDADE_EXPR = classificacao_escolaridade_sql("pes.grau_instrucao")
DEFICIENCIA_EXPR = classificacao_deficiencia_sql("pes")
DEF_BINARIA_EXPR = (
    f"CASE WHEN ({tem_deficiencia_expr('pes')}) THEN 'com_deficiencia' ELSE 'sem_deficiencia' END"
)


def _familia_renda_per_capita_buckets(
    conn: Connection,
    where_extra: str,
    params: dict,
) -> list[dict]:
    """Contagem de famílias por faixa de renda per capita (ordem fixa para o gráfico)."""
    sql = f"""
    WITH fam AS (
      SELECT f.codigo_familiar, f.renda_per_capita
      FROM vig.mvw_familia f
      WHERE TRUE {where_extra}
    ),
    classified AS (
      SELECT
        CASE
          WHEN renda_per_capita IS NULL THEN 'renda_nao_informada'
          WHEN renda_per_capita < 0 THEN 'renda_nao_informada'
          WHEN renda_per_capita <= 218 THEN 'renda_0_218'
          WHEN renda_per_capita <= 810 THEN 'renda_219_810'
          WHEN renda_per_capita <= 1621 THEN 'renda_811_1621'
          WHEN renda_per_capita <= 3242 THEN 'renda_1622_3242'
          ELSE 'renda_acima_3242'
        END AS rotulo,
        codigo_familiar
      FROM fam
    )
    SELECT
      rotulo,
      COUNT(DISTINCT codigo_familiar)::bigint AS total,
      ROUND(
        100.0 * COUNT(DISTINCT codigo_familiar)
          / NULLIF((SELECT COUNT(DISTINCT codigo_familiar) FROM fam), 0),
        2
      ) AS pct
    FROM classified
    GROUP BY rotulo
    """
    rows = {
        str(r["rotulo"]): r for r in conn.execute(text(sql), params).mappings().all()
    }
    out: list[dict] = []
    for key in RENDA_FAIXA_ORDER:
        row = rows.get(key)
        out.append(
            {
                "rotulo": key,
                "total": int(row["total"] or 0) if row else 0,
                "pct": float(row["pct"] or 0) if row else 0.0,
            }
        )
    return out


def _ranking_bairros_geo(
    conn: Connection,
    where_extra: str,
    params: dict,
    *,
    limit: int = 10,
) -> dict:
    """
    Top bairros por famílias, usando bairro territorial da geo (vig.mvw_familia, chave CEP).
    """
    if not _table_exists(conn, "vig", "mvw_familia"):
        return {
            "disponivel": False,
            "mensagem": "Visão vig.mvw_familia ausente.",
            "items": [],
        }

    sql = f"""
    WITH fam AS (
      SELECT
        f.codigo_familiar,
        COALESCE(
          NULLIF(btrim(f.bairro::text), ''),
          '(sem bairro)'
        ) AS bairro_label,
        COALESCE(f.tem_geo, FALSE) AS bairro_via_geo,
        COALESCE(f.marc_pbf, FALSE) AS na_folha_pbf
      FROM vig.mvw_familia f
      WHERE TRUE {where_extra}
    ),
    agg AS (
      SELECT
        bairro_label,
        COUNT(*) FILTER (WHERE bairro_via_geo)::bigint AS familias_com_bairro_geo,
        COUNT(*) FILTER (WHERE NOT bairro_via_geo)::bigint AS familias_bairro_cadu,
        COUNT(DISTINCT codigo_familiar)::bigint AS familias,
        COUNT(DISTINCT codigo_familiar) FILTER (WHERE na_folha_pbf)::bigint AS familias_pbf
      FROM fam
      GROUP BY bairro_label
    )
    SELECT
      bairro_label,
      familias,
      familias_pbf,
      familias_com_bairro_geo,
      familias_bairro_cadu,
      ROUND(100.0 * familias_pbf / NULLIF(familias, 0), 2) AS pct_pbf,
      ROUND(100.0 * familias / NULLIF((SELECT SUM(familias) FROM agg), 0), 2) AS pct_do_total
    FROM agg
    ORDER BY familias DESC
    LIMIT :lim
    """
    rows = conn.execute(text(sql), {**params, "lim": limit}).mappings().all()
    items = [
        {
            "posicao": i + 1,
            "bairro": str(r["bairro_label"] or "(sem bairro)"),
            "familias": int(r["familias"] or 0),
            "familias_pbf": int(r["familias_pbf"] or 0),
            "pct_pbf": float(r["pct_pbf"] or 0),
            "pct_do_total": float(r["pct_do_total"] or 0),
            "familias_bairro_geo": int(r["familias_com_bairro_geo"] or 0),
            "familias_bairro_cadu": int(r["familias_bairro_cadu"] or 0),
        }
        for i, r in enumerate(rows)
    ]
    return {
        "disponivel": True,
        "fonte_bairro": "vig.mvw_familia.bairro via CEP × raw.geo__tbl_geo (tem_geo=true)",
        "fonte_pbf": "Famílias com marc_pbf na visão (vínculo folha PBF no CADU)",
        "items": items,
    }


def _titulo_escopo(cras_sel: str, cras_nome: str | None, bairro: str | None = None) -> str:
    if cras_sel in ("", "__todos__"):
        base = "Município — Cadastro Único (todas as famílias)"
    elif cras_sel == "__sem_cras__":
        base = "Famílias sem CRAS territorial na geo (CEP sem match)"
    else:
        base = cras_nome or f"CRAS {cras_sel}"
    if bairro and bairro.strip():
        return f"{base} · {bairro.strip()}"
    return base


def _territorio_filter_clause(
    cras_cod: str | None,
    bairro: str | None = None,
) -> tuple[str, dict]:
    cras_sel = (cras_cod or "").strip() or "__todos__"
    where_extra, params = _cras_filter_clause(cras_sel)
    if bairro and bairro.strip():
        where_extra += " AND btrim(f.bairro::text) = :bairro "
        params["bairro"] = bairro.strip()
    return where_extra, params


def caracterizacao_painel_from_views(
    conn: Connection,
    cras_cod: str | None = None,
    bairro: str | None = None,
) -> dict:
    """Demografia de pessoas no CADU (fonte verdade), com filtro territorial opcional."""
    _require_views(conn)
    cras_sel = (cras_cod or "").strip() or "__todos__"
    where_extra, params = _territorio_filter_clause(cras_sel, bairro)
    cn = _cras_nome_sql("fam")

    base = conn.execute(
        text(
            f"""
            WITH fam AS (
              SELECT f.* FROM vig.mvw_familia f WHERE TRUE {where_extra}
            ),
            pes AS (
              SELECT p.* FROM vig.mvw_pessoas p
              INNER JOIN fam ON fam.codigo_familiar = p.codigo_familiar
            )
            SELECT
              COUNT(DISTINCT fam.codigo_familiar)::bigint AS familias,
              COUNT(pes.cadu_row_id)::bigint AS pessoas,
              COUNT(pes.cadu_row_id) FILTER (WHERE {SEXO_MASC})::bigint AS homens,
              COUNT(pes.cadu_row_id) FILTER (WHERE {SEXO_FEM})::bigint AS mulheres,
              MAX({cn}) AS cras_nome
            FROM fam
            LEFT JOIN pes ON pes.codigo_familiar = fam.codigo_familiar
            """
        ),
        params,
    ).mappings().first()

    if not base:
        return {"disponivel": False, "mensagem": "Sem dados no CADU para o recorte selecionado."}

    familias = int(base["familias"] or 0)
    pessoas = int(base["pessoas"] or 0)
    homens = int(base["homens"] or 0)
    mulheres = int(base["mulheres"] or 0)
    denom_sexo = homens + mulheres

    return {
        "disponivel": True,
        "painel_versao": PAINEL_CARACTERIZACAO_VERSAO,
        "cras_selecionado": cras_sel,
        "bairro_selecionado": bairro.strip() if bairro and bairro.strip() else None,
        "titulo": _titulo_escopo(cras_sel, base.get("cras_nome"), bairro),
        "fonte": "Cadastro Único — vig.mvw_familia + vig.mvw_pessoas",
        "resumo": {
            "familias": familias,
            "pessoas": pessoas,
            "homens": homens,
            "mulheres": mulheres,
            "pct_homens": round(100.0 * homens / denom_sexo, 2) if denom_sexo else 0.0,
            "pct_mulheres": round(100.0 * mulheres / denom_sexo, 2) if denom_sexo else 0.0,
            "nao_informado_sexo": max(0, pessoas - denom_sexo),
        },
        "por_sexo": _pessoas_bucket(conn, where_extra, params, SEXO_EXPR, 5),
        "por_deficiencia_binario": _pessoas_bucket(conn, where_extra, params, DEF_BINARIA_EXPR, 3),
        "por_raca": _pessoas_bucket(conn, where_extra, params, RACA_EXPR, 8),
        "por_escolaridade": _pessoas_bucket(conn, where_extra, params, ESCOLARIDADE_EXPR, 10),
        "por_deficiencia": _pessoas_bucket(conn, where_extra, params, DEFICIENCIA_EXPR, 10),
        "por_faixa_idade": _pessoas_bucket(conn, where_extra, params, IDADE_EXPR, 8),
        "por_renda_per_capita": _familia_renda_per_capita_buckets(conn, where_extra, params),
        "ranking_bairros": _ranking_bairros_geo(conn, where_extra, params),
    }
