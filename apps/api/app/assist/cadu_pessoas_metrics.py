"""Métricas canônicas — contagem de pessoas no CADU por recorte (dados primários).

Usa o dicionário/classificação CADU (cod_deficiencia, ind_def_*, cod_sexo, idade…)
sem depender do LLM para perguntas diretas de quantos/quais totais.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Any, Callable

from sqlalchemy import text
from sqlalchemy.engine import Connection

from ..vigilance.cadu_classificacao import cadu_sim, tem_deficiencia_expr
from ..vigilance.familia_mview import _table_exists
from .bairro_resolver import (
    _pick_variant,
    _prefix_name,
    extract_location_term,
    format_bairro_disambiguation,
    resolve_bairro,
    should_resolve_bairro,
)
from .geo_territorial import _CRAS_NUM

_QUANT = re.compile(
    r"quantas?|quantos?|total|n[uú]mero|numero|qtd|conte|existem|h[aá]\s+(?:quantas?)?",
    re.I,
)
_PESSOA = re.compile(
    r"\bpessoas?\b|\bindiv[ií]duos?\b|\bhabitantes?\b|\bcrian[cç]as?\b|"
    r"\badolesc|\bidosos?\b|\bmulheres?\b|\bhomens?\b",
    re.I,
)


def _fmt_int(n: int) -> str:
    return f"{n:,}".replace(",", ".")


@dataclass(frozen=True)
class PersonRecorte:
    key: str
    label: str
    sql_predicate: str
    dictionary_hint: str


def _recorte_deficiencia(alias: str = "p") -> PersonRecorte:
    pred = tem_deficiencia_expr(alias)
    return PersonRecorte(
        key="deficiencia",
        label="pessoas com deficiência",
        sql_predicate=pred,
        dictionary_hint=(
            "p.cod_deficiencia_memb = '1' (Sim) e/ou flags ind_def_* = '1' "
            "(física, visual, auditiva, mental, síndrome de Down, transtorno mental)"
        ),
    )


def _recorte_mulher(alias: str = "p") -> PersonRecorte:
    return PersonRecorte(
        key="mulher",
        label="mulheres",
        sql_predicate=f"btrim(COALESCE({alias}.cod_sexo::text, '')) IN ('2', '02')",
        dictionary_hint="p.cod_sexo_pessoa: 2 = feminino",
    )


def _recorte_homem(alias: str = "p") -> PersonRecorte:
    return PersonRecorte(
        key="homem",
        label="homens",
        sql_predicate=f"btrim(COALESCE({alias}.cod_sexo::text, '')) IN ('1', '01')",
        dictionary_hint="p.cod_sexo_pessoa: 1 = masculino",
    )


def _recorte_idoso(alias: str = "p") -> PersonRecorte:
    return PersonRecorte(
        key="idoso",
        label="pessoas com 60 anos ou mais",
        sql_predicate=f"{alias}.idade IS NOT NULL AND {alias}.idade >= 60",
        dictionary_hint="idade calculada a partir de p.dta_nasc_pessoa",
    )


def _recorte_crianca(alias: str = "p") -> PersonRecorte:
    return PersonRecorte(
        key="crianca",
        label="crianças (até 11 anos)",
        sql_predicate=f"{alias}.idade IS NOT NULL AND {alias}.idade <= 11",
        dictionary_hint="faixa etária CADU — idade em anos completos",
    )


def _recorte_adolescente(alias: str = "p") -> PersonRecorte:
    return PersonRecorte(
        key="adolescente",
        label="adolescentes (12 a 17 anos)",
        sql_predicate=f"{alias}.idade IS NOT NULL AND {alias}.idade BETWEEN 12 AND 17",
        dictionary_hint="faixa etária CADU — idade em anos completos",
    )


def _recorte_sit_rua(alias: str = "p") -> PersonRecorte:
    return PersonRecorte(
        key="sit_rua",
        label="pessoas em situação de rua",
        sql_predicate=cadu_sim(f"{alias}.marc_sit_rua"),
        dictionary_hint="p.cod_situacao_rua_pessoa marcado no CADU",
    )


def _recorte_trabalho_infantil(alias: str = "p") -> PersonRecorte:
    return PersonRecorte(
        key="trabalho_infantil",
        label="pessoas com indício de trabalho infantil",
        sql_predicate=cadu_sim(f"{alias}.ind_trabalho_infantil"),
        dictionary_hint="p.ind_trabalho_infantil_pessoa = '1'",
    )


_RECORTE_DETECTORS: tuple[tuple[re.Pattern[str], Callable[[], PersonRecorte]], ...] = (
    (
        re.compile(
            r"defici[eê]ncia|\bpcd\b|p\.?\s*c\.?\s*d\.?|com\s+defici|portador[a]?s?\s+de\s+defici",
            re.I,
        ),
        _recorte_deficiencia,
    ),
    (re.compile(r"trabalho\s+infantil", re.I), _recorte_trabalho_infantil),
    (
        re.compile(r"situa[cç][ãa]o\s+de\s+rua|em\s+situ[aç][ãa]o\s+de\s+rua|\bsit\s+rua\b", re.I),
        _recorte_sit_rua,
    ),
    (re.compile(r"\bmulheres?\b|\bfeminino\b", re.I), _recorte_mulher),
    (re.compile(r"\bhomens?\b|\bmasculino\b", re.I), _recorte_homem),
    (re.compile(r"\bidosos?\b|60\s*\+|terceira\s+idade|pessoa\s+idosa", re.I), _recorte_idoso),
    (re.compile(r"\badolesc", re.I), _recorte_adolescente),
    (re.compile(r"\bcrian[cç]as?\b", re.I), _recorte_crianca),
)


def detect_person_recorte(message: str) -> PersonRecorte | None:
    text_msg = (message or "").strip()
    for pattern, factory in _RECORTE_DETECTORS:
        if pattern.search(text_msg):
            return factory()
    return None


def _parse_cras(message: str) -> str | None:
    m = _CRAS_NUM.search(message or "")
    if not m:
        return None
    raw = m.group(1)
    return raw.lstrip("0") or raw


def _count_pessoas(
    conn: Connection,
    *,
    recorte: PersonRecorte,
    bairro: str | None = None,
    num_cras: str | None = None,
) -> int:
    clauses = [recorte.sql_predicate]
    params: dict[str, Any] = {}
    if bairro:
        clauses.append("lower(btrim(f.bairro::text)) = lower(:bairro)")
        params["bairro"] = bairro.strip()
    if num_cras:
        clauses.append("btrim(f.num_cras::text) = :num_cras")
        params["num_cras"] = num_cras.strip()
    where = " AND ".join(clauses)
    row = conn.execute(
        text(
            f"""
            SELECT COUNT(p.cadu_row_id)::bigint AS total
            FROM vig.mvw_pessoas p
            INNER JOIN vig.mvw_familia f ON f.codigo_familiar = p.codigo_familiar
            WHERE {where}
            """
        ),
        params,
    ).mappings().first()
    return int((row or {}).get("total") or 0)


def _format_answer(
    *,
    recorte: PersonRecorte,
    total: int,
    territory_label: str,
    seed: str,
    user_first_name: str = "",
) -> str:
    templates = [
        f"Em {territory_label}, há **{_fmt_int(total)}** **{recorte.label}** no CADU "
        f"(território geo via família).",
        f"No recorte {territory_label}, o CADU registra **{_fmt_int(total)}** **{recorte.label}**.",
    ]
    return _prefix_name(user_first_name, _pick_variant(seed, templates))


def build_cadu_pessoas_assist_hint() -> str:
    expr = tem_deficiencia_expr("p")
    return f"""## Pessoas CADU — recortes primários (vig.mvw_pessoas × vig.mvw_familia)
- Contagem de pessoas: `COUNT(p.cadu_row_id)` com `p JOIN f ON codigo_familiar`.
- **Deficiência / PCD**: NÃO use `= true`. Regra canônica:
  `{expr}`.
- Dicionário: `p.cod_deficiencia_memb` — 1=Sim, 2=Não; flags `ind_def_*` — 1=marcado.
- Sexo: `p.cod_sexo` texto '1' masculino, '2' feminino.
- Idade: `p.idade` (anos completos).
- Território: `f.bairro` (geo), `f.num_cras`. Match exato case-insensitive no bairro.
- IVS NC4 mede famílias com PCD no índice — para **contar pessoas**, use mvw_pessoas."""


def try_cadu_pessoas_recorte_metric(
    conn: Connection,
    message: str,
    *,
    user_first_name: str = "",
) -> dict[str, Any] | None:
    """Quantas pessoas [recorte] no bairro/CRAS — resposta canônica CADU."""
    text_msg = (message or "").strip()
    if not text_msg:
        return None
    if not _QUANT.search(text_msg) and not _PESSOA.search(text_msg):
        return None

    recorte = detect_person_recorte(text_msg)
    if not recorte:
        return None

    if not _table_exists(conn, "vig", "mvw_familia") or not _table_exists(conn, "vig", "mvw_pessoas"):
        return None

    num_cras = _parse_cras(text_msg)
    bairro_canon: str | None = None
    resolution = None

    if not num_cras:
        term = extract_location_term(text_msg)
        if term and should_resolve_bairro(text_msg, term):
            resolution = resolve_bairro(conn, term)
            if resolution.status == "multiple":
                return {
                    "answer": format_bairro_disambiguation(resolution, user_first_name),
                    "sql": None,
                    "row_count": 0,
                    "preview": resolution.matches,
                    "mode": "disambiguation",
                    "metric": "bairro_disambiguation",
                }
            if resolution.canonical:
                bairro_canon = resolution.canonical

    if not bairro_canon and not num_cras:
        return None

    total = _count_pessoas(
        conn,
        recorte=recorte,
        bairro=bairro_canon,
        num_cras=num_cras,
    )

    if bairro_canon:
        territory = f"**{bairro_canon}**"
        sql = (
            "SELECT COUNT(p.cadu_row_id) FROM vig.mvw_pessoas p "
            "INNER JOIN vig.mvw_familia f ON f.codigo_familiar = p.codigo_familiar "
            f"WHERE lower(btrim(f.bairro::text)) = lower('{bairro_canon.replace(chr(39), '')}') "
            f"AND {recorte.sql_predicate}"
        )
    else:
        territory = f"**CRAS {num_cras}**"
        sql = (
            "SELECT COUNT(p.cadu_row_id) FROM vig.mvw_pessoas p "
            "INNER JOIN vig.mvw_familia f ON f.codigo_familiar = p.codigo_familiar "
            f"WHERE btrim(f.num_cras::text) = '{num_cras}' "
            f"AND {recorte.sql_predicate}"
        )

    answer = _format_answer(
        recorte=recorte,
        total=total,
        territory_label=territory,
        seed=text_msg,
        user_first_name=user_first_name,
    )

    preview: dict[str, Any] = {
        "total": total,
        "recorte": recorte.key,
        "dictionary": recorte.dictionary_hint,
    }
    if bairro_canon:
        preview["bairro"] = bairro_canon
    if num_cras:
        preview["num_cras"] = num_cras

    return {
        "answer": answer,
        "sql": sql,
        "row_count": 1,
        "preview": [preview],
        "mode": "canonical",
        "metric": f"cadu_pessoas_{recorte.key}",
    }
