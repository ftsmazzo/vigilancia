"""Painel SIBEC Manutenções — KPIs a partir de vig.mvw_sibec_manut_familia_mes."""

from __future__ import annotations

import re
from collections import defaultdict

from sqlalchemy import text
from sqlalchemy.engine import Connection

from .familia_mview import PBF_TABLE, _columns, _pick_column, _table_exists, bolsa_folha_kpis_from_raw
from .sibec_manut_mview import latest_manut_competencia

CRAS_MANUT_GRUPOS: tuple[str, ...] = (
    "Cancelar",
    "Bloquear",
    "Suspender",
    "Encerrar",
    "Excluir",
    "Reverter",
    "Desbloquear",
)

PBF_COD_CANDIDATES = (
    "cod_familiar",
    "cod_familiar_fam",
    "d_cod_familiar_fam",
    "codigo_familiar",
)
PBF_REF_CANDIDATES = ("competencia", "ref_folha", "ref_pbf", "inicio_vig_beneficio")


def _qi(ident: str) -> str:
    return '"' + ident.replace('"', '""') + '"'


def _pct(n: int, den: int) -> float:
    if den <= 0:
        return 0.0
    return round((n / den) * 100, 2)


def _mview_ok(conn: Connection) -> bool:
    return bool(conn.execute(text("SELECT to_regclass('vig.mvw_sibec_manut_familia_mes')")).scalar())


def list_sibec_competencias(conn: Connection) -> list[str]:
    if not _mview_ok(conn):
        return []
    rows = conn.execute(
        text(
            """
            SELECT DISTINCT competencia
            FROM vig.mvw_sibec_manut_familia_mes
            WHERE competencia IS NOT NULL AND btrim(competencia) <> ''
            ORDER BY competencia DESC
            """
        )
    ).all()
    return [str(r[0]) for r in rows]


def _folha_familias_competencia(conn: Connection, competencia: str) -> int:
    if not _table_exists(conn, "raw", PBF_TABLE):
        return 0
    cols = _columns(conn, "raw", PBF_TABLE)
    cod_col = _pick_column(cols, PBF_COD_CANDIDATES)
    if not cod_col:
        return 0
    ref_col = _pick_column(cols, PBF_REF_CANDIDATES)
    if "competencia" in cols:
        filt = "btrim(competencia::text) = btrim(:comp)"
    elif ref_col:
        filt = f"btrim(COALESCE({_qi(ref_col)}::text, '')) = btrim(:comp)"
    else:
        bolsa = bolsa_folha_kpis_from_raw(conn)
        return bolsa.total_familias_folha

    sql = f"""
    SELECT COUNT(DISTINCT vig.norm_familia_cod({_qi(cod_col)}::text))::bigint
    FROM raw.{_qi(PBF_TABLE)}
    WHERE {filt}
      AND vig.norm_familia_cod({_qi(cod_col)}::text) IS NOT NULL
    """
    return int(conn.execute(text(sql), {"comp": competencia}).scalar() or 0)


def _prev_competencia(conn: Connection, competencia: str) -> str | None:
    rows = conn.execute(
        text(
            """
            SELECT competencia
            FROM vig.mvw_sibec_manut_familia_mes
            WHERE competencia < :comp
            GROUP BY competencia
            ORDER BY competencia DESC
            LIMIT 1
            """
        ),
        {"comp": competencia},
    ).scalar()
    return str(rows) if rows else None


def _cras_filter_clause(cras_cod: str | None) -> tuple[str, dict]:
    if not cras_cod or cras_cod.strip() in ("", "__todos__"):
        return "TRUE", {}
    c = cras_cod.strip()
    if c == "__sem_cras__":
        return "(tem_territorio IS NOT TRUE)", {}
    return "btrim(COALESCE(num_cras::text, '')) = btrim(:num_cras)", {"num_cras": c}


def _creas_filter_clause(creas_cod: str | None) -> tuple[str, dict]:
    if not creas_cod or creas_cod.strip() in ("", "__todos__"):
        return "TRUE", {}
    c = creas_cod.strip()
    if c == "__sem_creas__":
        return "(num_creas IS NULL OR btrim(num_creas::text) = '')", {}
    return "btrim(COALESCE(num_creas::text, '')) = btrim(:num_creas)", {"num_creas": c}


def _territorio_filter_clause(
    cras_cod: str | None,
    creas_cod: str | None = None,
) -> tuple[str, dict]:
    cras_sql, cras_params = _cras_filter_clause(cras_cod)
    creas_sql, creas_params = _creas_filter_clause(creas_cod)
    parts = [p for p in (cras_sql, creas_sql) if p and p != "TRUE"]
    if not parts:
        return "TRUE", {}
    return " AND ".join(parts), {**cras_params, **creas_params}


def fetch_sibec_painel(
    conn: Connection,
    *,
    competencia: str | None = None,
    cras_cod: str | None = None,
    creas_cod: str | None = None,
) -> dict:
    if not _mview_ok(conn):
        return {
            "disponivel": False,
            "mensagem": "Dados de manutenção ainda não disponíveis. Atualize em Vigilância.",
        }

    comp = (competencia or latest_manut_competencia(conn) or "").strip()
    if not comp:
        return {
            "disponivel": False,
            "mensagem": "Nenhuma competência encontrada na MV SIBEC Manutenções.",
        }

    where_territorio, territorio_params = _territorio_filter_clause(cras_cod, creas_cod)
    params = {"comp": comp, **territorio_params}

    resumo_row = conn.execute(
        text(
            f"""
            SELECT
              COUNT(*)::bigint AS familias_com_evento,
              COUNT(*) FILTER (WHERE tem_territorio)::bigint AS familias_territorializadas,
              COUNT(*) FILTER (WHERE vinculo_cadu)::bigint AS familias_vinculo_cadu,
              COUNT(*) FILTER (WHERE teve_bloqueio)::bigint AS bloqueios,
              COUNT(*) FILTER (WHERE teve_cancelamento)::bigint AS cancelamentos,
              COUNT(*) FILTER (WHERE teve_suspensao)::bigint AS suspensoes,
              COUNT(*) FILTER (WHERE teve_reversao)::bigint AS reversoes,
              COUNT(*) FILTER (WHERE teve_exclusao)::bigint AS exclusoes,
              COUNT(*) FILTER (WHERE teve_desbloqueio)::bigint AS desbloqueios,
              COUNT(*) FILTER (WHERE acao_grupo = 'Cancelar')::bigint AS situacao_cancelar,
              COUNT(*) FILTER (WHERE acao_grupo = 'Bloquear')::bigint AS situacao_bloquear
            FROM vig.mvw_sibec_manut_familia_mes
            WHERE competencia = :comp AND {where_territorio}
            """
        ),
        params,
    ).mappings().first() or {}

    por_grupo_rows = conn.execute(
        text(
            f"""
            SELECT acao_grupo, COUNT(*)::bigint AS n_fam
            FROM vig.mvw_sibec_manut_familia_mes
            WHERE competencia = :comp AND {where_territorio}
            GROUP BY acao_grupo
            ORDER BY n_fam DESC, acao_grupo
            """
        ),
        params,
    ).mappings().all()

    motivo_rows = conn.execute(
        text(
            f"""
            SELECT
              btrim(COALESCE(cod_motivo, '')) AS cod_motivo,
              btrim(COALESCE(motivo_txt, '')) AS motivo_txt,
              COUNT(*)::bigint AS n_fam
            FROM vig.mvw_sibec_manut_familia_mes
            WHERE competencia = :comp
              AND {where_territorio}
              AND teve_cancelamento
              AND btrim(COALESCE(motivo_txt, '')) <> ''
            GROUP BY 1, 2
            ORDER BY n_fam DESC, cod_motivo
            LIMIT 12
            """
        ),
        params,
    ).mappings().all()

    cras_rows = conn.execute(
        text(
            f"""
            SELECT
              btrim(COALESCE(num_cras::text, '')) AS num_cras,
              btrim(COALESCE(nom_cras::text, '')) AS nom_cras,
              acao_grupo,
              COUNT(*)::bigint AS n_fam
            FROM vig.mvw_sibec_manut_familia_mes
            WHERE competencia = :comp
              AND tem_territorio
              AND acao_grupo = ANY(:grupos)
            GROUP BY 1, 2, 3
            ORDER BY num_cras, nom_cras, n_fam DESC
            """
        ),
        {"comp": comp, "grupos": list(CRAS_MANUT_GRUPOS[:5])},
    ).mappings().all()

    por_cras = _aggregate_por_cras(cras_rows)

    folha_n = _folha_familias_competencia(conn, comp)
    n_evento = int(resumo_row.get("familias_com_evento") or 0)

    comp_ant = _prev_competencia(conn, comp)
    comparacao: dict | None = None
    if comp_ant:
        ant = conn.execute(
            text(
                f"""
                SELECT
                  COUNT(*)::bigint AS familias_com_evento,
                  COUNT(*) FILTER (WHERE teve_cancelamento)::bigint AS cancelamentos,
                  COUNT(*) FILTER (WHERE teve_bloqueio)::bigint AS bloqueios,
                  COUNT(*) FILTER (WHERE teve_reversao)::bigint AS reversoes
                FROM vig.mvw_sibec_manut_familia_mes
                WHERE competencia = :comp AND {where_territorio}
                """
            ),
            {"comp": comp_ant, **territorio_params},
        ).mappings().first() or {}
        comparacao = {
            "competencia_anterior": comp_ant,
            "familias_com_evento": int(ant.get("familias_com_evento") or 0),
            "delta_familias_com_evento": n_evento - int(ant.get("familias_com_evento") or 0),
            "delta_cancelamentos": int(resumo_row.get("cancelamentos") or 0)
            - int(ant.get("cancelamentos") or 0),
            "delta_bloqueios": int(resumo_row.get("bloqueios") or 0) - int(ant.get("bloqueios") or 0),
            "delta_reversoes": int(resumo_row.get("reversoes") or 0) - int(ant.get("reversoes") or 0),
        }

    return {
        "disponivel": True,
        "titulo": "SIBEC — Manutenções PBF",
        "competencia": comp,
        "cras_selecionado": cras_cod if cras_cod and cras_cod not in ("", "__todos__") else None,
        "resumo": {
            "familias_com_evento": n_evento,
            "familias_territorializadas": int(resumo_row.get("familias_territorializadas") or 0),
            "familias_vinculo_cadu": int(resumo_row.get("familias_vinculo_cadu") or 0),
            "bloqueios": int(resumo_row.get("bloqueios") or 0),
            "cancelamentos": int(resumo_row.get("cancelamentos") or 0),
            "suspensoes": int(resumo_row.get("suspensoes") or 0),
            "reversoes": int(resumo_row.get("reversoes") or 0),
            "exclusoes": int(resumo_row.get("exclusoes") or 0),
            "desbloqueios": int(resumo_row.get("desbloqueios") or 0),
            "situacao_final_cancelar": int(resumo_row.get("situacao_cancelar") or 0),
            "situacao_final_bloquear": int(resumo_row.get("situacao_bloquear") or 0),
            "familias_folha_pbf": folha_n,
            "pct_evento_sobre_folha": _pct(n_evento, folha_n),
        },
        "comparacao_anterior": comparacao,
        "por_acao_grupo": [
            {
                "grupo": str(r.get("acao_grupo") or ""),
                "familias_distintas": int(r.get("n_fam") or 0),
                "pct_sobre_eventos": _pct(int(r.get("n_fam") or 0), n_evento),
            }
            for r in por_grupo_rows
        ],
        "top_motivos_cancelamento": [
            {
                "cod_motivo": str(r.get("cod_motivo") or ""),
                "motivo": str(r.get("motivo_txt") or ""),
                "familias_distintas": int(r.get("n_fam") or 0),
            }
            for r in motivo_rows
        ],
        "por_cras": por_cras,
    }


def _cras_ordem(num_cras: str, nom_cras: str) -> tuple[int, int, str]:
    """Ordena CRAS 1–12 pelo número no código ou no nome."""
    for raw in (num_cras, nom_cras):
        s = (raw or "").strip()
        if s.isdigit():
            return (0, int(s), s)
        m = re.search(r"(?:CRAS\s*)?(\d+)", s, re.IGNORECASE)
        if m:
            return (0, int(m.group(1)), s)
    return (1, 999, nom_cras or num_cras or "")


def _aggregate_por_cras(rows) -> list[dict]:
    counts: dict[tuple[str, str], dict[str, int]] = defaultdict(dict)
    totals: dict[tuple[str, str], int] = defaultdict(int)
    for r in rows:
        key = (str(r.get("num_cras") or ""), str(r.get("nom_cras") or ""))
        grupo = str(r.get("acao_grupo") or "").strip()
        n = int(r.get("n_fam") or 0)
        counts[key][grupo] = n
        totals[key] += n

    out: list[dict] = []
    for key in sorted(counts.keys(), key=lambda k: _cras_ordem(k[0], k[1])):
        num_cras, nom_cras = key
        tot = totals.get(key, 0)
        grupos_list = []
        for g in CRAS_MANUT_GRUPOS[:5]:
            n = int(counts[key].get(g, 0))
            grupos_list.append(
                {
                    "grupo": g,
                    "familias_distintas": n,
                    "pct_sobre_manut_cras": _pct(n, tot),
                }
            )
        out.append(
            {
                "num_cras": num_cras,
                "nom_cras": nom_cras,
                "familias_com_manutencao": tot,
                "top_grupos": grupos_list,
            }
        )
    return out


def fetch_sibec_serie(
    conn: Connection,
    *,
    de: str | None = None,
    ate: str | None = None,
    cras_cod: str | None = None,
    creas_cod: str | None = None,
) -> dict:
    if not _mview_ok(conn):
        return {"disponivel": False, "items": []}

    where_parts = ["competencia IS NOT NULL"]
    params: dict = {}
    if de:
        where_parts.append("competencia >= :de")
        params["de"] = de.strip()
    if ate:
        where_parts.append("competencia <= :ate")
        params["ate"] = ate.strip()
    where_territorio, territorio_params = _territorio_filter_clause(cras_cod, creas_cod)
    where_parts.append(where_territorio)
    params.update(territorio_params)
    where_sql = " AND ".join(where_parts)

    rows = conn.execute(
        text(
            f"""
            SELECT
              competencia,
              COUNT(*)::bigint AS familias_com_evento,
              COUNT(*) FILTER (WHERE teve_bloqueio)::bigint AS bloqueios,
              COUNT(*) FILTER (WHERE teve_cancelamento)::bigint AS cancelamentos,
              COUNT(*) FILTER (WHERE teve_reversao)::bigint AS reversoes,
              COUNT(*) FILTER (WHERE tem_territorio)::bigint AS territorializadas
            FROM vig.mvw_sibec_manut_familia_mes
            WHERE {where_sql}
            GROUP BY competencia
            ORDER BY competencia
            """
        ),
        params,
    ).mappings().all()

    return {
        "disponivel": True,
        "items": [dict(r) for r in rows],
    }


def manut_kpis_from_mview(conn: Connection, competencia: str) -> dict | None:
    """KPIs compactos para /vigilance/kpis (substitui contagem bruta quando MV existe)."""
    if not _mview_ok(conn):
        return None

    row = conn.execute(
        text(
            """
            SELECT
              COUNT(*)::bigint AS familias_distintas,
              COUNT(*) FILTER (WHERE teve_bloqueio)::bigint AS bloqueios,
              COUNT(*) FILTER (WHERE teve_cancelamento)::bigint AS cancelamentos,
              COUNT(*) FILTER (WHERE teve_suspensao)::bigint AS suspensoes,
              COUNT(*) FILTER (WHERE teve_reversao)::bigint AS reversoes
            FROM vig.mvw_sibec_manut_familia_mes
            WHERE competencia = :comp
            """
        ),
        {"comp": competencia},
    ).mappings().first()
    if not row:
        return None

    por_acao = conn.execute(
        text(
            """
            SELECT acao_grupo AS acao_txt, COUNT(*)::bigint AS n_fam
            FROM vig.mvw_sibec_manut_familia_mes
            WHERE competencia = :comp
            GROUP BY acao_grupo
            ORDER BY n_fam DESC
            """
        ),
        {"comp": competencia},
    ).mappings().all()

    n_fam_tot = int(row.get("familias_distintas") or 0)
    por_acao_out = []
    for r in por_acao:
        n_fam = int(r.get("n_fam") or 0)
        por_acao_out.append(
            {
                "acao": str(r.get("acao_txt") or ""),
                "linhas": n_fam,
                "pct_linhas": _pct(n_fam, n_fam_tot),
                "familias_distintas": n_fam,
                "pct_familias": _pct(n_fam, n_fam_tot),
            }
        )

    por_cras = fetch_sibec_painel(conn, competencia=competencia).get("por_cras", [])

    return {
        "competencia": competencia,
        "total_acoes": n_fam_tot,
        "familias_distintas": n_fam_tot,
        "fonte": "vig.mvw_sibec_manut_familia_mes",
        "grao": "família × competência (nível 00)",
        "por_acao": por_acao_out,
        "por_cras": por_cras,
        "flags": {
            "bloqueios": int(row.get("bloqueios") or 0),
            "cancelamentos": int(row.get("cancelamentos") or 0),
            "suspensoes": int(row.get("suspensoes") or 0),
            "reversoes": int(row.get("reversoes") or 0),
        },
    }
