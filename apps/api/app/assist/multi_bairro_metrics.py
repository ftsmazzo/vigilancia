"""Métricas multi-bairro — listas coladas pelo usuário (PBF, famílias, pessoas)."""

from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Any

from sqlalchemy import text
from sqlalchemy.engine import Connection

from ..vigilance.familia_mview import _table_exists
from .bairro_resolver import _fold, resolve_bairro

_PBF = re.compile(
    r"\b(?:pbf|bolsa\s+fam[ií]lia|programa\s+bolsa|recebe[m]?\s+(?:o\s+)?(?:pbf|bolsa))\b",
    re.I,
)
_FAMILIAS = re.compile(r"\bfam[ií]lias?\b", re.I)
_PESSOAS = re.compile(r"\bpessoas?\b", re.I)
_QUANT = re.compile(r"\bquantas?\b|\bquantos?\b|\btotal\b", re.I)
_LIST_INTRO = re.compile(r"\b(?:nesses|nestes|nos|seguintes)\s+bairros?\b", re.I)
_BAIRRO_LIST_HEADER = re.compile(r"\bbairros?\s*:\s*", re.I)
_NOISE_LINE = re.compile(
    r"^(?:quantas?|quantos?|total|fam[ií]lias?|pessoas?|recebe|programa|bolsa|"
    r"nesse[s]?|neste[s]?|bairros?)\b",
    re.I,
)


def _fmt_int(n: int) -> str:
    return f"{n:,}".replace(",", ".")


def _clean_list_line(line: str) -> str:
    cleaned = (line or "").strip()
    cleaned = re.sub(r"^[\-\*•\d.]+\s*", "", cleaned).strip()
    cleaned = cleaned.strip(",;")
    return cleaned


def _looks_like_bairro_line(line: str) -> bool:
    cleaned = _clean_list_line(line)
    if len(cleaned) < 3:
        return False
    if _NOISE_LINE.match(cleaned):
        return False
    if not re.search(r"[A-Za-zÀ-ú]", cleaned):
        return False
    if cleaned.endswith("?"):
        return False
    return True


def extract_bairro_list(message: str) -> list[str]:
    """Extrai nomes de bairros de listas multilinha ou após 'bairros:'."""
    text_msg = (message or "").strip()
    if not text_msg:
        return []

    body = ""
    header = _BAIRRO_LIST_HEADER.search(text_msg)
    if header:
        body = text_msg[header.end() :]
    elif _LIST_INTRO.search(text_msg):
        parts = re.split(r"\b(?:nesses|nestes|nos|seguintes)\s+bairros?\s*:?\s*", text_msg, flags=re.I)
        body = parts[-1] if parts else ""
    else:
        lines = [ln.strip() for ln in text_msg.splitlines() if ln.strip()]
        if len(lines) >= 3 and _QUANT.search(lines[0]):
            candidates = [_clean_list_line(ln) for ln in lines[1:] if _looks_like_bairro_line(ln)]
            return _dedupe_preserve(candidates)

    if not body.strip():
        return []

    names: list[str] = []
    for chunk in re.split(r"[\n\r]+|[,;](?=\s*[A-Za-zÀ-ú])", body):
        part = _clean_list_line(chunk)
        if part and _looks_like_bairro_line(part):
            names.append(part)
    return _dedupe_preserve(names)


def _dedupe_preserve(names: list[str]) -> list[str]:
    seen: set[str] = set()
    out: list[str] = []
    for name in names:
        key = _fold(name)
        if key in seen:
            continue
        seen.add(key)
        out.append(name)
    return out


def message_has_bairro_list_scope(message: str) -> bool:
    if _LIST_INTRO.search(message or ""):
        return True
    if _BAIRRO_LIST_HEADER.search(message or ""):
        return True
    return len(extract_bairro_list(message)) >= 2


def find_bairro_list_in_conversation(
    message: str,
    transcript: list[dict[str, str]] | None = None,
) -> list[str]:
    """Lista na mensagem atual ou em turno anterior (ex.: usuário repete sem colar de novo)."""
    names = extract_bairro_list(message)
    if len(names) >= 2:
        return names
    refers_list = bool(
        _LIST_INTRO.search(message or "")
        or _BAIRRO_LIST_HEADER.search(message or "")
        or re.search(r"\b(?:nesses|nestes|seguintes)\s+bairros?\b", message or "", re.I)
    )
    if not refers_list or not transcript:
        return names
    for msg in reversed(transcript):
        if msg.get("role") != "user":
            continue
        prev = extract_bairro_list(msg.get("content", ""))
        if len(prev) >= 2:
            return prev
    return names


def is_simple_territorial_count(
    message: str,
    transcript: list[dict[str, str]] | None = None,
) -> bool:
    """Contagem numérica territorial — NÃO é planejamento/desbloqueio."""
    text_msg = (message or "").strip()
    if not text_msg or not _QUANT.search(text_msg):
        return False
    if message_has_bairro_list_scope(text_msg):
        return True
    if len(find_bairro_list_in_conversation(text_msg, transcript)) >= 2:
        return True
    if _FAMILIAS.search(text_msg) or _PESSOAS.search(text_msg):
        if _PBF.search(text_msg) and re.search(r"\bbairros?\b", text_msg, re.I):
            return True
    return False


@dataclass
class ResolvedBairroItem:
    input_name: str
    canonical: str | None
    status: str
    matches: list[dict[str, Any]]


def resolve_bairro_list(conn: Connection, names: list[str]) -> list[ResolvedBairroItem]:
    items: list[ResolvedBairroItem] = []
    for name in names:
        resolution = resolve_bairro(conn, name)
        canonical = resolution.canonical if resolution.status in (
            "exact",
            "single_fuzzy",
            "chosen",
        ) else None
        items.append(
            ResolvedBairroItem(
                input_name=name,
                canonical=canonical,
                status=resolution.status,
                matches=list(resolution.matches or []),
            )
        )
    return items


def _count_familias_pbf_multi(
    conn: Connection,
    canonicals: list[str],
) -> tuple[list[dict[str, Any]], int, int]:
    if not canonicals:
        return [], 0, 0

    lowered = [c.lower() for c in canonicals]
    rows = conn.execute(
        text(
            """
            SELECT
              btrim(f.bairro::text) AS bairro,
              COUNT(DISTINCT f.codigo_familiar)::bigint AS total_familias,
              COUNT(DISTINCT f.codigo_familiar) FILTER (
                WHERE COALESCE(f.marc_pbf, FALSE)
              )::bigint AS familias_pbf
            FROM vig.mvw_familia f
            WHERE btrim(COALESCE(f.bairro::text, '')) <> ''
              AND lower(btrim(f.bairro::text)) = ANY(:names)
            GROUP BY 1
            ORDER BY bairro ASC
            """
        ),
        {"names": lowered},
    ).mappings().all()

    preview = [
        {
            "bairro": str(r["bairro"]),
            "total_familias": int(r["total_familias"] or 0),
            "familias_pbf": int(r["familias_pbf"] or 0),
        }
        for r in rows
    ]
    total_fam = sum(int(r["total_familias"] or 0) for r in preview)
    total_pbf = sum(int(r["familias_pbf"] or 0) for r in preview)
    return preview, total_fam, total_pbf


def _count_pessoas_pbf_multi(
    conn: Connection,
    canonicals: list[str],
) -> tuple[list[dict[str, Any]], int, int]:
    if not canonicals:
        return [], 0, 0

    lowered = [c.lower() for c in canonicals]
    rows = conn.execute(
        text(
            """
            SELECT
              btrim(f.bairro::text) AS bairro,
              COUNT(p.cadu_row_id)::bigint AS total_pessoas,
              COUNT(p.cadu_row_id) FILTER (
                WHERE COALESCE(f.marc_pbf, FALSE)
              )::bigint AS pessoas_em_familia_pbf
            FROM vig.mvw_pessoas p
            INNER JOIN vig.mvw_familia f ON f.codigo_familiar = p.codigo_familiar
            WHERE btrim(COALESCE(f.bairro::text, '')) <> ''
              AND lower(btrim(f.bairro::text)) = ANY(:names)
            GROUP BY 1
            ORDER BY bairro ASC
            """
        ),
        {"names": lowered},
    ).mappings().all()

    preview = [
        {
            "bairro": str(r["bairro"]),
            "total_pessoas": int(r["total_pessoas"] or 0),
            "pessoas_em_familia_pbf": int(r["pessoas_em_familia_pbf"] or 0),
        }
        for r in rows
    ]
    total_pessoas = sum(int(r["total_pessoas"] or 0) for r in preview)
    total_pbf = sum(int(r["pessoas_em_familia_pbf"] or 0) for r in preview)
    return preview, total_pessoas, total_pbf


def try_multi_bairro_pbf_metric(
    conn: Connection,
    message: str,
    transcript: list[dict[str, str]] | None = None,
    *,
    user_first_name: str = "",
) -> dict[str, Any] | None:
    """
    Famílias/pessoas com Bolsa Família (marc_pbf) em lista explícita de bairros.
    """
    text_msg = (message or "").strip()
    if not text_msg or not _table_exists(conn, "vig", "mvw_familia"):
        return None
    if not _PBF.search(text_msg) and not _FAMILIAS.search(text_msg):
        return None

    names = find_bairro_list_in_conversation(text_msg, transcript)
    if len(names) < 2:
        return None

    resolved = resolve_bairro_list(conn, names)
    canonicals: list[str] = []
    unresolved: list[str] = []
    ambiguous: list[str] = []

    seen_canon: set[str] = set()
    for item in resolved:
        if item.canonical:
            key = _fold(item.canonical)
            if key not in seen_canon:
                seen_canon.add(key)
                canonicals.append(item.canonical)
        elif item.status == "multiple":
            ambiguous.append(item.input_name)
        else:
            unresolved.append(item.input_name)

    if not canonicals:
        return None

    wants_pessoas = bool(_PESSOAS.search(text_msg) and not _FAMILIAS.search(text_msg))

    if wants_pessoas:
        preview_rows, total_ent, total_pbf = _count_pessoas_pbf_multi(conn, canonicals)
        metric = "multi_bairro_pbf_pessoas"
        entity_label = "pessoas"
        pbf_label = "pessoas em famílias na folha PBF"
        sql = (
            "SELECT btrim(f.bairro::text), COUNT(p.cadu_row_id), "
            "COUNT(p.cadu_row_id) FILTER (WHERE COALESCE(f.marc_pbf, FALSE)) "
            "FROM vig.mvw_pessoas p JOIN vig.mvw_familia f ON f.codigo_familiar = p.codigo_familiar "
            "WHERE lower(btrim(f.bairro::text)) = ANY(:names) GROUP BY 1"
        )
    else:
        preview_rows, total_ent, total_pbf = _count_familias_pbf_multi(conn, canonicals)
        metric = "multi_bairro_pbf_familias"
        entity_label = "famílias"
        pbf_label = "famílias na folha PBF (marc_pbf)"
        sql = (
            "SELECT btrim(f.bairro::text), COUNT(DISTINCT f.codigo_familiar), "
            "COUNT(DISTINCT f.codigo_familiar) FILTER (WHERE COALESCE(f.marc_pbf, FALSE)) "
            "FROM vig.mvw_familia f WHERE lower(btrim(f.bairro::text)) = ANY(:names) GROUP BY 1"
        )

    if not preview_rows and total_pbf == 0:
        return {
            "answer": (
                f"Não encontrei {entity_label} nos bairros informados após resolver os nomes "
                f"no CADU territorial ({len(canonicals)} bairro(s) reconhecido(s))."
            ),
            "sql": sql,
            "row_count": 0,
            "preview": [{"bairros_solicitados": len(names), "bairros_resolvidos": len(canonicals)}],
            "mode": "canonical",
            "metric": metric,
            "filters_applied": f"lista de {len(names)} bairros; folha PBF (marc_pbf)",
            "response_mode": "lista",
        }

    pct = round(100.0 * total_pbf / total_ent, 2) if total_ent else 0.0
    notes: list[str] = []
    if unresolved:
        notes.append(f"Sem match no CADU: {', '.join(unresolved[:8])}" + ("…" if len(unresolved) > 8 else ""))
    if ambiguous:
        notes.append(f"Ambíguos (confirme grafia): {', '.join(ambiguous[:5])}")

    preview: list[dict[str, Any]] = list(preview_rows)
    preview.insert(
        0,
        {
            "label": "Total nos bairros listados",
            "value": str(total_pbf),
            "detail": f"{total_pbf} {pbf_label} de {total_ent} {entity_label} ({pct:.2f} %)",
            "source": "vig.mvw_familia × marc_pbf",
        },
    )
    if notes:
        preview.append({"avisos": "; ".join(notes)})

    return {
        "answer": "",  # síntese via analyst
        "sql": sql,
        "row_count": len(preview_rows),
        "preview": preview,
        "mode": "canonical",
        "metric": metric,
        "filters_applied": (
            f"{len(canonicals)} bairros resolvidos de {len(names)} informados; "
            f"folha PBF (marc_pbf no CADU)"
        ),
        "response_mode": "lista",
        "unresolved_bairros": unresolved,
        "ambiguous_bairros": ambiguous,
        "bairros_resolvidos": canonicals,
    }
