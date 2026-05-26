"""Métricas alinhadas aos KPIs do painel (mesma lógica de vigilance/kpis)."""

from __future__ import annotations

import re

from sqlalchemy import text
from sqlalchemy.engine import Connection

from ..vigilance.familia_mview import _table_exists, bolsa_folha_kpis_from_raw

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
_ADOL_12_17 = re.compile(r"12\s*(?:a|-|á)\s*17|adolesc|12\s*17", re.I)
_PBF_CTX = re.compile(r"pbf|bolsa\s+fam|folha", re.I)
_CRAS_BREAKDOWN = re.compile(
    r"por\s+cras|cada\s+cras|divide|divid|detalh|distribu|desdobr",
    re.I,
)


def _conversation_blob(message: str, transcript: list[dict[str, str]] | None) -> str:
    parts = [m.get("content", "") for m in (transcript or [])]
    parts.append(message)
    return " ".join(parts)


def _try_sisc_cross(
    conn: Connection,
    message: str,
    transcript: list[dict[str, str]] | None,
) -> dict | None:
    blob = _conversation_blob(message, transcript)
    if not _SISC.search(blob):
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

    wheres = ["s.classificacao_vinculo = 'vinculado_cadu'"]
    if _ADOL_12_17.search(blob):
        wheres.append("s.classificacao_faixa_idade = 'adolescente_12_17'")
    if _PBF_CTX.search(blob):
        wheres.append("COALESCE(s.familia_na_folha_pbf, FALSE)")

    where_sql = " AND ".join(wheres)
    count_children = bool(
        re.search(r"criança|crianca|adolesc|pessoas|nis|atendidos", message, re.I)
        or (_ADOL_12_17.search(blob) and re.search(r"quantas|quantos", message, re.I))
    )
    by_cras = _CRAS_BREAKDOWN.search(message) or _CRAS_BREAKDOWN.search(blob)

    if by_cras:
        sql = f"""
            SELECT
              COALESCE(NULLIF(btrim(s.cras_codigo::text), ''), '(sem código)') AS cras_codigo,
              COALESCE(NULLIF(btrim(s.cras_nome::text), ''), '(sem CRAS)') AS cras_nome,
              COUNT(DISTINCT s.nis_norm)::bigint AS atendidos
            FROM vig.mvw_sisc_qualificado s
            WHERE {where_sql}
            GROUP BY 1, 2
            ORDER BY 3 DESC
            LIMIT 30
        """
        rows = conn.execute(text(sql)).mappings().all()
        total = sum(int(r["atendidos"] or 0) for r in rows)
        linhas = [
            f"- **{r['cras_nome']}** ({r['cras_codigo']}): {_fmt_int(int(r['atendidos'] or 0))} atendidos"
            for r in rows[:20]
        ]
        extra = f"\n\n… e mais {len(rows) - 20} unidades." if len(rows) > 20 else ""
        filtros_txt = []
        if _ADOL_12_17.search(blob):
            filtros_txt.append("12–17 anos")
        if _PBF_CTX.search(blob):
            filtros_txt.append("folha PBF")
        ctx = f" ({', '.join(filtros_txt)})" if filtros_txt else ""
        answer = (
            f"**Serviço de Convivência (SISC)** vinculado ao CADU{ctx} — "
            f"**{_fmt_int(total)}** atendidos (NIS distintos) em **{len(rows)}** CRAS/unidades SISC:\n\n"
            + "\n".join(linhas)
            + extra
            + "\n\nCRAS aqui é o da **matrícula SISC** (`s.cras_nome`), não necessariamente o territorial do CADU da família."
        )
        preview = [
            {
                "cras_codigo": r["cras_codigo"],
                "cras_nome": r["cras_nome"],
                "atendidos": int(r["atendidos"] or 0),
            }
            for r in rows
        ]
        return {
            "answer": answer,
            "sql": " ".join(sql.split()),
            "row_count": len(rows),
            "preview": preview,
            "mode": "canonical",
            "metric": "sisc_por_cras",
        }

    if count_children:
        sql = f"""
            SELECT COUNT(DISTINCT s.nis_norm)::bigint AS total
            FROM vig.mvw_sisc_qualificado s
            WHERE {where_sql}
        """
        row = conn.execute(text(sql)).mappings().first()
        n = int((row or {}).get("total") or 0)
        filtros = []
        if _PBF_CTX.search(blob):
            filtros.append("famílias na folha PBF (CADU)")
        if _ADOL_12_17.search(blob):
            filtros.append("faixa etária 12–17 anos")
        ctx = " e ".join(filtros) if filtros else "filtros da conversa"
        answer = (
            f"Há **{_fmt_int(n)}** crianças/adolescentes (**NIS distintos**) no **Serviço de Convivência (SISC)** "
            f"vinculados ao CADU, com {ctx}.\n\n"
            "Fonte: `vig.mvw_sisc_qualificado` (matrícula SISC × NIS × CADU). "
            "Isso não usa o campo CADU `ind_atend_cras` (atendimento CRAS declarado na entrevista)."
        )
        metric = "criancas_sisc"
    else:
        sql = f"""
            SELECT COUNT(DISTINCT s.codigo_familiar)::bigint AS total
            FROM vig.mvw_sisc_qualificado s
            WHERE {where_sql}
              AND s.codigo_familiar IS NOT NULL
        """
        row = conn.execute(text(sql)).mappings().first()
        n = int((row or {}).get("total") or 0)
        answer = (
            f"Há **{_fmt_int(n)}** famílias com pelo menos um integrante no **SISC (Convivência)** "
            f"vinculado ao CADU"
            + (" e na folha PBF" if _PBF_CTX.search(blob) else "")
            + (", com adolescentes 12–17" if _ADOL_12_17.search(blob) else "")
            + "."
        )
        metric = "familias_sisc"

    return {
        "answer": answer,
        "sql": " ".join(sql.split()),
        "row_count": 1,
        "preview": [{"total": n}],
        "mode": "canonical",
        "metric": metric,
    }


def try_canonical_metric(
    conn: Connection,
    message: str,
    transcript: list[dict[str, str]] | None = None,
) -> dict | None:
    """
    Resposta sem LLM/SQL quando a pergunta bate com KPI oficial do painel.
    Retorna dict compatível com chat_turn ou None.
    """
    text_msg = message.strip()
    if not text_msg:
        return None

    sisc = _try_sisc_cross(conn, message, transcript)
    if sisc:
        return sisc

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
