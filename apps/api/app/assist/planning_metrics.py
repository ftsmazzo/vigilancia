"""Planejamento territorial — demanda potencial no CADU (≠ matrícula SISC existente)."""

from __future__ import annotations

import re
from typing import Any

from sqlalchemy import text
from sqlalchemy.engine import Connection
from sqlalchemy.orm import Session

from ..vigilance.familia_mview import _table_exists
from .bairro_resolver import _pick_variant, _prefix_name
from .conversation_intent import (
    is_planning_coverage_followup,
    is_planning_followup,
    is_planning_turn,
    user_messages_blob,
    wants_planning_ranking,
)
from .planning_diagnostico import collect_reflexion_result

_AGE_RANGE = re.compile(
    r"(\d{1,2})\s*(?:a|-|á|at[eé])\s*(\d{1,2})\s*(?:anos)?",
    re.I,
)
_CRAS_SUGGEST = re.compile(
    r"qual\s+cras|cras\s+(?:me\s+)?suger|suger.*cras|"
    r"cras\s+(?:mais|indicad)|maior\s+demanda.*cras|cras.*maior\s+demanda|"
    r"escolher\s+um\s+cras|escolhe\s+.*cras",
    re.I,
)
_BAIRRO_IN_CRAS = re.compile(
    r"\bbairro\b.*(?:desse|nesse|deste|dese)\s+cras|"
    r"(?:desse|nesse|deste|dese)\s+cras.*\bbairro\b|"
    r"qual\s+bairro|em\s+que\s+bairro|bairro\s+(?:mais|indicad)",
    re.I,
)
_COVERAGE = re.compile(
    r"car[eê]ncia|j[aá]\s+(?:possui|tem|existe)|possui\s+(?:algum|alguma)\s+serv|"
    r"servi[cç]o\s+(?:para|nesse|neste)|tem\s+car[eê]ncia|oferta|"
    r"considerou\s+como\s+vulnerabilidade|o\s*que\s+considerou",
    re.I,
)


def _fmt_int(n: int) -> str:
    return f"{n:,}".replace(",", ".")


def parse_age_range(message: str, transcript: list[dict[str, str]] | None) -> tuple[int, int]:
    blob = user_messages_blob(transcript, message)
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


def _extract_recommended_cras(transcript: list[dict[str, str]] | None) -> str | None:
    if not transcript:
        return None
    for msg in reversed(transcript):
        if msg.get("role") != "assistant":
            continue
        content = msg.get("content", "")
        head = content.split("Outros CRAS")[0].split("Demais unidades")[0].split("Demais CRAS")[0]

        patterns = (
            r"CRAS\s*(\d{1,2})\s*[—\-–].*?(?:mais indicado|indicado pelo|indicaria|sugeriria|maior demanda)",
            r"(?:indicaria|sugeriria|indicado|scfv)[^\n]{0,100}?CRAS\s*(\d{1,2})",
            r"CRAS\s*(\d{1,2})[^\n]{0,120}?(?:mais indicado|indicaria|maior demanda|reúne a maior)",
            r"\*\*CRAS\s*(\d{1,2})\*\*",
            r"\bCRAS\s*(\d{1,2})\b",
        )
        for pat in patterns:
            m = re.search(pat, head, re.I)
            if m:
                return m.group(1).strip()
    return None


def _cras_label(num: str, nome: str) -> str:
    n = (num or "").strip()
    name = (nome or "").strip()
    if not n:
        return name or "CRAS sem referência"
    if not name or re.fullmatch(rf"cras\s*{re.escape(n)}", name, re.I):
        return f"CRAS {n}"
    if name.lower().startswith(f"cras {n}".lower()):
        return name
    return f"CRAS {n} — {name}"


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


def _extract_recommended_bairro(transcript: list[dict[str, str]] | None) -> str | None:
    if not transcript:
        return None
    for msg in reversed(transcript):
        if msg.get("role") != "assistant":
            continue
        content = msg.get("content", "")
        patterns = (
            r"bairro\s+\*\*([^*]+)\*\*",
            r"olharia o bairro\s+\*\*([^*]+)\*\*",
            r"No \*\*CRAS \d+\*\*, o bairro \*\*([^*]+)\*\*",
        )
        for pat in patterns:
            m = re.search(pat, content, re.I)
            if m:
                return m.group(1).strip()
    return None


def _count_cadu_bairro(
    conn: Connection,
    bairro: str,
    age_min: int,
    age_max: int,
) -> int:
    row = conn.execute(
        text(
            """
            SELECT COUNT(p.cadu_row_id)::bigint AS total
            FROM vig.mvw_pessoas p
            INNER JOIN vig.mvw_familia f ON f.codigo_familiar = p.codigo_familiar
            WHERE p.idade IS NOT NULL
              AND p.idade >= :age_min
              AND p.idade <= :age_max
              AND btrim(f.bairro::text) = :bairro
            """
        ),
        {"age_min": age_min, "age_max": age_max, "bairro": bairro.strip()},
    ).mappings().first()
    return int((row or {}).get("total") or 0)


def _count_sisc_bairro(
    conn: Connection,
    bairro: str,
    age_min: int,
    age_max: int,
) -> int | None:
    if not _table_exists(conn, "vig", "mvw_sisc_qualificado"):
        return None
    row = conn.execute(
        text(
            """
            SELECT COUNT(DISTINCT s.nis_norm)::bigint AS total
            FROM vig.mvw_sisc_qualificado s
            INNER JOIN vig.mvw_familia f ON f.codigo_familiar = s.codigo_familiar
            WHERE s.classificacao_vinculo = 'vinculado_cadu'
              AND s.codigo_familiar IS NOT NULL
              AND s.cadu_idade IS NOT NULL
              AND s.cadu_idade >= :age_min
              AND s.cadu_idade <= :age_max
              AND btrim(f.bairro::text) = :bairro
            """
        ),
        {"age_min": age_min, "age_max": age_max, "bairro": bairro.strip()},
    ).mappings().first()
    return int((row or {}).get("total") or 0)


def try_planning_coverage_metric(
    conn: Connection,
    message: str,
    transcript: list[dict[str, str]] | None = None,
    *,
    db: Session | None = None,
    user_first_name: str = "",
) -> dict[str, Any] | None:
    """Carência SCFV: demanda CADU territorial × matrícula SISC no bairro/faixa."""
    if not is_planning_coverage_followup(message, transcript):
        return None
    if not _table_exists(conn, "vig", "mvw_familia") or not _table_exists(conn, "vig", "mvw_pessoas"):
        return None

    age_min, age_max = parse_age_range(message, transcript)
    faixa = f"{age_min} a {age_max} anos"
    bairro = _extract_recommended_bairro(transcript)
    num_cras = _extract_recommended_cras(transcript)

    if not bairro:
        answer = (
            "Para avaliar carência, preciso do **bairro** indicado na conversa "
            "(demanda CADU × matrícula SISC no mesmo recorte)."
        )
        return {
            "answer": _prefix_name(user_first_name, answer),
            "sql": None,
            "row_count": 0,
            "preview": [],
            "mode": "canonical",
            "metric": "planning_carencia",
            "use_analyst": True,
        }

    demanda = _count_cadu_bairro(conn, bairro, age_min, age_max)
    sisc = _count_sisc_bairro(conn, bairro, age_min, age_max)

    if db:
        reflex = collect_reflexion_result(
            conn,
            db,
            bairro=bairro,
            age_min=age_min,
            age_max=age_max,
            num_cras=num_cras,
            demanda=demanda,
            sisc=sisc,
        )
        return {
            "answer": "",
            "sql": "-- Reflexão territorial multi-eixo (analyst_reflexion v2)",
            "row_count": len(reflex["preview"]),
            "preview": reflex["preview"],
            "reflexion_guide": reflex["reflexion_guide"],
            "reflexion_axes": reflex["reflexion_axes"],
            "mode": "canonical",
            "metric": "planning_carencia",
            "use_analyst": True,
        }

    facts = [
        {
            "axis": "A",
            "label": f"Demanda CADU ({faixa}) — {bairro}",
            "value": str(demanda),
            "source": "vig.mvw_pessoas × vig.mvw_familia",
            "detail": "faixa etária no bairro",
        }
    ]
    return {
        "answer": "",
        "sql": None,
        "row_count": len(facts),
        "preview": facts,
        "mode": "canonical",
        "metric": "planning_carencia",
        "use_analyst": True,
    }


def try_planning_demand_metric(
    conn: Connection,
    message: str,
    transcript: list[dict[str, str]] | None = None,
    *,
    db: Session | None = None,
    user_first_name: str = "",
) -> dict[str, Any] | None:
    """Demanda potencial no CADU para planejar novo SCFV (não matrícula SISC)."""
    coverage = try_planning_coverage_metric(
        conn, message, transcript, db=db, user_first_name=user_first_name
    )
    if coverage:
        return coverage

    if not is_planning_turn(message, transcript):
        return None
    if not _table_exists(conn, "vig", "mvw_familia") or not _table_exists(conn, "vig", "mvw_pessoas"):
        return None

    age_min, age_max = parse_age_range(message, transcript)
    faixa = f"{age_min} a {age_max} anos"

    if is_planning_followup(message, transcript) or _BAIRRO_IN_CRAS.search(message):
        num_cras = _extract_recommended_cras(transcript)
        if not num_cras:
            answer = (
                "Para indicar o bairro, preciso saber **qual CRAS** — "
                "foi o que apareceu como maior demanda na pergunta anterior."
            )
            return {
                "answer": _prefix_name(user_first_name, answer),
                "sql": None,
                "row_count": 0,
                "preview": [],
                "mode": "disambiguation",
                "metric": "planning_cras_missing",
            }

        top = _top_bairro_in_cras(conn, num_cras, age_min, age_max)
        if not top:
            answer = (
                f"No território do **CRAS {num_cras}**, não encontrei crianças de **{faixa}** "
                "com bairro territorializado no CADU."
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
        sisc = _count_sisc_bairro(conn, bairro, age_min, age_max)
        sql = (
            "SELECT btrim(f.bairro), COUNT(p.cadu_row_id) FROM vig.mvw_pessoas p "
            "JOIN vig.mvw_familia f ON f.codigo_familiar = p.codigo_familiar "
            f"WHERE p.idade BETWEEN {age_min} AND {age_max} "
            f"AND btrim(f.num_cras::text) = '{num_cras}' GROUP BY 1 ORDER BY 2 DESC LIMIT 1"
        )
        if db:
            reflex = collect_reflexion_result(
                conn,
                db,
                bairro=bairro,
                age_min=age_min,
                age_max=age_max,
                num_cras=num_cras,
                demanda=total,
                sisc=sisc,
            )
            return {
                "answer": "",
                "sql": sql,
                "row_count": len(reflex["preview"]),
                "preview": reflex["preview"],
                "reflexion_guide": reflex["reflexion_guide"],
                "reflexion_axes": reflex["reflexion_axes"],
                "mode": "canonical",
                "metric": "planning_bairro_em_cras",
                "use_analyst": True,
            }
        templates = [
            f"No **CRAS {num_cras}**, o bairro **{bairro}** concentra a maior demanda "
            f"(**{_fmt_int(total)}** crianças de **{faixa}** no CADU).",
            f"Dentro do **CRAS {num_cras}**, eu olharia o bairro **{bairro}** "
            f"— **{_fmt_int(total)}** nessa faixa etária no cadastro.",
        ]
        return {
            "answer": _prefix_name(user_first_name, _pick_variant(message, templates)),
            "sql": sql,
            "row_count": 1,
            "preview": [{"num_cras": num_cras, "bairro": bairro, "total": total}],
            "mode": "canonical",
            "metric": "planning_bairro_em_cras",
        }

    if not (_CRAS_SUGGEST.search(message) or is_planning_turn(message, transcript)):
        return None

    rows = _rank_cras_by_demand(conn, age_min, age_max)
    if not rows:
        answer = f"Não encontrei crianças de **{faixa}** territorializadas por CRAS no CADU."
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
        f"Para um **SCFV** de **{faixa}**, eu indicaria o **{rotulo}**: "
        f"**{_fmt_int(total)}** crianças nessa faixa no território (CADU).",
        f"Pelo CADU, o **{rotulo}** reúne a maior demanda — "
        f"**{_fmt_int(total)}** crianças de **{faixa}** no território.",
    ]
    answer = _prefix_name(user_first_name, _pick_variant(message, templates))

    if wants_planning_ranking(message) and len(rows) > 1:
        others = [
            f"- **{_cras_label(str(r.get('num_cras') or ''), str(r.get('nom_cras') or ''))}**: "
            f"{_fmt_int(int(r.get('total') or 0))}"
            for r in rows[1:6]
        ]
        answer += "\n\n**Demais CRAS (CADU):**\n" + "\n".join(others)

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
