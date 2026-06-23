"""Agregações do painel IVS (layout Observatório MDS)."""

from __future__ import annotations

from sqlalchemy import text
from sqlalchemy.engine import Connection

from ..vigilance.cras_analytics import _cras_key_sql, _cras_nome_sql, _cras_numero_ordem, _sort_cras_items
from ..vigilance.creas_analytics import _creas_filter_clause
from ..vigilance.familia_mview import _columns, ensure_familia_territorial_indexes
from .catalog import DIMENSOES, DIM_POR_SIGLA, DimensaoMeta


def _territorio_clauses(
    *,
    prefix: str,
    num_cras: str | None,
    num_creas: str | None,
    bairro: str | None,
    available_cols: set[str] | None = None,
    conn: Connection | None = None,
) -> tuple[list[str], dict]:
    """Filtro territorial sem btrim (permite índice em num_cras/num_creas)."""
    clauses: list[str] = []
    params: dict = {}

    def _has(col: str) -> bool:
        return available_cols is None or col in available_cols

    if num_cras is not None and _has("num_cras"):
        cod = num_cras.strip()
        if cod == "__sem_cras__":
            clauses.append(f"({prefix}.num_cras IS NULL OR {prefix}.num_cras = '')")
        elif cod and cod != "__todos__":
            clauses.append(f"{prefix}.num_cras = :num_cras")
            params["num_cras"] = cod

    if num_creas is not None:
        cod = num_creas.strip()
        if cod and cod != "__todos__":
            if _has("num_creas"):
                if cod == "__sem_creas__":
                    clauses.append(f"({prefix}.num_creas IS NULL OR {prefix}.num_creas = '')")
                else:
                    clauses.append(f"{prefix}.num_creas = :num_creas")
                    params["num_creas"] = cod
            elif conn is not None:
                extra, p = _creas_filter_clause(cod, alias=prefix, conn=conn)
                part = extra.strip()
                if part.upper().startswith("AND "):
                    part = part[4:].strip()
                if part:
                    clauses.append(part)
                params.update(p)

    if bairro is not None and bairro.strip() and _has("bairro"):
        clauses.append(f"{prefix}.bairro = :bairro")
        params["bairro"] = bairro.strip()

    return clauses, params


def ivs_filter_clause(
    *,
    conn: Connection,
    num_cras: str | None,
    num_creas: str | None,
    bairro: str | None,
) -> tuple[str, dict]:
    """Filtro territorial sobre família (alias f) + elegível (alias i)."""
    terr, params = territorio_filter_clause(
        conn=conn, num_cras=num_cras, num_creas=num_creas, bairro=bairro
    )
    return f"i.elegivel_ivs AND {terr}", params


def territorio_filter_clause(
    *,
    conn: Connection,
    num_cras: str | None,
    num_creas: str | None,
    bairro: str | None,
) -> tuple[str, dict]:
    """Somente recorte CRAS/CREAS/bairro (alias f)."""
    familia_cols = _columns(conn, "vig", "mvw_familia")
    clauses, params = _territorio_clauses(
        prefix="f",
        num_cras=num_cras,
        num_creas=num_creas,
        bairro=bairro,
        available_cols=familia_cols,
        conn=conn,
    )
    if not clauses:
        return "TRUE", params
    return " AND ".join(clauses), params


def _ivs_native_territorial_cols(conn: Connection) -> set[str]:
    if not conn.execute(text("SELECT to_regclass('core.mvw_ivs_familia')")).scalar():
        return set()
    return {"num_cras", "num_creas", "bairro"} & _columns(conn, "core", "mvw_ivs_familia")


def _flag_avg_sql(col: str) -> str:
    return f"ROUND(100.0 * AVG(i.{col}::numeric)::numeric, 2)"


def _idx_avg_sql(col: str) -> str:
    return f"ROUND(AVG(i.{col})::numeric, 4)"


def _pct_acima_sql(idx_col: str) -> str:
    return f"""ROUND(
      100.0 * COUNT(*) FILTER (
        WHERE i.{idx_col} > stats.{idx_col}_avg
      )::numeric
      / NULLIF(COUNT(*), 0),
      1
    )"""


def build_painel_sql(
    *,
    conn: Connection,
    num_cras: str | None,
    num_creas: str | None,
    bairro: str | None,
) -> tuple[str, dict]:
    ensure_familia_territorial_indexes(conn)

    ivs_territorial = _ivs_native_territorial_cols(conn)
    familia_cols = _columns(conn, "vig", "mvw_familia")

    needs_cras = bool(num_cras and num_cras.strip() not in ("", "__todos__"))
    needs_creas = bool(num_creas and num_creas.strip() not in ("", "__todos__"))
    needs_bairro = bool(bairro and bairro.strip())
    use_ivs_native = bool(ivs_territorial) and (
        (not needs_cras or "num_cras" in ivs_territorial)
        and (not needs_creas or "num_creas" in ivs_territorial)
        and (not needs_bairro or "bairro" in ivs_territorial)
    )

    if use_ivs_native:
        ivs_clauses, params = _territorio_clauses(
            prefix="i",
            num_cras=num_cras,
            num_creas=num_creas,
            bairro=bairro,
            available_cols=ivs_territorial,
        )
        ivs_where = " AND ".join(["i.elegivel_ivs", *ivs_clauses])
        base_cte = f"""
    base AS (
      SELECT i.*
      FROM core.mvw_ivs_familia i
      WHERE {ivs_where}
    )"""
    else:
        join_clauses, params = _territorio_clauses(
            prefix="f",
            num_cras=num_cras,
            num_creas=num_creas,
            bairro=bairro,
            available_cols=familia_cols,
            conn=conn,
        )
        join_where = " AND ".join(["i.elegivel_ivs", *join_clauses])
        base_cte = f"""
    base AS (
      SELECT i.*
      FROM core.mvw_ivs_familia i
      INNER JOIN vig.mvw_familia f ON f.codigo_familiar = i.codigo_familiar
      WHERE {join_where}
    )"""

    cadu_clauses, cadu_params = _territorio_clauses(
        prefix="f",
        num_cras=num_cras,
        num_creas=num_creas,
        bairro=bairro,
        available_cols=familia_cols,
        conn=conn,
    )
    params.update(cadu_params)
    cadu_where = " AND ".join(["TRUE", *cadu_clauses]) if cadu_clauses else "TRUE"

    flag_cols = [ind.col for dim in DIMENSOES for ind in dim.indicadores]
    flag_select = ",\n          ".join(f"{_flag_avg_sql(c)} AS {c}_pct" for c in flag_cols)
    idx_cols = [dim.idx_col for dim in DIMENSOES]
    idx_select = ",\n          ".join(f"{_idx_avg_sql(c)} AS {c}" for c in idx_cols)
    pct_acima_select = ",\n          ".join(
        f"{_pct_acima_sql(c)} AS pct_acima_{c.replace('idx_', '')}" for c in idx_cols
    )
    stats_select = ",\n            ".join(f"AVG(i.{c}) AS {c}_avg" for c in idx_cols)

    sql = f"""
    WITH {base_cte},
    stats AS (
      SELECT
        {stats_select}
      FROM base i
    ),
    cadu AS (
      SELECT COUNT(*)::bigint AS total
      FROM vig.mvw_familia f
      WHERE {cadu_where}
    )
    SELECT
      COUNT(*)::bigint AS familias_elegiveis,
      (SELECT total FROM cadu)::bigint AS familias_cadu,
      ROUND(AVG(i.ivs)::numeric, 4) AS ivs_medio,
      {idx_select},
      {pct_acima_select},
      {flag_select}
    FROM base i
    CROSS JOIN stats
    """
    return sql, params


def _dim_from_row(dim: DimensaoMeta, row: dict) -> dict:
    idx = row.get(dim.idx_col)
    pct_acima = row.get(f"pct_acima_{dim.sigla.lower()}")
    indicadores = []
    for ind in dim.indicadores:
        pct = row.get(f"{ind.col}_pct")
        indicadores.append(
            {
                "codigo": ind.codigo,
                "titulo": ind.titulo,
                "pct_familias": float(pct) if pct is not None else None,
            }
        )
    return {
        "sigla": dim.sigla,
        "nome": dim.nome,
        "idx": float(idx) if idx is not None else None,
        "pct_acima_media": float(pct_acima) if pct_acima is not None else None,
        "indicadores": indicadores,
    }


def fetch_ivs_painel(
    conn: Connection,
    *,
    num_cras: str | None,
    num_creas: str | None,
    bairro: str | None,
    dimensao: str | None,
) -> dict:
    sql, params = build_painel_sql(
        conn=conn, num_cras=num_cras, num_creas=num_creas, bairro=bairro
    )
    row = conn.execute(text(sql), params).mappings().first() or {}

    elegiveis = int(row.get("familias_elegiveis") or 0)
    cadu = int(row.get("familias_cadu") or 0)
    pct_cadu = round(100.0 * elegiveis / cadu, 1) if cadu else None

    dimensoes = [_dim_from_row(dim, dict(row)) for dim in DIMENSOES]

    out: dict = {
        "recorte": {
            "num_cras": num_cras,
            "num_creas": num_creas,
            "bairro": bairro.strip() if bairro and bairro.strip() else None,
        },
        "universo": {
            "familias_elegiveis": elegiveis,
            "familias_cadu": cadu,
            "pct_sobre_cadu": pct_cadu,
        },
        "ivs_medio": float(row["ivs_medio"]) if row.get("ivs_medio") is not None else None,
        "dimensoes": dimensoes,
        "versao_metodologica": "1.0.5",
    }

    if dimensao:
        sigla = dimensao.strip().upper()
        det = next((d for d in dimensoes if d["sigla"] == sigla), None)
        if det is None and sigla in DIM_POR_SIGLA:
            det = _dim_from_row(DIM_POR_SIGLA[sigla], dict(row))
        if det:
            out["dimensao_detalhe"] = det

    return out


def fetch_ivs_por_cras(conn: Connection) -> list[dict]:
    ck = _cras_key_sql("f")
    cn = _cras_nome_sql("f")
    rows = conn.execute(
        text(
            f"""
            SELECT
              {ck} AS cras_cod,
              MAX({cn}) AS cras_nome,
              COUNT(*) FILTER (WHERE i.elegivel_ivs)::bigint AS familias_elegiveis,
              ROUND(AVG(i.ivs) FILTER (WHERE i.elegivel_ivs)::numeric, 4) AS ivs_medio,
              ROUND(AVG(i.idx_nc) FILTER (WHERE i.elegivel_ivs)::numeric, 4) AS idx_nc,
              ROUND(AVG(i.idx_dpi) FILTER (WHERE i.elegivel_ivs)::numeric, 4) AS idx_dpi,
              ROUND(AVG(i.idx_dca) FILTER (WHERE i.elegivel_ivs)::numeric, 4) AS idx_dca,
              ROUND(AVG(i.idx_tqa) FILTER (WHERE i.elegivel_ivs)::numeric, 4) AS idx_tqa,
              ROUND(AVG(i.idx_dr) FILTER (WHERE i.elegivel_ivs)::numeric, 4) AS idx_dr,
              ROUND(AVG(i.idx_ch) FILTER (WHERE i.elegivel_ivs)::numeric, 4) AS idx_ch
            FROM core.mvw_ivs_familia i
            INNER JOIN vig.mvw_familia f ON f.codigo_familiar = i.codigo_familiar
            GROUP BY {ck}
            """
        )
    ).mappings().all()

    items: list[dict] = []
    for r in rows:
        cod = (r["cras_cod"] or "").strip()
        nome = str(r["cras_nome"] or "")
        num_ordem = _cras_numero_ordem(cod, nome)
        rotulo = f"CRAS {num_ordem} — {nome}" if num_ordem < 999 else nome
        items.append(
            {
                "cras_cod": cod if cod else "__sem_cras__",
                "cras_nome": nome,
                "cras_numero_ordem": num_ordem if num_ordem < 999 else None,
                "rotulo_ordenado": rotulo,
                "familias_elegiveis": int(r["familias_elegiveis"] or 0),
                "ivs_medio": float(r["ivs_medio"]) if r["ivs_medio"] is not None else None,
                "idx_nc": float(r["idx_nc"]) if r["idx_nc"] is not None else None,
                "idx_dpi": float(r["idx_dpi"]) if r["idx_dpi"] is not None else None,
                "idx_dca": float(r["idx_dca"]) if r["idx_dca"] is not None else None,
                "idx_tqa": float(r["idx_tqa"]) if r["idx_tqa"] is not None else None,
                "idx_dr": float(r["idx_dr"]) if r["idx_dr"] is not None else None,
                "idx_ch": float(r["idx_ch"]) if r["idx_ch"] is not None else None,
            }
        )
    return _sort_cras_items(items)
