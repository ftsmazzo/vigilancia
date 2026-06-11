"""Resolução de bairro territorial — grafia aproximada e desambiguação."""

from __future__ import annotations

import re
import unicodedata
from dataclasses import dataclass, field
from difflib import SequenceMatcher
from typing import Any

from sqlalchemy import text
from sqlalchemy.engine import Connection

from ..vigilance.familia_mview import _table_exists

_FUZZY_MIN = 0.58
_SINGLE_MIN = 0.72
_SINGLE_GAP = 0.10

_DISAMBIG_MARKER = re.compile(r"quis dizer|parecidos no territ", re.I)
_OPTION_LINE = re.compile(r"^(\d+)\.\s+\*\*([^*]+)\*\*", re.M)
_CHOICE_NUM = re.compile(r"^(?:op[cç][ãa]o\s+)?(\d+)\.?$", re.I)
_CRAS_IN_TERM = re.compile(r"\bcras\b|\bcras\s*\d", re.I)

_LOCATION_PATTERNS = (
    re.compile(
        r"(?:crianças?|crianca|idosos?|pessoas?|fam[ií]lias?|mulheres|homens?)"
        r".*?\b(?:no|na|em)\s+(.+?)(?:\?|\.|$)",
        re.I,
    ),
    re.compile(
        r"(?:no|do|da)\s+bairro\s+(.+?)(?:\?|\.|$)",
        re.I,
    ),
    re.compile(
        r"bairro\s+(.+?)(?:\?|\.|$)",
        re.I,
    ),
    re.compile(
        r"\b(?:no|na|em)\s+([A-Za-zÀ-ú][A-Za-zÀ-ú0-9\s'\-]{2,}?)(?:\?|\.|$)",
        re.I,
    ),
)


def _fmt_int(n: int) -> str:
    return f"{n:,}".replace(",", ".")


def _fold(text: str) -> str:
    normalized = unicodedata.normalize("NFKD", text or "")
    stripped = "".join(c for c in normalized if not unicodedata.combining(c))
    return re.sub(r"\s+", " ", stripped.lower().strip())


def _clean_term(term: str) -> str:
    cleaned = term.strip().strip("\"'")
    cleaned = re.sub(
        r"\s+(?:com|sem|que|do|da|de|no|na|em|cadastro|cadu).*$",
        "",
        cleaned,
        flags=re.I,
    ).strip()
    return cleaned


def _score(term: str, bairro: str) -> float:
    t, b = _fold(term), _fold(bairro)
    if not t or not b:
        return 0.0
    if t == b:
        return 1.0
    if t in b or b in t:
        return max(0.88, SequenceMatcher(None, t, b).ratio())
    ratio = SequenceMatcher(None, t, b).ratio()
    t_tokens = t.split()
    b_tokens = b.split()
    if t_tokens and b_tokens:
        overlap = sum(1 for tok in t_tokens if any(SequenceMatcher(None, tok, bt).ratio() >= 0.82 for bt in b_tokens))
        token_boost = overlap / max(len(t_tokens), len(b_tokens))
        ratio = max(ratio, 0.55 * ratio + 0.45 * token_boost)
    return ratio


@dataclass
class BairroResolution:
    status: str  # exact | single_fuzzy | multiple | none | chosen
    user_term: str
    canonical: str | None = None
    matches: list[dict[str, Any]] = field(default_factory=list)
    corrected: bool = False


@dataclass
class BairroPreprocess:
    message: str
    resolution: BairroResolution | None = None
    early_response: dict[str, Any] | None = None


def extract_location_term(message: str) -> str | None:
    text_msg = message.strip()
    for pattern in _LOCATION_PATTERNS:
        match = pattern.search(text_msg)
        if not match:
            continue
        term = _clean_term(match.group(1) or "")
        if len(term) >= 2 and not _CRAS_IN_TERM.search(term):
            return term
    return None


def _load_all_bairros(conn: Connection) -> list[dict[str, Any]]:
    rows = conn.execute(
        text(
            """
            SELECT
              btrim(f.bairro::text) AS bairro,
              COUNT(DISTINCT f.codigo_familiar)::bigint AS familias
            FROM vig.mvw_familia f
            WHERE btrim(COALESCE(f.bairro::text, '')) <> ''
            GROUP BY 1
            ORDER BY familias DESC, bairro ASC
            """
        )
    ).mappings().all()
    return [{"bairro": str(r["bairro"]), "familias": int(r["familias"] or 0)} for r in rows if r.get("bairro")]


def _ilike_matches(conn: Connection, term: str, *, limit: int = 8) -> list[dict[str, Any]]:
    rows = conn.execute(
        text(
            """
            SELECT
              btrim(f.bairro::text) AS bairro,
              COUNT(DISTINCT f.codigo_familiar)::bigint AS familias
            FROM vig.mvw_familia f
            WHERE btrim(COALESCE(f.bairro::text, '')) <> ''
              AND btrim(f.bairro::text) ILIKE :pat
            GROUP BY 1
            ORDER BY familias DESC, bairro ASC
            LIMIT :lim
            """
        ),
        {"pat": f"%{term.strip()}%", "lim": limit},
    ).mappings().all()
    return [{"bairro": str(r["bairro"]), "familias": int(r["familias"] or 0)} for r in rows if r.get("bairro")]


def resolve_bairro(conn: Connection, term: str) -> BairroResolution:
    cleaned = _clean_term(term)
    if len(cleaned) < 2:
        return BairroResolution(status="none", user_term=cleaned)

    ilike = _ilike_matches(conn, cleaned)
    if len(ilike) == 1:
        canonical = ilike[0]["bairro"]
        if _fold(canonical) == _fold(cleaned):
            return BairroResolution(
                status="exact",
                user_term=cleaned,
                canonical=canonical,
                matches=ilike,
            )
        return BairroResolution(
            status="single_fuzzy",
            user_term=cleaned,
            canonical=canonical,
            matches=ilike,
            corrected=True,
        )

    if len(ilike) > 1:
        ranked = sorted(
            ((m, _score(cleaned, m["bairro"])) for m in ilike),
            key=lambda item: (-item[1], -item[0]["familias"]),
        )
        if (
            ranked[0][1] >= 0.85
            and ranked[0][1] - ranked[1][1] >= 0.15
        ):
            canonical = ranked[0][0]["bairro"]
            return BairroResolution(
                status="single_fuzzy" if _fold(canonical) != _fold(cleaned) else "exact",
                user_term=cleaned,
                canonical=canonical,
                matches=[ranked[0][0]],
                corrected=_fold(canonical) != _fold(cleaned),
            )
        return BairroResolution(
            status="multiple",
            user_term=cleaned,
            matches=[m for m, _ in ranked[:5]],
        )

    all_bairros = _load_all_bairros(conn)
    ranked = [
        (b, _score(cleaned, b["bairro"]))
        for b in all_bairros
        if _score(cleaned, b["bairro"]) >= _FUZZY_MIN
    ]
    ranked.sort(key=lambda item: (-item[1], -item[0]["familias"]))

    if not ranked:
        return BairroResolution(status="none", user_term=cleaned)

    if len(ranked) == 1:
        canonical = ranked[0][0]["bairro"]
        return BairroResolution(
            status="single_fuzzy",
            user_term=cleaned,
            canonical=canonical,
            matches=[ranked[0][0]],
            corrected=True,
        )

    best_score = ranked[0][1]
    second_score = ranked[1][1]
    if best_score >= _SINGLE_MIN and best_score - second_score >= _SINGLE_GAP:
        canonical = ranked[0][0]["bairro"]
        return BairroResolution(
            status="single_fuzzy",
            user_term=cleaned,
            canonical=canonical,
            matches=[ranked[0][0]],
            corrected=True,
        )

    return BairroResolution(
        status="multiple",
        user_term=cleaned,
        matches=[item[0] for item in ranked[:5]],
    )


def bairro_sql_filter(resolution: BairroResolution | None, term: str) -> tuple[str, dict[str, str]]:
    """Filtro SQL por bairro — usa nome canônico quando resolvido."""
    if resolution and resolution.canonical:
        return "lower(btrim(f.bairro::text)) = lower(:bairro_canon)", {"bairro_canon": resolution.canonical}
    safe = term.replace("'", "")
    return f"btrim(f.bairro::text) ILIKE '%{safe}%'", {}


def format_bairro_disambiguation(resolution: BairroResolution, user_first_name: str = "") -> str:
    prefix = f"{user_first_name}, " if user_first_name else ""
    intro = (
        f"{prefix}não encontrei **{resolution.user_term}** com essa grafia exata. "
        "Estes bairros do território parecem ser o que você quis dizer — qual deles?"
    )
    lines = [intro, ""]
    for index, match in enumerate(resolution.matches[:5], start=1):
        lines.append(f"{index}. **{match['bairro']}** ({_fmt_int(int(match['familias']))} famílias)")
    lines.extend(["", "Responda com **1**, **2**, etc., ou com o nome completo do bairro."])
    return "\n".join(lines)


def format_bairro_correction_note(resolution: BairroResolution, user_first_name: str = "") -> str:
    if not resolution.corrected or not resolution.canonical:
        return ""
    prefix = f"{user_first_name}, " if user_first_name else ""
    return (
        f"{prefix}notei um pequeno deslize na grafia de «{resolution.user_term}» — "
        f"consultei **{resolution.canonical}**, que é como o bairro consta no território."
    )


def apply_bairro_correction_to_answer(answer: str, resolution: BairroResolution | None, user_first_name: str = "") -> str:
    note = format_bairro_correction_note(resolution, user_first_name) if resolution else ""
    if not note:
        return answer
    return f"{note}\n\n{answer}"


def _parse_disambiguation_options(content: str) -> list[str]:
    return [name.strip() for _, name in _OPTION_LINE.findall(content)]


def try_parse_bairro_choice(message: str, transcript: list[dict[str, str]] | None) -> tuple[str, str] | None:
    """
    Interpreta escolha numerada (1, 2…) ou nome completo após desambiguação.
    Retorna (bairro_canonico, mensagem_reformulada) ou None.
    """
    text_msg = message.strip()
    if not transcript:
        return None

    disambig_idx = None
    options: list[str] = []
    for idx in range(len(transcript) - 1, -1, -1):
        msg = transcript[idx]
        if msg.get("role") != "assistant":
            continue
        content = msg.get("content", "")
        if _DISAMBIG_MARKER.search(content):
            options = _parse_disambiguation_options(content)
            if options:
                disambig_idx = idx
                break

    if not options or disambig_idx is None:
        return None

    original_user = ""
    for idx in range(disambig_idx - 1, -1, -1):
        if transcript[idx].get("role") == "user":
            original_user = transcript[idx].get("content", "").strip()
            break

    chosen: str | None = None
    num_match = _CHOICE_NUM.match(text_msg)
    if num_match:
        choice_num = int(num_match.group(1))
        if 1 <= choice_num <= len(options):
            chosen = options[choice_num - 1]
    else:
        folded = _fold(text_msg)
        for option in options:
            if _fold(option) == folded:
                chosen = option
                break

    if not chosen:
        return None

    if original_user:
        term = extract_location_term(original_user)
        if term:
            pattern = re.compile(re.escape(term), re.I)
            new_message = pattern.sub(chosen, original_user, count=1)
        else:
            new_message = f"{original_user} (bairro: {chosen})"
    else:
        new_message = f"No bairro {chosen}"

    return chosen, new_message


def preprocess_bairro_turn(
    conn: Connection,
    user_first_name: str,
    message: str,
    transcript: list[dict[str, str]] | None,
) -> BairroPreprocess:
    if not _table_exists(conn, "vig", "mvw_familia"):
        return BairroPreprocess(message=message)

    choice = try_parse_bairro_choice(message, transcript)
    if choice:
        chosen, rewritten = choice
        return BairroPreprocess(
            message=rewritten,
            resolution=BairroResolution(
                status="chosen",
                user_term=chosen,
                canonical=chosen,
            ),
        )

    term = extract_location_term(message)
    if not term:
        return BairroPreprocess(message=message)

    resolution = resolve_bairro(conn, term)
    if resolution.status == "multiple":
        return BairroPreprocess(
            message=message,
            resolution=resolution,
            early_response={
                "answer": format_bairro_disambiguation(resolution, user_first_name),
                "sql": None,
                "row_count": 0,
                "preview": resolution.matches,
                "mode": "disambiguation",
                "metric": "bairro_disambiguation",
            },
        )

    if resolution.status in ("exact", "single_fuzzy", "chosen") and resolution.canonical:
        if _fold(resolution.canonical) != _fold(term):
            pattern = re.compile(re.escape(term), re.I)
            rewritten = pattern.sub(resolution.canonical, message, count=1)
            return BairroPreprocess(message=rewritten, resolution=resolution)

    if resolution.status == "exact":
        return BairroPreprocess(message=message, resolution=resolution)

    return BairroPreprocess(message=message, resolution=resolution if resolution.status != "none" else None)
