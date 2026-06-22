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


def _creas_key_sql(prefix: str = "f") -> str:
    p = prefix
    return f"""CASE
      WHEN {p}.num_creas IS NULL OR btrim({p}.num_creas::text) = '' THEN ''
      ELSE btrim({p}.num_creas::text)
    END"""


def _creas_nome_sql(prefix: str = "f") -> str:
    p = prefix
    return f"""CASE
      WHEN {p}.nom_creas IS NULL OR btrim({p}.nom_creas::text) = '' THEN '(sem nome)'
      ELSE btrim({p}.nom_creas::text)
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


def _creas_filter_clause(creas_cod: str | None, *, alias: str = "f") -> tuple[str, dict]:
    if creas_cod is None or creas_cod.strip() in ("", "__todos__"):
        return "", {}
    cod = creas_cod.strip()
    p = alias
    if cod == "__sem_creas__":
        return f" AND ({p}.num_creas IS NULL OR btrim({p}.num_creas::text) = '') ", {}
    return f" AND btrim({p}.num_creas::text) = :creas_cod ", {"creas_cod": cod}


def bairros_por_creas_from_views(conn: Connection, creas_cod: str) -> list[dict]:
    """Bairros distintos vinculados a um CREAS territorial (vig.mvw_familia)."""
    _require_views(conn)
    cod = (creas_cod or "").strip()
    if not cod or cod in ("__todos__", "__sem_creas__"):
        return []

    rows = conn.execute(
        text(
            """
            SELECT
              btrim(f.bairro::text) AS bairro,
              COUNT(DISTINCT f.codigo_familiar)::bigint AS familias
            FROM vig.mvw_familia f
            WHERE btrim(f.num_creas::text) = :creas_cod
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


def creas_catalog_from_views(conn: Connection) -> list[dict]:
    _require_views(conn)
    if not _column_exists(conn, "vig", "mvw_familia", "num_creas"):
        return []

    ck = _creas_key_sql("f")
    cn = _creas_nome_sql("f")
    rows = conn.execute(
        text(
            f"""
            WITH fam AS (
              SELECT
                {ck} AS creas_cod,
                {cn} AS creas_nome,
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
    return _sort_creas_items(out)


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
