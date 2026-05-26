"""Correções seguras em SQL gerada pelo LLM (tipos CADU, etc.)."""

from __future__ import annotations

import re

CADU_SIM_IN = "('1', '01', 'sim', 's', 'true')"
CADU_NAO_IN = "('0', '02', 'nao', 'não', 'n', 'false')"

# Colunas em vig.mvw_pessoas armazenadas como código texto, não boolean.
TEXT_CODE_FIELDS = (
    "ind_atend_cras",
    "ind_frequenta_escola",
    "ind_trabalho_infantil",
    "marc_sit_rua",
    "ind_atend_creas",
    "ind_atend_centro_ref_rua",
)


def _cadu_sim_expr(col: str) -> str:
    return f"btrim(COALESCE({col}::text, '')) IN {CADU_SIM_IN}"


def sanitize_llm_sql(sql: str) -> str:
    out = sql
    for field in TEXT_CODE_FIELDS:
        pat_true = re.compile(rf"((?:[a-z]\.)?{field})\s*=\s*true\b", re.I)
        pat_false = re.compile(rf"((?:[a-z]\.)?{field})\s*=\s*false\b", re.I)
        out = pat_true.sub(lambda m, _f=field: _cadu_sim_expr(m.group(1)), out)
        out = pat_false.sub(
            lambda m, _f=field: f"btrim(COALESCE({m.group(1)}::text, '')) IN {CADU_NAO_IN}",
            out,
        )
    return out
