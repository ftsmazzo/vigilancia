"""Painel estilo Observatório MDS (identificação e controle + renda)."""

from __future__ import annotations

from sqlalchemy import text
from sqlalchemy.engine import Connection

from .cadu_params import LIMIAR_POBREZA_EXTREMA, MESES_TAC_MAX, SALARIO_MINIMO, SM_METADE
from .familia_mview import _table_exists

MESES_OBS_ORDER = ("ate_12", "12_18", "18_24", "24_36", "37_48")
MESES_OBS_LABELS = {
    "ate_12": "até 12 Meses",
    "12_18": "acima de 12 até 18 Meses",
    "18_24": "acima de 18 até 24 Meses",
    "24_36": "acima de 24 até 36 Meses",
    "37_48": "acima de 37 até 48 Meses",
}

RENDA_PC_ORDER = ("pobreza", "baixa_renda", "acima_meio_sm")
RENDA_PC_LABELS = {
    "pobreza": "Pobreza",
    "baixa_renda": "Baixa renda",
    "acima_meio_sm": "Acima de 1/2 SM",
}

RENDA_FAM_ORDER = ("ate_1_sm", "1_2_sm", "2_3_sm", "acima_3_sm")
RENDA_FAM_LABELS = {
    "ate_1_sm": "até 1 SM",
    "1_2_sm": "acima de 1 até 2 SM",
    "2_3_sm": "acima de 2 até 3 SM",
    "acima_3_sm": "acima de 3 SM",
}

CREAS_PLACEHOLDER = 5


def _pct(n: int, total: int) -> float:
    return round(100.0 * n / total, 2) if total else 0.0


def _rows_to_items(
    rows: dict[str, int],
    order: tuple[str, ...],
    labels: dict[str, str],
    total: int,
) -> list[dict]:
    return [
        {
            "rotulo": key,
            "titulo": labels.get(key, key),
            "total": rows.get(key, 0),
            "pct": _pct(rows.get(key, 0), total),
        }
        for key in order
        if rows.get(key, 0) > 0
    ]


def _sim_nao_items(rows: list, total: int) -> list[dict]:
    mapping = {str(r["rotulo"]): int(r["total"] or 0) for r in rows}
    return [
        {
            "rotulo": "sim",
            "titulo": "Sim",
            "total": mapping.get("sim", 0),
            "pct": _pct(mapping.get("sim", 0), total),
        },
        {
            "rotulo": "nao",
            "titulo": "Não",
            "total": mapping.get("nao", 0),
            "pct": _pct(mapping.get("nao", 0), total),
        },
    ]


def observatorio_painel_from_views(conn: Connection) -> dict:
    if not _table_exists(conn, "vig", "mvw_familia") or not _table_exists(conn, "vig", "mvw_pessoas"):
        raise ValueError(
            "Visões vig.mvw_familia e vig.mvw_pessoas ausentes. Gere as visões em Vigilância."
        )

    sm = SALARIO_MINIMO
    sm2 = sm * 2
    sm3 = sm * 3
    pobreza = LIMIAR_POBREZA_EXTREMA
    meio_sm = SM_METADE

    base = conn.execute(
        text(
            """
            SELECT
              (SELECT COUNT(*)::bigint FROM vig.mvw_familia) AS total_familias,
              (SELECT COUNT(*)::bigint FROM vig.mvw_pessoas) AS total_pessoas,
              (
                SELECT COUNT(DISTINCT btrim(f.bairro::text))::bigint
                FROM vig.mvw_familia f
                WHERE f.bairro IS NOT NULL AND btrim(f.bairro::text) <> ''
              ) AS total_bairros,
              (
                SELECT COUNT(DISTINCT btrim(f.num_cras::text))::bigint
                FROM vig.mvw_familia f
                WHERE f.num_cras IS NOT NULL AND btrim(f.num_cras::text) <> ''
              ) AS total_cras
            """
        )
    ).mappings().first() or {}

    total_fam = int(base.get("total_familias") or 0)

    domicilio_rows = conn.execute(
        text(
            """
            SELECT rotulo, COUNT(*)::bigint AS total
            FROM (
              SELECT
                CASE
                  WHEN btrim(COALESCE(tipo_coleta::text, '')) IN ('2', '02') THEN 'sim'
                  ELSE 'nao'
                END AS rotulo
              FROM vig.mvw_familia
            ) x
            GROUP BY rotulo
            """
        )
    ).mappings().all()

    atualizado_rows = conn.execute(
        text(
            f"""
            SELECT rotulo, COUNT(*)::bigint AS total
            FROM (
              SELECT
                CASE
                  WHEN meses_desatualizado IS NOT NULL
                    AND meses_desatualizado <= {MESES_TAC_MAX}
                  THEN 'sim'
                  ELSE 'nao'
                END AS rotulo
              FROM vig.mvw_familia
            ) x
            GROUP BY rotulo
            """
        )
    ).mappings().all()

    meses_rows = conn.execute(
        text(
            """
            SELECT rotulo, COUNT(*)::bigint AS total
            FROM (
              SELECT
                CASE
                  WHEN meses_desatualizado IS NULL THEN 'nao_informado'
                  WHEN meses_desatualizado <= 12 THEN 'ate_12'
                  WHEN meses_desatualizado <= 18 THEN '12_18'
                  WHEN meses_desatualizado <= 24 THEN '18_24'
                  WHEN meses_desatualizado <= 36 THEN '24_36'
                  WHEN meses_desatualizado <= 48 THEN '37_48'
                  ELSE 'acima_48'
                END AS rotulo
              FROM vig.mvw_familia
            ) x
            WHERE rotulo IN ('ate_12', '12_18', '18_24', '24_36', '37_48')
            GROUP BY rotulo
            """
        )
    ).mappings().all()
    meses_map = {str(r["rotulo"]): int(r["total"] or 0) for r in meses_rows}

    renda_pc_rows = conn.execute(
        text(
            f"""
            SELECT rotulo, COUNT(*)::bigint AS total
            FROM (
              SELECT
                CASE
                  WHEN renda_per_capita IS NULL OR renda_per_capita < 0 THEN 'nao_informado'
                  WHEN renda_per_capita <= {pobreza} THEN 'pobreza'
                  WHEN renda_per_capita <= {meio_sm} THEN 'baixa_renda'
                  ELSE 'acima_meio_sm'
                END AS rotulo
              FROM vig.mvw_familia
            ) x
            WHERE rotulo <> 'nao_informado'
            GROUP BY rotulo
            """
        )
    ).mappings().all()
    renda_pc_map = {str(r["rotulo"]): int(r["total"] or 0) for r in renda_pc_rows}
    renda_pc_total = sum(renda_pc_map.get(k, 0) for k in RENDA_PC_ORDER)

    renda_pos_rows = conn.execute(
        text(
            f"""
            WITH pessoas_por_fam AS (
              SELECT codigo_familiar, COUNT(*)::int AS n_pessoas
              FROM vig.mvw_pessoas
              GROUP BY codigo_familiar
            ),
            fam AS (
              SELECT
                f.renda_per_capita,
                COALESCE(f.vlrtotal, 0) AS vlrtotal,
                GREATEST(COALESCE(pc.n_pessoas, 1), 1) AS n_pessoas
              FROM vig.mvw_familia f
              LEFT JOIN pessoas_por_fam pc ON pc.codigo_familiar = f.codigo_familiar
            ),
            calc AS (
              SELECT
                COALESCE(renda_per_capita, 0)
                  + COALESCE(vlrtotal, 0) / NULLIF(n_pessoas, 0) AS renda_pc_pos
              FROM fam
            )
            SELECT rotulo, COUNT(*)::bigint AS total
            FROM (
              SELECT
                CASE
                  WHEN renda_pc_pos <= {pobreza} THEN 'pobreza'
                  WHEN renda_pc_pos <= {meio_sm} THEN 'baixa_renda'
                  ELSE 'acima_meio_sm'
                END AS rotulo
              FROM calc
            ) x
            GROUP BY rotulo
            """
        )
    ).mappings().all()
    renda_pos_map = {str(r["rotulo"]): int(r["total"] or 0) for r in renda_pos_rows}
    renda_pos_total = sum(renda_pos_map.get(k, 0) for k in RENDA_PC_ORDER)

    renda_fam_rows = conn.execute(
        text(
            f"""
            SELECT rotulo, COUNT(*)::bigint AS total
            FROM (
              SELECT
                CASE
                  WHEN renda_total IS NULL OR renda_total < 0 THEN 'nao_informado'
                  WHEN renda_total <= {sm} THEN 'ate_1_sm'
                  WHEN renda_total <= {sm2} THEN '1_2_sm'
                  WHEN renda_total <= {sm3} THEN '2_3_sm'
                  ELSE 'acima_3_sm'
                END AS rotulo
              FROM vig.mvw_familia
            ) x
            WHERE rotulo <> 'nao_informado'
            GROUP BY rotulo
            """
        )
    ).mappings().all()
    renda_fam_map = {str(r["rotulo"]): int(r["total"] or 0) for r in renda_fam_rows}
    renda_fam_total = sum(renda_fam_map.get(k, 0) for k in RENDA_FAM_ORDER)

    return {
        "total_familias": total_fam,
        "total_pessoas": int(base.get("total_pessoas") or 0),
        "total_bairros": int(base.get("total_bairros") or 0),
        "total_cras": int(base.get("total_cras") or 0),
        "total_creas": CREAS_PLACEHOLDER,
        "creas_placeholder": True,
        "por_cadastro_domicilio": _sim_nao_items(domicilio_rows, total_fam),
        "por_cadastro_atualizado": _sim_nao_items(atualizado_rows, total_fam),
        "por_meses_atualizacao": _rows_to_items(meses_map, MESES_OBS_ORDER, MESES_OBS_LABELS, total_fam),
        "por_renda_per_capita": _rows_to_items(
            renda_pc_map, RENDA_PC_ORDER, RENDA_PC_LABELS, renda_pc_total or total_fam
        ),
        "por_renda_per_capita_pos_pbf": _rows_to_items(
            renda_pos_map, RENDA_PC_ORDER, RENDA_PC_LABELS, renda_pos_total or total_fam
        ),
        "por_renda_familiar": _rows_to_items(
            renda_fam_map, RENDA_FAM_ORDER, RENDA_FAM_LABELS, renda_fam_total or total_fam
        ),
    }
