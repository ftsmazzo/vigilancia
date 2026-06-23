"""Dimensão de equipamentos SUAS — chave oficial id_equipamento (CRAS/CREAS/Centro POP)."""

from __future__ import annotations

import re
import unicodedata
from dataclasses import dataclass

from sqlalchemy import text
from sqlalchemy.engine import Connection

from .familia_mview import _table_exists

DIM_TABLE = "dim_equipamento_suas"

# Mesmo id nacional: CREAS POP (formulário antigo) → Centro POP (PSR dedicado).
CENTRO_POP_ID_OFICIAL = "35434096110"
CENTRO_POP_CUTOVER = "2014-01-01"

_CRAS_NUM_RE = re.compile(r"cras\s*(\d{1,2})", re.I)
_CREAS_NUM_RE = re.compile(r"paefi\s*(\d)", re.I)

# Id oficial SUAS → número territorial municipal (Ribeirão Preto).
_ID_CRAS_TERRITORIAL_OVERRIDE: dict[str, int] = {
    "35434003454": 1,
    "35434003939": 2,
    "35434003964": 3,
    "35434003456": 4,
    "35434003859": 5,
    "35434038956": 6,
    "35434039259": 7,
    "35434039963": 8,
    "35434039977": 9,  # "CRAS Bonfim" — nome sem número no RMA
    "35434040155": 10,
    "35434040163": 11,
    "35434040393": 12,
}

# Id legado SUAS (CREAS PAEFI 1) → número territorial municipal.
_ID_CREAS_TERRITORIAL_OVERRIDE: dict[str, int] = {
    "13543402410": 1,
    "35434096102": 2,
    "35434097190": 3,
    "35434099507": 4,
    "35434099655": 5,
}


def _qi(ident: str) -> str:
    return '"' + ident.replace('"', '""') + '"'


def _fold(value: str) -> str:
    normalized = unicodedata.normalize("NFKD", value or "")
    stripped = "".join(c for c in normalized if not unicodedata.combining(c))
    return re.sub(r"\s+", " ", stripped.lower().strip())


def parse_cras_num_territorial(nome_unidade: str | None) -> int | None:
    if not nome_unidade:
        return None
    m = _CRAS_NUM_RE.search(_fold(nome_unidade))
    if not m:
        return None
    n = int(m.group(1))
    return n if 1 <= n <= 99 else None


def resolve_cras_num_territorial(*, id_equipamento: str, nome_unidade: str | None) -> int | None:
    if id_equipamento in _ID_CRAS_TERRITORIAL_OVERRIDE:
        return _ID_CRAS_TERRITORIAL_OVERRIDE[id_equipamento]
    return parse_cras_num_territorial(nome_unidade)


def parse_creas_num_territorial(*, id_equipamento: str, nome_unidade: str | None) -> int | None:
    if id_equipamento in _ID_CREAS_TERRITORIAL_OVERRIDE:
        return _ID_CREAS_TERRITORIAL_OVERRIDE[id_equipamento]
    if id_equipamento == CENTRO_POP_ID_OFICIAL:
        return None
    if nome_unidade:
        m = _CREAS_NUM_RE.search(_fold(nome_unidade))
        if m:
            return int(m.group(1))
    return None


def infer_tipo_equipamento(*, id_equipamento: str, tipo_formulario: str, nome_unidade: str | None) -> str:
    if id_equipamento == CENTRO_POP_ID_OFICIAL or tipo_formulario.upper() == "CENTRO_POP":
        return "CENTRO_POP"
    if tipo_formulario.upper() == "CRAS":
        return "CRAS"
    fold = _fold(nome_unidade or "")
    if "pop" in fold and "creas" in fold:
        return "CENTRO_POP"
    return "CREAS"


def ensure_dim_equipamento_suas(conn: Connection) -> None:
    conn.execute(text("CREATE SCHEMA IF NOT EXISTS vig"))
    conn.execute(
        text(
            f"""
            CREATE TABLE IF NOT EXISTS vig.{_qi(DIM_TABLE)} (
              id_equipamento TEXT PRIMARY KEY,
              tipo_equipamento TEXT NOT NULL
                CHECK (tipo_equipamento IN ('CRAS', 'CREAS', 'CENTRO_POP')),
              nome_oficial TEXT,
              endereco TEXT,
              municipio TEXT,
              uf TEXT,
              codigo_ibge TEXT,
              cras_num_territorial SMALLINT,
              creas_num_territorial SMALLINT,
              grupo_psr_id TEXT,
              rma_historico_creas_pop BOOLEAN NOT NULL DEFAULT FALSE,
              ativo BOOLEAN NOT NULL DEFAULT TRUE,
              atualizado_em TIMESTAMPTZ NOT NULL DEFAULT NOW()
            )
            """
        )
    )
    conn.execute(
        text(
            f"""
            CREATE INDEX IF NOT EXISTS idx_dim_equip_suas_tipo
              ON vig.{_qi(DIM_TABLE)} (tipo_equipamento)
            """
        )
    )
    conn.execute(
        text(
            f"""
            CREATE INDEX IF NOT EXISTS idx_dim_equip_suas_cras_num
              ON vig.{_qi(DIM_TABLE)} (cras_num_territorial)
              WHERE cras_num_territorial IS NOT NULL
            """
        )
    )
    conn.execute(
        text(
            f"""
            CREATE INDEX IF NOT EXISTS idx_dim_equip_suas_creas_num
              ON vig.{_qi(DIM_TABLE)} (creas_num_territorial)
              WHERE creas_num_territorial IS NOT NULL
            """
        )
    )


@dataclass
class DimEquipamentoRefreshResult:
    upserted: int
    total: int


def refresh_dim_from_raw_rma(conn: Connection) -> DimEquipamentoRefreshResult:
    """Atualiza catálogo a partir das três tabelas RAW do RMA (último nome por id)."""
    ensure_dim_equipamento_suas(conn)

    sources = [
        ("CRAS", "rma__cras", "id_cras", "mes_referencia"),
        ("CREAS", "rma__creas", "id_creas", "mes_referencia"),
        ("CENTRO_POP", "rma__centro_pop", "id_unidade", "mes_ano"),
    ]

    candidates: dict[str, dict] = {}
    for tipo_form, table, id_col, date_col in sources:
        if not _table_exists(conn, "raw", table):
            continue
        rows = conn.execute(
            text(
                f"""
                SELECT DISTINCT ON (btrim({_qi(id_col)}::text))
                  btrim({_qi(id_col)}::text) AS id_equipamento,
                  btrim({_qi("nome_unidade")}::text) AS nome_unidade,
                  btrim({_qi("endereco")}::text) AS endereco,
                  btrim({_qi("municipio")}::text) AS municipio,
                  btrim({_qi("uf")}::text) AS uf,
                  COALESCE(
                    NULLIF(btrim({_qi("codigoibge")}::text), ''),
                    NULLIF(btrim({_qi("ibge")}::text), '')
                  ) AS codigo_ibge,
                  {_qi(date_col)}::date AS ref_date
                FROM raw.{_qi(table)}
                WHERE btrim(COALESCE({_qi(id_col)}::text, '')) <> ''
                ORDER BY btrim({_qi(id_col)}::text), {_qi(date_col)}::date DESC
                """
            )
        ).mappings()

        for row in rows:
            eid = str(row["id_equipamento"] or "").strip().strip("'")
            if not eid:
                continue
            if eid == CENTRO_POP_ID_OFICIAL and tipo_form == "CREAS":
                # Metadados CREAS POP não sobrescrevem o equipamento canônico Centro POP.
                if eid in candidates and candidates[eid].get("tipo_formulario") == "CENTRO_POP":
                    continue
            prev = candidates.get(eid)
            if prev and (prev.get("ref_date") or "") >= str(row["ref_date"]):
                continue
            candidates[eid] = {
                "id_equipamento": eid,
                "tipo_formulario": tipo_form,
                "nome_unidade": row["nome_unidade"],
                "endereco": row["endereco"],
                "municipio": row["municipio"],
                "uf": row["uf"],
                "codigo_ibge": row["codigo_ibge"],
                "ref_date": str(row["ref_date"]),
            }

    if _table_exists(conn, "raw", "rma__centro_pop"):
        pop_row = conn.execute(
            text(
                """
                SELECT DISTINCT ON (btrim(id_unidade::text))
                  btrim(id_unidade::text) AS id_equipamento,
                  btrim(nome_unidade::text) AS nome_unidade,
                  btrim(endereco::text) AS endereco,
                  btrim(municipio::text) AS municipio,
                  btrim(uf::text) AS uf,
                  NULLIF(btrim(ibge::text), '') AS codigo_ibge,
                  mes_ano::date AS ref_date
                FROM raw."rma__centro_pop"
                WHERE btrim(COALESCE(id_unidade::text, '')) <> ''
                ORDER BY btrim(id_unidade::text), mes_ano::date DESC
                """
            )
        ).mappings().first()
        if pop_row:
            eid = str(pop_row["id_equipamento"] or "").strip().strip("'")
            if eid:
                prev = candidates.get(eid, {})
                candidates[eid] = {
                    "id_equipamento": eid,
                    "tipo_formulario": "CENTRO_POP",
                    "nome_unidade": pop_row["nome_unidade"] or prev.get("nome_unidade"),
                    "endereco": pop_row["endereco"] or prev.get("endereco"),
                    "municipio": pop_row["municipio"] or prev.get("municipio"),
                    "uf": pop_row["uf"] or prev.get("uf"),
                    "codigo_ibge": pop_row["codigo_ibge"] or prev.get("codigo_ibge"),
                    "ref_date": str(pop_row["ref_date"] or prev.get("ref_date") or ""),
                }

    upserted = 0
    for eid, row in candidates.items():
        nome = (row.get("nome_unidade") or "").strip().strip("'")
        tipo = infer_tipo_equipamento(
            id_equipamento=eid,
            tipo_formulario=row["tipo_formulario"],
            nome_unidade=nome,
        )
        cras_num = resolve_cras_num_territorial(id_equipamento=eid, nome_unidade=nome) if tipo == "CRAS" else None
        creas_num = (
            parse_creas_num_territorial(id_equipamento=eid, nome_unidade=nome)
            if tipo == "CREAS"
            else None
        )
        grupo_psr = CENTRO_POP_ID_OFICIAL if eid == CENTRO_POP_ID_OFICIAL else None
        hist_creas_pop = eid == CENTRO_POP_ID_OFICIAL

        conn.execute(
            text(
                f"""
                INSERT INTO vig.{_qi(DIM_TABLE)} (
                  id_equipamento, tipo_equipamento, nome_oficial, endereco,
                  municipio, uf, codigo_ibge,
                  cras_num_territorial, creas_num_territorial,
                  grupo_psr_id, rma_historico_creas_pop, ativo, atualizado_em
                ) VALUES (
                  :id_equipamento, :tipo_equipamento, :nome_oficial, :endereco,
                  :municipio, :uf, :codigo_ibge,
                  :cras_num_territorial, :creas_num_territorial,
                  :grupo_psr_id, :rma_historico_creas_pop, TRUE, NOW()
                )
                ON CONFLICT (id_equipamento) DO UPDATE SET
                  tipo_equipamento = EXCLUDED.tipo_equipamento,
                  nome_oficial = EXCLUDED.nome_oficial,
                  endereco = EXCLUDED.endereco,
                  municipio = EXCLUDED.municipio,
                  uf = EXCLUDED.uf,
                  codigo_ibge = EXCLUDED.codigo_ibge,
                  cras_num_territorial = EXCLUDED.cras_num_territorial,
                  creas_num_territorial = EXCLUDED.creas_num_territorial,
                  grupo_psr_id = EXCLUDED.grupo_psr_id,
                  rma_historico_creas_pop = EXCLUDED.rma_historico_creas_pop,
                  ativo = TRUE,
                  atualizado_em = NOW()
                """
            ),
            {
                "id_equipamento": eid,
                "tipo_equipamento": tipo,
                "nome_oficial": nome or None,
                "endereco": (row.get("endereco") or "").strip().strip("'") or None,
                "municipio": (row.get("municipio") or "").strip().strip("'") or None,
                "uf": (row.get("uf") or "").strip().strip("'") or None,
                "codigo_ibge": (row.get("codigo_ibge") or "").strip() or None,
                "cras_num_territorial": cras_num,
                "creas_num_territorial": creas_num,
                "grupo_psr_id": grupo_psr,
                "rma_historico_creas_pop": hist_creas_pop,
            },
        )
        upserted += 1

    refresh_ponte_territorial(conn)
    return DimEquipamentoRefreshResult(upserted=upserted, total=len(candidates))


PONTE_TABLE = "ponte_territorio_equipamento"


def ensure_ponte_territorial(conn: Connection) -> None:
    conn.execute(text("CREATE SCHEMA IF NOT EXISTS vig"))
    conn.execute(
        text(
            f"""
            CREATE TABLE IF NOT EXISTS vig.{_qi(PONTE_TABLE)} (
              tipo_territorio TEXT NOT NULL CHECK (tipo_territorio IN ('CRAS', 'CREAS')),
              num_territorial SMALLINT NOT NULL,
              id_equipamento TEXT NOT NULL,
              nome_oficial TEXT,
              PRIMARY KEY (tipo_territorio, num_territorial),
              UNIQUE (id_equipamento)
            )
            """
        )
    )


def refresh_ponte_territorial(conn: Connection) -> int:
    """Uma linha por CRAS 1–12 e CREAS 1–5 ligando num territorial ↔ id oficial SUAS."""
    ensure_ponte_territorial(conn)
    conn.execute(text(f"TRUNCATE TABLE vig.{_qi(PONTE_TABLE)}"))

    rows = conn.execute(
        text(
            f"""
            SELECT id_equipamento, tipo_equipamento, nome_oficial,
                   cras_num_territorial, creas_num_territorial
            FROM vig.{_qi(DIM_TABLE)}
            WHERE ativo IS TRUE
            """
        )
    ).mappings()

    n = 0
    for row in rows:
        tipo = row["tipo_equipamento"]
        if tipo == "CRAS" and row["cras_num_territorial"] is not None:
            conn.execute(
                text(
                    f"""
                    INSERT INTO vig.{_qi(PONTE_TABLE)} (
                      tipo_territorio, num_territorial, id_equipamento, nome_oficial
                    ) VALUES ('CRAS', :num, :id, :nome)
                    """
                ),
                {
                    "num": row["cras_num_territorial"],
                    "id": row["id_equipamento"],
                    "nome": row["nome_oficial"],
                },
            )
            n += 1
        elif tipo == "CREAS" and row["creas_num_territorial"] is not None:
            conn.execute(
                text(
                    f"""
                    INSERT INTO vig.{_qi(PONTE_TABLE)} (
                      tipo_territorio, num_territorial, id_equipamento, nome_oficial
                    ) VALUES ('CREAS', :num, :id, :nome)
                    """
                ),
                {
                    "num": row["creas_num_territorial"],
                    "id": row["id_equipamento"],
                    "nome": row["nome_oficial"],
                },
            )
            n += 1
    return n
