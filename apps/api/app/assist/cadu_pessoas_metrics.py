"""Métricas canônicas — contagem de pessoas/famílias no CADU por recorte (dados primários).

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
from .bairro_resolver import _pick_variant, _prefix_name
from .cadu_territory import CaduTerritory, resolve_cadu_territory, territory_sql_where

_QUANT = re.compile(
    r"quantas?|quantos?|total|n[uú]mero|numero|qtd|conte|existem|h[aá]\s+(?:quantas?)?",
    re.I,
)
_PESSOA = re.compile(
    r"\bpessoas?\b|\bindiv[ií]duos?\b|\bhabitantes?\b|\bcrian[cç]as?\b|"
    r"\badolesc|\bidosos?\b|\bmulheres?\b|\bhomens?\b",
    re.I,
)
_FAMILIA = re.compile(r"\bfam[ií]lias?\b", re.I)
_DEFICIENCIA = re.compile(
    r"defici[eê]ncia|\bpcd\b|p\.?\s*c\.?\s*d\.?|com\s+defici|portador[a]?s?\s+de\s+defici",
    re.I,
)
_DEF_BREAKDOWN = re.compile(
    r"por\s+tipo|tipos?\s+de\s+defici|desdobr|distribu[ií][çc][ãa]o|divid|"
    r"separad[oa]s?\s+por|qual\s+tipo|"
    r"defici[eê]ncia\s+f[ií]sica|defici[eê]ncia\s+visual|defici[eê]ncia\s+auditiva|"
    r"defici[eê]ncia\s+mental|m[uú]ltipla|s[ií]ndrome\s+de\s+down",
    re.I,
)


def _fmt_int(n: int) -> str:
    return f"{n:,}".replace(",", ".")


@dataclass(frozen=True)
class PersonRecorte:
    key: str
    label_pessoa: str
    label_familia: str
    sql_predicate: str
    dictionary_hint: str

    def label(self, *, familia: bool) -> str:
        return self.label_familia if familia else self.label_pessoa


def _recorte_deficiencia(alias: str = "p") -> PersonRecorte:
    pred = tem_deficiencia_expr(alias)
    return PersonRecorte(
        key="deficiencia",
        label_pessoa="pessoas com deficiência",
        label_familia="famílias com pelo menos uma pessoa com deficiência",
        sql_predicate=pred,
        dictionary_hint=(
            "p.cod_deficiencia_memb = '1' (Sim) e/ou flags ind_def_* = '1' "
            "(física, visual, auditiva, mental, síndrome de Down, transtorno mental)"
        ),
    )


def _recorte_mulher(alias: str = "p") -> PersonRecorte:
    return PersonRecorte(
        key="mulher",
        label_pessoa="mulheres",
        label_familia="famílias com pelo menos uma mulher",
        sql_predicate=f"btrim(COALESCE({alias}.cod_sexo::text, '')) IN ('2', '02')",
        dictionary_hint="p.cod_sexo_pessoa: 2 = feminino",
    )


def _recorte_homem(alias: str = "p") -> PersonRecorte:
    return PersonRecorte(
        key="homem",
        label_pessoa="homens",
        label_familia="famílias com pelo menos um homem",
        sql_predicate=f"btrim(COALESCE({alias}.cod_sexo::text, '')) IN ('1', '01')",
        dictionary_hint="p.cod_sexo_pessoa: 1 = masculino",
    )


def _recorte_idoso(alias: str = "p") -> PersonRecorte:
    return PersonRecorte(
        key="idoso",
        label_pessoa="pessoas com 60 anos ou mais",
        label_familia="famílias com pelo menos uma pessoa com 60 anos ou mais",
        sql_predicate=f"{alias}.idade IS NOT NULL AND {alias}.idade >= 60",
        dictionary_hint="idade calculada a partir de p.dta_nasc_pessoa",
    )


def _recorte_crianca(alias: str = "p") -> PersonRecorte:
    return PersonRecorte(
        key="crianca",
        label_pessoa="crianças (até 11 anos)",
        label_familia="famílias com criança até 11 anos",
        sql_predicate=f"{alias}.idade IS NOT NULL AND {alias}.idade <= 11",
        dictionary_hint="faixa etária CADU — idade em anos completos",
    )


def _recorte_adolescente(alias: str = "p") -> PersonRecorte:
    return PersonRecorte(
        key="adolescente",
        label_pessoa="adolescentes (12 a 17 anos)",
        label_familia="famílias com adolescente (12 a 17 anos)",
        sql_predicate=f"{alias}.idade IS NOT NULL AND {alias}.idade BETWEEN 12 AND 17",
        dictionary_hint="faixa etária CADU — idade em anos completos",
    )


def _recorte_sit_rua(alias: str = "p") -> PersonRecorte:
    return PersonRecorte(
        key="sit_rua",
        label_pessoa="pessoas em situação de rua",
        label_familia="famílias com pessoa em situação de rua",
        sql_predicate=cadu_sim(f"{alias}.marc_sit_rua"),
        dictionary_hint="p.cod_situacao_rua_pessoa marcado no CADU",
    )


def _recorte_trabalho_infantil(alias: str = "p") -> PersonRecorte:
    return PersonRecorte(
        key="trabalho_infantil",
        label_pessoa="pessoas com indício de trabalho infantil",
        label_familia="famílias com indício de trabalho infantil",
        sql_predicate=cadu_sim(f"{alias}.ind_trabalho_infantil"),
        dictionary_hint="p.ind_trabalho_infantil_pessoa = '1'",
    )


def _recorte_fora_escola(alias: str = "p") -> PersonRecorte:
    freq = cadu_sim(f"{alias}.ind_frequenta_escola")
    return PersonRecorte(
        key="fora_escola",
        label_pessoa="pessoas de 7 a 17 anos fora da escola",
        label_familia="famílias com pessoa de 7 a 17 anos fora da escola",
        sql_predicate=(
            f"{alias}.idade IS NOT NULL AND {alias}.idade BETWEEN 7 AND 17 "
            f"AND NOT ({freq})"
        ),
        dictionary_hint="p.ind_frequenta_escola_memb ≠ '1' na faixa escolar",
    )


_RECORTE_DETECTORS: tuple[tuple[re.Pattern[str], Callable[[], PersonRecorte]], ...] = (
    (_DEFICIENCIA, _recorte_deficiencia),
    (re.compile(r"trabalho\s+infantil", re.I), _recorte_trabalho_infantil),
    (
        re.compile(r"situa[cç][ãa]o\s+de\s+rua|em\s+situ[aç][ãa]o\s+de\s+rua|\bsit\s+rua\b", re.I),
        _recorte_sit_rua,
    ),
    (re.compile(r"fora\s+da\s+escola|n[aã]o\s+frequent", re.I), _recorte_fora_escola),
    (re.compile(r"\bmulheres?\b|\bfeminino\b", re.I), _recorte_mulher),
    (re.compile(r"\bhomens?\b|\bmasculino\b", re.I), _recorte_homem),
    (re.compile(r"\bidosos?\b|60\s*\+|terceira\s+idade|pessoa\s+idosa", re.I), _recorte_idoso),
    (re.compile(r"\badolesc", re.I), _recorte_adolescente),
    (re.compile(r"\bcrian[cç]as?\b", re.I), _recorte_crianca),
)


@dataclass(frozen=True)
class DeficienciaTipo:
    key: str
    label: str
    sql_predicate: str


DEFICIENCIA_TIPOS: tuple[DeficienciaTipo, ...] = (
    DeficienciaTipo("fisica", "Deficiência física", cadu_sim("p.ind_def_fisica")),
    DeficienciaTipo(
        "visual",
        "Deficiência visual",
        f"({cadu_sim('p.ind_def_cegueira')} OR {cadu_sim('p.ind_def_baixa_visao')})",
    ),
    DeficienciaTipo(
        "auditiva",
        "Deficiência auditiva",
        f"({cadu_sim('p.ind_def_surdez_profunda')} OR {cadu_sim('p.ind_def_surdez_leve')})",
    ),
    DeficienciaTipo(
        "mental_cognitiva",
        "Deficiência mental/cognitiva",
        f"({cadu_sim('p.ind_def_mental')} OR {cadu_sim('p.ind_def_sindrome_down')} "
        f"OR {cadu_sim('p.ind_def_transtorno_mental')})",
    ),
)


def detect_person_recorte(message: str) -> PersonRecorte | None:
    text_msg = (message or "").strip()
    for pattern, factory in _RECORTE_DETECTORS:
        if pattern.search(text_msg):
            return factory()
    return None


def wants_familia_count(message: str) -> bool:
    text_msg = (message or "").strip()
    if not _FAMILIA.search(text_msg):
        return False
    if _PESSOA.search(text_msg) and not re.search(
        r"\bfam[ií]lias?\s+com\b", text_msg, re.I
    ):
        return False
    return True


def wants_deficiencia_breakdown(message: str) -> bool:
    text_msg = (message or "").strip()
    return bool(_DEFICIENCIA.search(text_msg) and _DEF_BREAKDOWN.search(text_msg))


def _count_pessoas(
    conn: Connection,
    *,
    recorte: PersonRecorte,
    terr: CaduTerritory,
) -> int:
    terr_sql, params = territory_sql_where(terr)
    row = conn.execute(
        text(
            f"""
            SELECT COUNT(p.cadu_row_id)::bigint AS total
            FROM vig.mvw_pessoas p
            INNER JOIN vig.mvw_familia f ON f.codigo_familiar = p.codigo_familiar
            WHERE {terr_sql} AND {recorte.sql_predicate}
            """
        ),
        params,
    ).mappings().first()
    return int((row or {}).get("total") or 0)


def _count_familias_com_recorte(
    conn: Connection,
    *,
    recorte: PersonRecorte,
    terr: CaduTerritory,
) -> int:
    terr_sql, params = territory_sql_where(terr)
    row = conn.execute(
        text(
            f"""
            SELECT COUNT(DISTINCT f.codigo_familiar)::bigint AS total
            FROM vig.mvw_familia f
            WHERE {terr_sql}
              AND EXISTS (
                SELECT 1
                FROM vig.mvw_pessoas p
                WHERE p.codigo_familiar = f.codigo_familiar
                  AND {recorte.sql_predicate}
              )
            """
        ),
        params,
    ).mappings().first()
    return int((row or {}).get("total") or 0)


def _count_deficiencia_por_tipo(
    conn: Connection,
    *,
    terr: CaduTerritory,
) -> tuple[list[dict[str, Any]], int]:
    terr_sql, params = territory_sql_where(terr)
    any_def = tem_deficiencia_expr("p")
    selects = [
        f"COUNT(p.cadu_row_id) FILTER (WHERE {any_def})::bigint AS total_pcd",
    ]
    for tipo in DEFICIENCIA_TIPOS:
        selects.append(
            f"COUNT(p.cadu_row_id) FILTER (WHERE {tipo.sql_predicate})::bigint AS {tipo.key}"
        )
    row = conn.execute(
        text(
            f"""
            SELECT {", ".join(selects)}
            FROM vig.mvw_pessoas p
            INNER JOIN vig.mvw_familia f ON f.codigo_familiar = p.codigo_familiar
            WHERE {terr_sql}
            """
        ),
        params,
    ).mappings().first() or {}

    rows: list[dict[str, Any]] = []
    total_pcd = int(row.get("total_pcd") or 0)
    for tipo in DEFICIENCIA_TIPOS:
        n = int(row.get(tipo.key) or 0)
        if n:
            rows.append({"tipo": tipo.key, "label": tipo.label, "total": n})
    rows.sort(key=lambda r: -int(r["total"]))
    return rows, total_pcd


def _format_count_answer(
    *,
    recorte: PersonRecorte,
    total: int,
    terr: CaduTerritory,
    familia: bool,
    seed: str,
    user_first_name: str = "",
) -> str:
    label = recorte.label(familia=familia)
    unidade = "famílias" if familia else "pessoas"
    templates = [
        f"Em {terr.label}, há **{_fmt_int(total)}** **{label}** no CADU "
        f"({unidade}, território geo via família).",
        f"No recorte {terr.label}, o CADU registra **{_fmt_int(total)}** **{label}**.",
    ]
    return _prefix_name(user_first_name, _pick_variant(seed, templates))


def build_cadu_pessoas_assist_hint() -> str:
    expr = tem_deficiencia_expr("p")
    return f"""## Pessoas/famílias CADU — recortes primários (vig.mvw_pessoas × vig.mvw_familia)
- **Pessoas**: `COUNT(p.cadu_row_id)` com `p JOIN f ON codigo_familiar`.
- **Famílias com recorte**: `COUNT(DISTINCT f.codigo_familiar)` + `EXISTS` pessoa que atende o filtro.
- **Deficiência / PCD**: NÃO use `= true`. Regra canônica: `{expr}`.
- **Tipos de deficiência**: ind_def_fisica, ind_def_cegueira/baixa_visao, surdez, mental/down/transtorno.
- Dicionário: `p.cod_deficiencia_memb` — 1=Sim, 2=Não; flags `ind_def_*` — 1=marcado.
- Fora da escola (7–17): idade BETWEEN 7 AND 17 AND NOT ind_frequenta_escola = '1'.
- Território: `f.bairro` (geo), `f.num_cras`. Match exato case-insensitive no bairro."""


def try_cadu_deficiencia_breakdown_metric(
    conn: Connection,
    message: str,
    *,
    user_first_name: str = "",
) -> dict[str, Any] | None:
    """Desdobramento de PCD por tipo de deficiência no território."""
    text_msg = (message or "").strip()
    if not wants_deficiencia_breakdown(text_msg):
        return None
    if not _table_exists(conn, "vig", "mvw_familia") or not _table_exists(conn, "vig", "mvw_pessoas"):
        return None

    resolved = resolve_cadu_territory(conn, text_msg, user_first_name=user_first_name)
    if resolved is None or isinstance(resolved, dict):
        return resolved
    terr = resolved

    tipos, total_pcd = _count_deficiencia_por_tipo(conn, terr=terr)
    if not tipos:
        answer = _prefix_name(
            user_first_name,
            f"Em {terr.label}, não encontrei pessoas com deficiência registradas no CADU.",
        )
        return {
            "answer": answer,
            "sql": None,
            "row_count": 0,
            "preview": [],
            "mode": "canonical",
            "metric": "cadu_pcd_tipo_vazio",
        }

    linhas = [f"- **{r['label']}**: {_fmt_int(int(r['total']))}" for r in tipos[:8]]
    answer = _prefix_name(
        user_first_name,
        f"Em {terr.label}, há **{_fmt_int(total_pcd)}** pessoas com deficiência no CADU. "
        f"Por tipo:\n\n" + "\n".join(linhas),
    )
    terr_sql, _ = territory_sql_where(terr)
    sql = (
        "SELECT tipo, COUNT(p.cadu_row_id) FROM vig.mvw_pessoas p "
        f"JOIN vig.mvw_familia f ON f.codigo_familiar = p.codigo_familiar "
        f"WHERE {terr_sql} GROUP BY tipo /* flags ind_def_* */"
    )
    preview = [{"bairro": terr.bairro, "num_cras": terr.num_cras, "total_pcd": total_pcd, **r} for r in tipos]
    return {
        "answer": answer,
        "sql": sql,
        "row_count": len(tipos),
        "preview": preview,
        "mode": "canonical",
        "metric": "cadu_pcd_por_tipo",
    }


def try_cadu_pessoas_recorte_metric(
    conn: Connection,
    message: str,
    *,
    user_first_name: str = "",
) -> dict[str, Any] | None:
    """Quantas pessoas/famílias [recorte] no bairro/CRAS — resposta canônica CADU."""
    text_msg = (message or "").strip()
    if not text_msg:
        return None

    breakdown = try_cadu_deficiencia_breakdown_metric(
        conn, text_msg, user_first_name=user_first_name
    )
    if breakdown:
        return breakdown

    if not _QUANT.search(text_msg) and not _PESSOA.search(text_msg) and not _FAMILIA.search(text_msg):
        return None

    recorte = detect_person_recorte(text_msg)
    if not recorte:
        return None

    if not _table_exists(conn, "vig", "mvw_familia") or not _table_exists(conn, "vig", "mvw_pessoas"):
        return None

    resolved = resolve_cadu_territory(conn, text_msg, user_first_name=user_first_name)
    if resolved is None:
        return None
    if isinstance(resolved, dict):
        return resolved
    terr = resolved

    familia = wants_familia_count(text_msg)
    if familia:
        total = _count_familias_com_recorte(conn, recorte=recorte, terr=terr)
        metric = f"cadu_familias_{recorte.key}"
    else:
        total = _count_pessoas(conn, recorte=recorte, terr=terr)
        metric = f"cadu_pessoas_{recorte.key}"

    terr_sql, params = territory_sql_where(terr)
    if familia:
        sql = (
            "SELECT COUNT(DISTINCT f.codigo_familiar) FROM vig.mvw_familia f "
            f"WHERE {terr_sql} AND EXISTS (SELECT 1 FROM vig.mvw_pessoas p "
            f"WHERE p.codigo_familiar = f.codigo_familiar AND {recorte.sql_predicate})"
        )
    else:
        sql = (
            "SELECT COUNT(p.cadu_row_id) FROM vig.mvw_pessoas p "
            "INNER JOIN vig.mvw_familia f ON f.codigo_familiar = p.codigo_familiar "
            f"WHERE {terr_sql} AND {recorte.sql_predicate}"
        )

    answer = _format_count_answer(
        recorte=recorte,
        total=total,
        terr=terr,
        familia=familia,
        seed=text_msg,
        user_first_name=user_first_name,
    )

    preview: dict[str, Any] = {
        "total": total,
        "recorte": recorte.key,
        "granularidade": "familia" if familia else "pessoa",
        "dictionary": recorte.dictionary_hint,
    }
    if terr.bairro:
        preview["bairro"] = terr.bairro
    if terr.num_cras:
        preview["num_cras"] = terr.num_cras

    return {
        "answer": answer,
        "sql": sql,
        "row_count": 1,
        "preview": [preview],
        "mode": "canonical",
        "metric": metric,
    }
