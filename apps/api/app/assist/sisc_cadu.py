"""Cruzamentos CADU × SISC (Serviço de Convivência) — sempre via mvw_sisc_qualificado."""

from __future__ import annotations

import re
from typing import Literal

from sqlalchemy import text
from sqlalchemy.engine import Connection

MetricKind = Literal["familias", "familias_crianca_sisc", "pessoas", "por_cras"]

_SISC = re.compile(r"sisc|conviv|scfv|servi[cç]o\s+de\s+conviv", re.I)
_PBF = re.compile(r"pbf|bolsa\s+fam|folha|benef[ií]cio", re.I)
_CRIANCA = re.compile(r"criança|crianca|menor|adolesc", re.I)
_PESSOAS = re.compile(r"pessoa|pessoas|atendidos|nis|integrantes|indiv[ií]duo", re.I)
_FAMILIAS = re.compile(r"fam[ií]lia|familias", re.I)
_CRAS_BREAKDOWN = re.compile(
    r"por\s+cras|cada\s+cras|divide|divid|detalh|distribu|desdobr|granula",
    re.I,
)
_THOSE_FAMILIES = re.compile(
    r"essas\s+fam|dessas\s+fam|representam|entre\s+elas|desse\s+grupo|"
    r"nesse\s+grupo|dessas\s+crianç|dessas\s+crianc",
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
    blob = conversation_blob(message, transcript)
    return bool(_SISC.search(message) or _SISC.search(blob))


def detect_metric_kind(message: str, transcript: list[dict[str, str]] | None) -> MetricKind:
    blob = conversation_blob(message, transcript)

    if _CRAS_BREAKDOWN.search(message) or _CRAS_BREAKDOWN.search(blob):
        return "por_cras"

    # Pergunta explícita por pessoas/atendidos/NIS
    if _PESSOAS.search(message):
        return "pessoas"

    # Famílias com crianças no SISC (não confundir com contagem de NIS criança)
    if (_FAMILIAS.search(message) or _FAMILIAS.search(blob)) and _CRIANCA.search(blob):
        return "familias_crianca_sisc"

    if _FAMILIAS.search(message) or (_FAMILIAS.search(blob) and not _PESSOAS.search(message)):
        return "familias"

    return "pessoas"


def _subfamily_scope_sql(pbf_in_blob: bool) -> str:
    """Restringe às famílias PBF com criança/adolescente no SISC (contexto da pergunta anterior)."""
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


def build_filters(message: str, transcript: list[dict[str, str]] | None) -> tuple[str, list[str], str]:
    """Retorna cláusula WHERE (sem WHERE), rótulos e SQL extra de escopo familiar."""
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

    if kind == "familias_crianca_sisc":
        parts.append("s.classificacao_faixa_idade IN ('crianca_0_11', 'adolescente_12_17')")
        labels.append("com criança/adolescente matriculado(a) no SISC")

    if kind == "pessoas" and _THOSE_FAMILIES.search(message) and _CRIANCA.search(blob):
        extra_scope = _subfamily_scope_sql(pbf_in_blob)
        labels.append("integrantes das famílias PBF com criança no SISC (follow-up)")

    return " AND ".join(parts), labels, extra_scope


def _fmt_int(n: int) -> str:
    return f"{n:,}".replace(",", ".")


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
        total = sum(int(r["atendidos"] or 0) for r in rows)
        linhas = [
            f"- **{r['cras_nome']}** ({r['cras_codigo']}): {_fmt_int(int(r['atendidos'] or 0))} atendidos"
            for r in rows[:20]
        ]
        answer = (
            f"**Serviço de Convivência (SISC)** — **{_fmt_int(total)}** atendidos (NIS) "
            f"em **{len(rows)}** unidades ({ctx_txt}).\n\n"
            + "\n".join(linhas)
            + "\n\n**Fonte:** `vig.mvw_sisc_qualificado` (matrícula SISC). "
            "CRAS listado é o da **matrícula SISC**, não o territorial do CADU (`vig.mvw_familia`)."
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
            lead = (
                f"Há **{_fmt_int(n)}** famílias na folha PBF com pelo menos uma "
                f"criança/adolescente matriculado(a) no **Serviço de Convivência (SISC)** ({ctx_txt})."
            )
            metric = "pbf_familias_crianca_sisc"
        else:
            lead = (
                f"Há **{_fmt_int(n)}** famílias com integrante no **SISC** ({ctx_txt})."
            )
            metric = "familias_sisc"
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
