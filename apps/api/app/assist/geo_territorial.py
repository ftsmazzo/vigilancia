"""Consultas territoriais (geo × CEP) — bairro e CRAS em vig.mvw_familia."""

from __future__ import annotations

import re
from typing import Any

from sqlalchemy import text
from sqlalchemy.engine import Connection

from ..vigilance.familia_mview import _table_exists

_FAMILIAS = re.compile(
    r"quantas?\s+fam[ií]lias?|total\s+de\s+fam[ií]lias?|n[uú]mero\s+de\s+fam[ií]lias?|"
    r"temos\s+(?:de\s+)?fam[ií]lias?",
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


def _count_familias_bairro(conn: Connection, term: str) -> tuple[int, list[dict[str, Any]]]:
    matches = _bairro_matches(conn, term, limit=8)
    total = sum(int(m.get("familias") or 0) for m in matches)
    return total, matches


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
                f"Há **{_fmt_int(n)}** bairros distintos na territorialização geo "
                f"(campo `f.bairro`, via CEP × tbl_geo)."
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
                f"Há **{_fmt_int(n)}** CRAS territoriais distintos "
                f"(campo `f.num_cras`, via geo × CEP)."
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
                f"No **{rotulo}** (CRAS territorial **{num}**), há "
                f"**{_fmt_int(total)}** famílias no Cadastro Único "
                f"(geo × CEP, `f.num_cras`)."
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
        term = _extract_bairro_term(text_msg)
        if not term:
            return None

        total, matches = _count_familias_bairro(conn, term)
        sql = (
            "SELECT COUNT(DISTINCT f.codigo_familiar) FROM vig.mvw_familia f "
            f"WHERE btrim(f.bairro::text) ILIKE '%{term.replace(chr(39), '')}%'"
        )

        if total == 0:
            sugestoes = _bairro_matches(conn, term[: max(3, len(term) // 2)], limit=5)
            if sugestoes:
                lista = ", ".join(
                    f"**{s['bairro']}** ({_fmt_int(int(s['familias'] or 0))})" for s in sugestoes
                )
                answer = (
                    f"Não encontrei famílias no bairro «{term}» na geo territorial (`f.bairro`). "
                    f"Bairros parecidos: {lista}. "
                    "Confira a grafia ou use o nome como aparece na geo."
                )
            else:
                answer = (
                    f"Não encontrei famílias no bairro «{term}» em `f.bairro` (geo × CEP). "
                    "Verifique se a geo foi ingerida e se a visão Família foi atualizada."
                )
            return {
                "answer": answer,
                "sql": sql,
                "row_count": 0,
                "preview": sugestoes,
                "mode": "canonical",
                "metric": "geo_familias_bairro_vazio",
            }

        if len(matches) == 1:
            b = matches[0]["bairro"]
            answer = (
                f"No bairro **{b}**, há **{_fmt_int(total)}** famílias no Cadastro Único "
                f"(territorialização geo via CEP, campo `f.bairro`)."
            )
        else:
            detalhe = "; ".join(
                f"**{m['bairro']}**: {_fmt_int(int(m['familias'] or 0))}" for m in matches[:5]
            )
            answer = (
                f"Para «{term}», há **{_fmt_int(total)}** famílias no total "
                f"(geo × CEP): {detalhe}."
            )

        return {
            "answer": answer,
            "sql": sql,
            "row_count": len(matches),
            "preview": matches,
            "mode": "canonical",
            "metric": "geo_familias_por_bairro",
        }

    return None
