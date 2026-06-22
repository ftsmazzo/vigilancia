"""Persistência dos mapas bairro × CRAS/CREAS para reaplicar após reingestão da tbl_geo."""

from __future__ import annotations

from sqlalchemy import text
from sqlalchemy.engine import Connection

from .geo_cras import GEO_TABLE, apply_cras_bairros_to_geo
from .geo_creas import apply_creas_bairros_to_geo

MAP_CRAS_TABLE = "geo_map_cras_bairro"
MAP_CREAS_TABLE = "geo_map_creas_bairro"


def _ensure_map_table(conn: Connection, table: str, unit_col: str) -> None:
    conn.execute(
        text(
            f"""
            CREATE TABLE IF NOT EXISTS raw."{table}" (
              bairro_key TEXT PRIMARY KEY,
              {unit_col} TEXT NOT NULL,
              bairro_label TEXT,
              atualizado_em TIMESTAMPTZ NOT NULL DEFAULT NOW()
            )
            """
        )
    )


def persist_cras_map(conn: Connection, bairro_to_cras: dict[str, int]) -> int:
    if not bairro_to_cras:
        return 0
    _ensure_map_table(conn, MAP_CRAS_TABLE, "cras_num")
    conn.execute(text(f'TRUNCATE TABLE raw."{MAP_CRAS_TABLE}"'))
    rows = [
        {"bairro_key": k, "cras_num": str(v), "bairro_label": k}
        for k, v in bairro_to_cras.items()
    ]
    conn.execute(
        text(
            f"""
            INSERT INTO raw."{MAP_CRAS_TABLE}" (bairro_key, cras_num, bairro_label)
            VALUES (:bairro_key, :cras_num, :bairro_label)
            """
        ),
        rows,
    )
    return len(rows)


def persist_creas_map(conn: Connection, bairro_to_creas: dict[str, int]) -> int:
    if not bairro_to_creas:
        return 0
    _ensure_map_table(conn, MAP_CREAS_TABLE, "creas_num")
    conn.execute(text(f'TRUNCATE TABLE raw."{MAP_CREAS_TABLE}"'))
    rows = [
        {"bairro_key": k, "creas_num": str(v), "bairro_label": k}
        for k, v in bairro_to_creas.items()
    ]
    conn.execute(
        text(
            f"""
            INSERT INTO raw."{MAP_CREAS_TABLE}" (bairro_key, creas_num, bairro_label)
            VALUES (:bairro_key, :creas_num, :bairro_label)
            """
        ),
        rows,
    )
    return len(rows)


def load_cras_map(conn: Connection) -> dict[str, int]:
    if not conn.execute(
        text(
            """
            SELECT 1 FROM information_schema.tables
            WHERE table_schema = 'raw' AND table_name = :t
            """
        ),
        {"t": MAP_CRAS_TABLE},
    ).scalar():
        return {}
    rows = conn.execute(
        text(f'SELECT bairro_key, cras_num FROM raw."{MAP_CRAS_TABLE}"')
    ).mappings().all()
    out: dict[str, int] = {}
    for r in rows:
        key = str(r["bairro_key"] or "").strip()
        num = str(r["cras_num"] or "").strip()
        if key and num.isdigit():
            out[key] = int(num)
    return out


def load_creas_map(conn: Connection) -> dict[str, int]:
    if not conn.execute(
        text(
            """
            SELECT 1 FROM information_schema.tables
            WHERE table_schema = 'raw' AND table_name = :t
            """
        ),
        {"t": MAP_CREAS_TABLE},
    ).scalar():
        return {}
    rows = conn.execute(
        text(f'SELECT bairro_key, creas_num FROM raw."{MAP_CREAS_TABLE}"')
    ).mappings().all()
    out: dict[str, int] = {}
    for r in rows:
        key = str(r["bairro_key"] or "").strip()
        num = str(r["creas_num"] or "").strip()
        if key and num.isdigit():
            out[key] = int(num)
    return out


def map_counts(conn: Connection) -> dict[str, int]:
    cras = load_cras_map(conn)
    creas = load_creas_map(conn)
    return {"cras_bairros": len(cras), "creas_bairros": len(creas)}


def geo_has_territorial_columns(conn: Connection) -> dict[str, bool]:
    rows = conn.execute(
        text(
            """
            SELECT column_name
            FROM information_schema.columns
            WHERE table_schema = 'raw' AND table_name = :t
              AND column_name IN ('cras', 'creas')
            """
        ),
        {"t": GEO_TABLE},
    ).scalars().all()
    cols = set(rows)
    return {"cras": "cras" in cols, "creas": "creas" in cols}


def geo_territorial_fill_stats(conn: Connection) -> dict[str, int]:
    cols = geo_has_territorial_columns(conn)
    stats: dict[str, int] = {}
    if cols["cras"]:
        stats["linhas_com_cras"] = int(
            conn.execute(
                text(
                    f"""
                    SELECT COUNT(*)::bigint FROM raw."{GEO_TABLE}"
                    WHERE cras IS NOT NULL AND btrim(cras::text) <> ''
                    """
                )
            ).scalar()
            or 0
        )
    if cols["creas"]:
        stats["linhas_com_creas"] = int(
            conn.execute(
                text(
                    f"""
                    SELECT COUNT(*)::bigint FROM raw."{GEO_TABLE}"
                    WHERE creas IS NOT NULL AND btrim(creas::text) <> ''
                    """
                )
            ).scalar()
            or 0
        )
    return stats


def reapply_persisted_territorial_maps(conn: Connection) -> dict:
    """Reaplica CRAS/CREAS na tbl_geo a partir dos mapas persistidos (último CSV aplicado)."""
    cras_map = load_cras_map(conn)
    creas_map = load_creas_map(conn)
    if not cras_map and not creas_map:
        return {
            "reaplicado": False,
            "motivo": "Nenhum mapa CRAS/CREAS persistido. Envie bairros_cras.csv e bairros_creas.csv em Ingestão.",
            "mapas": map_counts(conn),
        }

    result: dict = {"reaplicado": True, "mapas": map_counts(conn)}
    if cras_map:
        r = apply_cras_bairros_to_geo(
            conn,
            bairro_to_cras=cras_map,
            conflicts=[],
            dry_run=False,
        )
        result["cras"] = {
            "linhas_atualizadas": r.linhas_geo_atualizadas,
            "bairros_no_mapa": r.bairros_no_mapa,
        }
    if creas_map:
        r = apply_creas_bairros_to_geo(
            conn,
            bairro_to_creas=creas_map,
            conflicts=[],
            dry_run=False,
        )
        result["creas"] = {
            "linhas_atualizadas": r.linhas_geo_atualizadas,
            "bairros_no_mapa": r.bairros_no_mapa,
        }
    result["geo_apos_reaplicar"] = geo_territorial_fill_stats(conn)
    return result
