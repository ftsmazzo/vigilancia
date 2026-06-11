"""Cruzamentos CADU × SISC (Serviço de Convivência) — sempre via mvw_sisc_qualificado."""

from __future__ import annotations

import re
from typing import Literal

from sqlalchemy import text
from sqlalchemy.engine import Connection

MetricKind = Literal["familias", "familias_crianca_sisc", "pessoas", "pessoas_crianca_sisc", "por_cras"]

_ADOL_12_17 = re.compile(r"12\s*(?:a|-|á)\s*17|adolesc|12\s*17", re.I)
_CRIANCA_COUNT = re.compile(
    r"quantas?\s+(?:crianç|crianc|adolesc)|quantos?\s+(?:crianç|crianc|adolesc)|"
    r"(?:crianç|crianc|adolesc)[a-z\s]*/\s*(?:adolesc|crianç)",
    re.I,
)

_SISC = re.compile(r"sisc|conviv|scfv|servi[cç]o\s+de\s+conviv", re.I)
_PBF = re.compile(r"pbf|bolsa\s+fam|folha|benef[ií]cio", re.I)
_CRIANCA = re.compile(r"criança|crianca|menor|adolesc", re.I)
_PESSOAS = re.compile(r"pessoa|pessoas|atendidos|nis|integrantes|indiv[ií]duo", re.I)
_FAMILIAS = re.compile(r"fam[ií]lia|familias", re.I)
_CRAS = re.compile(r"\bcras\b", re.I)
_CRAS_BREAKDOWN = re.compile(
    r"por\s+cras|cada\s+cras|divide|divid|detalh|distribu|desdobr|granula|"
    r"separad\s+por\s+cras",
    re.I,
)
_CRAS_RANKING = re.compile(
    r"qual\s+(?:dos?\s+)?cras|qual\s+o\s+cras|"
    r"cras\s+(?:que\s+)?(?:tem|t[eê]m|atende)\s+(?:mais|o\s+maior)|"
    r"(?:mais|maior)\s+(?:pessoas|atendidos|gente).*cras|"
    r"cras\s+.*(?:mais|maior|l[ií]der|top)",
    re.I,
)
_CONTEXT_REF = re.compile(
    r"dessas|essas|destas|desse\s+grupo|dessas\s+pesso|essas\s+pesso|"
    r"dentro\s+dessas|dentro\s+destas",
    re.I,
)

_BASE_WHERE = """
    s.classificacao_vinculo = 'vinculado_cadu'
"""


def conversation_blob(message: str, transcript: list[dict[str, str]] | None) -> str:
    parts = [m.get("content", "") for m in (transcript or [])]
    parts.append(message)
    return " ".join(parts)


def is_sisc_context(message: str, transcript: list[dict[str, str]] | None) -> bool:
    from .planning_metrics import is_planning_demand

    if is_planning_demand(message, transcript):
        return False
    blob = conversation_blob(message, transcript)
    return bool(_SISC.search(message) or _SISC.search(blob))


def wants_cras_breakdown(message: str, transcript: list[dict[str, str]] | None) -> bool:
    blob = conversation_blob(message, transcript)
    if _CRAS_BREAKDOWN.search(message) or _CRAS_BREAKDOWN.search(blob):
        return True
    if _CRAS_RANKING.search(message):
        return True
    # "qual CRAS …" com convivência/SISC no contexto
    if _CRAS.search(message) and _SISC.search(blob) and re.search(
        r"qual|mais|maior|atende|ranking", message, re.I
    ):
        return True
    return False


def wants_cras_top_only(message: str) -> bool:
    return bool(
        _CRAS_RANKING.search(message)
        or re.search(r"qual\s+.*cras|cras\s+.*mais|mais\s+.*cras", message, re.I)
    )


def detect_metric_kind(message: str, transcript: list[dict[str, str]] | None) -> MetricKind:
    if wants_cras_breakdown(message, transcript):
        return "por_cras"

    # Contagem de crianças/adolescentes (NIS)
    if _CRIANCA_COUNT.search(message) or (
        _CRIANCA.search(message) and re.search(r"quantas|quantos", message, re.I)
    ):
        return "pessoas_crianca_sisc"

    if _PESSOAS.search(message):
        return "pessoas"

    if re.search(r"quantas?\s+fam|quantos?\s+fam", message, re.I) and _CRIANCA.search(
        conversation_blob(message, transcript)
    ):
        return "familias_crianca_sisc"

    blob = conversation_blob(message, transcript)
    if (_FAMILIAS.search(message) or _FAMILIAS.search(blob)) and _CRIANCA.search(blob):
        return "familias_crianca_sisc"

    if _FAMILIAS.search(message) or (_FAMILIAS.search(blob) and not _PESSOAS.search(message)):
        return "familias"

    return "pessoas"


def _pbf_child_subfamily_scope(pbf_in_blob: bool) -> str:
    """Famílias PBF com criança/adolescente matriculado no SISC."""
    pbf = " AND COALESCE(s2.familia_na_folha_pbf, FALSE)" if pbf_in_blob else ""
    return f"""
      AND s.codigo_familiar IN (
        SELECT DISTINCT s2.codigo_familiar
        FROM vig.mvw_sisc_qualificado s2
        WHERE s2.classificacao_vinculo = 'vinculado_cadu'{pbf}
          AND s2.classificacao_faixa_idade IN ('crianca_0_11', 'adolescente_12_17')
          AND s2.codigo_familiar IS NOT NULL
      )
    """


def _needs_pbf_child_subfamily_scope(message: str, transcript: list[dict[str, str]] | None) -> bool:
    """Escopo restrito só quando a conversa trata explicitamente de PBF + crianças no SISC."""
    if not _CONTEXT_REF.search(message):
        return False
    blob = conversation_blob(message, transcript)
    return bool(_PBF.search(blob) and _CRIANCA.search(blob) and _SISC.search(blob))


def build_filters(message: str, transcript: list[dict[str, str]] | None) -> tuple[str, list[str], str]:
    blob = conversation_blob(message, transcript)
    parts = [_BASE_WHERE.strip()]
    labels: list[str] = ["vinculados ao CADU (SISC × NIS)"]
    extra_scope = ""

    pbf_in_blob = bool(_PBF.search(blob))
    if pbf_in_blob:
        parts.append("COALESCE(s.familia_na_folha_pbf, FALSE)")
        labels.append("família na folha PBF")

    if _ADOL_12_17.search(blob):
        parts.append("s.classificacao_faixa_idade = 'adolescente_12_17'")
        labels.append("12–17 anos")

    kind = detect_metric_kind(message, transcript)

    if kind in ("familias_crianca_sisc", "pessoas_crianca_sisc"):
        parts.append("s.classificacao_faixa_idade IN ('crianca_0_11', 'adolescente_12_17')")
        if kind == "pessoas_crianca_sisc":
            labels.append("crianças/adolescentes (NIS distintos)")
        else:
            labels.append("com criança/adolescente matriculado(a) no SISC")

    if _needs_pbf_child_subfamily_scope(message, transcript):
        extra_scope = _pbf_child_subfamily_scope(pbf_in_blob)
        labels.append("famílias PBF com criança no SISC (contexto da conversa)")

    return " AND ".join(parts), labels, extra_scope


def _fmt_int(n: int) -> str:
    return f"{n:,}".replace(",", ".")


def _format_por_cras_answer(
    rows: list[dict],
    message: str,
    ctx_txt: str,
    top_only: bool,
) -> str:
    if not rows:
        return (
            "Não há atendidos no SISC com os filtros aplicados "
            f"({ctx_txt})."
        )

    total = sum(int(r["atendidos"] or 0) for r in rows)
    foot = (
        "\n\n**Fonte:** `vig.mvw_sisc_qualificado` (matrícula SISC). "
        "CRAS listado é o da **matrícula SISC**, não o territorial do CADU (`vig.mvw_familia`)."
    )

    if top_only:
        top = rows[0]
        n_top = int(top["atendidos"] or 0)
        lead = (
            f"O CRAS com **maior** número de pessoas no **Serviço de Convivência (SISC)** é "
            f"**{top['cras_nome']}** (código **{top['cras_codigo']}**), com "
            f"**{_fmt_int(n_top)}** atendidos (NIS distintos) ({ctx_txt})."
        )
        if len(rows) > 1:
            others = [
                f"- **{r['cras_nome']}** ({r['cras_codigo']}): {_fmt_int(int(r['atendidos'] or 0))}"
                for r in rows[1:8]
            ]
            lead += "\n\n**Demais unidades (SISC):**\n" + "\n".join(others)
        return lead + foot

    linhas = [
        f"- **{r['cras_nome']}** ({r['cras_codigo']}): {_fmt_int(int(r['atendidos'] or 0))} atendidos"
        for r in rows[:20]
    ]
    extra = f"\n\n… e mais {len(rows) - 20} unidades." if len(rows) > 20 else ""
    return (
        f"**Serviço de Convivência (SISC)** — **{_fmt_int(total)}** atendidos (NIS) "
        f"em **{len(rows)}** unidades ({ctx_txt}).\n\n"
        + "\n".join(linhas)
        + extra
        + foot
    )


def run_sisc_cadu_query(
    conn: Connection,
    message: str,
    transcript: list[dict[str, str]] | None,
) -> dict | None:
    if not is_sisc_context(message, transcript):
        return None

    where_sql, filter_labels, extra_scope = build_filters(message, transcript)
    kind = detect_metric_kind(message, transcript)
    ctx_txt = ", ".join(filter_labels)
    pbf_in_blob = bool(_PBF.search(conversation_blob(message, transcript)))

    if kind == "por_cras":
        sql = f"""
            SELECT
              COALESCE(NULLIF(btrim(s.cras_codigo::text), ''), '(sem código)') AS cras_codigo,
              COALESCE(NULLIF(btrim(s.cras_nome::text), ''), '(sem CRAS)') AS cras_nome,
              COUNT(DISTINCT s.nis_norm)::bigint AS atendidos
            FROM vig.mvw_sisc_qualificado s
            WHERE {where_sql}{extra_scope}
            GROUP BY 1, 2
            ORDER BY 3 DESC
            LIMIT 30
        """
        rows = [dict(r) for r in conn.execute(text(sql)).mappings().all()]
        answer = _format_por_cras_answer(
            rows,
            message,
            ctx_txt,
            top_only=wants_cras_top_only(message),
        )
        return {
            "answer": answer,
            "sql": " ".join(sql.split()),
            "row_count": len(rows),
            "preview": rows,
            "mode": "canonical",
            "metric": "sisc_por_cras",
            "source": "vig.mvw_sisc_qualificado",
        }

    if kind == "familias" or kind == "familias_crianca_sisc":
        sql = f"""
            SELECT COUNT(DISTINCT s.codigo_familiar)::bigint AS total
            FROM vig.mvw_sisc_qualificado s
            WHERE {where_sql}{extra_scope}
              AND s.codigo_familiar IS NOT NULL
        """
        row = conn.execute(text(sql)).mappings().first()
        n = int((row or {}).get("total") or 0)
        if kind == "familias_crianca_sisc":
            pbf_txt = " na folha PBF" if pbf_in_blob else ""
            lead = (
                f"Há **{_fmt_int(n)}** famílias{pbf_txt} com pelo menos uma "
                f"criança/adolescente matriculado(a) no **Serviço de Convivência (SISC)** ({ctx_txt})."
            )
            metric = "pbf_familias_crianca_sisc"
        else:
            lead = (
                f"Há **{_fmt_int(n)}** famílias com integrante no **SISC** ({ctx_txt})."
            )
            metric = "familias_sisc"
    elif kind == "pessoas_crianca_sisc":
        sql = f"""
            SELECT COUNT(DISTINCT s.nis_norm)::bigint AS total
            FROM vig.mvw_sisc_qualificado s
            WHERE {where_sql}{extra_scope}
        """
        row = conn.execute(text(sql)).mappings().first()
        n = int((row or {}).get("total") or 0)
        lead = (
            f"Há **{_fmt_int(n)}** crianças/adolescentes (**NIS distintos**) no "
            f"**Serviço de Convivência (SISC)** ({ctx_txt})."
        )
        metric = "pessoas_crianca_sisc"
    else:
        sql = f"""
            SELECT COUNT(DISTINCT s.nis_norm)::bigint AS total
            FROM vig.mvw_sisc_qualificado s
            WHERE {where_sql}{extra_scope}
        """
        row = conn.execute(text(sql)).mappings().first()
        n = int((row or {}).get("total") or 0)
        lead = (
            f"Há **{_fmt_int(n)}** pessoas (**NIS distintos**) atendidas no "
            f"**Serviço de Convivência (SISC)** ({ctx_txt})."
        )
        metric = "pessoas_sisc"

    foot = (
        "\n\n**Fonte:** `vig.mvw_sisc_qualificado` — cadastro do SISC qualificado por NIS e "
        "cruzado com o CADU. **Não** use `vig.mvw_familia` para matrícula em convivência; "
        "use `vig.mvw_familia` apenas para territorialização e indicadores familiares do CADU."
    )
    return {
        "answer": lead + foot,
        "sql": " ".join(sql.split()),
        "row_count": 1,
        "preview": [{"total": n}],
        "mode": "canonical",
        "metric": metric,
        "source": "vig.mvw_sisc_qualificado",
    }
