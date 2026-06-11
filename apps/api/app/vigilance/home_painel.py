"""Painel inicial (Observatório) + dados do mapa territorial por CRAS."""

from __future__ import annotations

from sqlalchemy import text
from sqlalchemy.engine import Connection

from .cadu_params import LIMIAR_POBREZA_EXTREMA, SM_METADE, sql_marcador_pbf_cadu
from .familia_mview import _table_exists

CRAS_CORES = (
    "#2563eb",
    "#ea580c",
    "#16a34a",
    "#dc2626",
    "#9333ea",
    "#0891b2",
    "#ca8a04",
    "#be185d",
    "#4f46e5",
    "#0d9488",
    "#b45309",
    "#64748b",
)


def _cras_color(num_cras: str | None) -> str:
    if not num_cras:
        return "#94a3b8"
    digits = "".join(c for c in str(num_cras) if c.isdigit())
    if not digits:
        return "#94a3b8"
    idx = (int(digits) - 1) % len(CRAS_CORES)
    return CRAS_CORES[idx]


def home_painel_from_views(conn: Connection) -> dict:
    if not _table_exists(conn, "vig", "mvw_familia") or not _table_exists(conn, "vig", "mvw_pessoas"):
        raise ValueError(
            "Visões vig.mvw_familia e vig.mvw_pessoas ausentes. Gere as visões em Vigilância."
        )

    pbf_pessoa_sql = f"""
      SELECT COUNT(*)::bigint
      FROM vig.mvw_pessoas p
      INNER JOIN vig.mvw_familia f ON f.codigo_familiar = p.codigo_familiar
      WHERE COALESCE(f.marc_pbf, FALSE) OR {sql_marcador_pbf_cadu("f.marc_pbf_cadu")}
    """

    base = conn.execute(
        text(
            f"""
            SELECT
              (SELECT COUNT(*)::bigint FROM vig.mvw_familia) AS total_familias,
              (SELECT COUNT(*)::bigint FROM vig.mvw_pessoas) AS total_pessoas,
              (SELECT COUNT(*)::bigint FROM vig.mvw_familia
               WHERE COALESCE(marc_pbf, FALSE) OR {sql_marcador_pbf_cadu("marc_pbf_cadu")}) AS familias_pbf,
              ({pbf_pessoa_sql}) AS pessoas_pbf
            """
        )
    ).mappings().first() or {}

    meses_rows = conn.execute(
        text(
            """
            SELECT rotulo, total FROM (
              SELECT
                CASE
                  WHEN meses_desatualizado IS NULL THEN 'nao_informado'
                  WHEN meses_desatualizado <= 12 THEN 'ate_12'
                  WHEN meses_desatualizado <= 18 THEN '12_18'
                  WHEN meses_desatualizado <= 24 THEN '18_24'
                  WHEN meses_desatualizado <= 36 THEN '24_36'
                  WHEN meses_desatualizado <= 48 THEN '37_48'
                  ELSE 'acima_48'
                END AS rotulo,
                COUNT(*)::bigint AS total
              FROM vig.mvw_familia
              GROUP BY 1
            ) x
            """
        )
    ).mappings().all()

    renda_rows = conn.execute(
        text(
            f"""
            SELECT
              CASE
                WHEN renda_per_capita IS NULL OR renda_per_capita < 0 THEN 'nao_informada'
                WHEN renda_per_capita <= {LIMIAR_POBREZA_EXTREMA} THEN 'pobreza'
                WHEN renda_per_capita <= {SM_METADE} THEN 'baixa_renda'
                ELSE 'acima_meio_sm'
              END AS rotulo,
              COUNT(*)::bigint AS total
            FROM vig.mvw_familia
            GROUP BY 1
            """
        )
    ).mappings().all()

    ivs_medio = None
    ivs_disponivel = _table_exists(conn, "core", "mvw_ivs_familia")
    if ivs_disponivel:
        ivs_medio = conn.execute(
            text(
                """
                SELECT ROUND(AVG(ivs) FILTER (WHERE elegivel_ivs)::numeric, 4)
                FROM core.mvw_ivs_familia
                """
            )
        ).scalar()

    meses_order = ["ate_12", "12_18", "18_24", "24_36", "37_48", "acima_48", "nao_informado"]
    meses_map = {str(r["rotulo"]): int(r["total"] or 0) for r in meses_rows}
    renda_order = ["pobreza", "baixa_renda", "acima_meio_sm", "nao_informada"]
    renda_map = {str(r["rotulo"]): int(r["total"] or 0) for r in renda_rows}

    meses_labels = {
        "ate_12": "Até 12 meses",
        "12_18": "12 a 18 meses",
        "18_24": "18 a 24 meses",
        "24_36": "24 a 36 meses",
        "37_48": "37 a 48 meses",
        "acima_48": "Acima de 48 meses",
        "nao_informado": "Sem data de atualização",
    }
    renda_labels = {
        "pobreza": "Pobreza (até R$ 218)",
        "baixa_renda": "Baixa renda (até R$ 810,50)",
        "acima_meio_sm": "Acima de ½ salário mínimo",
        "nao_informada": "Renda não informada",
    }

    total_fam = int(base.get("total_familias") or 0)

    def pct(n: int) -> float:
        return round(100.0 * n / total_fam, 2) if total_fam else 0.0

    mapa = mapa_territorial_from_views(conn)

    return {
        "total_familias": total_fam,
        "total_pessoas": int(base.get("total_pessoas") or 0),
        "familias_pbf": int(base.get("familias_pbf") or 0),
        "pessoas_pbf": int(base.get("pessoas_pbf") or 0),
        "ivs_medio": float(ivs_medio) if ivs_medio is not None else None,
        "ivs_disponivel": ivs_disponivel,
        "ivs_media_nacional": 0.283,
        "por_meses_atualizacao": [
            {
                "rotulo": k,
                "titulo": meses_labels.get(k, k),
                "total": meses_map.get(k, 0),
                "pct": pct(meses_map.get(k, 0)),
            }
            for k in meses_order
            if k in meses_map and meses_map[k] > 0
        ],
        "por_faixa_renda": [
            {
                "rotulo": k,
                "titulo": renda_labels.get(k, k),
                "total": renda_map.get(k, 0),
                "pct": pct(renda_map.get(k, 0)),
            }
            for k in renda_order
            if k in renda_map and renda_map[k] > 0
        ],
        "mapa": mapa,
    }


def mapa_territorial_from_views(conn: Connection) -> dict:
    if not _table_exists(conn, "vig", "mvw_familia"):
        return {"disponivel": False, "mensagem": "Visão família ausente.", "pontos": [], "cras": []}

    geo_stats = conn.execute(
        text(
            """
            SELECT
              COUNT(*) FILTER (WHERE tem_geo)::bigint AS com_geo,
              COUNT(*) FILTER (WHERE NOT COALESCE(tem_geo, FALSE))::bigint AS sem_geo
            FROM vig.mvw_familia
            """
        )
    ).mappings().first() or {}

    pontos = conn.execute(
        text(
            """
            SELECT
              btrim(f.num_cras::text) AS num_cras,
              ROUND(f.lat_num::numeric, 3) AS lat,
              ROUND(f.long_num::numeric, 3) AS lng,
              COUNT(*)::bigint AS familias
            FROM vig.mvw_familia f
            WHERE COALESCE(f.tem_geo, FALSE)
              AND f.lat_num IS NOT NULL
              AND f.long_num IS NOT NULL
              AND f.num_cras IS NOT NULL
              AND btrim(f.num_cras::text) <> ''
            GROUP BY 1, 2, 3
            ORDER BY familias DESC
            LIMIT 2500
            """
        )
    ).mappings().all()

    cras_rows = conn.execute(
        text(
            """
            SELECT
              btrim(f.num_cras::text) AS num_cras,
              max(btrim(f.nom_cras::text)) AS nom_cras,
              AVG(f.lat_num)::float AS lat,
              AVG(f.long_num)::float AS lng,
              COUNT(*)::bigint AS familias
            FROM vig.mvw_familia f
            WHERE COALESCE(f.tem_geo, FALSE)
              AND f.lat_num IS NOT NULL
              AND f.long_num IS NOT NULL
              AND f.num_cras IS NOT NULL
              AND btrim(f.num_cras::text) <> ''
            GROUP BY 1
            ORDER BY NULLIF(regexp_replace(btrim(num_cras), '[^0-9].*', ''), '')::int NULLS LAST
            """
        )
    ).mappings().all()

    cras_list = []
    for r in cras_rows:
        num = str(r["num_cras"] or "")
        cras_list.append(
            {
                "num_cras": num,
                "nom_cras": str(r["nom_cras"] or f"CRAS {num}"),
                "lat": float(r["lat"]) if r["lat"] is not None else None,
                "lng": float(r["lng"]) if r["lng"] is not None else None,
                "familias": int(r["familias"] or 0),
                "cor": _cras_color(num),
            }
        )

    bounds = None
    if pontos:
        lats = [float(p["lat"]) for p in pontos if p["lat"] is not None]
        lngs = [float(p["lng"]) for p in pontos if p["lng"] is not None]
        if lats and lngs:
            bounds = [
                [min(lats), min(lngs)],
                [max(lats), max(lngs)],
            ]

    return {
        "disponivel": len(pontos) > 0,
        "mensagem": (
            "Pontos agregados por CEP/coordenada na geo, coloridos por CRAS territorial."
            if pontos
            else "Sem coordenadas na visão família. Ingeste tbl_geo, aplique CRAS e regenere mvw_familia."
        ),
        "familias_com_geo": int(geo_stats.get("com_geo") or 0),
        "familias_sem_geo": int(geo_stats.get("sem_geo") or 0),
        "centro": [-21.1775, -47.8103],
        "bounds": bounds,
        "pontos": [
            {
                "lat": float(p["lat"]),
                "lng": float(p["lng"]),
                "num_cras": str(p["num_cras"] or ""),
                "familias": int(p["familias"] or 0),
                "cor": _cras_color(str(p["num_cras"] or "")),
            }
            for p in pontos
        ],
        "cras": cras_list,
    }
