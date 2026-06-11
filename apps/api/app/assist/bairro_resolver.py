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

_FUZZY_MIN = 0.55
_SINGLE_MIN = 0.78
_SINGLE_GAP = 0.08
_TOKEN_AUTO = 0.82
_TOKEN_MATCH = 0.82

_DISAMBIG_MARKER = re.compile(
    r"qual deles|me confirma|mais de um bairro|parecidos|confirma qual|"
    r"bate com mais|\d+\.\s+\*\*",
    re.I,
)
_OPTION_LINE = re.compile(r"^(\d+)\.\s+\*\*([^*]+)\*\*", re.M)
_CHOICE_NUM = re.compile(r"^(?:op[cç][ãa]o\s+)?(\d+)\.?$", re.I)
_CRAS_IN_TERM = re.compile(r"\bcras\b|\bcras\s*\d", re.I)

_IVS_DIM_SIGLAS = frozenset({"nc", "dpi", "dca", "tqa", "dr", "ch"})
_BAIRRO_STOPWORDS = frozenset({
    "consideracao", "consideração", "geral", "relacao", "relação", "mente",
    "vista", "funcao", "função", "termos", "sentido", "base", "acordo",
    "funcao", "parte", "caso", "forma", "modo", "todo", "toda", "todos",
    "novo", "nova", "servico", "serviço", "convivencia", "convivência",
    "municipio", "município", "contexto", "scfv",
})

_LOCATION_PATTERNS = (
    re.compile(
        r"(?:no|do|da|de)\s+bairro\s+(.+?)(?:\?|\.|$)",
        re.I,
    ),
    re.compile(
        r"\bbairro\s+(.+?)(?:\?|\.|$)",
        re.I,
    ),
    re.compile(
        r"(?:crianças?|crianca|idosos?|pessoas?|fam[ií]lias?|mulheres|homens?)"
        r".*?\b(?:no|na|em)\s+bairro\s+(.+?)(?:\?|\.|$)",
        re.I,
    ),
    re.compile(
        r"(?:crianças?|crianca|idosos?|pessoas?|fam[ií]lias?|mulheres|homens?)"
        r".*?\b(?:no|na|em)\s+(?!bairro\b|cras\b|munic[ií]pio\b|conviv|considera|geral|rela|mente\b|"
        r"funcao|função|servi[cç]o|novo\b|nova\b|contexto\b)([A-Za-zÀ-ú][A-Za-zÀ-ú0-9\s'\-]{3,}?)(?:\?|\.|$)",
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


def _pick_variant(seed: str, templates: list[str]) -> str:
    if not templates:
        return ""
    idx = hash(_fold(seed)) % len(templates)
    return templates[idx]


def _prefix_name(first_name: str, answer: str) -> str:
    if not first_name or answer.lower().startswith(first_name.lower()):
        return answer
    return f"{first_name}, {answer[0].lower()}{answer[1:]}"


def _term_differs(resolution: BairroResolution) -> bool:
    if not resolution.canonical:
        return False
    return resolution.corrected or _fold(resolution.user_term) != _fold(resolution.canonical)


def _token_coverage(term: str, bairro: str) -> float:
    t_tokens = _fold(term).split()
    b_tokens = _fold(bairro).split()
    if not t_tokens or not b_tokens:
        return 0.0
    matched = sum(
        1
        for tt in t_tokens
        if any(SequenceMatcher(None, tt, bt).ratio() >= _TOKEN_MATCH for bt in b_tokens)
    )
    return matched / len(t_tokens)


def _score(term: str, bairro: str) -> float:
    """Similaridade 0–1. Aceita parte do nome composto e grafia aproximada."""
    t, b = _fold(term), _fold(bairro)
    if not t or not b:
        return 0.0
    if t == b:
        return 1.0
    if t in b or b in t:
        return max(0.92, SequenceMatcher(None, t, b).ratio())

    scores: list[float] = [SequenceMatcher(None, t, b).ratio()]
    t_tokens = t.split()
    b_tokens = b.split()

    for bt in b_tokens:
        scores.append(SequenceMatcher(None, t, bt).ratio())
    for tt in t_tokens:
        scores.append(SequenceMatcher(None, tt, b).ratio())
        for bt in b_tokens:
            scores.append(SequenceMatcher(None, tt, bt).ratio())

    coverage = _token_coverage(term, bairro)
    if coverage >= 1.0:
        scores.append(0.96)
    elif coverage >= 0.5:
        scores.append(0.72 + 0.24 * coverage)

    return max(scores)


def _best_token_match(term: str, bairro: str) -> float:
    t, b = _fold(term), _fold(bairro)
    if not t or not b:
        return 0.0
    scores = [SequenceMatcher(None, t, bt).ratio() for bt in b.split()]
    scores.append(SequenceMatcher(None, t, b).ratio())
    return max(scores) if scores else 0.0


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


def is_valid_bairro_term(term: str) -> bool:
    cleaned = _clean_term(term)
    if len(cleaned) < 3:
        return False
    folded = _fold(cleaned)
    if folded in _IVS_DIM_SIGLAS:
        return False
    if folded in _BAIRRO_STOPWORDS:
        return False
    first = folded.split()[0]
    if first in _IVS_DIM_SIGLAS or first in _BAIRRO_STOPWORDS:
        return False
    if _CRAS_IN_TERM.search(cleaned):
        return False
    return True


def message_has_territorial_intent(message: str) -> bool:
    text_msg = message.strip()
    if not re.search(r"\bbairro\b", text_msg, re.I):
        return False
    if re.search(r"\b(?:desse|nesse|deste|dese)\s+cras\b", text_msg, re.I):
        return False
    term = extract_location_term(text_msg)
    return bool(term and is_valid_bairro_term(term))


def should_resolve_bairro(message: str, term: str | None) -> bool:
    if not term or not is_valid_bairro_term(term):
        return False
    from .conversation_intent import skips_bairro_preprocess

    if skips_bairro_preprocess(message, None):
        return False
    if re.search(r"\bbairro\b", message, re.I):
        if re.search(r"\b(?:desse|nesse|deste|dese)\s+cras\b", message, re.I):
            return False
        return True
    if re.search(
        r"\b(?:índice|indice|ivs|ivcad|quantas?|quantos?|pessoas?|fam[ií]lias?|idosos?)\b",
        message,
        re.I,
    ):
        return True
    return False


def extract_location_term(message: str) -> str | None:
    text_msg = message.strip()
    for pattern in _LOCATION_PATTERNS:
        match = pattern.search(text_msg)
        if not match:
            continue
        term = _clean_term(match.group(1) or "")
        if is_valid_bairro_term(term):
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
    if not ilike and len(cleaned.split()) > 1:
        for token in sorted(cleaned.split(), key=len, reverse=True):
            if len(token) >= 4:
                ilike = _ilike_matches(conn, token, limit=8)
                if ilike:
                    break

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
    best_token = _best_token_match(cleaned, ranked[0][0]["bairro"])
    if best_token >= _TOKEN_AUTO and best_token - _best_token_match(cleaned, ranked[1][0]["bairro"]) >= _SINGLE_GAP:
        canonical = ranked[0][0]["bairro"]
        return BairroResolution(
            status="single_fuzzy",
            user_term=cleaned,
            canonical=canonical,
            matches=[ranked[0][0]],
            corrected=_fold(canonical) != _fold(cleaned),
        )
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
    term = resolution.user_term
    seed = f"disambig:{term}"
    intros = [
        "«{term}» aparece em mais de um bairro no território. Qual deles você quer?",
        "Encontrei alguns bairros parecidos com «{term}». Me confirma qual?",
        "«{term}» bate com mais de um bairro aqui — qual você tinha em mente?",
        "Tenho mais de uma opção para «{term}». Qual delas?",
    ]
    intro = _pick_variant(seed, intros).format(term=term)
    intro = _prefix_name(user_first_name, intro)
    lines = [intro, ""]
    for index, match in enumerate(resolution.matches[:5], start=1):
        lines.append(f"{index}. **{match['bairro']}** ({_fmt_int(int(match['familias']))} famílias)")
    footers = [
        "Responda com **1**, **2**, etc., ou com o nome completo do bairro.",
        "Pode responder **1**, **2**… ou escrever o nome completo.",
        "Digite o número (**1**, **2**…) ou o nome do bairro.",
    ]
    lines.extend(["", _pick_variant(seed + ":footer", footers)])
    return "\n".join(lines)


def format_pessoas_bairro_answer(
    resolution: BairroResolution,
    total: int,
    *,
    seed: str = "",
    user_first_name: str = "",
) -> str:
    bairro = resolution.canonical or ""
    n = _fmt_int(total)
    pick = seed or f"{resolution.user_term}:{bairro}:pessoas"

    if not _term_differs(resolution):
        templates = [
            f"No bairro **{bairro}**, há **{n}** pessoas no Cadastro Único.",
            f"Em **{bairro}**, são **{n}** pessoas cadastradas no CADU.",
            f"Por **{bairro}**, contabilizei **{n}** pessoas no território.",
        ]
    else:
        templates = [
            f"Creio que falamos do **{bairro}**: por lá há **{n}** pessoas no Cadastro Único.",
            f"No **{bairro}** — deve ser esse o bairro — há **{n}** pessoas no CADU.",
            f"Considerando **{bairro}**, encontrei **{n}** pessoas cadastradas.",
            f"Por **{bairro}**, são **{n}** pessoas no Cadastro Único.",
            f"Em **{bairro}**, contabilizei **{n}** pessoas no território.",
        ]

    return _prefix_name(user_first_name, _pick_variant(pick, templates))


def format_familias_bairro_answer(
    resolution: BairroResolution,
    total: int,
    *,
    seed: str = "",
    user_first_name: str = "",
) -> str:
    bairro = resolution.canonical or ""
    n = _fmt_int(total)
    pick = seed or f"{resolution.user_term}:{bairro}:familias"

    if not _term_differs(resolution):
        templates = [
            f"No bairro **{bairro}**, há **{n}** famílias no Cadastro Único.",
            f"Em **{bairro}**, são **{n}** famílias cadastradas no CADU.",
            f"Por **{bairro}**, contabilizei **{n}** famílias no território.",
        ]
    else:
        templates = [
            f"Creio que falamos do **{bairro}**: por lá há **{n}** famílias no Cadastro Único.",
            f"No **{bairro}** — deve ser esse o bairro — há **{n}** famílias no CADU.",
            f"Considerando **{bairro}**, encontrei **{n}** famílias cadastradas.",
            f"Por **{bairro}**, são **{n}** famílias no Cadastro Único.",
        ]

    return _prefix_name(user_first_name, _pick_variant(pick, templates))


def apply_bairro_correction_to_answer(
    answer: str,
    resolution: BairroResolution | None,
    user_first_name: str = "",
    *,
    message: str = "",
) -> str:
    """Incorpora bairro resolvido só quando a pergunta tinha intenção territorial."""
    if message and not message_has_territorial_intent(message):
        return answer
    if not resolution or not resolution.canonical or not _term_differs(resolution):
        return answer
    if f"**{resolution.canonical}**" in answer:
        return answer
    leads = [
        f"Creio que falamos do **{resolution.canonical}**.",
        f"Considerando **{resolution.canonical}**.",
        f"Por **{resolution.canonical}**.",
    ]
    lead = _pick_variant(f"{resolution.user_term}{resolution.canonical}:lead", leads)
    lead = _prefix_name(user_first_name, lead)
    return f"{lead} {answer}"


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

    if original_user and not should_resolve_bairro(original_user, extract_location_term(original_user)):
        return None

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


def count_pessoas_bairro(
    conn: Connection,
    resolution: BairroResolution,
) -> int:
    if not resolution.canonical:
        return 0
    row = conn.execute(
        text(
            """
            SELECT COUNT(p.cadu_row_id)::bigint AS pessoas
            FROM vig.mvw_pessoas p
            INNER JOIN vig.mvw_familia f ON f.codigo_familiar = p.codigo_familiar
            WHERE lower(btrim(f.bairro::text)) = lower(:bairro_canon)
            """
        ),
        {"bairro_canon": resolution.canonical},
    ).mappings().first()
    return int((row or {}).get("pessoas") or 0)


def try_pessoas_bairro_metric(
    conn: Connection,
    message: str,
    user_first_name: str = "",
) -> dict[str, Any] | None:
    """Resposta canônica: quantas pessoas no bairro X (com correção de grafia)."""
    if not _table_exists(conn, "vig", "mvw_familia") or not _table_exists(conn, "vig", "mvw_pessoas"):
        return None
    if not re.search(r"\bpessoas?\b", message, re.I):
        return None
    if not re.search(r"\b(?:no|na|em|bairro)\b", message, re.I):
        return None

    term = extract_location_term(message)
    if not term or not should_resolve_bairro(message, term):
        return None

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
    if resolution.status == "none" or not resolution.canonical:
        return None

    total = count_pessoas_bairro(conn, resolution)
    answer = format_pessoas_bairro_answer(
        resolution,
        total,
        seed=message,
        user_first_name=user_first_name,
    )

    return {
        "answer": answer,
        "sql": (
            "SELECT COUNT(p.cadu_row_id) FROM vig.mvw_pessoas p "
            "INNER JOIN vig.mvw_familia f ON f.codigo_familiar = p.codigo_familiar "
            f"WHERE lower(btrim(f.bairro::text)) = lower('{resolution.canonical.replace(chr(39), '')}')"
        ),
        "row_count": 1,
        "preview": [{"bairro": resolution.canonical, "pessoas": total}],
        "mode": "canonical",
        "metric": "geo_pessoas_por_bairro",
    }


def preprocess_bairro_turn(
    conn: Connection,
    user_first_name: str,
    message: str,
    transcript: list[dict[str, str]] | None,
) -> BairroPreprocess:
    if not _table_exists(conn, "vig", "mvw_familia"):
        return BairroPreprocess(message=message)

    from .conversation_intent import skips_bairro_preprocess

    if skips_bairro_preprocess(message, transcript):
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
    if not term or not should_resolve_bairro(message, term):
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
