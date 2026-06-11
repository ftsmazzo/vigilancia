"""Agregações do painel IVS (layout Observatório MDS)."""

from __future__ import annotations

from sqlalchemy import text
from sqlalchemy.engine import Connection

from ..vigilance.cras_analytics import _cras_key_sql, _cras_nome_sql, _cras_numero_ordem, _sort_cras_items
from .catalog import DIMENSOES, DIM_POR_SIGLA, DimensaoMeta


def ivs_filter_clause(*, num_cras: str | None, bairro: str | None) -> tuple[str, dict]:
    """Filtro territorial sobre família (alias f) + elegível (alias i)."""
    terr, params = territorio_filter_clause(num_cras=num_cras, bairro=bairro)
    return f"i.elegivel_ivs AND {terr}", params


def territorio_filter_clause(*, num_cras: str | None, bairro: str | None) -> tuple[str, dict]:
    """Somente recorte CRAS/bairro (alias f)."""
    clauses = ["TRUE"]
    params: dict = {}
    if num_cras is not None:
        cod = num_cras.strip()
        if cod == "__sem_cras__":
            clauses.append("(f.num_cras IS NULL OR btrim(f.num_cras::text) = '')")
        elif cod:
            clauses.append("btrim(f.num_cras::text) = :num_cras")
            params["num_cras"] = cod
    if bairro is not None and bairro.strip():
        clauses.append("btrim(f.bairro::text) = :bairro")
        params["bairro"] = bairro.strip()
    return " AND ".join(clauses), params


def _flag_avg_sql(col: str) -> str:
    return f"ROUND(100.0 * AVG(i.{col}::numeric) FILTER (WHERE i.elegivel_ivs)::numeric, 2)"


def _idx_avg_sql(col: str) -> str:
    return f"ROUND(AVG(i.{col}) FILTER (WHERE i.elegivel_ivs)::numeric, 4)"


def _pct_acima_sql(idx_col: str) -> str:
    return f"""ROUND(
      100.0 * COUNT(*) FILTER (
        WHERE i.elegivel_ivs AND i.{idx_col} > stats.{idx_col}_avg
      )::numeric
      / NULLIF(COUNT(*) FILTER (WHERE i.elegivel_ivs), 0),
      1
    )"""


def build_painel_sql(*, num_cras: str | None, bairro: str | None) -> tuple[str, dict]:
    where, params = ivs_filter_clause(num_cras=num_cras, bairro=bairro)
    cadu_where, _ = territorio_filter_clause(num_cras=num_cras, bairro=bairro)
    flag_cols = [ind.col for dim in DIMENSOES for ind in dim.indicadores]
    flag_select = ",\n          ".join(f"{_flag_avg_sql(c)} AS {c}_pct" for c in flag_cols)
    idx_cols = [dim.idx_col for dim in DIMENSOES]
    idx_select = ",\n          ".join(f"{_idx_avg_sql(c)} AS {c}" for c in idx_cols)
    pct_acima_select = ",\n          ".join(
        f"{_pct_acima_sql(c)} AS pct_acima_{c.replace('idx_', '')}" for c in idx_cols
    )
    stats_select = ",\n            ".join(
        f"AVG(i.{c}) FILTER (WHERE i.elegivel_ivs) AS {c}_avg" for c in idx_cols
    )

    sql = f"""
    WITH stats AS (
      SELECT
        {stats_select}
      FROM core.mvw_ivs_familia i
      INNER JOIN vig.mvw_familia f ON f.codigo_familiar = i.codigo_familiar
      WHERE {where}
    ),
    cadu AS (
      SELECT COUNT(*)::bigint AS total
      FROM vig.mvw_familia f
      WHERE {cadu_where}
    )
    SELECT
      COUNT(*) FILTER (WHERE i.elegivel_ivs)::bigint AS familias_elegiveis,
      (SELECT total FROM cadu)::bigint AS familias_cadu,
      ROUND(AVG(i.ivs) FILTER (WHERE i.elegivel_ivs)::numeric, 4) AS ivs_medio,
      {idx_select},
      {pct_acima_select},
      {flag_select}
    FROM core.mvw_ivs_familia i
    INNER JOIN vig.mvw_familia f ON f.codigo_familiar = i.codigo_familiar
    CROSS JOIN stats
    WHERE {where}
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
    bairro: str | None,
    dimensao: str | None,
) -> dict:
    sql, params = build_painel_sql(num_cras=num_cras, bairro=bairro)
    row = conn.execute(text(sql), params).mappings().first() or {}

    elegiveis = int(row.get("familias_elegiveis") or 0)
    cadu = int(row.get("familias_cadu") or 0)
    pct_cadu = round(100.0 * elegiveis / cadu, 1) if cadu else None

    dimensoes = [_dim_from_row(dim, dict(row)) for dim in DIMENSOES]

    out: dict = {
        "recorte": {
            "num_cras": num_cras,
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
