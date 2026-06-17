"""Métricas canônicas SIBEC Manutenções — vig.mvw_sibec_manut_familia_mes (sem SQL livre)."""

from __future__ import annotations

import re
from typing import Any

from sqlalchemy import text
from sqlalchemy.engine import Connection

from ..vigilance.sibec_manut_mview import latest_manut_competencia
from .cras_breakdown import _fmt_int, _parse_num_cras, sort_cras_rows
from .geo_territorial import _CRAS_NUM

_MANUT = re.compile(
    r"manuten[cç][ãa][oõe]s?|"
    r"bloquead[oa]s?|bloqueio|"
    r"cancelad[oa]s?|cancelamento|"
    r"revers[aã]o|revertid[oa]s?|"
    r"suspen[soa]s?|suspens[aã]o|"
    r"perda\s+do\s+benef[ií]cio|"
    r"saiu\s+do\s+bolsa|"
    r"sa[ií]ram\s+do\s+pbf",
    re.I,
)

_FOLHA_ONLY = re.compile(
    r"folha\s+(?:do\s+)?(?:pbf|bolsa)|"
    r"(?:na\s+)?folha\s+(?:do\s+)?(?:pbf|bolsa)|"
    r"recebe[m]?\s+(?:o\s+)?(?:pbf|bolsa)|"
    r"pagamento\s+do\s+bolsa",
    re.I,
)

_QUANT = re.compile(
    r"quantas?|quantos?|total|n[uú]mero|qtd|conte|liste|mostre",
    re.I,
)

_CRAS_BREAKDOWN = re.compile(
    r"por\s+cras|cada\s+cras|divide|divid|detalh|distribu|desdobr|"
    r"separad\s+por\s+cras|distribu[ií][çc][ãa]o\s+por\s+cras",
    re.I,
)

_FOLLOWUP = re.compile(
    r"^(?:e\s+|e,|e\s+no\s+|e\s+na\s+|e\s+em\s+)|"
    r"\b(?:dessas?|destas?|essas?|delas?|nesse|neste|nesse\s+cras)\b",
    re.I,
)

_COMPARE = re.compile(
    r"maior|menor|compar|rela[cç][ãa]o\s+a|versus|\bvs\.?\b|"
    r"aumentou|diminuiu|subiu|caiu|diferen[cç]a|"
    r"esse\s+n[uú]mero|essa\s+quantidade|esse\s+valor|"
    r"foi\s+mais|foi\s+menos|mais\s+que|menos\s+que",
    re.I,
)

_COMP_FROM_ANSWER = re.compile(r"\*\*([a-z]{3,9}/20\d{4})\*\*", re.I)

_COMP_AAAAMM = re.compile(r"\b(20\d{4})\b")

_YEAR = re.compile(r"\b(20\d{2})\b")

_MESES: dict[str, str] = {
    "janeiro": "01",
    "jan": "01",
    "fevereiro": "02",
    "fev": "02",
    "marco": "03",
    "março": "03",
    "mar": "03",
    "abril": "04",
    "abr": "04",
    "maio": "05",
    "mai": "05",
    "junho": "06",
    "jun": "06",
    "julho": "07",
    "jul": "07",
    "agosto": "08",
    "ago": "08",
    "setembro": "09",
    "set": "09",
    "outubro": "10",
    "out": "10",
    "novembro": "11",
    "nov": "11",
    "dezembro": "12",
    "dez": "12",
}


def _table_exists(conn: Connection, schema: str, name: str) -> bool:
    return bool(
        conn.execute(
            text("SELECT to_regclass(:q) IS NOT NULL"),
            {"q": f"{schema}.{name}"},
        ).scalar()
    )


def _conversation_blob(message: str, transcript: list[dict[str, str]] | None) -> str:
    parts = [m.get("content", "") for m in (transcript or [])]
    parts.append(message)
    return " ".join(parts)


def is_sibec_manut_context(message: str, transcript: list[dict[str, str]] | None = None) -> bool:
    """Pergunta sobre eventos de manutenção PBF (não folha de pagamento)."""
    msg = message.strip()
    if not msg:
        return False
    blob = _conversation_blob(msg, transcript)
    if _COMPARE.search(msg) and _MANUT.search(blob):
        return True
    if not _MANUT.search(msg) and not _MANUT.search(blob):
        return False
    if _FOLHA_ONLY.search(msg) and not _MANUT.search(msg):
        return False
    return True


def _thread_has_sibec_manut(transcript: list[dict[str, str]] | None) -> bool:
    if not transcript:
        return False
    blob = " ".join(m.get("content", "") for m in transcript)
    return bool(_MANUT.search(blob))


def _comp_label_to_aaaamm(label: str) -> str | None:
    """Converte 'maio/2026' → '202605'."""
    m = re.match(r"([a-záéíóúãõ]+)/(\d{4})", label.strip().lower())
    if not m:
        return None
    mes_nome, ano = m.group(1), m.group(2)
    mes_nome = mes_nome.replace("ç", "c")
    for nome, mm in _MESES.items():
        if nome.replace("ç", "c") == mes_nome or nome == mes_nome:
            return f"{ano}{mm}"
    return None


def _parse_cras_session(message: str, transcript: list[dict[str, str]] | None) -> str | None:
    """CRAS da pergunta atual ou do contexto recente (comparações e follow-ups)."""
    hit = _cras_from_text(message)
    if hit is not None:
        return hit
    for msg in reversed(transcript or []):
        hit = _cras_from_text(msg.get("content", ""))
        if hit is not None:
            return hit
    return None


def _parse_competencia_atual(
    message: str,
    transcript: list[dict[str, str]] | None,
    conn: Connection,
    *,
    exclude: str | None = None,
) -> str | None:
    """Competência principal do fio (período que o usuário estava analisando)."""
    for msg in reversed(transcript or []):
        if msg.get("role") == "assistant":
            for m in _COMP_FROM_ANSWER.finditer(msg.get("content", "")):
                comp = _comp_label_to_aaaamm(m.group(1))
                if comp and comp != exclude:
                    return comp
        if msg.get("role") == "user":
            hit = _competencia_from_text(msg.get("content", ""))
            if hit and hit != exclude:
                return hit
    hit = _competencia_from_text(message)
    if hit and hit != exclude:
        return hit
    latest = latest_manut_competencia(conn)
    if latest and latest != exclude:
        return latest
    return None


def _competencia_disponivel(conn: Connection, competencia: str) -> bool:
    row = conn.execute(
        text(
            """
            SELECT 1 FROM vig.mvw_sibec_manut_familia_mes
            WHERE competencia = :comp
            LIMIT 1
            """
        ),
        {"comp": competencia},
    ).scalar()
    return bool(row)


def _count_manut(
    conn: Connection,
    *,
    competencia: str,
    flag_col: str | None,
    cras_num: str | None,
    motivo_sql: str,
    motivo_params: dict,
) -> int:
    flag_filter = f"AND {flag_col}" if flag_col else ""
    cras_sql, cras_params = _cras_sql_filter(cras_num)
    sql = f"""
        SELECT COUNT(*)::bigint AS n
        FROM vig.mvw_sibec_manut_familia_mes
        WHERE competencia = :comp
          {flag_filter}
          AND {motivo_sql}
          AND {cras_sql}
    """
    params: dict[str, Any] = {"comp": competencia, **cras_params, **motivo_params}
    return int(conn.execute(text(sql), params).scalar() or 0)


def _try_sibec_compare(
    conn: Connection,
    message: str,
    transcript: list[dict[str, str]] | None,
    *,
    user_first_name: str = "",
) -> dict | None:
    if not _COMPARE.search(message) or not _thread_has_sibec_manut(transcript):
        return None

    comp_b = _competencia_from_text(message)
    if not comp_b:
        return None

    comp_a = _parse_competencia_atual(message, transcript, conn, exclude=comp_b)
    if not comp_a:
        return None

    flag_col, acao_label = _parse_action(message, transcript)
    cras_num = _parse_cras_session(message, transcript)
    motivo_sql, motivo_params = _motivo_filter(message)
    who = f"{user_first_name}, " if user_first_name else ""

    label_a = _fmt_competencia(comp_a)
    label_b = _fmt_competencia(comp_b)
    cras_txt = f" no **CRAS {cras_num}**" if cras_num else ""

    if not _competencia_disponivel(conn, comp_b):
        return {
            "answer": (
                f"{who}não há dados de manutenção para **{label_b}** na base. "
                f"Ingeste essa competência em **Ingestão** e atualize a visão SIBEC em **Vigilância**."
            ),
            "sql": None,
            "row_count": 0,
            "preview": [],
            "mode": "canonical",
            "metric": "sibec_manut_compare_sem_mes",
        }

    n_a = _count_manut(
        conn,
        competencia=comp_a,
        flag_col=flag_col,
        cras_num=cras_num,
        motivo_sql=motivo_sql,
        motivo_params=motivo_params,
    )
    n_b = _count_manut(
        conn,
        competencia=comp_b,
        flag_col=flag_col,
        cras_num=cras_num,
        motivo_sql=motivo_sql,
        motivo_params=motivo_params,
    )
    diff = n_a - n_b

    if diff > 0:
        compara = (
            f"**Sim.** Em **{label_a}** houve **{_fmt_int(n_a)}** famílias com **{acao_label}**{cras_txt}, "
            f"contra **{_fmt_int(n_b)}** em **{label_b}** — **{_fmt_int(diff)} a mais**."
        )
    elif diff < 0:
        compara = (
            f"**Não.** Em **{label_a}** houve **{_fmt_int(n_a)}** famílias com **{acao_label}**{cras_txt}, "
            f"**{_fmt_int(abs(diff))} a menos** que as **{_fmt_int(n_b)}** de **{label_b}**."
        )
    else:
        compara = (
            f"**Empate.** Em **{label_a}** e **{label_b}** o total foi o mesmo: "
            f"**{_fmt_int(n_a)}** famílias com **{acao_label}**{cras_txt}."
        )

    return {
        "answer": f"{who}{compara}",
        "sql": None,
        "row_count": 2,
        "preview": [
            {"competencia": comp_a, "familias": n_a},
            {"competencia": comp_b, "familias": n_b},
        ],
        "mode": "canonical",
        "metric": "sibec_manut_compare",
    }


def _fmt_competencia(comp: str) -> str:
    if len(comp) != 6:
        return comp
    mm = comp[4:6]
    ano = comp[0:4]
    inv = {v: k for k, v in _MESES.items() if len(k) > 3}
    nome = inv.get(mm, mm)
    return f"{nome}/{ano}"


def _cras_from_text(text: str) -> str | None:
    """Extrai número do CRAS só do texto informado (não do histórico)."""
    if not text or not text.strip():
        return None
    m = _CRAS_NUM.search(text)
    if m:
        raw = m.group(1)
        return raw.lstrip("0") or raw
    m2 = re.search(r"\bcras\s*(\d{1,2})\b", text, re.I)
    if m2:
        raw = m2.group(1)
        return raw.lstrip("0") or raw
    return None


def _competencia_from_text(text: str) -> str | None:
    if not text or not text.strip():
        return None
    m = _COMP_AAAAMM.search(text)
    if m:
        return m.group(1)
    low = text.lower().replace("ç", "c")
    for nome, mm in sorted(_MESES.items(), key=lambda x: -len(x[0])):
        token = nome.replace("ç", "c")
        if re.search(rf"\b{re.escape(token)}\b", low):
            ym = _COMP_AAAAMM.search(text) or _YEAR.search(text)
            if ym:
                year = ym.group(1)[:4]
                return f"{year}{mm}"
    return None


def _action_from_text(text: str) -> tuple[str | None, str]:
    msg = text.lower()
    if re.search(r"cancel", msg):
        return "teve_cancelamento", "cancelamento"
    if re.search(r"bloque", msg):
        return "teve_bloqueio", "bloqueio"
    if re.search(r"revers", msg):
        return "teve_reversao", "reversão"
    if re.search(r"suspen", msg):
        return "teve_suspensao", "suspensão"
    if re.search(r"exclu", msg):
        return "teve_exclusao", "exclusão"
    return None, "manutenção"


def _parse_competencia(message: str, transcript: list[dict[str, str]] | None, conn: Connection) -> str | None:
    hit = _competencia_from_text(message)
    if hit:
        return hit
    for msg in reversed(transcript or []):
        if msg.get("role") != "user":
            continue
        hit = _competencia_from_text(msg.get("content", ""))
        if hit:
            return hit
    return latest_manut_competencia(conn)


def _parse_action(message: str, transcript: list[dict[str, str]] | None = None) -> tuple[str | None, str]:
    flag, label = _action_from_text(message)
    if flag:
        return flag, label
    if _FOLLOWUP.search(message.strip()) or _COMPARE.search(message):
        for msg in reversed(transcript or []):
            content = msg.get("content", "")
            flag, label = _action_from_text(content)
            if flag:
                return flag, label
    return None, "manutenção"


def _parse_cras_num(message: str, transcript: list[dict[str, str]] | None) -> str | None:
    """CRAS citado na pergunta atual; não reutiliza CRAS de turnos anteriores."""
    hit = _cras_from_text(message)
    if hit is not None:
        return hit
    return None


def _motivo_filter(message: str) -> tuple[str, dict]:
    msg = message.lower()
    if "revis" in msg and "cadastr" in msg:
        return (
            "(motivo_txt ILIKE '%REVISAO CADASTRAL%' OR cod_motivo IN ('1052', '1053'))",
            {},
        )
    if "renda" in msg and ("limite" in msg or "acima" in msg or "superior" in msg):
        return (
            "(motivo_txt ILIKE '%RENDA FAMILIAR%' OR cod_motivo IN ('1005', '1055'))",
            {},
        )
    if "permanencia" in msg or "permanência" in msg or "tempo" in msg:
        return ("(motivo_txt ILIKE '%PERMANENCIA%' OR cod_motivo = '1027')", {})
    return ("TRUE", {})


def _cras_sql_filter(num_cras: str | None) -> tuple[str, dict]:
    if not num_cras:
        return "TRUE", {}
    return (
        "NULLIF(regexp_replace(btrim(COALESCE(num_cras::text, '')), '[^0-9]', '', 'g'), '')"
        "::int = :num_cras_int",
        {"num_cras_int": int(num_cras)},
    )


def _format_cras_list(rows: list[dict[str, Any]], *, acao_label: str, comp_label: str) -> str:
    sorted_rows = sort_cras_rows(rows)
    lines: list[str] = []
    sem_ref = 0
    for row in sorted_rows:
        total = int(row.get("total_familias") or 0)
        num = _parse_num_cras(row.get("num_cras"))
        nome = str(row.get("nom_cras") or "").strip()
        if num is None:
            sem_ref = total
            continue
        label = f"CRAS {num}"
        if nome:
            short = nome.replace("AREA DO CRAS ", "").replace("AREA DO ", "")
            label = f"{label} — {short}"
        lines.append(f"- {label}: **{_fmt_int(total)}** famílias")
    body = "\n".join(lines)
    if sem_ref:
        body += f"\n- Sem referência de CRAS: **{_fmt_int(sem_ref)}** famílias"
    return (
        f"Famílias com **{acao_label}** em **{comp_label}**, por CRAS:\n\n{body}"
        if body
        else f"Nenhum registro de **{acao_label}** em **{comp_label}** por CRAS."
    )


def try_sibec_manut_metric(
    conn: Connection,
    message: str,
    transcript: list[dict[str, str]] | None = None,
    *,
    user_first_name: str = "",
) -> dict | None:
    if not is_sibec_manut_context(message, transcript):
        return None

    if not _table_exists(conn, "vig", "mvw_sibec_manut_familia_mes"):
        return {
            "answer": (
                "Ainda não há dados consolidados de manutenção do Bolsa Família. "
                "Atualize em **Vigilância** → **SIBEC Manutenções**."
            ),
            "sql": None,
            "row_count": 0,
            "preview": [],
            "mode": "canonical",
            "metric": "sibec_manut_indisponivel",
        }

    compare = _try_sibec_compare(conn, message, transcript, user_first_name=user_first_name)
    if compare:
        return compare

    is_followup = bool(_FOLLOWUP.search(message.strip()))
    is_compare = bool(_COMPARE.search(message))
    if (
        not _QUANT.search(message)
        and not _CRAS_BREAKDOWN.search(message)
        and not is_followup
        and not is_compare
        and _cras_from_text(message) is None
    ):
        return None

    competencia = _parse_competencia(message, transcript, conn)
    if not competencia:
        return {
            "answer": (
                "Não encontrei competência de manutenção ingerida. "
                "Importe o analítico SIBEC e gere a visão em Vigilância."
            ),
            "sql": None,
            "row_count": 0,
            "preview": [],
            "mode": "canonical",
            "metric": "sibec_manut_sem_competencia",
        }

    flag_col, acao_label = _parse_action(message, transcript)
    cras_num = _parse_cras_num(message, transcript)
    if cras_num is None and (is_followup or is_compare):
        cras_num = _parse_cras_session(message, transcript)
    motivo_sql, motivo_params = _motivo_filter(message)
    cras_sql, cras_params = _cras_sql_filter(cras_num)
    comp_label = _fmt_competencia(competencia)

    flag_filter = f"AND {flag_col}" if flag_col else ""
    who = f"{user_first_name}, " if user_first_name else ""

    params: dict[str, Any] = {"comp": competencia, **cras_params, **motivo_params}

    if _CRAS_BREAKDOWN.search(message):
        sql = f"""
            SELECT
              btrim(COALESCE(num_cras::text, '')) AS num_cras,
              btrim(COALESCE(nom_cras::text, '')) AS nom_cras,
              COUNT(*)::bigint AS total_familias
            FROM vig.mvw_sibec_manut_familia_mes
            WHERE competencia = :comp
              {flag_filter}
              AND {motivo_sql}
            GROUP BY num_cras, nom_cras
        """
        rows = [dict(r) for r in conn.execute(text(sql), params).mappings().all()]
        if not rows:
            answer = f"{who}não há famílias com **{acao_label}** em **{comp_label}**."
        else:
            answer = f"{who}{_format_cras_list(rows, acao_label=acao_label, comp_label=comp_label)}"
        return {
            "answer": answer,
            "sql": " ".join(sql.split()),
            "row_count": len(rows),
            "preview": sort_cras_rows(rows),
            "mode": "canonical",
            "metric": "sibec_manut_por_cras",
        }

    sql = f"""
        SELECT COUNT(*)::bigint AS n
        FROM vig.mvw_sibec_manut_familia_mes
        WHERE competencia = :comp
          {flag_filter}
          AND {motivo_sql}
          AND {cras_sql}
    """
    n = _count_manut(
        conn,
        competencia=competencia,
        flag_col=flag_col,
        cras_num=cras_num,
        motivo_sql=motivo_sql,
        motivo_params=motivo_params,
    )

    cras_txt = ""
    if cras_num:
        cras_txt = f" no **CRAS {cras_num}**"

    motivo_txt = ""
    if motivo_sql != "TRUE":
        if "REVISAO CADASTRAL" in motivo_sql:
            motivo_txt = " por **revisão cadastral**"
        elif "RENDA FAMILIAR" in motivo_sql:
            motivo_txt = " por **renda acima do limite**"
        elif "PERMANENCIA" in motivo_sql:
            motivo_txt = " por **tempo de permanência**"

    if flag_col:
        answer = (
            f"{who}em **{comp_label}**, há **{_fmt_int(n)}** famílias com "
            f"**{acao_label}**{motivo_txt}{cras_txt}."
        )
    else:
        answer = (
            f"{who}em **{comp_label}**, há **{_fmt_int(n)}** famílias com "
            f"**manutenção** registrada{cras_txt}."
        )

    return {
        "answer": answer,
        "sql": " ".join(sql.split()),
        "row_count": 1,
        "preview": [
            {
                "competencia": competencia,
                "familias": n,
                "acao": acao_label,
                "cras": cras_num,
            }
        ],
        "mode": "canonical",
        "metric": "sibec_manut_total",
    }
