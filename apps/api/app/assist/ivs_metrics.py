"""Métricas canônicas IVS/IVCAD — mesma lógica da página IVS, respostas naturais."""

from __future__ import annotations

import re
import unicodedata
from typing import Any

from sqlalchemy import text
from sqlalchemy.engine import Connection

from ..ivs.catalog import DIMENSOES, DIM_POR_SIGLA, DimensaoMeta, IndicadorMeta
from ..ivs.painel import ivs_filter_clause
from ..vigilance.familia_mview import _table_exists
from .bairro_resolver import (
    _pick_variant,
    _prefix_name,
    _term_differs,
    extract_location_term,
    format_bairro_disambiguation,
    is_valid_bairro_term,
    resolve_bairro,
    should_resolve_bairro,
)

_IVS = re.compile(
    r"\b(?:ivs|ivcad|ivc\b|índice\s+de\s+vulnerabilidade|vulnerabilidade\s+(?:social|das?\s+fam[ií]lias))\b|"
    r"necessidade\s+de\s+cuidados|"
    r"desenvolvimento\s+na\s+primeira\s+inf[aâ]ncia|"
    r"desenvolvimento\s+de\s+crian[cç]as|"
    r"trabalho\s+e\s+qualifica[cç][ãa]o|"
    r"disponibilidade\s+de\s+recursos|"
    r"condi[cç][õo]es\s+habitacionais|"
    r"\b(?:dimens[aã]o\s+)?(?:nc|dpi|dca|tqa|dr|ch)\d?\b|"
    r"\b(?:idx_)?(?:nc|dpi|dca|tqa|dr|ch)\b",
    re.I,
)

_INDICE = re.compile(r"\b(?:índice|indice|media|m[eé]dia|valor|quanto\s+[eé])\b", re.I)
_CRAS_NUM = re.compile(r"\bcras\s*(\d{1,2})\b", re.I)
_IVS_COMPARE = re.compile(
    r"(?:cras|unidad).*?(?:maior|superior|acima)|"
    r"(?:maior|superior|acima).*?(?:cras|índice|indice|nc)|"
    r"tem\s+algum\s+cras|qual\s+cras|"
    r"^qual\??$",
    re.I,
)
_THRESHOLD = re.compile(r"(\d+[,.]\d{2,4})")

_TERR_BAIRRO = re.compile(
    r"(?:"
    r"\bbairro\s+(.+?)(?:\?|\.|$)|"
    r"(?:no|do|da|de)\s+bairro\s+(.+?)(?:\?|\.|$)"
    r")",
    re.I,
)

_TERR_TRAILING = re.compile(
    r"\b(?:do|da|de)\s+(?!nc\b|dpi\b|dca\b|tqa\b|dr\b|ch\b|cras\b|"
    r"índice|indice|ivs|ivcad|dimens[aã]o\b)"
    r"([A-Za-zÀ-ú][A-Za-zÀ-ú0-9\s'\-]{3,}?)(?:\?|\.|$)",
    re.I,
)


def _fold(text: str) -> str:
    normalized = unicodedata.normalize("NFKD", text or "")
    stripped = "".join(c for c in normalized if not unicodedata.combining(c))
    return re.sub(r"\s+", " ", stripped.lower().strip())


def _fmt_int(n: int) -> str:
    return f"{n:,}".replace(",", ".")


def _fmt_idx(value: float) -> str:
    return f"{value:.2f}".replace(".", ",")


def _clean_territory_term(term: str) -> str:
    cleaned = term.strip().strip("\"'")
    cleaned = re.sub(
        r"\s+(?:com|sem|que|do|da|de|no|na|em|cadastro|cadu|\?).*$",
        "",
        cleaned,
        flags=re.I,
    ).strip()
    return cleaned


def extract_ivs_territory(message: str) -> str | None:
    text_msg = message.strip()

    match = _TERR_BAIRRO.search(text_msg)
    if match:
        raw = next(g for g in match.groups() if g)
        cleaned = _clean_territory_term(raw)
        if is_valid_bairro_term(cleaned):
            return cleaned

    term = extract_location_term(text_msg)
    if term:
        return term

    trailing: list[str] = []
    for match in _TERR_TRAILING.finditer(text_msg):
        cleaned = _clean_territory_term(match.group(1))
        if is_valid_bairro_term(cleaned):
            trailing.append(cleaned)
    if trailing:
        return trailing[-1]

    return None


def _detect_indicador(text_msg: str) -> tuple[DimensaoMeta, IndicadorMeta] | None:
    folded = _fold(text_msg)
    for dim in DIMENSOES:
        for ind in dim.indicadores:
            if re.search(rf"\b{re.escape(ind.codigo)}\b", text_msg, re.I):
                return dim, ind
            if _fold(ind.titulo) in folded:
                return dim, ind
    return None


def _detect_dimensao(text_msg: str) -> DimensaoMeta | None:
    ind_hit = _detect_indicador(text_msg)
    if ind_hit:
        return ind_hit[0]

    folded = _fold(text_msg)
    for dim in DIMENSOES:
        if re.search(rf"\b{dim.sigla}\b", text_msg, re.I):
            return dim
        if _fold(dim.nome) in folded:
            return dim

    if "necessidade" in folded and "cuidado" in folded:
        return DIM_POR_SIGLA["NC"]
    if "primeira inf" in folded:
        return DIM_POR_SIGLA["DPI"]
    if "crianc" in folded and "adolesc" in folded:
        return DIM_POR_SIGLA["DCA"]
    if "trabalho" in folded and "qualifica" in folded:
        return DIM_POR_SIGLA["TQA"]
    if "recursos" in folded and ("disponib" in folded or "renda" in folded):
        return DIM_POR_SIGLA["DR"]
    if "habitacion" in folded or "moradia" in folded and "condi" in folded:
        return DIM_POR_SIGLA["CH"]
    return None


def _is_ivs_question(message: str) -> bool:
    text_msg = message.strip()
    if not text_msg:
        return False
    if _IVS.search(text_msg):
        return True
    if _INDICE.search(text_msg) and _detect_dimensao(text_msg):
        return True
    if _INDICE.search(text_msg) and re.search(r"\bivs\b", text_msg, re.I):
        return True
    return False


def _fetch_recorte(
    conn: Connection,
    *,
    num_cras: str | None,
    bairro: str | None,
    idx_col: str | None = None,
    flag_col: str | None = None,
) -> dict[str, Any]:
    where, params = ivs_filter_clause(num_cras=num_cras, bairro=bairro)
    if flag_col:
        value_sql = (
            f"ROUND(100.0 * AVG(i.{flag_col}::numeric) FILTER (WHERE i.elegivel_ivs)::numeric, 2)"
        )
    elif idx_col:
        value_sql = f"ROUND(AVG(i.{idx_col}) FILTER (WHERE i.elegivel_ivs)::numeric, 4)"
    else:
        value_sql = "ROUND(AVG(i.ivs) FILTER (WHERE i.elegivel_ivs)::numeric, 4)"

    row = conn.execute(
        text(
            f"""
            SELECT
              COUNT(*) FILTER (WHERE i.elegivel_ivs)::bigint AS familias_elegiveis,
              {value_sql} AS idx_val
            FROM core.mvw_ivs_familia i
            INNER JOIN vig.mvw_familia f ON f.codigo_familiar = i.codigo_familiar
            WHERE {where}
            """
        ),
        params,
    ).mappings().first() or {}

    return {
        "familias_elegiveis": int(row.get("familias_elegiveis") or 0),
        "idx_val": float(row["idx_val"]) if row.get("idx_val") is not None else None,
    }


def _territory_label(
    *,
    bairro: str | None,
    num_cras: str | None,
    resolution,
) -> str:
    if bairro:
        if resolution and _term_differs(resolution):
            return f"**{bairro}**"
        return f"**{bairro}**"
    if num_cras:
        return f"**CRAS {num_cras}**"
    return "o **município**"


def format_ivs_answer(
    *,
    dim: DimensaoMeta | None,
    indicador: IndicadorMeta | None,
    idx_val: float | None,
    familias: int,
    territory_label: str,
    seed: str,
    user_first_name: str = "",
    resolution=None,
) -> str:
    if idx_val is None:
        return (
            f"Não há famílias elegíveis ao IVS nesse recorte territorial "
            f"({territory_label.strip('**')})."
        )

    differs = resolution and _term_differs(resolution)

    if indicador:
        pct = f"{idx_val:.2f} %"
        if differs:
            templates = [
                f"Creio que falamos de {territory_label}: **{indicador.codigo}** "
                f"({indicador.titulo}) aparece em **{pct}** das famílias elegíveis "
                f"({_fmt_int(familias)} famílias no recorte).",
                f"Em {territory_label}, **{indicador.codigo}** — {indicador.titulo} — "
                f"atinge **{pct}** das **{_fmt_int(familias)}** famílias do universo IVS.",
            ]
        else:
            templates = [
                f"Em {territory_label}, **{indicador.codigo}** ({indicador.titulo}) "
                f"atinge **{pct}** das **{_fmt_int(familias)}** famílias elegíveis ao IVS.",
                f"No recorte {territory_label}, **{indicador.codigo}** aparece em "
                f"**{pct}** das famílias analisadas ({_fmt_int(familias)}).",
            ]
        return _prefix_name(user_first_name, _pick_variant(seed, templates))

    dim_nome = dim.nome if dim else "Vulnerabilidade Social (IVS)"
    dim_sigla = dim.sigla if dim else "IVS"
    val = _fmt_idx(idx_val)

    if dim:
        if differs:
            templates = [
                f"Creio que falamos de {territory_label}: o índice de **{dim_nome}** ({dim_sigla}) "
                f"fica em **{val}** (escala 0 a 1), com **{_fmt_int(familias)}** famílias elegíveis.",
                f"Em {territory_label}, a dimensão **{dim_nome}** ({dim_sigla}) média **{val}** "
                f"entre **{_fmt_int(familias)}** famílias do universo IVS.",
                f"Por {territory_label}, o **{dim_sigla}** — {dim_nome} — está em **{val}** "
                f"({_fmt_int(familias)} famílias no recorte).",
            ]
        else:
            templates = [
                f"Em {territory_label}, o índice de **{dim_nome}** ({dim_sigla}) é **{val}** "
                f"(escala 0 a 1), com **{_fmt_int(familias)}** famílias elegíveis.",
                f"No recorte {territory_label}, **{dim_nome}** ({dim_sigla}) média **{val}** "
                f"entre **{_fmt_int(familias)}** famílias analisadas pelo IVS.",
                f"Por {territory_label}, o **{dim_sigla}** fica em **{val}** "
                f"({_fmt_int(familias)} famílias elegíveis no território).",
            ]
    else:
        if differs:
            templates = [
                f"Creio que falamos de {territory_label}: o **IVS** médio é **{val}** "
                f"(escala 0 a 1), com **{_fmt_int(familias)}** famílias elegíveis.",
                f"Em {territory_label}, o índice composto **IVS** fica em **{val}** "
                f"entre **{_fmt_int(familias)}** famílias do universo IN084.",
            ]
        else:
            templates = [
                f"Em {territory_label}, o **IVS** médio é **{val}** (escala 0 a 1), "
                f"com **{_fmt_int(familias)}** famílias elegíveis.",
                f"No recorte {territory_label}, o índice **IVS** composto média **{val}** "
                f"({_fmt_int(familias)} famílias analisadas).",
            ]

    return _prefix_name(user_first_name, _pick_variant(seed, templates))


def build_ivs_assist_hint() -> str:
    dims = "; ".join(f"{d.sigla}={d.nome} ({d.idx_col})" for d in DIMENSOES)
    return f"""## IVS / IVCAD (página IVS — core.mvw_ivs_familia)
- Metodologia IVCAD v1.0.5 (IN084). Escala **0 a 1** (quanto maior, maior vulnerabilidade).
- Join obrigatório: `core.mvw_ivs_familia i` INNER JOIN `vig.mvw_familia f` ON `i.codigo_familiar = f.codigo_familiar`.
- Território (bairro, CRAS): sempre via `f.bairro`, `f.num_cras` — a MV de IVS **não** tem colunas territoriais.
- Universo: `i.elegivel_ivs = true` (PBF ou TAC ≤ 24 meses + renda per capita ≤ R$ 810,50).
- Índice composto: `i.ivs` (alias `i.ivcad`). Dimensões: {dims}.
- Indicadores binários por família: nc1–nc7, dpi1–dpi3, dca1–dca5, tqa1–tqa7, dr1–dr4, ch1–ch14.
- Agregação dimensão: `AVG(i.idx_nc) FILTER (WHERE i.elegivel_ivs)` (idem idx_dpi, idx_dca, idx_tqa, idx_dr, idx_ch).
- Agregação indicador (% famílias): `100 * AVG(i.nc1::numeric) FILTER (WHERE i.elegivel_ivs)`.
- Bairro no IVS: match exato em `btrim(f.bairro::text) = :bairro` (nome canônico da geo)."""


def _extract_ivs_threshold(
    message: str,
    transcript: list[dict[str, str]] | None,
) -> float | None:
    for text_msg in [message] + [
        m.get("content", "")
        for m in reversed(transcript or [])
        if m.get("role") == "assistant"
    ]:
        for match in _THRESHOLD.finditer(text_msg):
            raw = match.group(1).replace(",", ".")
            try:
                val = float(raw)
            except ValueError:
                continue
            if 0 <= val <= 1:
                return val
    return None


def _is_ivs_compare_question(message: str, transcript: list[dict[str, str]] | None) -> bool:
    text_msg = message.strip()
    if not text_msg:
        return False
    if not _is_ivs_question(text_msg) and not re.search(
        r"\b(?:nc|ivs|necessidade\s+de\s+cuidados)\b", " ".join(
            m.get("content", "") for m in (transcript or [])[-4:]
        ),
        re.I,
    ):
        return False
    if _IVS_COMPARE.search(text_msg):
        return True
    blob = " ".join(m.get("content", "") for m in (transcript or [])[-3:])
    return bool(
        re.search(r"maior\s+(?:do\s+)?que|superior\s+a|acima\s+de", blob, re.I)
        and re.search(r"\b(?:nc|0[,.]\d+)\b", blob, re.I)
    )


def try_ivs_cras_compare(
    conn: Connection,
    message: str,
    transcript: list[dict[str, str]] | None = None,
    *,
    user_first_name: str = "",
) -> dict[str, Any] | None:
    """CRAS com índice IVS/dimensão estritamente acima de um limiar (escala 0–1)."""
    if not _is_ivs_compare_question(message, transcript):
        return None
    if not _table_exists(conn, "core", "mvw_ivs_familia"):
        return None

    dim = _detect_dimensao(message) or _detect_dimensao(
        " ".join(m.get("content", "") for m in (transcript or []) if m.get("role") == "user")
    )
    if not dim:
        dim = DIM_POR_SIGLA["NC"]
    idx_col = dim.idx_col

    threshold = _extract_ivs_threshold(message, transcript)
    if threshold is None:
        return {
            "answer": _prefix_name(
                user_first_name,
                "Preciso do **valor de referência** do índice (ex.: 0,45 do CRAS 6) "
                "para comparar os demais CRAS.",
            ),
            "sql": None,
            "row_count": 0,
            "preview": [],
            "mode": "disambiguation",
            "metric": "ivs_cras_compare",
        }

    rows = conn.execute(
        text(
            f"""
            SELECT
              btrim(f.num_cras::text) AS num_cras,
              MAX(btrim(f.nom_cras::text)) AS nom_cras,
              ROUND(AVG(i.{idx_col}) FILTER (WHERE i.elegivel_ivs)::numeric, 4) AS idx_val,
              COUNT(*) FILTER (WHERE i.elegivel_ivs)::bigint AS familias_elegiveis
            FROM core.mvw_ivs_familia i
            INNER JOIN vig.mvw_familia f ON f.codigo_familiar = i.codigo_familiar
            WHERE btrim(COALESCE(f.num_cras::text, '')) <> ''
            GROUP BY btrim(f.num_cras::text)
            HAVING AVG(i.{idx_col}) FILTER (WHERE i.elegivel_ivs) > :threshold
            ORDER BY idx_val DESC, num_cras ASC
            """
        ),
        {"threshold": threshold},
    ).mappings().all()

    preview = [
        {
            "num_cras": str(r["num_cras"]),
            "nom_cras": str(r.get("nom_cras") or ""),
            "valor": float(r["idx_val"]) if r.get("idx_val") is not None else None,
            "familias_elegiveis": int(r.get("familias_elegiveis") or 0),
            "dimensao": dim.sigla,
            "threshold": threshold,
        }
        for r in rows
    ]

    if not preview:
        answer = _prefix_name(
            user_first_name,
            f"Nenhum CRAS apresenta **{dim.sigla}** estritamente acima de "
            f"**{_fmt_idx(threshold)}** (escala 0 a 1).",
        )
        return {
            "answer": answer,
            "sql": None,
            "row_count": 0,
            "preview": [{"dimensao": dim.sigla, "threshold": threshold}],
            "mode": "canonical",
            "metric": "ivs_cras_compare",
        }

    if re.fullmatch(r"qual\??", message.strip(), re.I) and len(preview) == 1:
        row = preview[0]
        answer = _prefix_name(
            user_first_name,
            f"Com **{dim.sigla}** acima de **{_fmt_idx(threshold)}**, destaco o "
            f"**CRAS {row['num_cras']}** (**{_fmt_idx(float(row['valor']))}**).",
        )
    else:
        linhas = [
            f"CRAS {r['num_cras']}: {_fmt_idx(float(r['valor']))}"
            for r in preview[:8]
            if r.get("valor") is not None
        ]
        answer = _prefix_name(
            user_first_name,
            f"CRAS com **{dim.sigla}** **maior que {_fmt_idx(threshold)}** (0 a 1): "
            + "; ".join(linhas) + ".",
        )

    sql = (
        f"SELECT num_cras, AVG(i.{idx_col}) FILTER (WHERE i.elegivel_ivs) "
        f"FROM core.mvw_ivs_familia i JOIN vig.mvw_familia f ... "
        f"HAVING AVG > {threshold}"
    )
    return {
        "answer": answer,
        "sql": sql,
        "row_count": len(preview),
        "preview": preview,
        "mode": "canonical",
        "metric": "ivs_cras_compare",
    }


def try_ivs_metric(
    conn: Connection,
    message: str,
    *,
    user_first_name: str = "",
) -> dict[str, Any] | None:
    """Resposta canônica IVS/IVCAD — dimensão, indicador ou composto, por território."""
    text_msg = message.strip()
    if not _is_ivs_question(text_msg):
        return None

    if not _table_exists(conn, "core", "mvw_ivs_familia"):
        return {
            "answer": (
                "O índice IVS ainda não foi calculado neste ambiente. "
                "Atualize em **Vigilância → IVS** (refresh de `core.mvw_ivs_familia`) e tente novamente."
            ),
            "sql": None,
            "row_count": 0,
            "preview": [],
            "mode": "canonical",
            "metric": "ivs_indisponivel",
        }

    dim = _detect_dimensao(text_msg)
    indicador_hit = _detect_indicador(text_msg)
    indicador = indicador_hit[1] if indicador_hit else None
    if indicador and not dim:
        dim = indicador_hit[0] if indicador_hit else None

    num_cras: str | None = None
    cras_m = _CRAS_NUM.search(text_msg)
    if cras_m:
        num_cras = cras_m.group(1)

    bairro_canon: str | None = None
    resolution = None
    term = extract_ivs_territory(text_msg)
    if term and not num_cras and should_resolve_bairro(text_msg, term):
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

    idx_col = dim.idx_col if dim and not indicador else None
    flag_col = indicador.col if indicador else None

    stats = _fetch_recorte(
        conn,
        num_cras=num_cras,
        bairro=bairro_canon,
        idx_col=idx_col,
        flag_col=flag_col,
    )

    territory_label = _territory_label(
        bairro=bairro_canon,
        num_cras=num_cras,
        resolution=resolution,
    )

    answer = format_ivs_answer(
        dim=dim,
        indicador=indicador,
        idx_val=stats["idx_val"],
        familias=stats["familias_elegiveis"],
        territory_label=territory_label,
        seed=text_msg,
        user_first_name=user_first_name,
        resolution=resolution,
    )

    where, params = ivs_filter_clause(num_cras=num_cras, bairro=bairro_canon)
    if flag_col:
        metric_sql = f"100*AVG(i.{flag_col}::numeric) FILTER (WHERE i.elegivel_ivs)"
    elif idx_col:
        metric_sql = f"AVG(i.{idx_col}) FILTER (WHERE i.elegivel_ivs)"
    else:
        metric_sql = "AVG(i.ivs) FILTER (WHERE i.elegivel_ivs)"

    sql = (
        f"SELECT COUNT(*) FILTER (WHERE i.elegivel_ivs), {metric_sql} "
        "FROM core.mvw_ivs_familia i "
        "INNER JOIN vig.mvw_familia f ON f.codigo_familiar = i.codigo_familiar "
        f"WHERE {where}"
    )

    preview: dict[str, Any] = {
        "familias_elegiveis": stats["familias_elegiveis"],
        "valor": stats["idx_val"],
        "num_cras": num_cras,
        "bairro": bairro_canon,
    }
    if dim:
        preview["dimensao"] = dim.sigla
    if indicador:
        preview["indicador"] = indicador.codigo

    return {
        "answer": answer,
        "sql": sql,
        "row_count": 1,
        "preview": [preview],
        "mode": "canonical",
        "metric": f"ivs_{indicador.codigo.lower() if indicador else (dim.sigla.lower() if dim else 'composto')}",
    }
