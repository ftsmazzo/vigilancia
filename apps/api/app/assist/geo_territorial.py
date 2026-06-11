"""Consultas territoriais (geo × CEP) — bairro e CRAS em vig.mvw_familia."""

from __future__ import annotations

import re
from typing import Any

from sqlalchemy import text
from sqlalchemy.engine import Connection

from ..vigilance.familia_mview import _table_exists
from .bairro_resolver import (
    bairro_sql_filter,
    extract_location_term,
    format_bairro_disambiguation,
    resolve_bairro,
)

_BAIRRO_FROM_ANSWER = re.compile(r"No bairro \*\*([^*]+)\*\*", re.I)
_FOLLOWUP = re.compile(
    r"dessas|destas|essas|delas|dessas\s+fam|destas\s+fam|nesse\s+bairro|"
    r"neste\s+bairro|no\s+mesmo\s+bairro|dessas\s+fam[ií]lias|destas\s+fam[ií]lias",
    re.I,
)
_PBF = re.compile(r"pbf|bolsa\s+fam|programa\s+bolsa|recebe[m]?\s+(?:o\s+)?(?:pbf|bolsa)", re.I)
_FAMILIAS = re.compile(
    r"quantas?\s+fam[ií]lias?|total\s+de\s+fam[ií]lias?|n[uú]mero\s+de\s+fam[ií]lias?|"
    r"temos\s+(?:de\s+)?fam[ií]lias?|recebe[m]?|recebem",
    re.I,
)
_BAIRRO = re.compile(r"\bbairro\b", re.I)
_CRAS = re.compile(r"\bcras\b", re.I)
_CRAS_NUM = re.compile(r"(?:cras|no\s+cras)\s*(\d{1,2})\b", re.I)
_COUNT_BAIRROS = re.compile(r"quantos?\s+bairros?", re.I)
_COUNT_CRAS = re.compile(r"quantos?\s+cras\b", re.I)

_BAIRRO_TERM = re.compile(
    r"(?:"
    r"(?:no|do|da)\s+bairro\s+(.+?)(?:\?|\.|$)|"
    r"bairro\s+(.+?)(?:\?|\.|$)"
    r")",
    re.I,
)


def _fmt_int(n: int) -> str:
    return f"{n:,}".replace(",", ".")


def _conversation_blob(message: str, transcript: list[dict[str, str]] | None) -> str:
    parts = [m.get("content", "") for m in (transcript or [])]
    parts.append(message)
    return " ".join(parts)


def _extract_bairro_term(message: str) -> str | None:
    m = _BAIRRO_TERM.search(message.strip())
    if not m:
        return None
    term = (m.group(1) or m.group(2) or "").strip().strip("\"'")
    term = re.sub(r"\s+(?:tem|temos|h[aá]|existem).*$", "", term, flags=re.I).strip()
    if len(term) < 2:
        return None
    return term


def extract_bairro_context(
    message: str,
    transcript: list[dict[str, str]] | None,
) -> tuple[str | None, str | None]:
    """
    Recupera bairro territorial da pergunta ou do histórico recente.
    Retorna (termo_busca, nome_canonico) — nome_canonico quando há match único na geo.
    """
    term = _extract_bairro_term(message)
    if not term:
        for msg in reversed(transcript or []):
            content = msg.get("content", "")
            if msg.get("role") == "assistant":
                m = _BAIRRO_FROM_ANSWER.search(content)
                if m:
                    term = m.group(1).strip()
                    break
            if msg.get("role") == "user":
                t = _extract_bairro_term(content)
                if t:
                    term = t
                    break

    if not term:
        return None, None
    return term, None


def _resolve_bairro_label(conn: Connection, term: str) -> tuple[str, list[dict[str, Any]], Any]:
    resolution = resolve_bairro(conn, term)
    if resolution.status == "multiple":
        return term, resolution.matches, resolution
    if resolution.canonical:
        return resolution.canonical, resolution.matches or [{"bairro": resolution.canonical}], resolution
    matches = _bairro_matches(conn, term, limit=8)
    if len(matches) == 1:
        return str(matches[0]["bairro"]), matches, resolution
    return term, matches, resolution


def _count_pbf_bairro(
    conn: Connection,
    term: str,
    resolution=None,
) -> tuple[int, int, list[dict[str, Any]], Any]:
    if resolution is None:
        resolution = resolve_bairro(conn, term)
    where_sql, params = bairro_sql_filter(
        resolution if resolution.status != "multiple" else None,
        term,
    )
    row = conn.execute(
        text(
            f"""
            SELECT
              COUNT(DISTINCT f.codigo_familiar)::bigint AS total,
              COUNT(DISTINCT f.codigo_familiar) FILTER (
                WHERE COALESCE(f.marc_pbf, FALSE)
              )::bigint AS com_pbf
            FROM vig.mvw_familia f
            WHERE btrim(COALESCE(f.bairro::text, '')) <> ''
              AND {where_sql}
            """
        ),
        params,
    ).mappings().first() or {}
    total = int(row.get("total") or 0)
    com_pbf = int(row.get("com_pbf") or 0)
    matches = resolution.matches if resolution.status == "multiple" else _bairro_matches(conn, term, limit=8)
    if total == 0 and resolution.status not in ("multiple", "none"):
        matches = resolution.matches or _bairro_matches(conn, term, limit=8)
    return com_pbf, total, matches, resolution


def try_geo_contextual_followup(
    conn: Connection,
    message: str,
    transcript: list[dict[str, str]] | None = None,
) -> dict | None:
    """Follow-up com memória de bairro (ex.: «dessas famílias recebem PBF?»)."""
    if not _table_exists(conn, "vig", "mvw_familia"):
        return None

    text_msg = message.strip()
    is_followup = bool(_FOLLOWUP.search(text_msg))
    if not is_followup and not (_PBF.search(text_msg) and transcript):
        return None

    term, _ = extract_bairro_context(text_msg, transcript)
    if not term:
        return None

    if _PBF.search(text_msg) and (_FAMILIAS.search(text_msg) or is_followup):
        com_pbf, total, matches, resolution = _count_pbf_bairro(conn, term)
        if resolution.status == "multiple":
            return {
                "answer": format_bairro_disambiguation(resolution),
                "sql": None,
                "row_count": 0,
                "preview": matches,
                "mode": "disambiguation",
                "metric": "bairro_disambiguation",
            }
        label, _, resolution = _resolve_bairro_label(conn, term)
        pct = round(100.0 * com_pbf / total, 2) if total else 0.0
        where_sql, params = bairro_sql_filter(resolution, term)
        sql = (
            "SELECT COUNT(DISTINCT f.codigo_familiar) FROM vig.mvw_familia f "
            f"WHERE btrim(COALESCE(f.bairro::text, '')) <> '' AND {where_sql} "
            "AND COALESCE(f.marc_pbf, FALSE)"
        )
        if total == 0:
            return None
        answer = (
            f"No bairro **{label}**, **{_fmt_int(com_pbf)}** famílias recebem o Bolsa Família "
            f"de um total de **{_fmt_int(total)}** famílias no território "
            f"(**{pct:.2f} %**)."
        )
        return {
            "answer": answer,
            "sql": sql,
            "row_count": 1,
            "preview": [{"bairro": label, "familias_pbf": com_pbf, "familias_total": total}],
            "mode": "canonical",
            "metric": "geo_contextual_pbf_bairro",
        }

    return None


def _bairro_matches(conn: Connection, term: str, *, limit: int = 5) -> list[dict[str, Any]]:
    sql = """
        SELECT
          btrim(f.bairro::text) AS bairro,
          COUNT(DISTINCT f.codigo_familiar)::bigint AS familias,
          COUNT(DISTINCT f.codigo_familiar) FILTER (WHERE COALESCE(f.tem_geo, FALSE))::bigint AS com_geo
        FROM vig.mvw_familia f
        WHERE btrim(COALESCE(f.bairro::text, '')) <> ''
          AND btrim(f.bairro::text) ILIKE :pat
        GROUP BY 1
        ORDER BY familias DESC
        LIMIT :lim
    """
    return [
        dict(r)
        for r in conn.execute(
            text(sql),
            {"pat": f"%{term.strip()}%", "lim": limit},
        ).mappings().all()
    ]


def _count_familias_bairro(
    conn: Connection,
    term: str,
    resolution=None,
) -> tuple[int, list[dict[str, Any]], Any]:
    if resolution is None:
        resolution = resolve_bairro(conn, term)
    if resolution.status == "multiple":
        return 0, resolution.matches, resolution

    where_sql, params = bairro_sql_filter(resolution, term)
    row = conn.execute(
        text(
            f"""
            SELECT COUNT(DISTINCT f.codigo_familiar)::bigint AS familias
            FROM vig.mvw_familia f
            WHERE btrim(COALESCE(f.bairro::text, '')) <> ''
              AND {where_sql}
            """
        ),
        params,
    ).mappings().first() or {}
    total = int(row.get("familias") or 0)
    matches = resolution.matches or _bairro_matches(conn, term, limit=8)
    if resolution.canonical:
        matches = [{"bairro": resolution.canonical, "familias": total}]
    return total, matches, resolution


def _count_familias_cras(conn: Connection, num_cras: str) -> tuple[int, str | None]:
    row = conn.execute(
        text(
            """
            SELECT
              COUNT(DISTINCT f.codigo_familiar)::bigint AS familias,
              MAX(btrim(f.nom_cras::text)) AS nom_cras
            FROM vig.mvw_familia f
            WHERE btrim(COALESCE(f.num_cras::text, '')) = :num
            """
        ),
        {"num": num_cras.strip()},
    ).mappings().first()
    if not row:
        return 0, None
    return int(row["familias"] or 0), str(row["nom_cras"] or "") or None


def build_geo_territorial_hint(conn: Connection) -> str:
    """Resumo ao vivo para o AgenteSQL (bairros/CRAS territorializados)."""
    if not _table_exists(conn, "vig", "mvw_familia"):
        return ""

    stats = conn.execute(
        text(
            """
            SELECT
              COUNT(*) FILTER (WHERE COALESCE(tem_geo, FALSE))::bigint AS com_geo,
              COUNT(*) FILTER (WHERE NOT COALESCE(tem_geo, FALSE))::bigint AS sem_geo,
              COUNT(DISTINCT btrim(num_cras::text)) FILTER (
                WHERE num_cras IS NOT NULL AND btrim(num_cras::text) <> ''
              )::bigint AS n_cras,
              COUNT(DISTINCT btrim(bairro::text)) FILTER (
                WHERE bairro IS NOT NULL AND btrim(bairro::text) <> ''
              )::bigint AS n_bairros
            FROM vig.mvw_familia
            """
        )
    ).mappings().first() or {}

    top = conn.execute(
        text(
            """
            SELECT btrim(bairro::text) AS bairro, COUNT(*)::bigint AS familias
            FROM vig.mvw_familia
            WHERE btrim(COALESCE(bairro::text, '')) <> ''
            GROUP BY 1
            ORDER BY familias DESC
            LIMIT 12
            """
        )
    ).mappings().all()

    lines = [
        "## Territorialização geo (vig.mvw_familia — via CEP × raw.geo__tbl_geo)",
        f"- Famílias com geo (tem_geo=true): {_fmt_int(int(stats.get('com_geo') or 0))}",
        f"- Famílias sem match de CEP na geo: {_fmt_int(int(stats.get('sem_geo') or 0))}",
        f"- CRAS territoriais distintos (f.num_cras): {int(stats.get('n_cras') or 0)}",
        f"- Bairros distintos (f.bairro): {int(stats.get('n_bairros') or 0)}",
        "- Filtro por bairro: btrim(f.bairro::text) ILIKE '%termo%' (NUNCA f.bairro_cadu salvo auditoria).",
        "- Filtro por CRAS: btrim(f.num_cras::text) = 'N' (1 a 12). CRAS 9 = Bonfim Paulista.",
    ]
    if top:
        amostra = ", ".join(f"{r['bairro']} ({int(r['familias'] or 0)})" for r in top[:8])
        lines.append(f"- Bairros com mais famílias (amostra): {amostra}")
    return "\n".join(lines)


def try_geo_territorial_metric(
    conn: Connection,
    message: str,
    transcript: list[dict[str, str]] | None = None,
) -> dict | None:
    """Respostas canônicas para bairro/CRAS territorial (sem LLM)."""
    if not _table_exists(conn, "vig", "mvw_familia"):
        return None

    text_msg = message.strip()
    blob = _conversation_blob(message, transcript)

    # Quantos bairros / quantos CRAS
    if _COUNT_BAIRROS.search(text_msg):
        n = conn.execute(
            text(
                """
                SELECT COUNT(DISTINCT btrim(bairro::text))::bigint
                FROM vig.mvw_familia
                WHERE bairro IS NOT NULL AND btrim(bairro::text) <> ''
                """
            )
        ).scalar()
        n = int(n or 0)
        return {
            "answer": (
                f"Há **{_fmt_int(n)}** bairros distintos na territorialização do município."
            ),
            "sql": (
                "SELECT COUNT(DISTINCT btrim(bairro::text)) FROM vig.mvw_familia "
                "WHERE btrim(COALESCE(bairro::text,'')) <> ''"
            ),
            "row_count": 1,
            "preview": [{"bairros_distintos": n}],
            "mode": "canonical",
            "metric": "geo_bairros_distintos",
        }

    if _COUNT_CRAS.search(text_msg) and not _CRAS_NUM.search(text_msg):
        n = conn.execute(
            text(
                """
                SELECT COUNT(DISTINCT btrim(num_cras::text))::bigint
                FROM vig.mvw_familia
                WHERE num_cras IS NOT NULL AND btrim(num_cras::text) <> ''
                """
            )
        ).scalar()
        n = int(n or 0)
        return {
            "answer": (
                f"Há **{_fmt_int(n)}** CRAS com famílias territorializadas no município."
            ),
            "sql": (
                "SELECT COUNT(DISTINCT btrim(num_cras::text)) FROM vig.mvw_familia "
                "WHERE btrim(COALESCE(num_cras::text,'')) <> ''"
            ),
            "row_count": 1,
            "preview": [{"cras_distintos": n}],
            "mode": "canonical",
            "metric": "geo_cras_distintos",
        }

    # Famílias em CRAS N
    m_cras = _CRAS_NUM.search(text_msg) or _CRAS_NUM.search(blob)
    if m_cras and _FAMILIAS.search(text_msg) and _CRAS.search(text_msg):
        num = m_cras.group(1)
        total, nom = _count_familias_cras(conn, num)
        rotulo = nom or f"CRAS {num}"
        return {
            "answer": (
                f"No **{rotulo}**, há **{_fmt_int(total)}** famílias no Cadastro Único."
            ),
            "sql": (
                f"SELECT COUNT(DISTINCT codigo_familiar) FROM vig.mvw_familia "
                f"WHERE btrim(num_cras::text) = '{num}'"
            ),
            "row_count": 1,
            "preview": [{"num_cras": num, "nom_cras": rotulo, "familias": total}],
            "mode": "canonical",
            "metric": "geo_familias_por_cras",
        }

    # Famílias por bairro
    if _BAIRRO.search(text_msg) and _FAMILIAS.search(text_msg):
        term = _extract_bairro_term(text_msg) or extract_location_term(text_msg)
        if not term:
            return None

        total, matches, resolution = _count_familias_bairro(conn, term)
        where_sql, params = bairro_sql_filter(resolution if resolution.status != "multiple" else None, term)
        sql = (
            "SELECT COUNT(DISTINCT f.codigo_familiar) FROM vig.mvw_familia f "
            f"WHERE btrim(COALESCE(f.bairro::text, '')) <> '' AND {where_sql}"
        )

        if resolution.status == "multiple":
            return {
                "answer": format_bairro_disambiguation(resolution),
                "sql": None,
                "row_count": 0,
                "preview": matches,
                "mode": "disambiguation",
                "metric": "bairro_disambiguation",
            }

        if total == 0:
            if resolution.status == "none":
                sugestoes = _bairro_matches(conn, term[: max(3, len(term) // 2)], limit=5)
                if sugestoes:
                    lista = ", ".join(
                        f"**{s['bairro']}** ({_fmt_int(int(s['familias'] or 0))})" for s in sugestoes
                    )
                    answer = (
                        f"Não encontrei famílias no bairro «{term}». "
                        f"Bairros parecidos: {lista}. "
                        "Confira a grafia ou use o nome como aparece no mapa territorial."
                    )
                else:
                    answer = (
                        f"Não encontrei famílias no bairro «{term}». "
                        "Verifique a grafia ou escolha um bairro da lista territorial."
                    )
            else:
                answer = (
                    f"Não encontrei famílias no bairro «{term}». "
                    "Verifique a grafia ou escolha um bairro da lista territorial."
                )
            return {
                "answer": answer,
                "sql": sql,
                "row_count": 0,
                "preview": matches,
                "mode": "canonical",
                "metric": "geo_familias_bairro_vazio",
            }

        b = (resolution.canonical or matches[0]["bairro"]) if matches else term
        answer = f"No bairro **{b}**, há **{_fmt_int(total)}** famílias no Cadastro Único."

        return {
            "answer": answer,
            "sql": sql,
            "row_count": len(matches),
            "preview": matches,
            "mode": "canonical",
            "metric": "geo_familias_por_bairro",
        }

    return None
