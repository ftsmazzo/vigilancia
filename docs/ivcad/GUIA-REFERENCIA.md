# Guia de referência — IVCAD (VigSocial)

> **Para quê serve este documento:** referência operacional para calcular, consultar e expor o IVCAD e suas dimensões/indicadores em painéis, API e agente VigIA.  
> **Grain analítico:** família · **Tronco:** `vig.mvw_familia`, `vig.mvw_pessoas`, `vig.mvw_familia_domicilio`  
> **Metodologia:** MDS IN084 v1.0.5 + extensão territorial VigSocial (CRAS, bairro)

---

## Índice

1. [Visão geral](#1-visão-geral)
2. [Processo em 7 etapas](#2-processo-em-7-etapas)
3. [Universo elegível (v1.0.5)](#3-universo-elegível-v105)
4. [Fórmulas gerais](#4-fórmulas-gerais)
5. [Idade e decisão D10](#5-idade-e-decisão-d10)
6. [Agregação territorial](#6-agregação-territorial)
7. [Dimensão NC — indicadores e SQL](#7-dimensão-nc--indicadores-e-sql)
7b. [Dimensão DPI — resumo](#7b-dimensão-dpi--resumo)
7c. [Dimensão DCA — resumo](#7c-dimensão-dca--resumo)
7d. [Dimensão TQA — resumo](#7d-dimensão-tqa--resumo)
7e. [Dimensão DR — resumo](#7e-dimensão-dr--resumo)
7f. [Dimensão CH — resumo](#7f-dimensão-ch--resumo)
8. [Matriz completa (40 indicadores)](#8-matriz-completa-40-indicadores)
9. [Catálogo de indicadores (template)](#9-catálogo-de-indicadores-template)
10. [Métricas para painéis](#10-métricas-para-painéis)
11. [Validação e conciliação MDS](#11-validação-e-conciliação-mds)
12. [Decisões VigSocial](#12-decisões-vigsocial)
13. [Roadmap de implementação](#13-roadmap-de-implementação)

---

## 1. Visão geral

### 1.1 O que é

| Item | Definição |
|------|-----------|
| **Nome** | Índice de Vulnerabilidade das Famílias do Cadastro Único |
| **Código MDS** | IN084 |
| **Unidade** | Família |
| **Escala** | 0 a 1 (maior = mais vulnerável) |
| **Fonte principal** | Cadastro Único (CECAD) |
| **Composição** | 40 indicadores binários → 6 dimensões → 1 índice |

### 1.2 As seis dimensões

| Sigla | Nome | Qtd indicadores* | Doc dimensão |
|-------|------|------------------|--------------|
| **NC** | Necessidade de Cuidados | 7 | IN078 · VD001–VD007 · [detalhe](../03-ivcad-dimensao-nc.md) |
| **DPI** | Desenvolvimento na Primeira Infância | 3 | IN079 · VD008–VD010 · [detalhe](../04-ivcad-dimensao-dpi.md) |
| **DCA** | Desenvolvimento de Crianças e Adolescentes | 5 | IN080 · VD011–VD015 · [detalhe](../05-ivcad-dimensao-dca.md) |
| **TQA** | Trabalho e Qualificação de Adultos | 7 | IN081 · VD016–VD022 · [detalhe](../06-ivcad-dimensao-tqa.md) |
| **DR** | Disponibilidade de Recursos | 4 | IN082 · VD023–VD026 · [detalhe](../07-ivcad-dimensao-dr.md) |
| **CH** | Condições Habitacionais | 14 | IN083 · VD027–VD040 · [detalhe](../08-ivcad-dimensao-ch.md) |

\* Total = 40. **Documentados: 40 / 40** ✅

### 1.3 Granulação

| Nível | MDS | VigSocial |
|-------|-----|-----------|
| Município | ✅ | ✅ |
| CRAS | ❌ | ✅ `vig.mvw_familia.num_cras` |
| Bairro | ❌ | ✅ GEO / `bairro` |

---

## 2. Processo em 7 etapas

Fluxo lógico para **qualquer** consulta ou job de IVCAD:

```
┌─────────────────────────────────────────────────────────────────┐
│ ETAPA 1 — Ingestão CECAD (+ SIBEC quando indicador/universo exigir) │
└───────────────────────────────┬─────────────────────────────────┘
                                ▼
┌─────────────────────────────────────────────────────────────────┐
│ ETAPA 2 — Materializar tronco: mvw_familia, mvw_pessoas, domicílio │
└───────────────────────────────┬─────────────────────────────────┘
                                ▼
┌─────────────────────────────────────────────────────────────────┐
│ ETAPA 3 — Calcular idade (operacional ou conciliação — D10)      │
└───────────────────────────────┬─────────────────────────────────┘
                                ▼
┌─────────────────────────────────────────────────────────────────┐
│ ETAPA 4 — Filtrar UNIVERSO IVCAD (famílias elegíveis)            │
└───────────────────────────────┬─────────────────────────────────┘
                                ▼
┌─────────────────────────────────────────────────────────────────┐
│ ETAPA 5 — Calcular 40 flags binários (0/1) por codigo_familiar    │
└───────────────────────────────┬─────────────────────────────────┘
                                ▼
┌─────────────────────────────────────────────────────────────────┐
│ ETAPA 6 — Calcular idx por dimensão + IVCAD por família          │
└───────────────────────────────┬─────────────────────────────────┘
                                ▼
┌─────────────────────────────────────────────────────────────────┐
│ ETAPA 7 — Agregar por município / CRAS / bairro + expor UI/agente │
└─────────────────────────────────────────────────────────────────┘
```

### Detalhamento por etapa

| Etapa | Entrada | Saída | Responsável VigSocial |
|-------|---------|-------|------------------------|
| 1 | `CECAD` CSV, opcional `SIBEC` folha | `raw.cecad__cadu`, `raw.sibec__*` | Ingestão |
| 2 | raw | `vig.mvw_*` | Vigilância → refresh views |
| 3 | `data_nascimento`, data referência | `idade` por pessoa | `pessoas_mview` / mart IVCAD |
| 4 | família + PBF + renda + atualização | `elegivel_ivcad` bool | `core.ivcad_familia` |
| 5 | pessoas + domicílio + regras VD | `nc1…nc7`, `dpi…`, … | `core.ivcad_familia` |
| 6 | flags | `idx_nc`, …, `ivcad` | `core.ivcad_familia` |
| 7 | família + território | KPIs agregados | API `/vigilance/ivcad`, painéis |

**Regra de ouro:** etapas 4–6 rodam **só** sobre famílias elegíveis; total CADU ≠ universo IVCAD.

---

## 3. Universo elegível (v1.0.5)

### 3.1 Regra em linguagem natural

Família **f** entra no universo se:

1. É **beneficiária do PBF** (folha SIBEC ou marcador consistente), **OU**
2. **Não** é PBF **e** cadastro atualizado em **≤ 24 meses** **e** renda per capita **≤ ½ salário mínimo**

### 3.2 Pseudocódigo

```
elegivel(f) =
  familia_na_folha_pbf(f)
  OR (
    meses_desatualizado(f) <= 24
    AND renda_per_capita(f) <= (salario_minimo_vigente / 2)
  )
```

### 3.3 SQL conceitual (VigSocial)

```sql
-- Parâmetros (tabela de config ou env)
-- :sm_metade = metade do SM da competência (ex. 706/2 ou valor oficial MDS)

WITH folha_pbf AS (
  SELECT DISTINCT codigo_familiar_norm AS codigo_familiar
  FROM raw.sibec__programa_bolsa_familia  -- normalizar como mvw_familia
  WHERE competencia = :ultima_competencia
),
fam AS (
  SELECT
    f.codigo_familiar,
    f.renda_per_capita,
    f.meses_desatualizado,
    COALESCE(f.marc_pbf, FALSE) AS marc_pbf_cadu,
    EXISTS (
      SELECT 1 FROM folha_pbf p WHERE p.codigo_familiar = f.codigo_familiar
    ) AS na_folha_pbf
  FROM vig.mvw_familia f
)
SELECT
  codigo_familiar,
  (
    na_folha_pbf
    OR marc_pbf_cadu  -- reforço se folha local incompleta; validar vs MDS
    OR (
      COALESCE(meses_desatualizado, 999) <= 24
      AND COALESCE(renda_per_capita, 1e9) <= :sm_metade
    )
  ) AS elegivel_ivcad
FROM fam;
```

> **Nota:** confirmar com documentação MDS se “beneficiária PBF” usa **somente folha** ou também marcador CADU. DR2 (v1.0.4) usa folha para valor PBF.

### 3.4 Contagens típicas (Observatório)

No print nacional, **~62%** das famílias CADU estão no universo IVCAD. O restante **não recebe** cálculo de flags/índice.

---

## 4. Fórmulas gerais

### 4.1 Por família (dentro do universo)

Para cada indicador binário `I_k(f) ∈ {0, 1}`:

```
idx_D(f) = (1 / n_D) * Σ I_k(f)   para k ∈ indicadores da dimensão D
```

Exemplo NC: `n_NC = 7`

```
idx_nc(f) = (NC1 + NC2 + NC3 + NC4 + NC5 + NC6 + NC7) / 7
```

Exemplo DPI: `n_DPI = 3`

```
idx_dpi(f) = (DPI1 + DPI2 + DPI3) / 3
```

Exemplo DCA: `n_DCA = 5`

```
idx_dca(f) = (DCA1 + DCA2 + DCA3 + DCA4 + DCA5) / 5
```

Exemplo TQA: `n_TQA = 7`

```
idx_tqa(f) = (TQA1 + TQA2 + TQA3 + TQA4 + TQA5 + TQA6 + TQA7) / 7
```

Exemplo DR: `n_DR = 4`

```
idx_dr(f) = (DR1 + DR2 + DR3 + DR4) / 4
```

Exemplo CH: `n_CH = 14`

```
idx_ch(f) = (CH1 + … + CH14) / 14
```

IVCAD:

```
IVCAD(f) = (idx_nc + idx_dpi + idx_dca + idx_tqa + idx_dr + idx_ch) / 6
```

Família **fora do universo:** `IVCAD(f) = NULL` (não entra em médias).

### 4.2 Indicadores binários — padrão

| Valor | Significado |
|-------|-------------|
| **1** | Família apresenta a condição de vulnerabilidade |
| **0** | Não apresenta |

Regras do tipo “∃ membro com…” → agregar com `MAX` ou `BOOL_OR` por `codigo_familiar`.  
Regras proporcionais (NC6, NC7) → razão sobre **total de membros** da família no CADU.

---

## 5. Idade e decisão D10

### 5.1 Dois modos

| Modo | Fórmula idade | Quando usar |
|------|---------------|-------------|
| **Operacional** (padrão VigSocial) | `EXTRACT(YEAR FROM age(CURRENT_DATE, data_nascimento))` | Painéis, CRAS, bairro, agente, decisão |
| **Conciliação MDS** | `EXTRACT(YEAR FROM age(dt_extracao_cecado, data_nascimento))` | Comparar com Observatório MDS |

**Motivo (D10):** CECAD é snapshot; base pode chegar com **~2 meses de atraso**. Idade dinâmica reflete vigilância **hoje**; idade na extração replica **competência MDS**.

### 5.2 Expressão SQL reutilizável

```sql
-- Operacional (padrão)
idade_operacional AS (
  EXTRACT(YEAR FROM age(CURRENT_DATE, vig.parse_cadu_date(data_nascimento::text)))::int
),

-- Conciliação (dt_extracao do LEIAME / metadado ingestão)
idade_ivcad AS (
  EXTRACT(YEAR FROM age(:dt_extracao_cecado::date, vig.parse_cadu_date(data_nascimento::text)))::int
)
```

Hoje `vig.mvw_pessoas.idade` segue modo **operacional** (equivalente a `CURRENT_DATE` na refresh).

---

## 6. Agregação territorial

### 6.1 Grain família → território

Join territorial sempre pela **família**:

```sql
FROM core.ivcad_familia iv
JOIN vig.mvw_familia f ON f.codigo_familiar = iv.codigo_familiar
-- CRAS: f.num_cras, f.nom_cras
-- Bairro: f.bairro ou dim_bairro_geo via CEP
WHERE iv.elegivel_ivcad
```

### 6.2 Métricas agregadas

| Métrica | Fórmula SQL | Uso no painel |
|---------|-------------|---------------|
| IVCAD médio | `AVG(ivcad)` | Barra / gauge principal |
| Índice dimensão D | `AVG(idx_nc)` etc. | Barras por dimensão |
| % famílias com indicador k | `100.0 * AVG(flag_nc1)` | Barras NC1–NC7 (print Observatório) |
| Famílias no universo | `COUNT(*)` | “Informações gerais” |
| % universo sobre CADU | `COUNT(universo) / COUNT(cadu)` | Contexto |

### 6.3 Exemplo — IVCAD médio por CRAS

```sql
SELECT
  COALESCE(NULLIF(btrim(f.num_cras::text), ''), '(sem CRAS)') AS cras_codigo,
  COALESCE(NULLIF(btrim(f.nom_cras::text), ''), '(sem CRAS)') AS cras_nome,
  COUNT(*)::bigint AS familias_universo,
  ROUND(AVG(iv.ivcad)::numeric, 4) AS ivcad_medio,
  ROUND(AVG(iv.idx_nc)::numeric, 4) AS idx_nc_medio
FROM core.ivcad_familia iv
JOIN vig.mvw_familia f USING (codigo_familiar)
WHERE iv.elegivel_ivcad
GROUP BY 1, 2
ORDER BY ivcad_medio DESC;
```

---

## 7. Dimensão NC — indicadores e SQL

**Referência normativa:** IN078 · VD001–VD007 · alteração NC7 v1.0.5

### 7.1 Tabela de indicadores

| Flag | VD | Condição (= 1) | Tipo |
|------|-----|----------------|------|
| **NC1** | VD001 | ∃ membro idade ≤ 3 | ∃ membro |
| **NC2** | VD002 | ∃ membro idade ≤ 6 | ∃ membro |
| **NC3** | VD003 | ∃ membro idade ≤ 12 | ∃ membro |
| **NC4** | VD004 | ∃ membro `cod_deficiencia = '1'` | ∃ membro |
| **NC5** | VD005 | ∃ membro idade ≥ 60 | ∃ membro |
| **NC6** | VD006 | adultos 18–59 / total membros ≤ 0,5 | proporção |
| **NC7** | VD007 | dependente (≤12 ou ≥60 ou PCD) **E** mulheres 18–59 / total ≤ 0,5 | composta |

**NC7 — priorizar VD007** (não só texto resumido IN078).

### 7.2 SQL de referência (NC por família)

```sql
-- Pré-requisito: pessoas com idade operacional (D10) e elegivel_ivcad já definido

WITH pess AS (
  SELECT
    p.codigo_familiar,
    p.idade,
    btrim(COALESCE(p.cod_sexo::text, '')) AS cod_sexo,
    btrim(COALESCE(p.cod_deficiencia::text, '')) IN ('1', '01') AS tem_def_mds
  FROM vig.mvw_pessoas p
),
agg AS (
  SELECT
    codigo_familiar,
    COUNT(*)::numeric AS n_membros,
    MAX(CASE WHEN idade IS NOT NULL AND idade <= 3  THEN 1 ELSE 0 END) AS nc1,
    MAX(CASE WHEN idade IS NOT NULL AND idade <= 6  THEN 1 ELSE 0 END) AS nc2,
    MAX(CASE WHEN idade IS NOT NULL AND idade <= 12 THEN 1 ELSE 0 END) AS nc3,
    MAX(CASE WHEN tem_def_mds THEN 1 ELSE 0 END) AS nc4,
    MAX(CASE WHEN idade IS NOT NULL AND idade >= 60 THEN 1 ELSE 0 END) AS nc5,
    COUNT(*) FILTER (WHERE idade BETWEEN 18 AND 59)::numeric AS n_adultos,
    COUNT(*) FILTER (
      WHERE idade BETWEEN 18 AND 59 AND cod_sexo IN ('2', '02')
    )::numeric AS n_mulheres_adultas,
    MAX(CASE WHEN idade IS NOT NULL AND idade <= 12 THEN 1 ELSE 0 END) AS tem_crianca_12,
    MAX(CASE WHEN idade IS NOT NULL AND idade >= 60 THEN 1 ELSE 0 END) AS tem_idoso,
    MAX(CASE WHEN tem_def_mds THEN 1 ELSE 0 END) AS tem_pcd
  FROM pess
  GROUP BY codigo_familiar
),
nc AS (
  SELECT
    codigo_familiar,
    nc1, nc2, nc3, nc4, nc5,
    CASE WHEN n_membros > 0 AND (n_adultos / n_membros) <= 0.5 THEN 1 ELSE 0 END AS nc6,
    CASE
      WHEN (tem_crianca_12 = 1 OR tem_idoso = 1 OR tem_pcd = 1)
       AND n_membros > 0
       AND (n_mulheres_adultas / n_membros) <= 0.5
      THEN 1 ELSE 0
    END AS nc7,
    (nc1 + nc2 + nc3 + nc4 + nc5
      + CASE WHEN n_membros > 0 AND (n_adultos / n_membros) <= 0.5 THEN 1 ELSE 0 END
      + CASE
          WHEN (tem_crianca_12 = 1 OR tem_idoso = 1 OR tem_pcd = 1)
           AND n_membros > 0 AND (n_mulheres_adultas / n_membros) <= 0.5
          THEN 1 ELSE 0
        END
    ) / 7.0 AS idx_nc
  FROM agg
)
SELECT * FROM nc;
```

### 7.3 Sobreposição NC1 ⊂ NC2 ⊂ NC3

Intencional: família com bebê de 2 anos marca **1** em NC1, NC2 e NC3. O índice NC reflete **múltiplos sinais** de necessidade de cuidado, não categorias mutuamente exclusivas.

---

## 7b. Dimensão DPI — resumo

**Referência normativa:** IN079 · VD008–VD010 · [documento completo](../04-ivcad-dimensao-dpi.md)

**Fórmula:** `idx_dpi = (DPI1 + DPI2 + DPI3) / 3`

| Flag | VD | Faixa etária | Condição (= 1) |
|------|-----|--------------|----------------|
| **DPI1** | VD008 | 4–6 anos | `ind_frequenta_escola IN ('3','4')` — não frequenta / nunca frequentou |
| **DPI2** | VD009 | 0–6 anos | idem |
| **DPI3** | VD010 | 0–6 anos | `cod_parentesco_rf NOT IN ('3','4')` — não filho(a) nem enteado(a) do RF |

**Sobreposição:** criança 5 anos fora da escola marca DPI1 **e** DPI2; neto 4 anos do RF pode marcar DPI2 **e** DPI3.

**Benchmark Brasil (Observatório):** idx_dpi ≈ 0,078 · DPI1 3,5% · DPI2 18,3% · DPI3 1,4% das famílias no universo IVCAD.

---

## 7c. Dimensão DCA — resumo

**Referência normativa:** IN080 · VD011–VD015 · [documento completo](../05-ivcad-dimensao-dca.md)

**Fórmula:** `idx_dca = (DCA1 + DCA2 + DCA3 + DCA4 + DCA5) / 5`

| Flag | VD | Faixa | Condição (= 1) |
|------|-----|-------|----------------|
| **DCA1** | VD011 | 7–15* | Trabalho infantil: flag `<16` **ou** 10–15 trabalhando/afastado (14–15 exclui estagiário/aprendiz) |
| **DCA2** | VD012 | 15–17 | `ind_frequenta_escola IN ('3','4')` |
| **DCA3** | VD013 | 7–17 | idem |
| **DCA4** | VD014 | 10–17 | `cod_sabe_ler_escrever = 2` (analfabeto) |
| **DCA5** | VD015 | 10–17 | `idade - (7 + anos_estudo) > 2` (VD048) |

\* DCA1 alterado em **IVCAD v1.0.2**.

**Benchmark Brasil (Observatório):** idx_dca ≈ 0,049 · DCA1 0,01% · DCA2 0,6% · DCA3 1,1% · DCA4 9,7% · DCA5 13,9%.

**Gap VigSocial:** `cod_trabalhou` / `cod_afastado_trab` (raw only); `anos_estudo` (VD048) a implementar.

---

## 7d. Dimensão TQA — resumo

**Referência normativa:** IN081 · VD016–VD022 · [documento completo](../06-ivcad-dimensao-tqa.md)

**Fórmula:** `idx_tqa = (TQA1 + … + TQA7) / 7` · **Faixa:** adultos **18–59**

| Flag | VD | Condição (= 1) |
|------|-----|----------------|
| **TQA1** | VD016 | ∃ adulto analfabeto (`sabe_ler=2`) ou `anos_estudo ≤ 3` |
| **TQA2** | VD017 | ∃ adulto `anos_estudo < 8` |
| **TQA3** | VD018 | ∃ adulto `anos_estudo < 11` |
| **TQA4** | VD019 | **Nenhum** adulto ocupado |
| **TQA5** | VD020 | **Nenhum** adulto ocupado formal (CLT 4, doméstico 6, militar 8, empregador 9†, estagiário 10, aprendiz 11) |
| **TQA6** | VD021 | **Nenhum** ocupado com rendimento ≥ 1 SM |
| **TQA7** | VD022 | **Nenhum** ocupado com rendimento ≥ 2 SM |

† Código 9 excluído em **v1.0.6**.

**Ocupado:** trabalhou semana passada **ou** afastado (doença, férias, etc.).

**Benchmark Brasil:** idx_tqa ≈ 0,636 · TQA1 17,2% · … · TQA7 99,9%.

---

## 7e. Dimensão DR — resumo

**Referência normativa:** IN082 · VD023–VD026 · [documento completo](../07-ivcad-dimensao-dr.md)

**Fórmula:** `idx_dr = (DR1 + DR2 + DR3 + DR4) / 4` · **Limiar pobreza:** R$ **218** (per capita)

| Flag | VD | Condição (= 1) |
|------|-----|----------------|
| **DR1** | VD023 | Sem renda: `vlrtotal + renda_pc × n = 0` |
| **DR2** | VD024 | `(renda_pc + vlrtotal/n) ≤ 218` — **com PBF** |
| **DR3** | VD025 | `renda_pc ≤ 218` — CADU, sem PBF |
| **DR4** | VD026 | `(renda_pc - bpc_pc_retirar) ≤ 218` — sem PBF e BPC (Maciça) |

**Satélites:** folha PBF (DR1, DR2); Maciça BPC + aposent. membro (DR4). DR2 alterado **v1.0.4** (fonte PBF = folha).

**Benchmark Brasil:** idx_dr ≈ 0,409 · DR1 3,5% · DR2 12,0% · DR3 70,9% · DR4 77,0%.

---

## 7f. Dimensão CH — resumo

**Referência normativa:** IN083 · VD027–VD040 · [documento completo](../08-ivcad-dimensao-ch.md)

**Fórmula:** `idx_ch = (CH1 + … + CH14) / 14`

**Regra transversal:** `SIT_RUA = 1` **ou** domicílio improvisado (espécie = 2) → **todos** CH1–CH14 = **1**.

| Grupo | Indicadores |
|-------|-------------|
| Moradia extrema | CH1 |
| Densidade / aluguel | CH2–CH4 |
| Material (piso/parede) | CH5–CH6 |
| Água / esgoto / banheiro | CH7–CH10 |
| Lixo / energia | CH11–CH14 |

**Fonte:** `vig.mvw_familia_domicilio` + `renda_per_capita` + despesa aluguel (raw).

**Benchmark Brasil:** idx_ch ≈ 0,171 · CH10 38,1% · CH4 30,3% · CH7 27,4%.

---

## 8. Matriz completa (40 indicadores)

Todas as dimensões documentadas — detalhes nos arquivos `03`–`08`:

| Dimensão | Códigos IN | Indicadores | Fonte principal | Doc |
|----------|------------|-------------|-----------------|-----|
| NC | IN078 | 7 (VD001–07) | `mvw_pessoas`, domicílio | ✅ [03](../03-ivcad-dimensao-nc.md) |
| DPI | IN079 | 3 (VD008–10) | `mvw_pessoas` idade, escola, parentesco | ✅ [04](../04-ivcad-dimensao-dpi.md) |
| DCA | IN080 | 5 (VD011–15) | `mvw_pessoas`, VD048 anos estudo | ✅ [05](../05-ivcad-dimensao-dca.md) |
| TQA | IN081 | 7 (VD016–22) | `mvw_pessoas`, VD048, renda/SM | ✅ [06](../06-ivcad-dimensao-tqa.md) |
| DR | IN082 | 4 (VD023–26) | `mvw_familia`, folha PBF, Maciça BPC | ✅ [07](../07-ivcad-dimensao-dr.md) |
| CH | IN083 | 14 (VD027–40) | `mvw_familia_domicilio` | ✅ [08](../08-ivcad-dimensao-ch.md) |

**Status:** 40 / 40 indicadores documentados (v1.0.5).

---

## 9. Catálogo de indicadores (template)

Cada indicador no repositório / API deve seguir esta ficha (YAML):

```yaml
id: nc1
codigo_mds: VD001
dimensao: NC
titulo: Presença de criança de 0 a 3 anos
versao_ivcad: "1.0.5"
grain: familia
universo: elegivel_ivcad
tipo: binario
valor_1_quando: "Existe membro com idade <= 3"
fontes:
  - vig.mvw_pessoas
campos:
  - idade
  - data_nascimento
idade_modo: operacional  # ou conciliacao_mds
sql_flag: "MAX(CASE WHEN idade <= 3 THEN 1 ELSE 0 END)"
dimensao_sql: "idx_nc = (nc1+...+nc7)/7"
ivcad_sql: "ivcad = (idx_nc+...+idx_ch)/6"
painel: ivcad-nc
agente: canonical.ivcad.nc1
filtros: [cras, bairro]
```

Arquivo futuro sugerido: `apps/api/app/ivcad/catalog.yaml`

---

## 10. Métricas para painéis

Espelho do Observatório MDS:

| Bloco UI | Métrica | Cálculo |
|----------|---------|---------|
| Gauge IVCAD | Índice sintético | `AVG(ivcad)` no recorte |
| Barras dimensão | NC, DPI, … | `AVG(idx_nc)`, … |
| Barras indicador | NC1…NC7 | `100 * AVG(nc1)`, … (% famílias vulneráveis) |
| Info geral | Famílias analisadas | `COUNT(*) WHERE elegivel_ivcad` |
| Info geral | % sobre CADU | divisão pelo total `mvw_familia` |
| Info geral | % acima média dimensão | famílias com `idx_nc > AVG(idx_nc)` no recorte |

---

## 11. Validação e conciliação MDS

| Objetivo | Modo idade | Comparação |
|----------|------------|------------|
| Vigilância municipal | Operacional | Uso interno; não exige match MDS |
| Auditoria / publicação | Conciliação | IVCAD municipal vs Observatório MDS |

Checklist de validação:

1. Mesma **competência** / data extração CECAD  
2. Mesmo **universo** v1.0.5  
3. Idade na **data de extração** (modo conciliação)  
4. NC7 com regra **v1.0.5** (dependente + proporção mulheres)  
5. Tolerância numérica pequena (arredondamento)

---

## 12. Decisões VigSocial

| ID | Decisão |
|----|---------|
| D5 | Grain família; agregação município + **CRAS** + **bairro** |
| D6 | Implementar **v1.0.5** antes de 1.0.6 |
| D7 | Universo elegível **antes** dos 40 flags |
| D8 | Fonte IVCAD = CADU; SIBEC onde metodologia exige |
| D10 | Idade **operacional** = `CURRENT_DATE`; conciliação = `DT_EXTRACAO` CECAD |

---

## 13. Roadmap de implementação

| Fase | Entrega | Status |
|------|---------|--------|
| A | Documentação IN084 + 6 dimensões (40 indicadores) | ✅ |
| B | ~~Documentar CH~~ | ✅ |
| C | `core.ivcad_familia` (view/materialized) | ⏳ |
| D | API + painel IVCAD + filtros CRAS/bairro | ⏳ |
| E | Métricas canônicas agente (`ivcad`, `idx_nc`, …) | ⏳ |
| F | Validação conciliação vs Observatório municipal | ⏳ |
| G | Migração v1.0.6 (universo PBF suspenso, TQA5) | ⏳ |

---

*Guia mantido pelo time VigSocial. Atualizar ao receber novos IN/VD do MDS.*
