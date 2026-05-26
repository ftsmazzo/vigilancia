"""Catálogo de dados para o modelo (visões vig)."""

from __future__ import annotations

from sqlalchemy import text
from sqlalchemy.engine import Connection
from sqlalchemy.orm import Session

from ..municipio_context import load_context_prompt
from ..vigilance.familia_mview import _table_exists
from .dictionary import build_dictionary_prompt

CATALOG_STATIC = """
## Visões disponíveis (PostgreSQL, schema vig)

### vig.mvw_familia — uma linha por família (CADU)
- codigo_familiar (text, chave familiar)
- num_cras, nom_cras (unidade territorial / CRAS de referência)
- renda_per_capita (numeric), faixa_renda (text), renda_total
- marc_pbf (boolean, na folha PBF), marc_pbf_cadu (marcador CADU)
- bairro, endereco, cep
- meses_desatualizado (int), data_atualizacao, data_cadastro

### vig.mvw_pessoas — uma linha por pessoa no CADU
- cadu_row_id, codigo_familiar, num_nis, num_cpf
- nome, data_nascimento, idade (int, anos completos)
- cod_sexo ('1' masculino, '2' feminino)
- cod_raca_cor ('1' branca … '5' indígena)
- grau_instrucao ('1' analfabeto … '7' superior completo)
- cod_deficiencia, ind_def_* (flags deficiência)
- marc_sit_rua, ind_frequenta_escola, ind_atend_cras
- ind_trabalho_infantil

### vig.mvw_familia_domicilio — moradia e riscos por família
- codigo_familiar
- situacao_domicilio, tipo_piso, tipo_parede, agua_canalizada, existencia_banheiro
- inseguranca_alimentar, risco_violacao_direitos, gpte
- total_pessoas (contagem CPF na família)

### vig.mvw_sisc_qualificado — atendidos SISC × CADU (após qualificação)
- nis_norm, grupo, cras_nome, cras_codigo, faixa_etaria
- classificacao_vinculo ('vinculado_cadu' | 'sem_vinculo_cadu')
- classificacao_sexo, classificacao_raca, classificacao_escolaridade
- classificacao_faixa_idade, classificacao_deficiencia, tem_deficiencia (bool)
- renda_per_capita (da família CADU quando vinculado)

## Regras de junção
- Família ↔ pessoa: p.codigo_familiar = f.codigo_familiar
- Família ↔ domicílio: d.codigo_familiar = f.codigo_familiar
- Use COUNT(DISTINCT f.codigo_familiar) para contar famílias.
- Use COUNT(p.cadu_row_id) ou COUNT(*) em pessoas para contar indivíduos.
- Filtro por CRAS: f.num_cras = 'código' ou f.nom_cras ILIKE '%nome%'.
"""


def build_schema_context(conn: Connection, db: Session | None = None) -> str:
    parts = [CATALOG_STATIC.strip()]
    if _table_exists(conn, "vig", "mvw_familia"):
        row = conn.execute(text("SELECT COUNT(*) FROM vig.mvw_familia")).scalar()
        parts.append(f"\nContagem atual: vig.mvw_familia tem {int(row or 0):,} famílias.".replace(",", "."))
    if _table_exists(conn, "vig", "mvw_pessoas"):
        row = conn.execute(text("SELECT COUNT(*) FROM vig.mvw_pessoas")).scalar()
        parts.append(f"vig.mvw_pessoas tem {int(row or 0):,} registros de pessoas.".replace(",", "."))

    try:
        dict_block = build_dictionary_prompt()
        if dict_block:
            parts.append("\n" + dict_block)
    except Exception:
        pass

    if db is not None:
        try:
            municipio_block = load_context_prompt(db)
            if municipio_block:
                parts.append("\n" + municipio_block)
        except Exception:
            pass

    return "\n".join(parts)
