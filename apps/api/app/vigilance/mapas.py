"""Mapas de calor territorial — indicadores por família georreferenciada (geo × CEP)."""

from __future__ import annotations

import json

from sqlalchemy import text
from sqlalchemy.engine import Connection

from .caracterizacao import _territorio_filter_clause
from .cras_analytics import _require_views
from .home_painel import _lat_sql, _lng_sql

CENTRO_PADRAO: tuple[float, float] = (-21.1775, -47.8103)

_ADULTO_18_59 = "pes.idade IS NOT NULL AND pes.idade >= 18 AND pes.idade < 60"
_SEM_MEDIO_COMPLETO = (
    "btrim(COALESCE(pes.grau_instrucao::text, '')) NOT IN ('5', '05', '6', '06', '7', '07')"
)
_CRIANCAS = "pes.idade IS NOT NULL AND pes.idade < 12"
_IDOSOS = "pes.idade >= 60"


def _familias_pbf_expr(alias: str) -> str:
    return f"COALESCE({alias}.marc_pbf, FALSE)"


def _bounds_from_points(points: list[dict]) -> list[list[float]] | None:
    lats = [float(p["lat"]) for p in points if p.get("lat") is not None]
    lngs = [float(p["lng"]) for p in points if p.get("lng") is not None]
    if not lats or not lngs:
        return None
    return [[min(lats), min(lngs)], [max(lats), max(lngs)]]


def _empty_totais_cadu() -> dict:
    return {
        "criancas": 0,
        "idosos": 0,
        "familias_pbf": 0,
        "adultos_sem_medio": 0,
        "pessoas": 0,
        "familias": 0,
    }


def bairros_geo_catalog_from_views(conn: Connection) -> list[dict]:
    """Bairros georreferenciados do município (independente de CRAS)."""
    _require_views(conn)
    rows = conn.execute(
        text(
            """
            SELECT
              btrim(f.bairro::text) AS bairro,
              COUNT(DISTINCT f.codigo_familiar)::bigint AS familias
            FROM vig.mvw_familia f
            WHERE COALESCE(f.tem_geo, FALSE)
              AND btrim(COALESCE(f.bairro::text, '')) <> ''
            GROUP BY 1
            ORDER BY familias DESC, bairro ASC
            """
        )
    ).mappings().all()
    return [
        {"bairro": str(r["bairro"] or ""), "familias": int(r["familias"] or 0)}
        for r in rows
        if r.get("bairro")
    ]


def mapas_heatmap_from_views(
    conn: Connection,
    cras_cod: str | None = None,
    bairro: str | None = None,
    creas_cod: str | None = None,
) -> dict:
    """Pontos por família (coordenada real) + totais CADU em uma única consulta."""
    _require_views(conn)

    cras_sel = (cras_cod or "").strip() or "__todos__"
    creas_sel = (creas_cod or "").strip() or "__todos__"
    where_extra, params = _territorio_filter_clause(cras_sel, bairro, creas_sel)

    lat_expr = _lat_sql("fam.lat_num")
    lng_expr = _lng_sql("fam.long_num")

    row = conn.execute(
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
            ),
            totais_cadu AS (
              SELECT
                COUNT(pes.cadu_row_id) FILTER (WHERE {_CRIANCAS})::bigint AS criancas,
                COUNT(pes.cadu_row_id) FILTER (WHERE {_IDOSOS})::bigint AS idosos,
                COUNT(DISTINCT fam.codigo_familiar) FILTER (WHERE {_familias_pbf_expr("fam")})::bigint AS familias_pbf,
                COUNT(pes.cadu_row_id) FILTER (
                  WHERE {_ADULTO_18_59} AND {_SEM_MEDIO_COMPLETO}
                )::bigint AS adultos_sem_medio,
                COUNT(pes.cadu_row_id)::bigint AS pessoas,
                COUNT(DISTINCT fam.codigo_familiar)::bigint AS familias
              FROM fam
              LEFT JOIN pes ON pes.codigo_familiar = fam.codigo_familiar
            ),
            fam_geo AS (
              SELECT
                fam.codigo_familiar,
                btrim(fam.bairro::text) AS bairro,
                btrim(fam.num_cras::text) AS num_cras,
                COALESCE(fam.marc_pbf, FALSE) AS marc_pbf,
                {lat_expr} AS lat,
                {lng_expr} AS lng
              FROM fam
              WHERE COALESCE(fam.tem_geo, FALSE)
                AND btrim(COALESCE(fam.bairro::text, '')) <> ''
                AND {lat_expr} IS NOT NULL
                AND {lng_expr} IS NOT NULL
            ),
            por_familia AS (
              SELECT
                fg.codigo_familiar,
                fg.bairro,
                fg.num_cras,
                fg.marc_pbf,
                fg.lat,
                fg.lng,
                COUNT(pes.cadu_row_id)::bigint AS pessoas,
                COUNT(pes.cadu_row_id) FILTER (WHERE {_CRIANCAS})::bigint AS criancas,
                COUNT(pes.cadu_row_id) FILTER (WHERE {_IDOSOS})::bigint AS idosos,
                COUNT(pes.cadu_row_id) FILTER (
                  WHERE {_ADULTO_18_59} AND {_SEM_MEDIO_COMPLETO}
                )::bigint AS adultos_sem_medio
              FROM fam_geo fg
              LEFT JOIN pes ON pes.codigo_familiar = fg.codigo_familiar
              GROUP BY
                fg.codigo_familiar,
                fg.bairro,
                fg.num_cras,
                fg.marc_pbf,
                fg.lat,
                fg.lng
            )
            SELECT
              (SELECT row_to_json(t) FROM totais_cadu t) AS totais_cadu,
              COALESCE(
                (SELECT json_agg(row_to_json(p) ORDER BY p.pessoas DESC)
                 FROM por_familia p
                 WHERE p.lat IS NOT NULL AND p.lng IS NOT NULL),
                '[]'::json
              ) AS pontos
            """
        ),
        params,
    ).mappings().first()

    raw_pontos = row["pontos"] if row else []
    if isinstance(raw_pontos, str):
        raw_pontos = json.loads(raw_pontos)
    raw_pontos = raw_pontos or []

    totais_cadu_raw = row.get("totais_cadu") if row else None
    if isinstance(totais_cadu_raw, str):
        totais_cadu_raw = json.loads(totais_cadu_raw)
    totais_cadu = _empty_totais_cadu()
    if totais_cadu_raw:
        totais_cadu = {
            "criancas": int(totais_cadu_raw.get("criancas") or 0),
            "idosos": int(totais_cadu_raw.get("idosos") or 0),
            "familias_pbf": int(totais_cadu_raw.get("familias_pbf") or 0),
            "adultos_sem_medio": int(totais_cadu_raw.get("adultos_sem_medio") or 0),
            "pessoas": int(totais_cadu_raw.get("pessoas") or 0),
            "familias": int(totais_cadu_raw.get("familias") or 0),
        }

    pontos = [
        {
            "bairro": str(r.get("bairro") or ""),
            "num_cras": str(r.get("num_cras") or ""),
            "lat": round(float(r["lat"]), 5),
            "lng": round(float(r["lng"]), 5),
            "pessoas": int(r.get("pessoas") or 0),
            "criancas": int(r.get("criancas") or 0),
            "idosos": int(r.get("idosos") or 0),
            "adultos_sem_medio": int(r.get("adultos_sem_medio") or 0),
            "na_folha_pbf": 1 if r.get("marc_pbf") else 0,
        }
        for r in raw_pontos
        if r.get("lat") is not None and r.get("lng") is not None
    ]

    bairros_distintos = len({p["bairro"] for p in pontos if p["bairro"]})

    totais_geo = {
        "criancas": sum(p["criancas"] for p in pontos),
        "idosos": sum(p["idosos"] for p in pontos),
        "familias_pbf": sum(p["na_folha_pbf"] for p in pontos),
        "adultos_sem_medio": sum(p["adultos_sem_medio"] for p in pontos),
        "pessoas": sum(p["pessoas"] for p in pontos),
        "familias": len(pontos),
        "bairros": bairros_distintos,
    }

    bounds = _bounds_from_points(pontos)
    centro = list(CENTRO_PADRAO)
    if bounds:
        centro = [
            (bounds[0][0] + bounds[1][0]) / 2,
            (bounds[0][1] + bounds[1][1]) / 2,
        ]

    bairro_sel = (bairro or "").strip() or None
    cras_label = cras_sel if cras_sel not in ("", "__todos__") else None
    creas_label = creas_sel if creas_sel not in ("", "__todos__") else None

    return {
        "disponivel": len(pontos) > 0,
        "mensagem": (
            "Calor contínuo a partir das coordenadas das famílias georreferenciadas. "
            "Totais no cabeçalho: mapa vs. CADU completo do recorte."
            if pontos
            else "Sem famílias georreferenciadas para o recorte. Ajuste filtros ou atualize a geo."
        ),
        "recorte": {"cras_cod": cras_label, "creas_cod": creas_label, "bairro": bairro_sel},
        "centro": centro,
        "bounds": bounds,
        "totais_geo": totais_geo,
        "totais_cadu": totais_cadu,
        "pontos": pontos,
    }
