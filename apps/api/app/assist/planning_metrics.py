"""Planejamento territorial — demanda potencial no CADU (≠ matrícula SISC existente)."""

from __future__ import annotations

import re
from typing import Any

from sqlalchemy import text
from sqlalchemy.engine import Connection

from ..vigilance.familia_mview import _table_exists
from .bairro_resolver import (
    _pick_variant,
    _prefix_name,
)

_PLANNING = re.compile(
    r"implantar|implementar|novo\s+servi|abrir|criar|expandir|"
    r"suger|indic|recomend|onde\s+(?:abrir|implantar|criar)|"
    r"maior\s+demanda|potencial\s+(?:de\s+)?demanda|"
    r"preciso\s+(?:de\s+)?(?:um|uma)\s+(?:novo|nova)",
    re.I,
)
_EXISTING_SISC_QUERY = re.compile(
    r"matriculad|matricul|atendid[oa]s?\s+(?:no|em)\s+(?:sisc|conviv)|"
    r"quantos?\s+(?:atendid|matricul)|"
    r"servi[cç]os?\s+(?:de\s+conviv|scfv).*(?:exist|j[aá]\s+temos|temos\s+hoje)",
    re.I,
)
_AGE_RANGE = re.compile(
    r"(\d{1,2})\s*(?:a|-|á|at[eé])\s*(\d{1,2})\s*(?:anos)?",
    re.I,
)
_CRAS_SUGGEST = re.compile(
    r"qual\s+cras|cras\s+(?:me\s+)?suger|suger.*cras|"
    r"cras\s+(?:mais|indicad)|maior\s+demanda.*cras|cras.*maior\s+demanda",
    re.I,
)
_BAIRRO_IN_CRAS = re.compile(
    r"qual\s+bairro|bairro\s+(?:me\s+)?suger|suger.*bairro|"
    r"em\s+que\s+bairro|bairro\s+(?:mais|indicad)|onde\s+(?:no|em)\s+bairro",
    re.I,
)
_CRAS_FROM_TEXT = re.compile(
    r"cras\s*(\d{1,2})\b|"
    r"CRAS\s+(\d{1,2})\s*[—\-]",
    re.I,
)
_FAIXA = re.compile(r"crianç|crianc|adolesc|menor|faixa\s+et[aá]ria", re.I)


def _fmt_int(n: int) -> str:
    return f"{n:,}".replace(",", ".")


def _conversation_blob(message: str, transcript: list[dict[str, str]] | None) -> str:
    parts = [m.get("content", "") for m in (transcript or [])]
    parts.append(message)
    return " ".join(parts)


def parse_age_range(message: str, transcript: list[dict[str, str]] | None) -> tuple[int, int]:
    blob = _conversation_blob(message, transcript)
    match = _AGE_RANGE.search(message) or _AGE_RANGE.search(blob)
    if match:
        lo, hi = int(match.group(1)), int(match.group(2))
        if lo > hi:
            lo, hi = hi, lo
        return lo, hi
    if re.search(r"12\s*15|12\s*a\s*15", blob, re.I):
        return 12, 15
    if re.search(r"adolesc|12\s*17", blob, re.I):
        return 12, 17
    return 6, 17


def is_planning_demand(message: str, transcript: list[dict[str, str]] | None) -> bool:
    text_msg = message.strip()
    if not text_msg:
        return False
    if _EXISTING_SISC_QUERY.search(text_msg):
        return False
    blob = _conversation_blob(message, transcript)
    if not _PLANNING.search(text_msg):
        return False
    return bool(_FAIXA.search(text_msg) or _FAIXA.search(blob) or _CRAS_SUGGEST.search(text_msg))


def _extract_cras_from_transcript(transcript: list[dict[str, str]] | None) -> str | None:
    if not transcript:
        return None
    for msg in reversed(transcript):
        if msg.get("role") != "assistant":
            continue
        content = msg.get("content", "")
        m = _CRAS_FROM_TEXT.search(content)
        if m:
            return (m.group(1) or m.group(2) or "").strip()
        m = re.search(r"\*\*CRAS\s+(\d{1,2})", content, re.I)
        if m:
            return m.group(1)
    return None


def _cras_label(num: str, nome: str) -> str:
    n = (num or "").strip()
    name = (nome or "").strip()
    if n and name:
        return f"CRAS {n} — {name}"
    if n:
        return f"CRAS {n}"
    return name or "CRAS sem referência"


def _rank_cras_by_demand(
    conn: Connection,
    age_min: int,
    age_max: int,
) -> list[dict[str, Any]]:
    rows = conn.execute(
        text(
            """
            SELECT
              btrim(f.num_cras::text) AS num_cras,
              MAX(btrim(f.nom_cras::text)) AS nom_cras,
              COUNT(p.cadu_row_id)::bigint AS total
            FROM vig.mvw_pessoas p
            INNER JOIN vig.mvw_familia f ON f.codigo_familiar = p.codigo_familiar
            WHERE p.idade IS NOT NULL
              AND p.idade >= :age_min
              AND p.idade <= :age_max
              AND btrim(COALESCE(f.num_cras::text, '')) <> ''
            GROUP BY btrim(f.num_cras::text)
            ORDER BY total DESC, num_cras ASC
            """
        ),
        {"age_min": age_min, "age_max": age_max},
    ).mappings().all()
    return [dict(r) for r in rows]


def _top_bairro_in_cras(
    conn: Connection,
    num_cras: str,
    age_min: int,
    age_max: int,
) -> dict[str, Any] | None:
    row = conn.execute(
        text(
            """
            SELECT
              btrim(f.bairro::text) AS bairro,
              COUNT(p.cadu_row_id)::bigint AS total
            FROM vig.mvw_pessoas p
            INNER JOIN vig.mvw_familia f ON f.codigo_familiar = p.codigo_familiar
            WHERE p.idade IS NOT NULL
              AND p.idade >= :age_min
              AND p.idade <= :age_max
              AND btrim(f.num_cras::text) = :num_cras
              AND btrim(COALESCE(f.bairro::text, '')) <> ''
            GROUP BY btrim(f.bairro::text)
            ORDER BY total DESC, bairro ASC
            LIMIT 1
            """
        ),
        {"age_min": age_min, "age_max": age_max, "num_cras": num_cras.strip()},
    ).mappings().first()
    return dict(row) if row else None


def try_planning_demand_metric(
    conn: Connection,
    message: str,
    transcript: list[dict[str, str]] | None = None,
    *,
    user_first_name: str = "",
) -> dict[str, Any] | None:
    """Demanda potencial no CADU para planejar novo serviço (não usa matrícula SISC)."""
    if not is_planning_demand(message, transcript):
        return None
    if not _table_exists(conn, "vig", "mvw_familia") or not _table_exists(conn, "vig", "mvw_pessoas"):
        return None

    age_min, age_max = parse_age_range(message, transcript)
    faixa = f"{age_min} a {age_max} anos"

    if _BAIRRO_IN_CRAS.search(message):
        num_cras = _extract_cras_from_transcript(transcript)
        if not num_cras:
            return None

        top = _top_bairro_in_cras(conn, num_cras, age_min, age_max)
        if not top:
            answer = (
                f"Não encontrei bairros com crianças/adolescentes de **{faixa}** "
                f"no território do **CRAS {num_cras}**."
            )
            return {
                "answer": _prefix_name(user_first_name, answer),
                "sql": None,
                "row_count": 0,
                "preview": [],
                "mode": "canonical",
                "metric": "planning_bairro_cras_vazio",
            }

        bairro = str(top["bairro"])
        total = int(top["total"] or 0)
        templates = [
            f"Dentro do **CRAS {num_cras}**, o bairro **{bairro}** concentra a maior demanda "
            f"potencial: **{_fmt_int(total)}** crianças/adolescentes de **{faixa}** no CADU.",
            f"No território do **CRAS {num_cras}**, eu indicaria o bairro **{bairro}** — "
            f"**{_fmt_int(total)}** pessoas nessa faixa etária no cadastro.",
        ]
        answer = _prefix_name(user_first_name, _pick_variant(message, templates))
        sql = (
            "SELECT btrim(f.bairro), COUNT(p.cadu_row_id) FROM vig.mvw_pessoas p "
            "JOIN vig.mvw_familia f ON f.codigo_familiar = p.codigo_familiar "
            f"WHERE p.idade BETWEEN {age_min} AND {age_max} "
            f"AND btrim(f.num_cras::text) = '{num_cras}' GROUP BY 1 ORDER BY 2 DESC LIMIT 1"
        )
        return {
            "answer": answer,
            "sql": sql,
            "row_count": 1,
            "preview": [{"num_cras": num_cras, "bairro": bairro, "total": total}],
            "mode": "canonical",
            "metric": "planning_bairro_em_cras",
        }

    if not (_CRAS_SUGGEST.search(message) or _PLANNING.search(message)):
        return None

    rows = _rank_cras_by_demand(conn, age_min, age_max)
    if not rows:
        answer = (
            f"Não encontrei crianças/adolescentes de **{faixa}** territorializadas "
            "no CADU para comparar CRAS."
        )
        return {
            "answer": _prefix_name(user_first_name, answer),
            "sql": None,
            "row_count": 0,
            "preview": [],
            "mode": "canonical",
            "metric": "planning_cras_vazio",
        }

    top = rows[0]
    num = str(top.get("num_cras") or "")
    nome = str(top.get("nom_cras") or "")
    total = int(top.get("total") or 0)
    rotulo = _cras_label(num, nome)

    templates = [
        f"Para implantar um **novo Serviço de Convivência** para crianças de **{faixa}**, "
        f"o **{rotulo}** é o mais indicado pelo CADU: **{_fmt_int(total)}** pessoas "
        f"nessa faixa no território dele. Olhei **demanda potencial no cadastro**, "
        f"não quem já está matriculado no SISC.",
        f"Pelo CADU, eu sugeriria o **{rotulo}** — são **{_fmt_int(total)}** "
        f"crianças/adolescentes de **{faixa}** no território. "
        f"É demanda no cadastro, não matrícula atual no SISC.",
    ]
    answer = _prefix_name(user_first_name, _pick_variant(message, templates))

    if len(rows) > 1:
        others = [
            f"- **{_cras_label(str(r.get('num_cras') or ''), str(r.get('nom_cras') or ''))}**: "
            f"{_fmt_int(int(r.get('total') or 0))}"
            for r in rows[1:6]
        ]
        answer += "\n\n**Outros CRAS (demanda no CADU):**\n" + "\n".join(others)

    sql = (
        "SELECT btrim(f.num_cras), MAX(f.nom_cras), COUNT(p.cadu_row_id) "
        "FROM vig.mvw_pessoas p JOIN vig.mvw_familia f ON f.codigo_familiar = p.codigo_familiar "
        f"WHERE p.idade BETWEEN {age_min} AND {age_max} "
        "AND btrim(COALESCE(f.num_cras::text,'')) <> '' "
        "GROUP BY 1 ORDER BY 3 DESC"
    )
    return {
        "answer": answer,
        "sql": sql,
        "row_count": len(rows),
        "preview": rows[:8],
        "mode": "canonical",
        "metric": "planning_cras_demanda",
    }
