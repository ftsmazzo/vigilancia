"""Cruzamento endereço CADU × base geográfica local (ex.: tbl_geo Ribeirão)."""

from __future__ import annotations

from typing import Any

from fastapi import APIRouter, Depends, File, HTTPException, Query, UploadFile, status
from pydantic import BaseModel, Field
from sqlalchemy import text
from sqlalchemy.orm import Session

from ..db import get_db
from ..deps import get_current_user
from ..models import User
from ..vigilance.familia_mview import ensure_vig_functions
from ..vigilance.geo_cras import apply_cras_bairros_to_geo, parse_bairros_cras_csv

router = APIRouter(prefix="/geo", tags=["geo"])

CADU_TABLE = "cecad__cadu"
GEO_TABLE = "geo__tbl_geo"


@router.post("/apply-cras-bairros")
async def geo_apply_cras_bairros(
    file: UploadFile = File(..., description="Matriz bairros_cras.csv (delimitador ;)"),
    dry_run: bool = Query(False, description="Se true, só simula sem gravar cras na tbl_geo"),
    db: Session = Depends(get_db),
    _: User = Depends(get_current_user),
):
    """
    Preenche `cras` em raw.geo__tbl_geo cruzando **bairro** com a matriz municipal.

    O arquivo `bairros_cras.csv` tem colunas CRAS 1…12 (cabeçalho + linhas de bairros).
    Células com vários bairros (separados por ; ou ,) são expandidas.

    Duplicatas: se o bairro aparece em CRAS 1–7 e 8–12, prevalece o CRAS 8–12 (redistribuição
    territorial recente). Abreviações (Jd, Cond, Vl, etc.) são normalizadas no cruzamento.

    **Rua/endereço não entra neste cruzamento** — só o campo `bairro` da tbl_geo.
    """
    if not _raw_table_exists(db, GEO_TABLE):
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=(
                "Tabela raw.geo__tbl_geo não encontrada. "
                "Envie tbl_geo.csv em Ingestão → Geo antes."
            ),
        )

    content = await file.read()
    if not content:
        raise HTTPException(status_code=400, detail="Arquivo vazio.")

    try:
        mapping, conflicts = parse_bairros_cras_csv(content)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc

    with db.bind.begin() as conn:
        result = apply_cras_bairros_to_geo(
            conn,
            bairro_to_cras=mapping,
            conflicts=conflicts,
            dry_run=dry_run,
        )

    return {
        "status": "preview" if dry_run else "success",
        "metodo": "bairro",
        "nota_rua": (
            "Endereço/rua da tbl_geo não foi usado. "
            "Se precisar de cruzamento por logradouro, avise para evoluirmos depois."
        ),
        "regra_duplicata": (
            "Bairro em CRAS antigo (1–7) e novo (8–12): mantém 8–12. "
            "Abreviações Jd/Cond/Vl/Pq/Conj expandidas na comparação."
        ),
        "bairros_no_mapa": result.bairros_no_mapa,
        "linhas_geo_atualizadas": result.linhas_geo_atualizadas,
        "linhas_geo_bairro_renomeadas": result.linhas_geo_bairro_renomeadas,
        "linhas_geo_ja_com_cras": result.linhas_geo_ja_com_cras,
        "linhas_sem_bairro": result.linhas_sem_bairro,
        "linhas_geo_com_bairro": result.linhas_geo_total,
        "bairros_geo_sem_match": result.bairros_geo_sem_match,
        "conflitos_bairro": result.conflitos_bairro,
        "amostra_atualizacoes": result.amostra_atualizacoes,
        "amostra_renomes_bairro": result.amostra_renomes_bairro,
    }


def _geo_fam_pipeline_ctes() -> str:
    """fam_base → fam_sim (reutilizado no relatório e no cruzamento 'outro CEP')."""
    return f"""
        fam_base AS (
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
        geo_cep_counts AS (
          SELECT cep_norm, count(*)::bigint AS n
          FROM raw.{_qi(GEO_TABLE)}
          GROUP BY cep_norm
        ),
        fam_enriched AS (
          SELECT f.cod_fam, f.cep_n, f.logra_raw, f.bairro_raw, COALESCE(c.n, 0::bigint) AS n_geo_por_cep
          FROM fam f
          LEFT JOIN geo_cep_counts c ON c.cep_norm = f.cep_n
        ),
        fam_sim AS (
          SELECT
            fe.*,
            (
              SELECT max(
                (
                  similarity(
                    lower(coalesce(fe.logra_raw, '')),
                    lower(coalesce(btrim(g.endereco::text), ''))
                  )
                  + similarity(
                    lower(coalesce(fe.bairro_raw, '')),
                    lower(coalesce(btrim(g.bairro::text), ''))
                  )
                ) / 2.0
              )
              FROM raw.{_qi(GEO_TABLE)} g
              WHERE fe.cep_n IS NOT NULL
                AND g.cep_norm = fe.cep_n
            ) AS sim_mesmo_cep
          FROM fam_enriched fe
        )"""


def _cte_fam_alvo_outro_cep_amostra() -> str:
    return """
        fam_alvo AS (
          SELECT *
          FROM fam_sim
          WHERE cep_n IS NOT NULL
            AND (logra_raw IS NOT NULL OR bairro_raw IS NOT NULL)
            AND (
              n_geo_por_cep = 0
              OR (n_geo_por_cep >= 1 AND sim_mesmo_cep IS NOT NULL AND sim_mesmo_cep < :sim_media)
            )
          ORDER BY random()
          LIMIT :amostra_pool
        )"""


def _cte_fam_alvo_outro_cep_todas() -> str:
    return """
        fam_alvo AS (
          SELECT *
          FROM fam_sim
          WHERE cep_n IS NOT NULL
            AND (logra_raw IS NOT NULL OR bairro_raw IS NOT NULL)
            AND (
              n_geo_por_cep = 0
              OR (n_geo_por_cep >= 1 AND sim_mesmo_cep IS NOT NULL AND sim_mesmo_cep < :sim_media)
            )
        )"""


def _cte_pares_melhor_outro_cep() -> str:
    return f"""
        pares AS (
          SELECT
            fa.cod_fam,
            fa.cep_n AS cep_cadu,
            fa.logra_raw,
            fa.bairro_raw,
            fa.n_geo_por_cep,
            fa.sim_mesmo_cep,
            g.cep_norm AS cep_candidato,
            btrim(g.endereco::text) AS endereco_ref,
            btrim(g.bairro::text) AS bairro_ref,
            (
              similarity(
                lower(coalesce(fa.logra_raw, '')),
                lower(coalesce(btrim(g.endereco::text), ''))
              )
              + similarity(
                lower(coalesce(fa.bairro_raw, '')),
                lower(coalesce(btrim(g.bairro::text), ''))
              )
            ) / 2.0 AS sim_outro_cep
          FROM fam_alvo fa
          INNER JOIN raw.{_qi(GEO_TABLE)} g
            ON g.cep_norm IS DISTINCT FROM fa.cep_n
        ),
        melhor AS (
          SELECT DISTINCT ON (cod_fam)
            cod_fam,
            cep_cadu,
            logra_raw,
            bairro_raw,
            n_geo_por_cep,
            sim_mesmo_cep,
            cep_candidato,
            endereco_ref,
            bairro_ref,
            sim_outro_cep
          FROM pares
          ORDER BY cod_fam, sim_outro_cep DESC
        )"""


def _qi(ident: str) -> str:
    return '"' + ident.replace('"', '""') + '"'


def _raw_table_exists(db: Session, table_name: str) -> bool:
    r = db.execute(
        text(
            """
            SELECT 1
            FROM information_schema.tables
            WHERE table_schema = 'raw' AND table_name = :t
            """
        ),
        {"t": table_name},
    ).scalar()
    return r is not None


def _geo_columns(db: Session) -> set[str]:
    rows = db.execute(
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


def _cadu_columns(db: Session) -> set[str]:
    rows = db.execute(
        text(
            """
            SELECT column_name
            FROM information_schema.columns
            WHERE table_schema = 'raw' AND table_name = :t
            """
        ),
        {"t": CADU_TABLE},
    ).all()
    return {r[0] for r in rows}


def _ensure_vig_and_trgm(db: Session) -> bool:
    """Garante schema vig, funções CADU e tenta pg_trgm (similaridade de texto)."""
    with db.bind.begin() as conn:
        conn.execute(text("CREATE SCHEMA IF NOT EXISTS vig"))
        ensure_vig_functions(conn)

    try:
        with db.bind.begin() as conn:
            conn.execute(text("CREATE EXTENSION IF NOT EXISTS pg_trgm"))
        return True
    except Exception:
        with db.bind.begin() as conn:
            return bool(
                conn.execute(
                    text("SELECT EXISTS (SELECT 1 FROM pg_extension WHERE extname = 'pg_trgm')")
                ).scalar()
            )


def _fmt_pt_threshold(x: float) -> str:
    """Dois decimais com vírgula (texto para metodologia)."""
    return f"{x:.2f}".replace(".", ",")


def _serialize_row(r: dict[str, Any]) -> dict[str, Any]:
    out: dict[str, Any] = {}
    for k, v in r.items():
        if hasattr(v, "hex") and hasattr(v, "as_tuple"):
            out[k] = float(v)
        else:
            out[k] = v
    return out


class CepCorrecaoItem(BaseModel):
    cod_fam: str = Field(..., min_length=1, max_length=64)
    cep_candidato: str = Field(..., min_length=1, max_length=32)


class ApplyCepCorrecoesBody(BaseModel):
    """Atualiza `d_num_cep_logradouro_fam` no CADU RAW para todas as linhas de cada código familiar."""

    updates: list[CepCorrecaoItem] = Field(..., min_length=1, max_length=50_000)


class BulkOutroCepBody(BaseModel):
    """Cruzamento completo no servidor (todas as famílias elegíveis): prévia ou gravação em uma única transação."""

    sim_media_min: float = Field(0.35, ge=0.0, le=1.0)
    sim_outro_cep_min: float = Field(0.6, ge=0.0, le=1.0)
    dry_run: bool = Field(True, description="Se true, só contagem; se false, aplica UPDATE no CADU RAW.")


@router.post("/apply-cep-suggestions")
def geo_apply_cep_suggestions(
    body: ApplyCepCorrecoesBody,
    db: Session = Depends(get_db),
    _: User = Depends(get_current_user),
):
    """
    Aplica CEPs candidatos (ex.: da amostra `amostra_suspeita_cep_errado_outro_cep_mais_parecido`) na tabela
    `raw.cecad__cadu`: todas as linhas cuja família normalizada coincide com `cod_fam`.

    Exige que cada `cep_candidato` normalizado exista em pelo menos uma linha de `raw.geo__tbl_geo` (`cep_norm`).
    """
    if not _raw_table_exists(db, CADU_TABLE):
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Tabela raw.cecad__cadu não encontrada. Ingeste o CADU antes.",
        )
    if not _raw_table_exists(db, GEO_TABLE):
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Tabela raw.geo__tbl_geo não encontrada.",
        )

    cadu_cols = _cadu_columns(db)
    if "d_cod_familiar_fam" not in cadu_cols or "d_num_cep_logradouro_fam" not in cadu_cols:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="CADU RAW sem colunas d_cod_familiar_fam ou d_num_cep_logradouro_fam.",
        )
    if "cep_norm" not in _geo_columns(db):
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Geo RAW sem coluna cep_norm.",
        )

    db.execute(text("CREATE SCHEMA IF NOT EXISTS vig"))
    ensure_vig_functions(db.connection())

    # Último par vence se houver cod_fam repetido no payload
    merged: dict[str, str] = {}
    for item in body.updates:
        cod_raw = item.cod_fam.strip()
        cep_raw = item.cep_candidato.strip()
        cod_n = db.scalar(text("SELECT vig.norm_familia_cod(:t)"), {"t": cod_raw})
        cep_n = db.scalar(text("SELECT vig.norm_cep(:t)"), {"t": cep_raw})
        if not cod_n:
            raise HTTPException(
                status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
                detail=f"Código de família inválido após normalização: {item.cod_fam!r}",
            )
        if not cep_n:
            raise HTTPException(
                status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
                detail=f"CEP candidato inválido após normalização: {item.cep_candidato!r}",
            )
        exists_geo = db.scalar(
            text(f"SELECT 1 FROM raw.{_qi(GEO_TABLE)} WHERE cep_norm = :c LIMIT 1"),
            {"c": cep_n},
        )
        if not exists_geo:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail=f"CEP {cep_n} não existe em raw.{GEO_TABLE} (cep_norm). Confira a base geo.",
            )
        merged[cod_n] = cep_n

    db.execute(
        text(
            "CREATE TEMP TABLE _vig_cep_pairs (cod_fam text NOT NULL, cep_new text NOT NULL) "
            "ON COMMIT DROP"
        )
    )
    for cod_n, cep_n in merged.items():
        db.execute(
            text("INSERT INTO _vig_cep_pairs (cod_fam, cep_new) VALUES (:c, :e)"),
            {"c": cod_n, "e": cep_n},
        )
    res = db.execute(
        text(
            f"""
            UPDATE raw.{_qi(CADU_TABLE)} AS c
            SET d_num_cep_logradouro_fam = p.cep_new
            FROM _vig_cep_pairs AS p
            WHERE vig.norm_familia_cod(c.d_cod_familiar_fam::text) = p.cod_fam
            """
        )
    )
    linhas = res.rowcount or 0
    db.commit()

    cods_list = list(merged.keys())
    return {
        "familias_unicas_atualizadas": len(cods_list),
        "linhas_cadu_atualizadas": linhas,
        "pares": [{"cod_fam": c, "cep_aplicado": merged[c]} for c in cods_list],
    }


def _geo_require_trgm(db: Session) -> None:
    if not _ensure_vig_and_trgm(db):
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="pg_trgm é obrigatório para esta operação. Execute CREATE EXTENSION pg_trgm;",
        )


@router.post("/bulk-apply-outro-cep")
def geo_bulk_apply_outro_cep(
    body: BulkOutroCepBody,
    db: Session = Depends(get_db),
    _: User = Depends(get_current_user),
):
    """
    Todas as famílias elegíveis (CEP ausente na geo ou similaridade baixa no mesmo CEP): melhor linha em
    **outro** CEP na tbl_geo. Com `dry_run=true`, devolve só contagens; com `dry_run=false`, um único
    UPDATE no CADU RAW (pode demorar minutos em bases grandes).
    """
    if body.sim_media_min >= 1.0:
        raise HTTPException(status_code=422, detail="sim_media_min deve ser < 1.")
    if not _raw_table_exists(db, CADU_TABLE):
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Tabela raw.cecad__cadu não encontrada.",
        )
    if not _raw_table_exists(db, GEO_TABLE):
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Tabela raw.geo__tbl_geo não encontrada.",
        )
    gcols = _geo_columns(db)
    for required in ("cep_norm", "endereco", "bairro"):
        if required not in gcols:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail=f"Coluna obrigatória ausente em raw.{GEO_TABLE}: {required}",
            )
    cadu_cols = _cadu_columns(db)
    if "d_cod_familiar_fam" not in cadu_cols or "d_num_cep_logradouro_fam" not in cadu_cols:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="CADU RAW sem d_cod_familiar_fam ou d_num_cep_logradouro_fam.",
        )

    _geo_require_trgm(db)
    db.execute(text("CREATE SCHEMA IF NOT EXISTS vig"))
    ensure_vig_functions(db.connection())
    db.execute(text("SET LOCAL statement_timeout TO '0'"))

    pipeline_head = f"""WITH {_geo_fam_pipeline_ctes()},
        {_cte_fam_alvo_outro_cep_todas()},
        {_cte_pares_melhor_outro_cep()}"""

    params = {"sim_media": body.sim_media_min, "sim_outro_cep_min": body.sim_outro_cep_min}

    if body.dry_run:
        sql_preview = f"""
        {pipeline_head},
        aplica AS (
          SELECT cod_fam
          FROM melhor
          WHERE sim_outro_cep >= :sim_outro_cep_min
        )
        SELECT
          (SELECT count(*)::bigint FROM aplica) AS familias_com_candidato,
          (
            SELECT count(*)::bigint
            FROM raw.{_qi(CADU_TABLE)} AS c
            INNER JOIN aplica AS a ON vig.norm_familia_cod(c.d_cod_familiar_fam::text) = a.cod_fam
          ) AS linhas_cadu_que_seriam_atualizadas
        """
        prev = db.execute(text(sql_preview), params).mappings().first()
        db.commit()
        return {
            "dry_run": True,
            "familias_com_candidato": int(prev["familias_com_candidato"] or 0) if prev else 0,
            "linhas_cadu_que_seriam_atualizadas": int(prev["linhas_cadu_que_seriam_atualizadas"] or 0)
            if prev
            else 0,
            "sim_media_min": body.sim_media_min,
            "sim_outro_cep_min": body.sim_outro_cep_min,
        }

    sql_apply = f"""
    {pipeline_head},
    aplica AS (
      SELECT cod_fam, cep_candidato
      FROM melhor
      WHERE sim_outro_cep >= :sim_outro_cep_min
    ),
    exec_upd AS (
      UPDATE raw.{_qi(CADU_TABLE)} AS c
      SET d_num_cep_logradouro_fam = a.cep_candidato
      FROM aplica AS a
      WHERE vig.norm_familia_cod(c.d_cod_familiar_fam::text) = a.cod_fam
      RETURNING c.id
    )
    SELECT
      (SELECT count(*)::bigint FROM aplica) AS familias_com_candidato,
      (SELECT count(*)::bigint FROM exec_upd) AS linhas_cadu_atualizadas
    """
    row = db.execute(text(sql_apply), params).mappings().first()
    db.commit()
    return {
        "dry_run": False,
        "familias_com_candidato": int(row["familias_com_candidato"] or 0) if row else 0,
        "linhas_cadu_atualizadas": int(row["linhas_cadu_atualizadas"] or 0) if row else 0,
        "sim_media_min": body.sim_media_min,
        "sim_outro_cep_min": body.sim_outro_cep_min,
    }


@router.get("/match-report")
def geo_cep_match_report(
    db: Session = Depends(get_db),
    _: User = Depends(get_current_user),
    sim_alta_min: float = Query(
        0.65,
        ge=0.0,
        le=1.0,
        description="Limiar inferior da faixa 'alta' de similaridade (mesmo CEP).",
    ),
    sim_media_min: float = Query(
        0.35,
        ge=0.0,
        le=1.0,
        description="Limiar entre faixa média e baixa; elegibilidade 'outro CEP' usa sim_mesmo_cep < este valor.",
    ),
    sim_outro_cep_min: float = Query(
        0.6,
        ge=0.0,
        le=1.0,
        description="Mínimo de sim_outro_cep para amostra e trocas (padrão 0,6).",
    ),
    amostra_pool: int = Query(
        8_000,
        ge=1,
        le=100_000,
        description=(
            "Com todas_elegiveis_outro_cep=false: quantas famílias elegíveis entram no sorteio "
            "antes do cruzamento com a geo (aumente para JSON maior sem marcar 'todas')."
        ),
    ),
    amostra_limite: int = Query(
        5_000,
        ge=0,
        le=200_000,
        description="Máximo de linhas na amostra JSON (0 = sem limite; use com cuidado no navegador).",
    ),
    todas_elegiveis_outro_cep: bool = Query(
        False,
        description="Se true, considera todas as famílias elegíveis no cruzamento (sem amostragem aleatória). Pode demorar.",
    ),
):
    """
    Cruzamento família (1 linha por código no CADU) × `raw.geo__tbl_geo`.

    **Mesmo CEP** (várias linhas na geo por CEP é esperado):
    - Conta famílias por quantidade de linhas na geo (`n_geo_por_cep`).
    - Match estrito: CEP + rua + bairro (lower).
    - Com **pg_trgm**: melhor similaridade média `(sim(logradouro)+sim(bairro))/2` entre o CADU e *alguma*
      linha da geo com aquele CEP — útil para grafia errada com CEP “certo” ou escolher candidato entre
      vários logradouros do mesmo CEP.

    **CEP suspeito**: amostra de famílias em que o texto se parece mais com uma linha da geo em *outro* CEP
    do que com as linhas do CEP informado (ou CEP inexistente na base) — típico de CEP do centro digitado
    com endereço de outro bairro.

    Ordem sugerida de saneamento: conferir CEP quando `sim_mesmo_cep` for baixa ou houver candidato
    `cep_sugerido` forte; depois ajustar grafia do logradouro/bairro.

    Limiares padrão: `sim_alta_min=0.65`, `sim_media_min=0.35`, `sim_outro_cep_min=0.6` (sobrescreva via query).

    Para milhares de famílias, use `POST /geo/bulk-apply-outro-cep` (prévia + um único UPDATE no servidor).
    """
    if sim_media_min >= sim_alta_min:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail="sim_media_min deve ser estritamente menor que sim_alta_min.",
        )
    if not _raw_table_exists(db, CADU_TABLE):
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Tabela raw.cecad__cadu não encontrada. Ingeste o CADU antes.",
        )
    if not _raw_table_exists(db, GEO_TABLE):
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=(
                "Tabela raw.geo__tbl_geo não encontrada. Envie tbl_geo.csv na ingestão "
                "(source=geo, dataset=tbl_geo, delimitador vírgula)."
            ),
        )

    gcols = _geo_columns(db)
    for required in ("cep_norm", "endereco", "bairro"):
        if required not in gcols:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail=f"Coluna obrigatória ausente em raw.{GEO_TABLE}: {required}",
            )

    trgm_ok = _ensure_vig_and_trgm(db)
    if todas_elegiveis_outro_cep and trgm_ok:
        db.execute(text("SET LOCAL statement_timeout TO '0'"))

    # --- Bloco base (sempre)
    sql_base = f"""
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
    geo_cep_counts AS (
      SELECT cep_norm, count(*)::bigint AS n
      FROM raw.{_qi(GEO_TABLE)}
      GROUP BY cep_norm
    ),
    fam_enriched AS (
      SELECT
        f.cod_fam,
        f.cep_n,
        f.logra_raw,
        f.bairro_raw,
        COALESCE(c.n, 0::bigint) AS n_geo_por_cep
      FROM fam f
      LEFT JOIN geo_cep_counts c ON c.cep_norm = f.cep_n
    ),
    strict_fam AS (
      SELECT DISTINCT fe.cod_fam
      FROM fam_enriched fe
      INNER JOIN raw.{_qi(GEO_TABLE)} g
        ON g.cep_norm = fe.cep_n
        AND fe.logra_raw IS NOT NULL
        AND fe.bairro_raw IS NOT NULL
        AND lower(fe.logra_raw) = lower(btrim(g.endereco::text))
        AND lower(fe.bairro_raw) = lower(btrim(g.bairro::text))
    )
    SELECT
      (SELECT count(*)::bigint FROM fam) AS familias_total,
      (SELECT count(*)::bigint FROM fam_enriched WHERE cep_n IS NULL) AS familias_cep_invalido,
      (SELECT count(*)::bigint FROM fam_enriched WHERE cep_n IS NOT NULL) AS familias_cep_valido,
      (SELECT count(*)::bigint FROM fam_enriched WHERE cep_n IS NOT NULL AND n_geo_por_cep = 0)
        AS familias_sem_linha_geo_no_cep,
      (SELECT count(*)::bigint FROM fam_enriched WHERE cep_n IS NOT NULL AND n_geo_por_cep = 1)
        AS familias_cep_unico_na_base,
      (SELECT count(*)::bigint FROM fam_enriched WHERE cep_n IS NOT NULL AND n_geo_por_cep > 1)
        AS familias_cep_ambiguo,
      (SELECT count(*)::bigint FROM fam_enriched WHERE cep_n IS NOT NULL AND n_geo_por_cep >= 1)
        AS familias_com_cep_na_geo,
      (SELECT count(*)::bigint FROM strict_fam) AS familias_match_estrito_rua_bairro,
      (SELECT count(*)::bigint FROM raw.{_qi(GEO_TABLE)}) AS geo_linhas_total,
      (SELECT count(DISTINCT cep_norm)::bigint FROM raw.{_qi(GEO_TABLE)}) AS geo_ceps_distintos
    """

    row = db.execute(text(sql_base)).mappings().first()
    if not row:
        raise HTTPException(status_code=500, detail="Falha ao calcular relatório.")

    out: dict[str, Any] = dict(row)
    out["pg_trgm_disponivel"] = trgm_ok

    # --- Similaridade no mesmo CEP (múltiplas linhas na geo: MAX entre candidatos)
    if trgm_ok:
        sql_sim = f"""
        WITH {_geo_fam_pipeline_ctes()}
        SELECT
          count(*) FILTER (
            WHERE cep_n IS NOT NULL AND n_geo_por_cep >= 1 AND sim_mesmo_cep >= :sim_alta
          )::bigint AS familias_mesmo_cep_sim_alta,
          count(*) FILTER (
            WHERE cep_n IS NOT NULL AND n_geo_por_cep >= 1
              AND sim_mesmo_cep >= :sim_media AND sim_mesmo_cep < :sim_alta
          )::bigint AS familias_mesmo_cep_sim_media,
          count(*) FILTER (
            WHERE cep_n IS NOT NULL AND n_geo_por_cep >= 1
              AND sim_mesmo_cep IS NOT NULL AND sim_mesmo_cep < :sim_media
          )::bigint AS familias_mesmo_cep_sim_baixa,
          count(*) FILTER (
            WHERE cep_n IS NOT NULL AND n_geo_por_cep >= 1
              AND sim_mesmo_cep IS NULL
          )::bigint AS familias_mesmo_cep_sem_texto_para_comparar
        FROM fam_sim
        """
        sim_row = db.execute(
            text(sql_sim),
            {"sim_alta": sim_alta_min, "sim_media": sim_media_min},
        ).mappings().first()
        if sim_row:
            out.update(dict(sim_row))

    # --- Amostras simples (ambiguidade / sem linha)
    samples_sql = f"""
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
    geo_cep_counts AS (
      SELECT cep_norm, count(*)::bigint AS n
      FROM raw.{_qi(GEO_TABLE)}
      GROUP BY cep_norm
    ),
    fam_enriched AS (
      SELECT f.cod_fam, f.cep_n, f.logra_raw, f.bairro_raw, COALESCE(c.n, 0::bigint) AS n_geo_por_cep
      FROM fam f
      LEFT JOIN geo_cep_counts c ON c.cep_norm = f.cep_n
    )
    SELECT cod_fam, cep_n, logra_raw, bairro_raw, n_geo_por_cep
    FROM fam_enriched
    WHERE cep_n IS NOT NULL AND n_geo_por_cep > 1
    LIMIT 8
    """
    out["amostra_familias_cep_ambiguo"] = [
        _serialize_row(dict(r)) for r in db.execute(text(samples_sql)).mappings().all()
    ]

    no_geo_sql = samples_sql.replace(
        "WHERE cep_n IS NOT NULL AND n_geo_por_cep > 1",
        "WHERE cep_n IS NOT NULL AND n_geo_por_cep = 0",
    )
    out["amostra_familias_sem_geo_no_cep"] = [
        _serialize_row(dict(r)) for r in db.execute(text(no_geo_sql)).mappings().all()
    ]

    # --- Candidato em OUTRO CEP (amostra): CEP inexistente na geo OU match fraco no próprio CEP
    if trgm_ok:
        fam_alvo_cte = (
            _cte_fam_alvo_outro_cep_todas()
            if todas_elegiveis_outro_cep
            else _cte_fam_alvo_outro_cep_amostra()
        )
        lim_sql = "" if amostra_limite == 0 else "LIMIT :amostra_limite"
        sql_alt = f"""
        WITH {_geo_fam_pipeline_ctes()},
        {fam_alvo_cte},
        {_cte_pares_melhor_outro_cep()}
        SELECT *
        FROM melhor
        WHERE sim_outro_cep >= :sim_outro_cep_min
        ORDER BY sim_outro_cep DESC
        {lim_sql}
        """
        try:
            bind_alt: dict[str, Any] = {
                "sim_media": sim_media_min,
                "sim_outro_cep_min": sim_outro_cep_min,
            }
            if not todas_elegiveis_outro_cep:
                bind_alt["amostra_pool"] = amostra_pool
            if amostra_limite > 0:
                bind_alt["amostra_limite"] = amostra_limite
            alt_rows = db.execute(text(sql_alt), bind_alt).mappings().all()
            out["amostra_suspeita_cep_errado_outro_cep_mais_parecido"] = [
                _serialize_row(dict(r)) for r in alt_rows
            ]
        except Exception as exc:
            out["amostra_suspeita_cep_errado_outro_cep_mais_parecido"] = []
            out["aviso_cruzamento_outro_cep"] = str(exc)[:400]

    out["parametros_relatorio"] = {
        "sim_alta_min": sim_alta_min,
        "sim_media_min": sim_media_min,
        "sim_outro_cep_min": sim_outro_cep_min,
        "amostra_pool": amostra_pool,
        "amostra_limite": amostra_limite,
        "todas_elegiveis_outro_cep": todas_elegiveis_outro_cep,
    }
    out["metodologia"] = {
        "mesmo_cep": (
            "Para cada família, comparamos logradouro e bairro do CADU com todas as linhas da geo "
            "que têm o mesmo cep_norm; guardamos a maior similaridade média (pg_trgm). "
            "Várias linhas por CEP na geo são esperadas."
        ),
        "faixas_similaridade": {
            "alta": (
                f">= {_fmt_pt_threshold(sim_alta_min)} — tende OK ou grafia leve; "
                "se n_geo>1, escolher linha com maior sim."
            ),
            "media": (
                f"{_fmt_pt_threshold(sim_media_min)}–{_fmt_pt_threshold(sim_alta_min)} — "
                "revisar texto e/ou qual logradouro do CEP."
            ),
            "baixa": (
                f"< {_fmt_pt_threshold(sim_media_min)} — CEP pode não ser o do endereço OU texto muito divergente; "
                "ver amostra de outro CEP."
            ),
        },
        "outro_cep": (
            (
                "Todas as famílias elegíveis no cruzamento; "
                if todas_elegiveis_outro_cep
                else f"Até {amostra_pool} famílias aleatórias elegíveis; "
            )
            + (
                "sem limite de linhas na resposta JSON. "
                if amostra_limite == 0
                else f"até {amostra_limite} linhas na resposta. "
            )
            + " Entre linhas da geo com CEP diferente do CADU, a maior similaridade de texto. "
            f"Inclusão quando sim_outro_cep >= {_fmt_pt_threshold(sim_outro_cep_min)}. "
            "Para aplicar milhares de correções de uma vez, use POST /api/v1/geo/bulk-apply-outro-cep."
        ),
        "ordem_saneamento_sugerida": (
            "1) Conferir CEP quando sim_mesmo_cep baixa ou cep ausente na geo mas candidato forte em outro CEP; "
            "2) Depois padronizar grafia de logradouro/bairro com a linha escolhida na geo."
        ),
    }

    if not trgm_ok:
        out["metodologia"]["pg_trgm"] = (
            "Extensão pg_trgm não pôde ser criada (permissão?). Similaridade e cruzamento 'outro CEP' ficam indisponíveis; "
            "peça ao DBA: CREATE EXTENSION pg_trgm;"
        )

    return out
