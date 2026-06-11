"""Funções SQL auxiliares para cálculo do IVS (IVCAD v1.0.5)."""

from __future__ import annotations

from sqlalchemy import text
from sqlalchemy.engine import Connection

IVS_DDL: list[str] = [
    "CREATE SCHEMA IF NOT EXISTS core",
    r"""
CREATE OR REPLACE FUNCTION vig.cod_sim(val text)
RETURNS boolean
LANGUAGE sql
IMMUTABLE
AS $$
  SELECT btrim(COALESCE(val, '')) IN ('1', '01')
$$;
""",
    r"""
CREATE OR REPLACE FUNCTION vig.anos_estudo_aprox(grau text)
RETURNS integer
LANGUAGE sql
IMMUTABLE
AS $$
  SELECT CASE btrim(COALESCE(grau, ''))
    WHEN '1' THEN 0
    WHEN '2' THEN 4
    WHEN '3' THEN 8
    WHEN '4' THEN 10
    WHEN '5' THEN 11
    WHEN '6' THEN 15
    ELSE NULL
  END
$$;
""",
    r"""
CREATE OR REPLACE FUNCTION vig.pessoa_ocupado(trab text, afast text)
RETURNS boolean
LANGUAGE sql
IMMUTABLE
AS $$
  SELECT
    vig.cod_sim(trab)
    OR (
      btrim(COALESCE(trab, '')) IN ('2', '02')
      AND vig.cod_sim(afast)
    )
$$;
""",
    r"""
CREATE OR REPLACE FUNCTION vig.fx_faixa_lb(fx text)
RETURNS numeric
LANGUAGE sql
IMMUTABLE
AS $$
  SELECT CASE
    WHEN fx IS NULL OR btrim(fx) = '' OR btrim(fx) IN ('0', '00') THEN 0::numeric
    ELSE GREATEST(
      0::numeric,
      (NULLIF(regexp_replace(btrim(fx), '[^0-9]', '', 'g'), '')::numeric - 1) * 200
    )
  END
$$;
""",
]


def ensure_ivs_functions(conn: Connection) -> None:
    from ..vigilance.familia_mview import ensure_vig_functions

    ensure_vig_functions(conn)
    for stmt in IVS_DDL:
        conn.execute(text(stmt))
