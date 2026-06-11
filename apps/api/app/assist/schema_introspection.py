"""Schema vivo do PostgreSQL (materialized views vig.mvw_*)."""

from __future__ import annotations

from sqlalchemy import text
from sqlalchemy.engine import Connection

from ..vigilance.familia_mview import _table_exists

ALLOWED_MVIEWS = (
    "mvw_familia",
    "mvw_familia_domicilio",
    "mvw_pessoas",
    "mvw_sisc_qualificado",
)

CORE_IVIEWS = ("mvw_ivs_familia",)


def build_live_schema_markdown(conn: Connection) -> str:
    """Colunas reais via information_schema (alinha AgenteSQL ao banco em produção)."""
    if not _table_exists(conn, "vig", "mvw_familia"):
        return "(Views vig.mvw_* ainda não materializadas — execute Vigilância → Família/Pessoas.)"

    names_sql = ", ".join(f"'{n}'" for n in ALLOWED_MVIEWS)
    rows = conn.execute(
        text(
            f"""
            SELECT table_name, column_name, data_type
            FROM information_schema.columns
            WHERE table_schema = 'vig'
              AND table_name IN ({names_sql})
            ORDER BY table_name, ordinal_position
            """
        )
    ).fetchall()

    ivs_rows: list = []
    if _table_exists(conn, "core", "mvw_ivs_familia"):
        ivs_names = ", ".join(f"'{n}'" for n in CORE_IVIEWS)
        ivs_rows = conn.execute(
            text(
                f"""
                SELECT table_name, column_name, data_type
                FROM information_schema.columns
                WHERE table_schema = 'core'
                  AND table_name IN ({ivs_names})
                ORDER BY table_name, ordinal_position
                """
            )
        ).fetchall()

    if not rows and not ivs_rows:
        return "(Nenhuma coluna encontrada em vig.mvw_* / core.mvw_ivs_familia.)"

    lines = ["## Schema vig (introspecção ao vivo)", ""]
    current_table = ""
    for table_name, column_name, data_type in rows:
        if table_name != current_table:
            current_table = table_name
            lines.append(f"### vig.{table_name}")
        lines.append(f"- {column_name} ({data_type})")

    if ivs_rows:
        lines.extend(["", "## Schema core (IVS)", ""])
        current_table = ""
        for table_name, column_name, data_type in ivs_rows:
            if table_name != current_table:
                current_table = table_name
                lines.append(f"### core.{table_name}")
            lines.append(f"- {column_name} ({data_type})")

    return "\n".join(lines)
