"""Métricas alinhadas aos KPIs do painel (mesma lógica de vigilance/kpis)."""

from __future__ import annotations

import re

from sqlalchemy import text
from sqlalchemy.engine import Connection

from ..vigilance.familia_mview import bolsa_folha_kpis_from_raw

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


def try_canonical_metric(conn: Connection, message: str) -> dict | None:
    """
    Resposta sem LLM/SQL quando a pergunta bate com KPI oficial do painel.
    Retorna dict compatível com chat_turn ou None.
    """
    text_msg = message.strip()
    if not text_msg:
        return None

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
