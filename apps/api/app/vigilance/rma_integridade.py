"""Auditoria de integridade — RMA × território × geo (evitar buracos na ponte)."""

from __future__ import annotations

from dataclasses import dataclass, field

from sqlalchemy import text
from sqlalchemy.engine import Connection

from .familia_mview import _table_exists
from .geo_territorial_maps import MAP_CRAS_TABLE, MAP_CREAS_TABLE, load_cras_map, load_creas_map
from .rma_catalogo import resolve_rma_data_dir
from .rma_equipamento import (
    CENTRO_POP_ID_OFICIAL,
    DIM_TABLE,
    PONTE_TABLE,
    _ID_CRAS_TERRITORIAL_OVERRIDE,
)
from .rma_loader import FATO_TABLE
from .rma_mview import RESUMO_MVIEW

_RAW_TABLES = ("rma__cras", "rma__creas", "rma__centro_pop")
_EXPECTED_CRAS = set(range(1, 13))
_EXPECTED_CREAS = set(range(1, 6))


@dataclass
class IntegridadeReport:
    ok: bool
    erros: list[str] = field(default_factory=list)
    avisos: list[str] = field(default_factory=list)
    raw: dict[str, int] = field(default_factory=dict)
    dim_equipamentos: int = 0
    ponte_cras: dict[int, str] = field(default_factory=dict)
    ponte_creas: dict[int, str] = field(default_factory=dict)
    geo_map_cras_nums: list[int] = field(default_factory=list)
    geo_map_creas_nums: list[int] = field(default_factory=list)
    fato_rows: int = 0
    fato_psr_excluidos: int = 0
    resumo_rows: int = 0
    data_dir: str = ""
    familia_mview: bool = False


def auditar_rma_integridade(conn: Connection) -> IntegridadeReport:
    report = IntegridadeReport(ok=True, data_dir=str(resolve_rma_data_dir()))

    if not resolve_rma_data_dir().is_dir():
        report.erros.append(f"Pasta RMA não encontrada: {report.data_dir}")
        report.ok = False

    for table in _RAW_TABLES:
        if not _table_exists(conn, "raw", table):
            report.erros.append(f"Tabela raw.{table} ausente — execute bootstrap RMA.")
            report.ok = False
            report.raw[table] = 0
        else:
            n = int(
                conn.execute(text(f'SELECT COUNT(*)::bigint FROM raw."{table}"')).scalar() or 0
            )
            report.raw[table] = n
            if n == 0:
                report.erros.append(f"Tabela raw.{table} vazia.")

    if not _table_exists(conn, "vig", DIM_TABLE):
        report.erros.append(f"Tabela vig.{DIM_TABLE} ausente.")
        report.ok = False
    else:
        report.dim_equipamentos = int(
            conn.execute(text(f'SELECT COUNT(*)::bigint FROM vig."{DIM_TABLE}"')).scalar() or 0
        )

        pop = conn.execute(
            text(
                f"""
                SELECT tipo_equipamento FROM vig."{DIM_TABLE}"
                WHERE id_equipamento = :id
                """
            ),
            {"id": CENTRO_POP_ID_OFICIAL},
        ).scalar()
        if pop != "CENTRO_POP":
            report.erros.append(
                f"Centro POP ({CENTRO_POP_ID_OFICIAL}) deveria ser tipo CENTRO_POP, veio: {pop!r}."
            )
            report.ok = False

        cras_sem_num = conn.execute(
            text(
                f"""
                SELECT id_equipamento, nome_oficial FROM vig."{DIM_TABLE}"
                WHERE tipo_equipamento = 'CRAS' AND cras_num_territorial IS NULL
                """
            )
        ).mappings().all()
        for row in cras_sem_num:
            report.erros.append(
                f"CRAS sem num territorial: {row['id_equipamento']} ({row['nome_oficial']})"
            )
            report.ok = False

    if _table_exists(conn, "vig", PONTE_TABLE):
        for row in conn.execute(
            text(
                f"""
                SELECT num_territorial, id_equipamento
                FROM vig."{PONTE_TABLE}" WHERE tipo_territorio = 'CRAS'
                ORDER BY num_territorial
                """
            )
        ).mappings():
            report.ponte_cras[int(row["num_territorial"])] = str(row["id_equipamento"])

        for row in conn.execute(
            text(
                f"""
                SELECT num_territorial, id_equipamento
                FROM vig."{PONTE_TABLE}" WHERE tipo_territorio = 'CREAS'
                ORDER BY num_territorial
                """
            )
        ).mappings():
            report.ponte_creas[int(row["num_territorial"])] = str(row["id_equipamento"])

    faltando_cras = sorted(_EXPECTED_CRAS - set(report.ponte_cras))
    if faltando_cras:
        report.erros.append(f"CRAS territoriais sem ponte oficial: {faltando_cras}")
        report.ok = False

    faltando_creas = sorted(_EXPECTED_CREAS - set(report.ponte_creas))
    if faltando_creas:
        report.erros.append(f"CREAS territoriais sem ponte oficial: {faltando_creas}")
        report.ok = False

    if len(_ID_CRAS_TERRITORIAL_OVERRIDE) != 12:
        report.avisos.append(
            f"Mapa estático CRAS tem {len(_ID_CRAS_TERRITORIAL_OVERRIDE)} ids (esperado 12)."
        )

    cras_map = load_cras_map(conn)
    if cras_map:
        nums = sorted({v for v in cras_map.values() if v})
        report.geo_map_cras_nums = nums
        geo_set = set(nums)
        if geo_set != _EXPECTED_CRAS:
            diff = sorted(_EXPECTED_CRAS - geo_set)
            if diff:
                report.avisos.append(f"Mapa geo CRAS sem bairros para nums: {diff}")
        for num, eid in report.ponte_cras.items():
            if num not in geo_set:
                report.avisos.append(
                    f"CRAS {num} (id {eid}) sem bairros no mapa geo persistido."
                )
    elif _table_exists(conn, "raw", MAP_CRAS_TABLE):
        report.avisos.append("Mapa geo CRAS persistido existe mas está vazio.")
    else:
        report.avisos.append(
            "Mapa geo CRAS não aplicado — aplique bairros_cras.csv em Ingestão/Geo."
        )

    creas_map = load_creas_map(conn)
    if creas_map:
        nums = sorted({v for v in creas_map.values() if v})
        report.geo_map_creas_nums = nums
        geo_set = set(nums)
        if geo_set != _EXPECTED_CREAS:
            diff = sorted(_EXPECTED_CREAS - geo_set)
            if diff:
                report.avisos.append(f"Mapa geo CREAS sem bairros para nums: {diff}")
    elif _table_exists(conn, "raw", MAP_CREAS_TABLE):
        report.avisos.append("Mapa geo CREAS persistido existe mas está vazio.")
    else:
        report.avisos.append(
            "Mapa geo CREAS não aplicado — aplique bairros_creas.csv em Ingestão/Geo."
        )

    if _table_exists(conn, "vig", FATO_TABLE):
        report.fato_rows = int(
            conn.execute(text(f'SELECT COUNT(*)::bigint FROM vig."{FATO_TABLE}"')).scalar() or 0
        )
        report.fato_psr_excluidos = int(
            conn.execute(
                text(
                    f"""
                    SELECT COUNT(*)::bigint FROM vig."{FATO_TABLE}"
                    WHERE incluir_analitico IS FALSE
                    """
                )
            ).scalar()
            or 0
        )
        if report.fato_rows == 0:
            report.erros.append("Fato RMA vazio.")
            report.ok = False
    else:
        report.erros.append(f"Tabela vig.{FATO_TABLE} ausente.")
        report.ok = False

    if _table_exists(conn, "vig", RESUMO_MVIEW):
        report.resumo_rows = int(
            conn.execute(text(f'SELECT COUNT(*)::bigint FROM vig."{RESUMO_MVIEW}"')).scalar() or 0
        )
        if report.resumo_rows == 0:
            report.erros.append("MV resumo RMA vazia.")
            report.ok = False
    else:
        report.erros.append(f"MV vig.{RESUMO_MVIEW} ausente — execute refresh.")
        report.ok = False

    report.familia_mview = _table_exists(conn, "vig", "mvw_familia")
    if not report.familia_mview:
        report.avisos.append(
            "vig.mvw_familia ausente — comparativo CRAS×demanda CADU não funcionará."
        )

    if report.erros:
        report.ok = False

    return report
