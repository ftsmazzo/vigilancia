"""Lentes IVS contextuais — correlaciona indicadores (40) com a ação territorial.

Não despeja os 40 indicadores: escolhe os pertinentes à ação e destaca
os 3–5 mais salientes no bairro (prevalência × desvio vs município).
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Any

from sqlalchemy import text
from sqlalchemy.engine import Connection

from ..ivs.catalog import DIMENSOES, DIM_POR_SIGLA, IndicadorMeta
from ..vigilance.familia_mview import _table_exists

_IND_BY_COL: dict[str, IndicadorMeta] = {
    ind.col: ind for dim in DIMENSOES for ind in dim.indicadores
}


@dataclass(frozen=True)
class IvsPlanningLens:
    """Recorte de indicadores IVS relevante a um tipo de ação."""

    key: str
    label: str
    indicator_cols: tuple[str, ...]
    primary_dims: tuple[str, ...]
    rationale: str


# Mapa curado: ação → indicadores que enriquecem a decisão (não todos os 40).
PLANNING_IVS_LENSES: dict[str, IvsPlanningLens] = {
    "pbf_desbloqueio": IvsPlanningLens(
        key="pbf_desbloqueio",
        label="Desbloqueio Bolsa Família",
        indicator_cols=(
            "dr1", "dr2", "dr3", "dr4",
            "tqa4", "tqa5", "tqa6", "tqa7",
            "ch3", "ch4", "nc5",
        ),
        primary_dims=("DR", "TQA", "NC"),
        rationale="Bloqueio PBF cruza renda, ocupação adulta e custo de moradia.",
    ),
    "cadu_acao": IvsPlanningLens(
        key="cadu_acao",
        label="Atualização cadastral CADU",
        indicator_cols=(
            "dr2", "dr3", "dr4",
            "tqa1", "tqa2", "tqa3",
            "ch5", "ch6", "ch7", "ch8", "ch9",
            "nc6", "nc7",
        ),
        primary_dims=("DR", "CH", "TQA"),
        rationale="Cadastro desatualizado mascara renda, moradia e composição familiar.",
    ),
    "scfv_idosos": IvsPlanningLens(
        key="scfv_idosos",
        label="SCFV idosos",
        indicator_cols=("nc5", "nc6", "nc7", "nc4", "ch1", "ch2", "dr2", "dr3"),
        primary_dims=("NC", "CH", "DR"),
        rationale="Convivência idosos: dependência, moradia e pobreza estrutural.",
    ),
    "scfv_infancia": IvsPlanningLens(
        key="scfv_infancia",
        label="SCFV primeira infância",
        indicator_cols=("nc1", "nc2", "dpi1", "dpi2", "dpi3", "ch2", "ch7", "ch9"),
        primary_dims=("NC", "DPI", "CH"),
        rationale="Primeira infância: cuidado, escola 0–6 e condições habitacionais.",
    ),
    "scfv_adolescencia": IvsPlanningLens(
        key="scfv_adolescencia",
        label="SCFV infância/adolescência",
        indicator_cols=("nc3", "dca1", "dca2", "dca3", "dca4", "dca5", "dpi1"),
        primary_dims=("DCA", "NC", "DPI"),
        rationale="Faixa 6–17: escola, trabalho infantil e defasagem escolar.",
    ),
    "scfv_default": IvsPlanningLens(
        key="scfv_default",
        label="SCFV / convivência",
        indicator_cols=("nc3", "dca1", "dca2", "dca3", "dpi2", "nc5"),
        primary_dims=("DCA", "NC", "DPI"),
        rationale="Demanda convivência geral: crianças/adolescentes e cuidados.",
    ),
}


def resolve_planning_ivs_lens(
    *,
    sibec_focus: str | None = None,
    faixa_label: str | None = None,
    age_min: int = 0,
    age_max: int = 120,
    message: str = "",
) -> IvsPlanningLens:
    """Escolhe a lente IVS conforme o tipo de ação territorial."""
    blob = f"{message} {faixa_label or ''}".lower()
    if sibec_focus == "bloqueio" or re.search(r"desbloque|bloqueio.*pbf|pbf.*bloque", blob):
        return PLANNING_IVS_LENSES["pbf_desbloqueio"]
    if re.search(r"atualiza[cç][ãa]o\s+cadastral|tac|recadastramento", blob):
        return PLANNING_IVS_LENSES["cadu_acao"]
    if age_min >= 60 or re.search(r"idos|60\s*\+|melhor\s+idade|terceira\s+idade", blob):
        return PLANNING_IVS_LENSES["scfv_idosos"]
    if age_max <= 6 or re.search(r"primeira\s+inf|0\s*a\s*6", blob):
        return PLANNING_IVS_LENSES["scfv_infancia"]
    if age_min >= 6 and age_max <= 17:
        return PLANNING_IVS_LENSES["scfv_adolescencia"]
    return PLANNING_IVS_LENSES["scfv_default"]


def _fmt_pct(v: float) -> str:
    return f"{v:.1f} %".replace(".", ",")


def _fmt_delta(v: float) -> str:
    sign = "+" if v > 0 else ""
    return f"{sign}{v:.1f} p.p.".replace(".", ",")


def _salience_score(bairro_pct: float, delta_pp: float) -> float:
    """Prioriza indicadores altos no bairro e/ou muito acima do município."""
    return abs(delta_pp) * 1.2 + bairro_pct * 0.4


def _fetch_indicator_pcts(
    conn: Connection,
    cols: tuple[str, ...],
    *,
    bairro: str | None,
) -> tuple[int, dict[str, float]]:
    if not cols:
        return 0, {}
    select_parts = [
        f"ROUND(100.0 * AVG(i.{c}::numeric) FILTER (WHERE i.elegivel_ivs)::numeric, 2) AS {c}_pct"
        for c in cols
    ]
    where = "i.elegivel_ivs"
    params: dict[str, Any] = {}
    if bairro:
        where += " AND btrim(f.bairro::text) = :bairro"
        params["bairro"] = bairro.strip()

    row = conn.execute(
        text(
            f"""
            SELECT
              COUNT(*) FILTER (WHERE i.elegivel_ivs)::bigint AS fam,
              {", ".join(select_parts)}
            FROM core.mvw_ivs_familia i
            INNER JOIN vig.mvw_familia f ON f.codigo_familiar = i.codigo_familiar
            WHERE {where}
            """
        ),
        params,
    ).mappings().first() or {}

    fam = int(row.get("fam") or 0)
    pcts = {
        c: float(row[f"{c}_pct"])
        for c in cols
        if row.get(f"{c}_pct") is not None
    }
    return fam, pcts


def collect_contextual_ivs_indicator_facts(
    conn: Connection,
    *,
    bairro: str,
    lens: IvsPlanningLens,
    limit: int = 5,
    min_delta_pp: float = 2.0,
    min_bairro_pct: float = 12.0,
) -> list[dict[str, Any]]:
    """
    Retorna fatos eixo D com indicadores IVS salientes para o bairro.

    Critério: top N por salience entre os indicadores da lente, incluindo
    indicadores com prevalência relevante no bairro OU desvio vs município.
    """
    if not _table_exists(conn, "core", "mvw_ivs_familia"):
        return []

    cols = lens.indicator_cols
    fam_b, pcts_b = _fetch_indicator_pcts(conn, cols, bairro=bairro)
    fam_m, pcts_m = _fetch_indicator_pcts(conn, cols, bairro=None)

    if fam_b < 5:
        return [
            {
                "axis": "D",
                "label": f"Indicadores IVS ({lens.label}) — {bairro}",
                "value": "universo IVS pequeno no bairro",
                "source": "core.mvw_ivs_familia",
                "detail": f"{fam_b} fam. elegíveis — interpretar dimensões agregadas com cautela",
                "signal": "ressalva",
            }
        ]

    scored: list[tuple[float, str, float, float]] = []
    for col in cols:
        bp = pcts_b.get(col)
        if bp is None:
            continue
        mp = pcts_m.get(col, bp)
        delta = bp - mp
        if bp < min_bairro_pct and abs(delta) < min_delta_pp:
            continue
        scored.append((_salience_score(bp, delta), col, bp, delta))

    scored.sort(key=lambda x: (-x[0], -x[2]))
    picks = scored[:limit]

    if not picks:
        picks = sorted(
            (( _salience_score(pcts_b[c], pcts_b[c] - pcts_m.get(c, 0)), c, pcts_b[c], pcts_b[c] - pcts_m.get(c, 0))
             for c in cols if c in pcts_b),
            key=lambda x: -x[0],
        )[: min(3, limit)]

    facts: list[dict[str, Any]] = []
    for _, col, bp, delta in picks:
        ind = _IND_BY_COL.get(col)
        if not ind:
            continue
        dim = next((d for d in DIMENSOES if ind in d.indicadores), None)
        dim_sigla = dim.sigla if dim else "?"
        tend = "acima" if delta > 1 else ("abaixo" if delta < -1 else "próximo")
        signal = (
            "reforça_prioridade"
            if bp >= 20 or delta >= 5
            else ("modera" if delta <= -3 else "neutro")
        )
        facts.append(
            {
                "axis": "D",
                "label": f"IVS {ind.codigo} — {ind.titulo} ({bairro})",
                "value": _fmt_pct(bp),
                "source": "core.mvw_ivs_familia × vig.mvw_familia",
                "detail": (
                    f"dim. {dim_sigla}; município {_fmt_pct(pcts_m.get(col, bp))} "
                    f"({_fmt_delta(delta)} vs município, {tend}); "
                    f"lente: {lens.label}"
                ),
                "signal": signal,
            }
        )

    if facts:
        facts.insert(
            0,
            {
                "axis": "D",
                "label": f"Lente IVS — {lens.label}",
                "value": f"{len(picks)} indicadores salientes de {len(cols)} pertinentes",
                "source": "ivs_context_lens",
                "detail": lens.rationale,
                "signal": "neutro",
            },
        )
    return facts


def build_ivs_lens_playbook_snippet(lens: IvsPlanningLens | None) -> str:
    if not lens:
        return ""
    dims = ", ".join(lens.primary_dims)
    return (
        f"### Lente IVS — {lens.label}\n"
        f"- Dimensões prioritárias: **{dims}**.\n"
        f"- Indicadores pertinentes (amostra curada): "
        f"{', '.join(c.upper() for c in lens.indicator_cols[:8])}"
        f"{'…' if len(lens.indicator_cols) > 8 else ''}.\n"
        f"- **Não cite os 40 indicadores** — use só os **salientes** nos fatos (eixo D).\n"
        f"- Correlate: se indicador IVS **reforça** o eixo principal (ex.: DR alto + bloqueio SIBEC), "
        f"mencione **uma frase**; se IVS **modera** (ex.: NC baixo + carência SISC alta), "
        f"diferencie urgência operacional vs estrutural.\n"
        f"- Racional: {lens.rationale}"
    )
