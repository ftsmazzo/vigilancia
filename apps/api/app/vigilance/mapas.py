"""Mapas de calor territorial — indicadores por bairro (geo × CEP)."""

from __future__ import annotations

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


def _totais_cadu_referencia(conn: Connection, where_extra: str, params: dict) -> dict:
    """Totais no CADU inteiro do recorte (sem filtro geo), para comparação nos mapas."""
    row = conn.execute(
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
            """
        ),
        params,
    ).mappings().first()

    if not row:
        return {
            "criancas": 0,
            "idosos": 0,
            "familias_pbf": 0,
            "adultos_sem_medio": 0,
            "pessoas": 0,
            "familias": 0,
        }

    return {
        "criancas": int(row["criancas"] or 0),
        "idosos": int(row["idosos"] or 0),
        "familias_pbf": int(row["familias_pbf"] or 0),
        "adultos_sem_medio": int(row["adultos_sem_medio"] or 0),
        "pessoas": int(row["pessoas"] or 0),
        "familias": int(row["familias"] or 0),
    }


def mapas_heatmap_from_views(
    conn: Connection,
    cras_cod: str | None = None,
    bairro: str | None = None,
) -> dict:
    """Agrega indicadores por bairro territorial com coordenadas médias (centroide)."""
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
                COUNT(DISTINCT f.codigo_familiar)::bigint AS familias,
                COUNT(pes.cadu_row_id)::bigint AS pessoas,
                COUNT(pes.cadu_row_id) FILTER (WHERE {_CRIANCAS})::bigint AS criancas,
                COUNT(pes.cadu_row_id) FILTER (WHERE {_IDOSOS})::bigint AS idosos,
                COUNT(DISTINCT f.codigo_familiar) FILTER (WHERE {_familias_pbf_expr("f")})::bigint AS familias_pbf,
                COUNT(pes.cadu_row_id) FILTER (
                  WHERE {_ADULTO_18_59} AND {_SEM_MEDIO_COMPLETO}
                )::bigint AS adultos_sem_medio
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
            "familias": int(r["familias"] or 0),
            "pessoas": int(r["pessoas"] or 0),
            "criancas": int(r["criancas"] or 0),
            "idosos": int(r["idosos"] or 0),
            "familias_pbf": int(r["familias_pbf"] or 0),
            "adultos_sem_medio": int(r["adultos_sem_medio"] or 0),
        }
        for r in rows
    ]

    totais_geo = {
        "criancas": sum(p["criancas"] for p in pontos),
        "idosos": sum(p["idosos"] for p in pontos),
        "familias_pbf": sum(p["familias_pbf"] for p in pontos),
        "adultos_sem_medio": sum(p["adultos_sem_medio"] for p in pontos),
        "pessoas": sum(p["pessoas"] for p in pontos),
        "familias": sum(p["familias"] for p in pontos),
        "bairros": len(pontos),
    }
    totais_cadu = _totais_cadu_referencia(conn, where_extra, params)

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
            "Intensidade por bairro (centroide geo). Totais no cabeçalho: georreferenciados "
            "vs. CADU completo do recorte."
            if pontos
            else "Sem bairros georreferenciados para o recorte. Ajuste filtros ou atualize a geo."
        ),
        "recorte": {"cras_cod": cras_label, "bairro": bairro_sel},
        "centro": centro,
        "bounds": bounds,
        "totais_geo": totais_geo,
        "totais_cadu": totais_cadu,
        "pontos": pontos,
    }
