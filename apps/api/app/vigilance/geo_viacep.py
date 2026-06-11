"""Complemento da base geo com CEPs do CADU via API ViaCEP."""

from __future__ import annotations

import re
import time
from dataclasses import dataclass, field

import httpx
from sqlalchemy import text
from sqlalchemy.engine import Connection

from .familia_mview import ensure_vig_functions
from .geo_cras import GEO_TABLE, canonical_bairro_display, lookup_bairro_key, normalize_bairro_key

CADU_TABLE = "cecad__cadu"
VIACEP_URL = "https://viacep.com.br/ws/{cep}/json/"
RIBEIRAO_IBGE = "3543402"


def format_cep_display(cep_norm: str) -> str:
    c = re.sub(r"\D", "", cep_norm or "")
    if len(c) == 8:
        return f"{c[:5]}-{c[5:]}"
    return cep_norm


def title_case_pt(value: str | None) -> str:
    if not value:
        return ""
    return " ".join(part.capitalize() for part in value.strip().split())


@dataclass
class ViaCepAddress:
    cep_norm: str
    cep: str
    endereco: str
    bairro: str
    localidade: str
    uf: str
    ibge: str
    fonte: str = "viacep"


@dataclass
class SupplementResult:
    ceps_analisados: int
    linhas_inseridas: int
    ceps_ja_na_geo: int
    ceps_sem_dados: int
    ceps_fora_municipio: int
    amostra_insercoes: list[dict] = field(default_factory=list)
    erros: list[dict] = field(default_factory=list)
    dry_run: bool = False


def fetch_viacep(cep_norm: str, *, timeout: float = 15.0) -> ViaCepAddress | None:
    cep = re.sub(r"\D", "", cep_norm or "")
    if len(cep) != 8:
        return None
    try:
        with httpx.Client(timeout=timeout) as client:
            resp = client.get(VIACEP_URL.format(cep=cep))
            resp.raise_for_status()
            data = resp.json()
    except (httpx.HTTPError, ValueError):
        return None
    if not isinstance(data, dict) or data.get("erro"):
        return None
    logra = str(data.get("logradouro") or "").strip()
    bairro = str(data.get("bairro") or "").strip()
    if not logra and not bairro:
        return None
    return ViaCepAddress(
        cep_norm=cep,
        cep=format_cep_display(cep),
        endereco=logra,
        bairro=bairro,
        localidade=str(data.get("localidade") or "").strip(),
        uf=str(data.get("uf") or "").strip().upper(),
        ibge=str(data.get("ibge") or "").strip(),
    )


def _qi(ident: str) -> str:
    return '"' + ident.replace('"', '""') + '"'


def _ensure_vig_norm_cep(conn: Connection) -> None:
    conn.execute(text("CREATE SCHEMA IF NOT EXISTS vig"))
    ensure_vig_functions(conn)


def list_missing_ceps_from_cadu(
    conn: Connection,
    *,
    limit: int = 100,
) -> list[dict]:
    _ensure_vig_norm_cep(conn)
    rows = conn.execute(
        text(
            f"""
            WITH fam_base AS (
              SELECT
                t.id,
                vig.norm_familia_cod(t.d_cod_familiar_fam::text) AS cod_fam,
                vig.norm_cep(t.d_num_cep_logradouro_fam::text) AS cep_n,
                NULLIF(btrim(t.d_nom_logradouro_fam::text), '') AS logra_raw,
                NULLIF(btrim(t.d_nom_localidade_fam::text), '') AS bairro_raw
              FROM raw.{_qi(CADU_TABLE)} AS t
              WHERE t.d_cod_familiar_fam IS NOT NULL
                AND btrim(t.d_cod_familiar_fam::text) <> ''
            ),
            fam AS (
              SELECT DISTINCT ON (cod_fam)
                cod_fam, cep_n, logra_raw, bairro_raw
              FROM fam_base
              WHERE cod_fam IS NOT NULL
              ORDER BY cod_fam, id DESC
            ),
            missing AS (
              SELECT
                f.cep_n,
                count(*)::bigint AS familias,
                max(f.logra_raw) AS logra_raw,
                max(f.bairro_raw) AS bairro_raw
              FROM fam f
              LEFT JOIN raw.{_qi(GEO_TABLE)} g ON g.cep_norm = f.cep_n
              WHERE f.cep_n IS NOT NULL
                AND length(f.cep_n) = 8
                AND g.cep_norm IS NULL
              GROUP BY f.cep_n
              ORDER BY count(*) DESC, f.cep_n
              LIMIT :lim
            )
            SELECT cep_n, familias, logra_raw, bairro_raw FROM missing
            """
        ),
        {"lim": limit},
    ).mappings().all()
    return [dict(r) for r in rows]


def _cadu_fallback_for_cep(conn: Connection, cep_norm: str) -> tuple[str, str]:
    row = conn.execute(
        text(
            f"""
            SELECT
              max(NULLIF(btrim(t.d_nom_logradouro_fam::text), '')) AS logra_raw,
              max(NULLIF(btrim(t.d_nom_localidade_fam::text), '')) AS bairro_raw
            FROM raw.{_qi(CADU_TABLE)} AS t
            WHERE vig.norm_cep(t.d_num_cep_logradouro_fam::text) = :cep
            """
        ),
        {"cep": cep_norm},
    ).mappings().first()
    if not row:
        return "", ""
    return str(row["logra_raw"] or ""), str(row["bairro_raw"] or "")


def _infer_cras_for_bairro(conn: Connection, bairro: str) -> str | None:
    key = lookup_bairro_key(normalize_bairro_key(bairro))
    if not key:
        return None
    rows = conn.execute(
        text(
            f"""
            SELECT btrim(bairro::text) AS bairro, btrim(cras::text) AS cras
            FROM raw.{_qi(GEO_TABLE)}
            WHERE cras IS NOT NULL AND btrim(cras::text) <> ''
            """
        )
    ).mappings().all()
    for row in rows:
        row_key = lookup_bairro_key(normalize_bairro_key(str(row["bairro"] or "")))
        if row_key == key:
            return str(row["cras"])
    return None


def _next_geo_id(conn: Connection) -> int:
    return int(
        conn.execute(text(f'SELECT COALESCE(MAX(id), 0) + 1 FROM raw.{_qi(GEO_TABLE)}')).scalar() or 1
    )


def _geo_columns(conn: Connection) -> set[str]:
    rows = conn.execute(
        text(
            """
            SELECT column_name
            FROM information_schema.columns
            WHERE table_schema = 'raw' AND table_name = :t
            """
        ),
        {"t": GEO_TABLE},
    ).all()
    return {r[0] for r in rows}


def _matches_municipio(via: ViaCepAddress, *, ibge: str | None, uf: str | None) -> bool:
    if ibge and via.ibge and via.ibge != ibge:
        return False
    if uf and via.uf and via.uf.upper() != uf.upper():
        return False
    return True


def supplement_geo_from_viacep(
    conn: Connection,
    *,
    dry_run: bool = False,
    limit: int = 50,
    ibge: str | None = RIBEIRAO_IBGE,
    uf: str | None = "SP",
    ceps: list[str] | None = None,
    viacep_delay_s: float = 0.25,
) -> SupplementResult:
    _ensure_vig_norm_cep(conn)
    cols = _geo_columns(conn)
    for required in ("cep_norm", "endereco", "bairro", "cep"):
        if required not in cols:
            raise ValueError(f"Coluna obrigatória ausente em raw.{GEO_TABLE}: {required}")

    if ceps:
        targets = []
        for raw in ceps:
            cep_n = re.sub(r"\D", "", raw or "")
            if len(cep_n) == 8:
                logra, bairro = _cadu_fallback_for_cep(conn, cep_n)
                targets.append({"cep_n": cep_n, "logra_raw": logra, "bairro_raw": bairro, "familias": 0})
    else:
        targets = list_missing_ceps_from_cadu(conn, limit=limit)

    result = SupplementResult(
        ceps_analisados=len(targets),
        linhas_inseridas=0,
        ceps_ja_na_geo=0,
        ceps_sem_dados=0,
        ceps_fora_municipio=0,
        dry_run=dry_run,
    )

    next_id = _next_geo_id(conn) if not dry_run else 0
    inserts: list[dict] = []

    for item in targets:
        cep_n = str(item["cep_n"])
        exists = conn.execute(
            text(f"SELECT 1 FROM raw.{_qi(GEO_TABLE)} WHERE cep_norm = :c LIMIT 1"),
            {"c": cep_n},
        ).scalar()
        if exists:
            result.ceps_ja_na_geo += 1
            continue

        via = fetch_viacep(cep_n)
        if via and not _matches_municipio(via, ibge=ibge, uf=uf):
            result.ceps_fora_municipio += 1
            result.erros.append(
                {
                    "cep_n": cep_n,
                    "motivo": "viacep_fora_municipio",
                    "localidade": via.localidade,
                    "ibge": via.ibge,
                }
            )
            continue

        logra_fb = title_case_pt(str(item.get("logra_raw") or ""))
        bairro_fb = title_case_pt(str(item.get("bairro_raw") or ""))

        if via:
            endereco = via.endereco or logra_fb
            bairro = via.bairro or bairro_fb
            cep_display = via.cep
            fonte = "viacep"
        else:
            if not logra_fb and not bairro_fb:
                result.ceps_sem_dados += 1
                result.erros.append({"cep_n": cep_n, "motivo": "viacep_e_cadu_sem_endereco"})
                continue
            endereco = logra_fb
            bairro = bairro_fb
            cep_display = format_cep_display(cep_n)
            fonte = "cadu_fallback"

        canonical = canonical_bairro_display(normalize_bairro_key(bairro))
        if canonical:
            bairro = canonical

        cras = _infer_cras_for_bairro(conn, bairro)
        row = {
            "id": next_id,
            "endereco": endereco,
            "bairro": bairro,
            "cep": cep_display,
            "cep_norm": cep_n,
            "cras": cras,
            "fonte": fonte,
            "familias_cadu": int(item.get("familias") or 0),
        }
        inserts.append(row)
        if not dry_run:
            next_id += 1
        if viacep_delay_s > 0:
            time.sleep(viacep_delay_s)

    result.amostra_insercoes = inserts[:20]
    result.linhas_inseridas = len(inserts)

    if dry_run or not inserts:
        return result

    has_created = "created_at" in cols
    for ins in inserts:
        fields = ["id", "endereco", "bairro", "cep", "cep_norm"]
        values = [":id", ":endereco", ":bairro", ":cep", ":cep_norm"]
        params: dict = {
            "id": ins["id"],
            "endereco": ins["endereco"],
            "bairro": ins["bairro"],
            "cep": ins["cep"],
            "cep_norm": ins["cep_norm"],
        }
        if "cras" in cols and ins.get("cras"):
            fields.append("cras")
            values.append(":cras")
            params["cras"] = ins["cras"]
        if has_created:
            fields.append("created_at")
            values.append("NOW()")
        sql = (
            f'INSERT INTO raw.{_qi(GEO_TABLE)} ({", ".join(_qi(f) for f in fields)}) '
            f"VALUES ({', '.join(values)})"
        )
        conn.execute(text(sql), params)

    return result
