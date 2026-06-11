# IVCAD — Dimensão TQA (Trabalho e Qualificação de Adultos)

> **IN081** — dimensão TQA · **VD016–VD022** — indicadores binários  
> **Fórmula dimensão:** `idx_tqa = (TQA1 + TQA2 + TQA3 + TQA4 + TQA5 + TQA6 + TQA7) / 7`  
> **Referência:** [`ivcad/GUIA-REFERENCIA.md`](./ivcad/GUIA-REFERENCIA.md) · [`05-ivcad-dimensao-dca.md`](./05-ivcad-dimensao-dca.md)

---

## 1. Interpretação (IN081)

A dimensão **TQA** sinaliza vulnerabilidade de **adultos de 18 a 59 anos** em relação a:

1. **Escolaridade** — analfabetismo, fundamental incompleto, médio incompleto;  
2. **Inserção no mercado de trabalho** — ausência de adulto ocupado, de ocupação formal, ou com rendimento ≥ 1 ou ≥ 2 salários mínimos.

O **índice sintético da dimensão** = proporção média dos **7 indicadores binários** (grain **família**).

| Metadado | Valor |
|----------|-------|
| Código dimensão | IN081 |
| Domínio | 0 a 1 |
| Fonte | Cadastro Único |
| Periodicidade | Mensal |
| Desagregação MDS | Municipal |
| Desagregação VigSocial | Municipal + **CRAS** + **bairro** |

**Faixa etária comum:** `18 ≤ idade ≤ 59` (todos os indicadores TQA).

### 1.1 Exemplo Observatório (Brasil — print TQA)

| Elemento | Valor |
|----------|-------|
| **idx_tqa** (IVCAD-TQA) | 0,636 |
| Famílias no universo IVCAD | 26.373.806 (62,1% do CADU) |
| **TQA1** — % famílias vulneráveis | 17,2% (4.539.785 famílias) |
| **TQA2** — % famílias vulneráveis | 41,1% (10.847.487 famílias) |
| **TQA3** — % famílias vulneráveis | 62,7% (16.541.206 famílias) |
| **TQA4** — % famílias vulneráveis | 47,3% (12.474.831 famílias) |
| **TQA5** — % famílias vulneráveis | 81,0% |
| **TQA6** — % famílias vulneráveis | 96,6% |
| **TQA7** — % famílias vulneráveis | 99,9% |

**Leitura:** TQA é a dimensão de **maior índice médio** no universo IVCAD (~0,64). TQA6 e TQA7 concentram quase todas as famílias — poucos adultos ocupados com rendimento ≥ 1 ou 2 SM.

---

## 2. Matriz de indicadores

| Flag | VD | Indicador | Lógica (= 1) | Campos CECAD (MDS) | VigSocial |
|------|-----|-----------|--------------|--------------------|-----------|
| **TQA1** | VD016 | Adulto analfabeto ou funcional | ∃ adulto 18–59 analfabeto **ou** `anos_estudo ≤ 3` | `IDADE`, `ANOS_ESTUDO`, `CO_SABE_LER_ESCREVER_MEMB` | `idade`, `cod_sabe_ler_escrever`, VD048‡ |
| **TQA2** | VD017 | Sem fundamental completo | ∃ adulto 18–59 com `anos_estudo < 8` | `IDADE`, `ANOS_ESTUDO` | idem |
| **TQA3** | VD018 | Sem médio completo | ∃ adulto 18–59 com `anos_estudo < 11` | idem | idem |
| **TQA4** | VD019 | Nenhum adulto ocupado | **Não** ∃ adulto 18–59 ocupado | `IDADE`, `CO_TRABALHOU_SEMANA_MEMB`, `CO_AFASTADO_TRAB_MEMB` | `idade`, `cod_trabalhou`†, `cod_afastado_trab`† |
| **TQA5** | VD020 | Nenhum adulto ocupado formal | **Não** ∃ adulto 18–59 ocupado formal | + `CO_PRINCIPAL_TRAB_MEMB` | + `cod_principal_trab` |
| **TQA6** | VD021 | Nenhum ocupado com renda ≥ 1 SM | **Não** ∃ adulto 18–59 ocupado com rendimento ≥ 1 SM | + `VL_REMUNER_EMPREGO_MEMB`, `VL_RENDA_BRUTA_12_MESES_MEMB` | faixas `fx_renda_*`†† ou valores contínuos |
| **TQA7** | VD022 | Nenhum ocupado com renda ≥ 2 SM | **Não** ∃ adulto 18–59 ocupado com rendimento ≥ 2 SM | idem | idem |

‡ `ANOS_ESTUDO` — variável construída [VD048](https://wiki-sagi.cidadania.gov.br/home/DS/Cad/VD/VD048).  
† Campos no CECAD bruto; **ainda não** em `vig.mvw_pessoas`.  
†† Layout **tudo** expõe faixas `fx_renda_individual_805` (mês) e `808` (12 meses), não valores contínuos MDS.

---

## 3. Conceitos auxiliares

### 3.1 Adulto ocupado

Pessoa **ocupada** na semana anterior à entrevista:

```
ocupado = (CO_TRABALHOU_SEMANA_MEMB = 1)
       OR (CO_TRABALHOU_SEMANA_MEMB = 2 AND CO_AFASTADO_TRAB_MEMB = 1)
```

De-para VigSocial: `cod_trabalhou` = 1 (sim) ou 2 (não) + `cod_afastado_trab` = 1 (sim).

### 3.2 Adulto ocupado no setor formal (TQA5)

```
ocupado_formal = ocupado
  AND CO_PRINCIPAL_TRAB_MEMB IN (4, 6, 8, 9, 10, 11)   -- v1.0.5 (VD020)
```

| Código | Função principal |
|--------|------------------|
| 4 | Empregado com carteira assinada |
| 6 | Trabalhador doméstico com carteira |
| 8 | Militar ou servidor público |
| 9 | Empregador |
| 10 | Estagiário |
| 11 | Aprendiz |

**IVCAD v1.0.6:** código **9 (empregador) deixa de contar** como formal — permanecem 4, 6, 8, 10, 11. VigSocial implementa **v1.0.5** primeiro (decisão D6); documentar ambas as regras.

### 3.3 Rendimento do trabalho (TQA6 / TQA7)

Para adulto **ocupado**:

```
rendimento_trabalho = MIN(
  VL_REMUNER_EMPREGO_MEMB,
  VL_RENDA_BRUTA_12_MESES_MEMB / 12
)
```

Comparar com **salário mínimo vigente** na competência da extração (`DT_EXTRACAO_DADOS`):

| Indicador | Limiar |
|-----------|--------|
| TQA6 | rendimento < 1 SM → família **não** tem adulto com ≥ 1 SM → **TQA6 = 1** |
| TQA7 | rendimento < 2 SM → **TQA7 = 1** |

**TQA6/TQA7 = 1** quando a família **não possui nenhum** adulto 18–59 ocupado cujo rendimento atinja o limiar.

### 3.4 Anos de estudo — limiares

| Conceito | Limiar `ANOS_ESTUDO` |
|----------|----------------------|
| Analfabeto funcional (TQA1) | ≤ 3 |
| Fundamental completo | ≥ 8 |
| Médio completo | ≥ 11 |

Fonte: VD048.

---

## 4. Regras detalhadas (VD016–VD022)

### TQA1 (VD016)

```
∃ adulto p: 18 ≤ idade(p) ≤ 59
  AND (
    cod_sabe_ler_escrever(p) = 2          -- analfabeto
    OR anos_estudo(p) <= 3                -- analfabeto funcional
  )
→ TQA1 = 1
```

### TQA2 (VD017)

```
∃ adulto p: 18 ≤ idade(p) ≤ 59 AND anos_estudo(p) < 8
→ TQA2 = 1
```

### TQA3 (VD018)

```
∃ adulto p: 18 ≤ idade(p) ≤ 59 AND anos_estudo(p) < 11
→ TQA3 = 1
```

### TQA4 (VD019)

```
NOT EXISTS adulto p: 18 ≤ idade(p) ≤ 59 AND ocupado(p)
→ TQA4 = 1
```

### TQA5 (VD020)

```
NOT EXISTS adulto p: 18 ≤ idade(p) ≤ 59 AND ocupado_formal(p)
→ TQA5 = 1
```

### TQA6 (VD021)

```
NOT EXISTS adulto p: 18 ≤ idade(p) ≤ 59
  AND ocupado(p)
  AND rendimento_trabalho(p) >= salario_minimo_vigente
→ TQA6 = 1
```

### TQA7 (VD022)

```
NOT EXISTS adulto p: 18 ≤ idade(p) ≤ 59
  AND ocupado(p)
  AND rendimento_trabalho(p) >= 2 * salario_minimo_vigente
→ TQA7 = 1
```

### Índice da dimensão

```
idx_tqa = (TQA1 + TQA2 + TQA3 + TQA4 + TQA5 + TQA6 + TQA7) / 7.0
```

**Sobreposição:** adulto com 2 anos de estudo marca TQA1 **e** TQA2 **e** TQA3; família sem ocupado formal marca TQA5 **e** tipicamente TQA6/TQA7.

**Cadeia escolar:** TQA1 ⊂ TQA2 ⊂ TQA3 em muitos casos (anos ≤ 3 implica < 8 e < 11).

---

## 5. SQL de referência (VigSocial)

### 5.1 Expressões reutilizáveis

```sql
-- Adulto 18-59
idade BETWEEN 18 AND 59

-- Ocupado (após materializar cod_trabalhou / cod_afastado_trab)
(
  cod_trabalhou IN ('1', '01')
  OR (cod_trabalhou IN ('2', '02') AND cod_afastado_trab IN ('1', '01'))
) AS ocupado

-- Formal v1.0.5
ocupado AND cod_principal_trab IN ('4','04','6','06','8','08','9','09','10','11')

-- Formal v1.0.6 (sem empregador)
ocupado AND cod_principal_trab IN ('4','04','6','06','8','08','10','11')
```

### 5.2 TQA1–TQA3 (parcial — requer `anos_estudo`)

```sql
WITH pess AS (
  SELECT
    p.codigo_familiar,
    p.idade,
    btrim(COALESCE(p.cod_sabe_ler_escrever::text, '')) AS sabe_ler
    -- , vig.anos_estudo(p) AS anos_estudo  -- VD048
  FROM vig.mvw_pessoas p
),
flags AS (
  SELECT
    codigo_familiar,
    MAX(CASE
      WHEN idade BETWEEN 18 AND 59
       AND (sabe_ler IN ('2', '02') OR anos_estudo <= 3)
      THEN 1 ELSE 0
    END) AS tqa1,
    MAX(CASE
      WHEN idade BETWEEN 18 AND 59 AND anos_estudo < 8
      THEN 1 ELSE 0
    END) AS tqa2,
    MAX(CASE
      WHEN idade BETWEEN 18 AND 59 AND anos_estudo < 11
      THEN 1 ELSE 0
    END) AS tqa3
  FROM pess
  GROUP BY codigo_familiar
)
SELECT * FROM flags;
```

### 5.3 TQA4–TQA5 (por família — lógica invertida)

```sql
WITH adultos AS (
  SELECT
    codigo_familiar,
    MAX(CASE WHEN idade BETWEEN 18 AND 59 AND ocupado THEN 1 ELSE 0 END) AS tem_ocupado,
    MAX(CASE WHEN idade BETWEEN 18 AND 59 AND ocupado_formal THEN 1 ELSE 0 END) AS tem_formal
  FROM pess_enriched
  GROUP BY codigo_familiar
)
SELECT
  codigo_familiar,
  CASE WHEN tem_ocupado = 0 THEN 1 ELSE 0 END AS tqa4,
  CASE WHEN tem_formal = 0 THEN 1 ELSE 0 END AS tqa5
FROM adultos;
```

### 5.4 TQA6–TQA7 (rendimento + SM)

```sql
-- rendimento_trabalho e parametro salario_minimo(competencia)
WITH rend AS (
  SELECT
    codigo_familiar,
    MAX(CASE
      WHEN idade BETWEEN 18 AND 59 AND ocupado
       AND rendimento_trabalho >= :sm
      THEN 1 ELSE 0
    END) AS tem_ocupado_1sm
  FROM pess_enriched
  GROUP BY codigo_familiar
)
SELECT
  codigo_familiar,
  CASE WHEN tem_ocupado_1sm = 0 THEN 1 ELSE 0 END AS tqa6,
  CASE WHEN tem_ocupado_2sm = 0 THEN 1 ELSE 0 END AS tqa7  -- idem com 2*:sm
FROM rend;
```

### 5.5 Índice por família

```sql
SELECT
  codigo_familiar,
  tqa1, tqa2, tqa3, tqa4, tqa5, tqa6, tqa7,
  (tqa1 + tqa2 + tqa3 + tqa4 + tqa5 + tqa6 + tqa7) / 7.0 AS idx_tqa
FROM flags;
```

---

## 6. Idade (decisão D10)

Mesma regra das demais dimensões: idade **operacional** para vigilância; **`DT_EXTRACAO`** para conciliação MDS. Faixa 18–59 é sensível a defasagem da base CECAD.

---

## 7. Cobertura VigSocial

| Requisito | Campo / expressão | Disponível |
|-----------|-------------------|------------|
| Idade 18–59 | `mvw_pessoas.idade` | ✅ |
| Sabe ler/escrever | `cod_sabe_ler_escrever` | ✅ |
| Anos de estudo (VD048) | derivar | ⚠️ pendente |
| Trabalhou / afastado | raw `cod_trabalhou_memb`, `cod_afastado_trab_memb` | ⚠️ raw only |
| Função principal | `cod_principal_trab` | ✅ |
| Remuneração contínua | `VL_REMUNER_*` (MDS) | ❌ layout tudo usa faixas |
| Faixas renda | `fx_renda_individual_805`, `808` | ✅ na MV |
| Salário mínimo mensal | parâmetro por competência | ⚠️ pendente |
| Grau instrução (auxiliar) | `grau_instrucao`, cursos/série | ✅ |

**Ações de implementação:**

- [ ] `vig.anos_estudo(...)` conforme VD048 (TQA1–TQA3, DCA5)  
- [ ] Incluir `cod_trabalhou`, `cod_afastado_trab` em `mvw_pessoas`  
- [ ] Tabela `param.salario_minimo` por competência (TQA6–TQA7, universo IVCAD)  
- [ ] Estratégia faixas → limiar SM (`fx_renda_805`/`808`) ou ingestão de valores contínuos  
- [ ] Flag `versao_ivcad` para TQA5 (v1.0.5 vs v1.0.6)  

---

## 8. Ficha catálogo (YAML)

```yaml
id: tqa5
codigo_mds: VD020
dimensao: TQA
in081: true
titulo: Nenhum adulto ocupado no setor formal
versao_ivcad: "1.0.5"
grain: familia
universo: elegivel_ivcad
tipo: binario
valor_1_quando: "NOT EXISTS adulto 18-59 ocupado com cod_principal_trab in (4,6,8,9,10,11)"
notas_versao: "v1.0.6 remove cod 9 (empregador)"
fontes:
  - vig.mvw_pessoas
campos:
  - idade
  - cod_trabalhou
  - cod_afastado_trab
  - cod_principal_trab
dimensao_sql: "idx_tqa = (tqa1+...+tqa7)/7"
ivcad_sql: "ivcad = (idx_nc+idx_dpi+idx_dca+idx_tqa+idx_dr+idx_ch)/6"
```

---

## 9. Progresso IVCAD (40 indicadores)

| Dimensão | Indicadores | Status doc |
|----------|-------------|------------|
| NC | 7 (VD001–VD007) | ✅ [03-ivcad-dimensao-nc.md](./03-ivcad-dimensao-nc.md) |
| DPI | 3 (VD008–VD010) | ✅ [04-ivcad-dimensao-dpi.md](./04-ivcad-dimensao-dpi.md) |
| DCA | 5 (VD011–VD015) | ✅ [05-ivcad-dimensao-dca.md](./05-ivcad-dimensao-dca.md) |
| **TQA** | **7 (VD016–VD022)** | ✅ [06-ivcad-dimensao-tqa.md](./06-ivcad-dimensao-tqa.md) |
| DR | 4 (VD023–VD026) | ✅ [07-ivcad-dimensao-dr.md](./07-ivcad-dimensao-dr.md) |
| CH | 14 (VD027–VD040) | ✅ [08-ivcad-dimensao-ch.md](./08-ivcad-dimensao-ch.md) |
| **Total documentado** | **40 / 40** | ✅ |

---

*Documentação TQA validada a partir de IN081, VD016–VD022 e print Observatório MDS.*
