"""Catálogo de dados para o modelo (visões vig)."""

from __future__ import annotations

from sqlalchemy import text
from sqlalchemy.engine import Connection
from sqlalchemy.orm import Session

from ..municipio_context import load_context_prompt
from ..vigilance.familia_mview import _table_exists
from .dictionary import build_dictionary_prompt

CATALOG_STATIC = """
## Fonte verdade e medidas (modelo VigSocial)

**Fonte verdade = CADU** (`vig.mvw_familia`, `vig.mvw_pessoas`, `vig.mvw_familia_domicilio`):
universo de famílias e pessoas do município. Toda pergunta parte daqui.

**Medidas e cruzamentos** (sempre ligados ao CADU por `codigo_familiar` ou `num_nis` / `nis_norm`):
- **Folha PBF** (SIBEC): quem recebe pagamento — KPI folha pode incluir famílias fora do CADU local; no CADU use `marc_pbf`.
- **SISC (Convivência)**: matrícula no serviço — `vig.mvw_sisc_qualificado`; divisão territorial do atendimento: `s.cras_codigo`, `s.cras_nome`.
- **Território CADU**: referência da família no cadastro — `f.num_cras`, `f.nom_cras` (pode diferir do CRAS do SISC na mesma pessoa).

Conversas em sequência ("dessas crianças… depois por CRAS"): mantenha filtros anteriores e acrescente `GROUP BY s.cras_nome, s.cras_codigo`.

## Visões disponíveis (PostgreSQL, schema vig)

### vig.mvw_familia — uma linha por família (CADU)
- codigo_familiar (text, chave familiar)
- num_cras, nom_cras (unidade territorial / CRAS de referência)
- renda_per_capita (numeric), faixa_renda (text), renda_total
- marc_pbf (boolean: família do CADU presente na folha SIBEC importada)
- marc_pbf_cadu (texto: marcador "recebe PBF" no CADU — não é a mesma coisa que a folha de pagamento)
- bairro, endereco, cep
- meses_desatualizado (int), data_atualizacao, data_cadastro

### vig.mvw_pessoas — uma linha por pessoa no CADU
- cadu_row_id, codigo_familiar, num_nis, num_cpf
- nome, data_nascimento, idade (int, anos completos)
- cod_sexo ('1' masculino, '2' feminino)
- cod_raca_cor ('1' branca … '5' indígena)
- grau_instrucao ('1' analfabeto … '7' superior completo)
- cod_deficiencia, ind_def_* (flags deficiência)
- marc_sit_rua, ind_frequenta_escola, ind_atend_cras (texto '1'/'0' — atendido CRAS no CADU, ≠ SISC)
- ind_trabalho_infantil

### vig.mvw_familia_domicilio — moradia e riscos por família
- codigo_familiar
- situacao_domicilio, tipo_piso, tipo_parede, agua_canalizada, existencia_banheiro
- inseguranca_alimentar, risco_violacao_direitos, gpte
- total_pessoas (contagem CPF na família)

### vig.mvw_sisc_qualificado — atendidos SISC × CADU (Serviço de Convivência; após qualificar)
- nis_norm (NIS do atendido), codigo_familiar (quando vinculado ao CADU)
- grupo, cras_nome, cras_codigo, faixa_etaria (texto SISC)
- classificacao_vinculo ('vinculado_cadu' | 'sem_vinculo_cadu')
- classificacao_faixa_idade ('adolescente_12_17', 'crianca_0_11', …)
- familia_na_folha_pbf (boolean — família do atendido na folha PBF)
- classificacao_sexo, classificacao_raca, classificacao_escolaridade
- classificacao_faixa_idade, classificacao_deficiencia, tem_deficiencia (bool)
- renda_per_capita (da família CADU quando vinculado)

## Métricas oficiais (alinhar com o painel Início)
- **Famílias na folha PBF**: contagem na base SIBEC (`raw.sibec__programa_bolsa_familia`, última competência) — pode ser maior que `marc_pbf` no CADU.
- **% sobre CADU**: folha PBF ÷ total `vig.mvw_familia`.
- **Marcador PBF no CADU**: filtrar `marc_pbf_cadu`, não confundir com folha.

## Regras de junção
- Família ↔ pessoa: p.codigo_familiar = f.codigo_familiar
- Família ↔ domicílio: d.codigo_familiar = f.codigo_familiar
- Use COUNT(DISTINCT f.codigo_familiar) para contar famílias.
- Use COUNT(p.cadu_row_id) ou COUNT(*) em pessoas para contar indivíduos.
- CRAS no CADU (família): f.num_cras, f.nom_cras.
- CRAS no SISC (atendimento convivência): s.cras_codigo, s.cras_nome — use para "dividir por CRAS" após pergunta sobre SISC.
- Desdobramento por CRAS (CADU): GROUP BY f.num_cras, f.nom_cras; ORDER BY num_cras numérico 1→12; NULL/sem referência por último.
- CRAS 9 = Bonfim Paulista. Informe famílias sem num_cras como sem referência territorial.
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
