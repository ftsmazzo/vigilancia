"""Validação de SQL gerado pelo assistente (somente leitura)."""

from __future__ import annotations

import re

FORBIDDEN = re.compile(
    r"\b("
    r"insert|update|delete|drop|alter|create|truncate|grant|revoke|"
    r"copy|execute|call|merge|replace|into|"
    r"pg_sleep|pg_terminate|lo_import|dblink"
    r")\b",
    re.I,
)

ALLOWED_SCHEMAS = frozenset({"vig"})

# Views materializadas permitidas (evita raw.cecad__cadu gigante no MVP).
ALLOWED_RELATIONS = frozenset(
    {
        "vig.mvw_familia",
        "vig.mvw_pessoas",
        "vig.mvw_familia_domicilio",
        "vig.mvw_sisc_qualificado",
    }
)


class SqlGuardError(ValueError):
    pass


def _normalize(sql: str) -> str:
    s = sql.strip().rstrip(";").strip()
    if ";" in s:
        raise SqlGuardError("Apenas uma instrução SQL por consulta.")
    return s


def _referenced_relations(sql: str) -> set[str]:
    """Extrai apenas vig.nome_tabela (ignora alias f., p., d., s.)."""
    found: set[str] = set()
    for m in re.finditer(r"\b(vig)\.(mvw_[a-z0-9_]+)\b", sql, re.I):
        found.add(f"{m.group(1).lower()}.{m.group(2).lower()}")
    return found


def validate_select_sql(sql: str) -> str:
    s = _normalize(sql)
    if not re.match(r"^select\b", s, re.I):
        raise SqlGuardError("Somente consultas SELECT são permitidas.")
    if FORBIDDEN.search(s):
        raise SqlGuardError("Comando não permitido na consulta.")
    refs = _referenced_relations(s)
    if not refs:
        raise SqlGuardError("A consulta deve usar tabelas vig.mvw_* (ex.: vig.mvw_familia).")
    bad = {r for r in refs if r.split(".", 1)[0] not in ALLOWED_SCHEMAS}
    if bad:
        raise SqlGuardError(f"Schema não permitido: {', '.join(sorted(bad))}")
    unknown = refs - ALLOWED_RELATIONS
    if unknown:
        raise SqlGuardError(
            "Tabela não permitida: "
            + ", ".join(sorted(unknown))
            + ". Use: "
            + ", ".join(sorted(ALLOWED_RELATIONS))
        )
    return s


def wrap_limit(sql: str, limit: int = 500) -> str:
    s = validate_select_sql(sql)
    if re.search(r"\blimit\s+\d+", s, re.I):
        return s
    return f"{s} LIMIT {int(limit)}"
