"""Métricas alinhadas aos KPIs do painel (mesma lógica de vigilance/kpis)."""

from __future__ import annotations

import re

from sqlalchemy import text
from sqlalchemy.engine import Connection

from ..vigilance.familia_mview import _table_exists, bolsa_folha_kpis_from_raw
from .cras_breakdown import (
    format_cras_breakdown_answer,
    sort_cras_rows,
)
from .geo_territorial import try_geo_contextual_followup, try_geo_territorial_metric
from .ivs_metrics import try_ivs_cras_compare, try_ivs_metric
from .planning_metrics import try_planning_demand_metric
from .sibec_metrics import try_sibec_manut_metric
from .sisc_cadu import run_sisc_cadu_query

_FOLHA_PBF = re.compile(
    r"(?:"
    r"folha\s+(?:do\s+)?(?:pbf|bolsa)|"
    r"(?:pbf|bolsa)\s+(?:na\s+)?folha|"
    r"na\s+folha\s+(?:do\s+)?(?:pbf|bolsa)|"
    r"programa\s+bolsa\s+fam[ií]lia"
    r")",
    re.I,
)

_MARCADOR_CADU = re.compile(
    r"marcador|cadu.*pbf|pbf.*cadu|recebe\s+pbf\s+no\s+cadu",
    re.I,
)


def _fmt_int(n: int) -> str:
    return f"{n:,}".replace(",", ".")


_SISC = re.compile(r"sisc|conviv|scfv|servi[cç]o\s+de\s+conviv", re.I)
_CRAS_BREAKDOWN = re.compile(
    r"por\s+cras|cada\s+cras|divide|divid|detalh|distribu|desdobr|granula|"
    r"separad\s+por\s+cras|distribu[ií][çc][ãa]o\s+por\s+cras",
    re.I,
)


def _try_cadu_familias_por_cras(
    conn: Connection,
    message: str,
    transcript: list[dict[str, str]] | None,
) -> dict | None:
    """Desdobramento CADU por CRAS territorial (f.num_cras), ordem 1–12 + sem referência."""
    # Só dispara quando a pergunta atual pede desdobramento — não reutiliza palavras do histórico
    # (ex.: "territorialização" na resposta anterior sobre bairro).
    if not _CRAS_BREAKDOWN.search(message):
        return None
    blob = _conversation_blob(message, transcript)
    # Prioriza SISC quando a pergunta é claramente sobre convivência
    if _SISC.search(blob) and _SISC.search(message) and not re.search(
        r"cadu|cadastro\s+[úu]nico|fam[ií]lia", message, re.I
    ):
        return None

    if not _table_exists(conn, "vig", "mvw_familia"):
        return None

    sql = """
        SELECT
            f.num_cras,
            f.nom_cras,
            COUNT(DISTINCT f.codigo_familiar)::bigint AS total_familias
        FROM vig.mvw_familia f
        GROUP BY f.num_cras, f.nom_cras
        ORDER BY
            CASE
                WHEN f.num_cras IS NULL OR btrim(COALESCE(f.num_cras::text, '')) = '' THEN 9999
                ELSE NULLIF(regexp_replace(btrim(f.num_cras::text), '[^0-9].*', ''), '')::int
            END NULLS LAST,
            f.nom_cras
    """
    rows = [dict(r) for r in conn.execute(text(sql)).mappings().all()]
    if not rows:
        return None

    answer = format_cras_breakdown_answer(
        rows,
        metric_label="famílias do Cadastro Único",
    )
    return {
        "answer": answer,
        "sql": " ".join(sql.split()),
        "row_count": len(rows),
        "preview": sort_cras_rows(rows),
        "mode": "canonical",
        "metric": "cadu_familias_por_cras",
    }


def _conversation_blob(message: str, transcript: list[dict[str, str]] | None) -> str:
    parts = [m.get("content", "") for m in (transcript or [])]
    parts.append(message)
    return " ".join(parts)


def _try_sisc_cross(
    conn: Connection,
    message: str,
    transcript: list[dict[str, str]] | None,
) -> dict | None:
    from .sisc_cadu import is_sisc_context

    if not is_sisc_context(message, transcript):
        return None
    if not _table_exists(conn, "vig", "mvw_sisc_qualificado"):
        return {
            "answer": (
                "A base do Serviço de Convivência (SISC) ainda não está qualificada. "
                "Vá em **Convivência** → **Qualificar atendidos** (após ingestão do SISC.csv) "
                "e tente novamente."
            ),
            "sql": None,
            "row_count": 0,
            "preview": [],
            "mode": "canonical",
            "metric": "sisc_indisponivel",
        }

    return run_sisc_cadu_query(conn, message, transcript)


def try_canonical_metric(
    conn: Connection,
    message: str,
    transcript: list[dict[str, str]] | None = None,
    *,
    db: Session | None = None,
    user_first_name: str = "",
    block_sisc: bool = False,
) -> dict | None:
    """
    Resposta sem LLM/SQL quando a pergunta bate com KPI oficial do painel.
    Retorna dict compatível com chat_turn ou None.
    """
    text_msg = message.strip()
    if not text_msg:
        return None

    planning = try_planning_demand_metric(
        conn, message, transcript, db=db, user_first_name=user_first_name
    )
    if planning:
        return planning

    if not block_sisc:
        sisc = _try_sisc_cross(conn, message, transcript)
        if sisc:
            return sisc

    ivs_compare = try_ivs_cras_compare(
        conn, message, transcript, user_first_name=user_first_name
    )
    if ivs_compare:
        return ivs_compare

    ivs = try_ivs_metric(conn, message, user_first_name=user_first_name)
    if ivs:
        return ivs

    sibec_manut = try_sibec_manut_metric(
        conn, message, transcript, user_first_name=user_first_name
    )
    if sibec_manut:
        return sibec_manut

    contextual = try_geo_contextual_followup(conn, message, transcript)
    if contextual:
        return contextual

    geo = try_geo_territorial_metric(conn, message, transcript)
    if geo:
        return geo

    cadu_cras = _try_cadu_familias_por_cras(conn, message, transcript)
    if cadu_cras:
        return cadu_cras

    total_familias_cadu = int(
        conn.execute(text("SELECT COUNT(*)::bigint FROM vig.mvw_familia")).scalar() or 0
    )

    if _FOLHA_PBF.search(text_msg) and not _MARCADOR_CADU.search(text_msg):
        bolsa = bolsa_folha_kpis_from_raw(conn)
        n_folha = bolsa.total_familias_folha
        pct = round(100.0 * n_folha / total_familias_cadu, 2) if total_familias_cadu else 0.0
        answer = (
            f"Há **{_fmt_int(n_folha)}** famílias na folha de pagamento do Programa Bolsa Família "
            f"(base SIBEC, mesma regra do painel Início).\n\n"
            f"Isso corresponde a **{pct:.2f} %** das **{_fmt_int(total_familias_cadu)}** famílias "
            f"no Cadastro Único do município.\n\n"
            "Este indicador conta códigos familiares distintos na folha importada, "
            "incluindo famílias que podem não estar na extração CADU local. "
            "Para famílias do CADU com marcador PBF (sem folha), pergunte explicitamente por "
            "\"marcador PBF no CADU\"."
        )
        return {
            "answer": answer,
            "sql": (
                "-- Métrica oficial (painel Início): bolsa_folha_kpis_from_raw → "
                "raw.sibec__programa_bolsa_familia, última competência quando houver."
            ),
            "row_count": 1,
            "preview": [
                {
                    "familias_folha_pbf": n_folha,
                    "total_familias_cadu": total_familias_cadu,
                    "pct_sobre_cadu": pct,
                }
            ],
            "mode": "canonical",
            "metric": "familias_folha_pbf",
        }

    if _MARCADOR_CADU.search(text_msg) and _FOLHA_PBF.search(text_msg):
        return None

    if _MARCADOR_CADU.search(text_msg):
        row = conn.execute(
            text(
                """
                SELECT COUNT(DISTINCT codigo_familiar)::bigint AS n
                FROM vig.mvw_familia
                WHERE btrim(COALESCE(marc_pbf_cadu::text, '')) IN ('1', '01', 'sim', 's', 'true')
                """
            )
        ).mappings().first()
        n = int((row or {}).get("n") or 0)
        pct = round(100.0 * n / total_familias_cadu, 2) if total_familias_cadu else 0.0
        answer = (
            f"Há **{_fmt_int(n)}** famílias no CADU com marcador de Bolsa Família "
            f"(**{pct:.2f} %** do total de famílias cadastradas).\n\n"
            "Isso usa o campo do Cadastro Único (marc_pbf_cadu), não a folha de pagamento SIBEC."
        )
        return {
            "answer": answer,
            "sql": (
                "SELECT COUNT(DISTINCT codigo_familiar) FROM vig.mvw_familia "
                "WHERE btrim(COALESCE(marc_pbf_cadu::text, '')) IN ('1', '01', 'sim', 's', 'true')"
            ),
            "row_count": 1,
            "preview": [
                {
                    "familias_marcador_cadu": n,
                    "total_familias_cadu": total_familias_cadu,
                }
            ],
            "mode": "canonical",
            "metric": "familias_marcador_pbf_cadu",
        }

    # CADU ∩ folha (marc_pbf na MV)
    if re.search(r"\bpbf\b", text_msg, re.I) and re.search(
        r"quantas|quantos|total|n[uú]mero", text_msg, re.I
    ):
        row = conn.execute(
            text(
                """
                SELECT COUNT(DISTINCT codigo_familiar)::bigint AS n
                FROM vig.mvw_familia
                WHERE COALESCE(marc_pbf, FALSE)
                """
            )
        ).mappings().first()
        n = int((row or {}).get("n") or 0)
        pct = round(100.0 * n / total_familias_cadu, 2) if total_familias_cadu else 0.0
        bolsa = bolsa_folha_kpis_from_raw(conn)
        n_folha = bolsa.total_familias_folha
        answer = (
            f"No Cadastro Único local, **{_fmt_int(n)}** famílias estão vinculadas à folha PBF "
            f"(marc_pbf na visão familiar, **{pct:.2f} %** do CADU).\n\n"
            f"Na folha SIBEC completa (painel Início) são **{_fmt_int(n_folha)}** famílias — "
            f"a diferença pode ser famílias na folha sem registro na extração CADU do município."
        )
        return {
            "answer": answer,
            "sql": "SELECT COUNT(DISTINCT codigo_familiar) FROM vig.mvw_familia WHERE COALESCE(marc_pbf, FALSE)",
            "row_count": 1,
            "preview": [
                {
                    "familias_cadu_na_folha": n,
                    "familias_folha_sibec": n_folha,
                    "total_familias_cadu": total_familias_cadu,
                }
            ],
            "mode": "canonical",
            "metric": "familias_cadu_intersecao_folha",
        }

    return None
