"""Indicadores do CADU agrupados por unidade territorial (CREAS)."""

from __future__ import annotations

import re

from sqlalchemy import text
from sqlalchemy.engine import Connection

from .familia_mview import _table_exists

SEXO_MASC = "UPPER(COALESCE(pes.cod_sexo, '')) IN ('1', '01', 'M', 'MASCULINO')"
SEXO_FEM = "UPPER(COALESCE(pes.cod_sexo, '')) IN ('2', '02', 'F', 'FEMININO')"


def _require_views(conn: Connection) -> None:
    if not _table_exists(conn, "vig", "mvw_familia"):
        raise ValueError(
            "Visão vig.mvw_familia ausente. Gere a visão Família em Vigilância antes de usar o painel por CREAS."
        )
    if not _table_exists(conn, "vig", "mvw_pessoas"):
        raise ValueError(
            "Visão vig.mvw_pessoas ausente. Gere a visão Pessoas em Vigilância antes de usar o painel por CREAS."
        )


def _column_exists(conn: Connection, schema: str, table: str, column: str) -> bool:
    return bool(
        conn.execute(
            text(
                """
                SELECT 1
                FROM information_schema.columns
                WHERE table_schema = :s AND table_name = :t AND column_name = :c
                """
            ),
            {"s": schema, "t": table, "c": column},
        ).scalar()
    )


def _geo_has_creas_column(conn: Connection) -> bool:
    return _column_exists(conn, "raw", "geo__tbl_geo", "creas")


def _geo_creas_cte() -> str:
    return """
    geo_creas AS (
      SELECT
        btrim(g.cep_norm::text) AS cep_norm,
        mode() WITHIN GROUP (
          ORDER BY NULLIF(btrim(g.creas::text), '')
        )::text AS creas
      FROM raw."geo__tbl_geo" g
      WHERE g.cep_norm IS NOT NULL
        AND length(btrim(g.cep_norm::text)) = 8
      GROUP BY 1
    )"""


def _familia_creas_resolution(conn: Connection) -> tuple[str, str, str]:
    """Retorna (expr creas, CTE geo_creas, JOIN)."""
    cte = _geo_creas_cte()
    join = "LEFT JOIN geo_creas gc ON gc.cep_norm = btrim(f.cep::text)"
    if _column_exists(conn, "vig", "mvw_familia", "num_creas"):
        val = "COALESCE(NULLIF(btrim(f.num_creas::text), ''), NULLIF(btrim(gc.creas::text), ''))"
    else:
        val = "NULLIF(btrim(gc.creas::text), '')"
    return val, cte, join


def _geo_creas_subquery(alias: str = "f") -> str:
    p = alias
    return f"""(
      SELECT mode() WITHIN GROUP (
        ORDER BY NULLIF(btrim(g.creas::text), '')
      )::text
      FROM raw."geo__tbl_geo" g
      WHERE g.cep_norm = {p}.cep
        AND length(btrim(g.cep_norm::text)) = 8
    )"""


def _creas_val_sql(conn: Connection, alias: str = "f") -> str:
    """CREAS territorial: mvw_familia.num_creas ou, se vazio, creas da geo via CEP."""
    p = alias
    geo = _geo_creas_subquery(p)
    if _column_exists(conn, "vig", "mvw_familia", "num_creas"):
        return f"COALESCE(NULLIF(btrim({p}.num_creas::text), ''), {geo})"
    return geo


def _creas_key_sql(conn: Connection, prefix: str = "f") -> str:
    v = _creas_val_sql(conn, prefix)
    return f"""CASE
      WHEN {v} IS NULL OR btrim({v}::text) = '' THEN ''
      ELSE btrim({v}::text)
    END"""


def _creas_nome_sql(conn: Connection, prefix: str = "f") -> str:
    v = _creas_val_sql(conn, prefix)
    return f"""CASE
      WHEN {v} IS NULL OR btrim({v}::text) = '' THEN '(sem CREAS na geo)'
      ELSE 'CREAS ' || btrim({v}::text)
    END"""


def _creas_numero_ordem(creas_cod: str, creas_nome: str) -> int:
    nome = creas_nome or ""
    m = re.search(r"CREAS\s*(\d+)", nome, flags=re.I)
    if m:
        return int(m.group(1))
    if creas_cod.isdigit():
        return int(creas_cod)
    return 999


def _sort_creas_items(items: list[dict]) -> list[dict]:
    sem = [x for x in items if x.get("creas_cod") == "__sem_creas__"]
    rest = [x for x in items if x.get("creas_cod") != "__sem_creas__"]
    rest.sort(
        key=lambda x: (
            _creas_numero_ordem(str(x.get("creas_cod") or ""), str(x.get("creas_nome") or "")),
            str(x.get("creas_nome") or "").upper(),
        )
    )
    return rest + sem


def creas_catalog_diagnostic(conn: Connection) -> dict:
    from .geo_territorial_maps import geo_territorial_fill_stats, map_counts

    diag: dict = {
        "mvw_familia_tem_coluna_num_creas": _column_exists(conn, "vig", "mvw_familia", "num_creas"),
        "geo_tem_coluna_creas": _geo_has_creas_column(conn),
        "mapas_persistidos": map_counts(conn),
        "geo_preenchimento": geo_territorial_fill_stats(conn),
    }
    if diag["mvw_familia_tem_coluna_num_creas"]:
        fam_com = conn.execute(
            text(
                """
                SELECT COUNT(*)::bigint
                FROM vig.mvw_familia
                WHERE num_creas IS NOT NULL AND btrim(num_creas::text) <> ''
                """
            )
        ).scalar()
        diag["familias_com_num_creas_na_mvw"] = int(fam_com or 0)
    else:
        diag["familias_com_num_creas_na_mvw"] = 0
    if diag["geo_preenchimento"].get("linhas_com_creas", 0) == 0:
        diag["acao_sugerida"] = (
            "Aplique bairros_creas.csv em Ingestão → Geo (botão Aplicar, não só Prévia)."
        )
    return diag


def _creas_filter_clause(creas_cod: str | None, *, alias: str = "f", conn: Connection | None = None) -> tuple[str, dict]:
    if creas_cod is None or creas_cod.strip() in ("", "__todos__"):
        return "", {}
    cod = creas_cod.strip()
    p = alias

    # Caminho rápido: num_creas já materializado em vig.mvw_familia (evita subquery geo por linha).
    if conn is None or _column_exists(conn, "vig", "mvw_familia", "num_creas"):
        if cod == "__sem_creas__":
            return f" AND ({p}.num_creas IS NULL OR {p}.num_creas = '') ", {}
        return f" AND {p}.num_creas = :creas_cod ", {"creas_cod": cod}

    val = _creas_val_sql(conn, p)
    if cod == "__sem_creas__":
        return f" AND ({val} IS NULL OR btrim({val}::text) = '') ", {}
    return f" AND btrim({val}::text) = :creas_cod ", {"creas_cod": cod}


def bairros_por_creas_from_views(conn: Connection, creas_cod: str) -> list[dict]:
    """Bairros distintos vinculados a um CREAS territorial."""
    _require_views(conn)
    cod = (creas_cod or "").strip()
    if not cod or cod in ("__todos__", "__sem_creas__"):
        return []

    val, geo_cte, join = _familia_creas_resolution(conn)
    rows = conn.execute(
        text(
            f"""
            WITH {geo_cte}
            SELECT
              btrim(f.bairro::text) AS bairro,
              COUNT(DISTINCT f.codigo_familiar)::bigint AS familias
            FROM vig.mvw_familia f
            {join}
            WHERE btrim({val}::text) = :creas_cod
              AND f.bairro IS NOT NULL
              AND btrim(f.bairro::text) <> ''
            GROUP BY 1
            ORDER BY familias DESC, bairro ASC
            """
        ),
        {"creas_cod": cod},
    ).mappings().all()

    return [
        {
            "bairro": str(r["bairro"] or ""),
            "familias": int(r["familias"] or 0),
        }
        for r in rows
        if r.get("bairro")
    ]


def build_familia_territorio_ctx(
    conn: Connection,
    *,
    cras_cod: str | None,
    creas_cod: str | None,
    bairro: str | None,
) -> dict:
    """Monta CTE/join/WHERE para filtrar vig.mvw_familia por CRAS/CREAS/bairro."""
    from .cras_analytics import _cras_filter_clause

    cras_sel = (cras_cod or "").strip() or "__todos__"
    creas_sel = (creas_cod or "").strip() or "__todos__"
    params: dict = {}
    parts: list[str] = []

    cras_extra, cras_params = _cras_filter_clause(cras_sel)
    if cras_extra.strip():
        clause = cras_extra.strip()
        if clause.upper().startswith("AND "):
            clause = clause[4:].strip()
        parts.append(clause)
    params.update(cras_params)

    lead_cte = ""
    fam_join = ""
    if creas_sel not in ("", "__todos__"):
        val, geo_cte, join = _familia_creas_resolution(conn)
        lead_cte = geo_cte
        fam_join = join
        if creas_sel == "__sem_creas__":
            parts.append(f"({val} IS NULL OR btrim({val}::text) = '')")
        else:
            parts.append(f"btrim({val}::text) = :creas_cod")
            params["creas_cod"] = creas_sel

    if bairro and bairro.strip():
        parts.append("btrim(f.bairro::text) = :bairro")
        params["bairro"] = bairro.strip()

    where_sql = f" AND {' AND '.join(parts)}" if parts else ""

    return {
        "lead_cte": lead_cte,
        "fam_join": fam_join,
        "where_sql": where_sql,
        "params": params,
        "cras_sel": cras_sel,
        "creas_sel": creas_sel,
    }


def creas_catalog_lite_from_views(conn: Connection) -> list[dict]:
    """Catálogo CREAS leve (só famílias) para filtros territoriais."""
    if not _table_exists(conn, "vig", "mvw_familia"):
        raise ValueError(
            "Visão vig.mvw_familia ausente. Gere a visão Família em Vigilância antes de usar o painel por CREAS."
        )
    val, geo_cte, join = _familia_creas_resolution(conn)
    ck = f"""CASE
      WHEN {val} IS NULL OR btrim({val}::text) = '' THEN ''
      ELSE btrim({val}::text)
    END"""
    rows = conn.execute(
        text(
            f"""
            WITH {geo_cte}
            SELECT
              {ck} AS creas_cod,
              COUNT(DISTINCT f.codigo_familiar)::bigint AS familias
            FROM vig.mvw_familia f
            {join}
            GROUP BY 1
            """
        )
    ).mappings().all()
    out: list[dict] = []
    for r in rows:
        cod = (r["creas_cod"] or "").strip()
        num_ordem = _creas_numero_ordem(cod, f"CREAS {cod}" if cod else "")
        rotulo = f"CREAS {num_ordem}" if num_ordem < 999 and cod else "(sem CREAS na geo)"
        out.append(
            {
                "creas_cod": cod if cod else "__sem_creas__",
                "creas_codigo_exibicao": cod if cod else "—",
                "creas_nome": rotulo,
                "rotulo_ordenado": rotulo,
                "familias": int(r["familias"] or 0),
            }
        )
    return _sort_creas_items(out)


def creas_catalog_from_views(conn: Connection) -> tuple[list[dict], dict]:
    _require_views(conn)
    val, geo_cte, join = _familia_creas_resolution(conn)
    ck = f"""CASE
      WHEN {val} IS NULL OR btrim({val}::text) = '' THEN ''
      ELSE btrim({val}::text)
    END"""
    cn = f"""CASE
      WHEN {val} IS NULL OR btrim({val}::text) = '' THEN '(sem CREAS na geo)'
      ELSE 'CREAS ' || btrim({val}::text)
    END"""
    rows = conn.execute(
        text(
            f"""
            WITH {geo_cte},
            fam AS (
              SELECT
                {ck} AS creas_cod,
                {cn} AS creas_nome,
                f.codigo_familiar,
                COALESCE(f.marc_pbf, FALSE) AS na_folha_pbf,
                f.renda_per_capita
              FROM vig.mvw_familia f
              {join}
            ),
            pes AS (
              SELECT
                p.codigo_familiar,
                p.cadu_row_id,
                p.cod_sexo
              FROM vig.mvw_pessoas p
            )
            SELECT
              fam.creas_cod,
              MAX(fam.creas_nome) AS creas_nome,
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
            GROUP BY fam.creas_cod
            """
        )
    ).mappings().all()

    out: list[dict] = []
    for r in rows:
        cod = (r["creas_cod"] or "").strip()
        nome = str(r["creas_nome"] or "")
        num_ordem = _creas_numero_ordem(cod, nome)
        rotulo = f"CREAS {num_ordem} — {nome}" if num_ordem < 999 else nome
        out.append(
            {
                "creas_cod": cod if cod else "__sem_creas__",
                "creas_codigo_exibicao": cod if cod else "—",
                "creas_nome": nome,
                "creas_numero_ordem": num_ordem if num_ordem < 999 else None,
                "rotulo_ordenado": rotulo,
                "familias": int(r["familias"] or 0),
                "pessoas": int(r["pessoas"] or 0),
                "homens": int(r["homens"] or 0),
                "mulheres": int(r["mulheres"] or 0),
                "familias_pbf": int(r["familias_pbf"] or 0),
                "familias_renda_ate_218": int(r["familias_renda_ate_218"] or 0),
            }
        )
    diagnostic = creas_catalog_diagnostic(conn)
    unidades = [x for x in out if x.get("creas_cod") not in ("", "__sem_creas__")]
    linhas_creas = int((diagnostic.get("geo_preenchimento") or {}).get("linhas_com_creas") or 0)
    if not unidades and linhas_creas > 0:
        diagnostic.pop("acao_sugerida", None)
    elif not unidades and linhas_creas == 0:
        diagnostic["acao_sugerida"] = (
            "Em Ingestão → Geo, envie bairros_creas.csv e clique «Aplicar CREAS na tbl_geo»."
        )
    elif unidades:
        diagnostic.pop("acao_sugerida", None)
    fonte = "geo_cep_join" if diagnostic.get("geo_tem_coluna_creas") else "indisponivel"
    return _sort_creas_items(out), {**diagnostic, "fonte_catalogo": fonte}
