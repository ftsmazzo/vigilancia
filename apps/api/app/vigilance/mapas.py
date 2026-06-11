"""Mapas de calor territorial — crianças e idosos por bairro (geo × CEP)."""

from __future__ import annotations

from sqlalchemy import text
from sqlalchemy.engine import Connection

from .caracterizacao import _territorio_filter_clause
from .cras_analytics import _require_views
from .home_painel import _lat_sql, _lng_sql

CENTRO_PADRAO: tuple[float, float] = (-21.1775, -47.8103)


def _bounds_from_points(points: list[dict]) -> list[list[float]] | None:
    lats = [float(p["lat"]) for p in points if p.get("lat") is not None]
    lngs = [float(p["lng"]) for p in points if p.get("lng") is not None]
    if not lats or not lngs:
        return None
    return [[min(lats), min(lngs)], [max(lats), max(lngs)]]


def mapas_heatmap_from_views(
    conn: Connection,
    cras_cod: str | None = None,
    bairro: str | None = None,
) -> dict:
    """Agrega pessoas por bairro territorial com coordenadas médias (centroide)."""
    _require_views(conn)

    cras_sel = (cras_cod or "").strip() or "__todos__"
    where_extra, params = _territorio_filter_clause(cras_sel, bairro)

    rows = conn.execute(
        text(
            f"""
            WITH fam AS (
              SELECT f.*
              FROM vig.mvw_familia f
              WHERE COALESCE(f.tem_geo, FALSE)
                AND btrim(COALESCE(f.bairro::text, '')) <> ''
                AND {_lat_sql()} IS NOT NULL
                AND {_lng_sql()} IS NOT NULL
                {where_extra}
            ),
            pes AS (
              SELECT p.*
              FROM vig.mvw_pessoas p
              INNER JOIN fam ON fam.codigo_familiar = p.codigo_familiar
            ),
            por_bairro AS (
              SELECT
                btrim(f.bairro::text) AS bairro,
                btrim(f.num_cras::text) AS num_cras,
                AVG({_lat_sql()}) AS lat,
                AVG({_lng_sql()}) AS lng,
                COUNT(pes.cadu_row_id)::bigint AS pessoas,
                COUNT(pes.cadu_row_id) FILTER (
                  WHERE pes.idade IS NOT NULL AND pes.idade < 12
                )::bigint AS criancas,
                COUNT(pes.cadu_row_id) FILTER (
                  WHERE pes.idade >= 60
                )::bigint AS idosos
              FROM fam f
              LEFT JOIN pes ON pes.codigo_familiar = f.codigo_familiar
              GROUP BY 1, 2
            )
            SELECT *
            FROM por_bairro
            WHERE lat IS NOT NULL AND lng IS NOT NULL
            ORDER BY pessoas DESC
            """
        ),
        params,
    ).mappings().all()

    pontos = [
        {
            "bairro": str(r["bairro"] or ""),
            "num_cras": str(r["num_cras"] or ""),
            "lat": round(float(r["lat"]), 5),
            "lng": round(float(r["lng"]), 5),
            "pessoas": int(r["pessoas"] or 0),
            "criancas": int(r["criancas"] or 0),
            "idosos": int(r["idosos"] or 0),
        }
        for r in rows
    ]

    tot_criancas = sum(p["criancas"] for p in pontos)
    tot_idosos = sum(p["idosos"] for p in pontos)
    tot_pessoas = sum(p["pessoas"] for p in pontos)

    bounds = _bounds_from_points(pontos)
    centro = list(CENTRO_PADRAO)
    if bounds:
        centro = [
            (bounds[0][0] + bounds[1][0]) / 2,
            (bounds[0][1] + bounds[1][1]) / 2,
        ]

    bairro_sel = (bairro or "").strip() or None
    cras_label = cras_sel if cras_sel not in ("", "__todos__") else None

    return {
        "disponivel": len(pontos) > 0,
        "mensagem": (
            "Intensidade por bairro (centroide geo). Crianças: 0–11 anos; idosos: 60 anos ou mais."
            if pontos
            else "Sem bairros georreferenciados para o recorte. Ajuste filtros ou atualize a geo."
        ),
        "recorte": {"cras_cod": cras_label, "bairro": bairro_sel},
        "centro": centro,
        "bounds": bounds,
        "totais": {
            "criancas": tot_criancas,
            "idosos": tot_idosos,
            "pessoas": tot_pessoas,
            "bairros": len(pontos),
        },
        "pontos": pontos,
    }
