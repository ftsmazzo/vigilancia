# IVCAD — Dimensão DPI (Desenvolvimento na Primeira Infância)

> **IN079** — dimensão DPI · **VD008–VD010** — indicadores binários  
> **Fórmula dimensão:** `idx_dpi = (DPI1 + DPI2 + DPI3) / 3`  
> **Referência:** [`ivcad/GUIA-REFERENCIA.md`](./ivcad/GUIA-REFERENCIA.md) · [`03-ivcad-dimensao-nc.md`](./03-ivcad-dimensao-nc.md)

---

## 1. Interpretação (IN079)

A dimensão **DPI** sinaliza vulnerabilidade de **crianças de 0 a 6 anos** em relação a:

1. **Acesso a creche/pré-escola/escola** (não frequenta ou nunca frequentou);  
2. **Composição familiar** — criança que **não** é filho(a) nem enteado(a) do responsável familiar (possível necessidade de acompanhamento mais estreito pela assistência social).

O **índice sintético da dimensão** = proporção média dos **3 indicadores binários** (grain **família**).

| Metadado | Valor |
|----------|-------|
| Código dimensão | IN079 |
| Domínio | 0 a 1 |
| Fonte | Cadastro Único |
| Periodicidade | Mensal |
| Desagregação MDS | Municipal |
| Desagregação VigSocial | Municipal + **CRAS** + **bairro** |

### 1.1 Exemplo Observatório (Brasil — print DPI)

| Elemento | Valor |
|----------|-------|
| **idx_dpi** (IVCAD-DPI) | 0,078 |
| Famílias no universo IVCAD | 26.373.806 (62,1% do CADU) |
| **DPI1** — % famílias vulneráveis | 3,5% (935.833 famílias) |
| **DPI2** — % famílias vulneráveis | 18,3% (4.836.660 famílias) |
| **DPI3** — % famílias vulneráveis | 1,4% (379.882 famílias) |

---

## 2. Matriz de indicadores

| Flag | VD | Indicador | Valor 1 quando | Campos CECAD (MDS) | VigSocial |
|------|-----|-----------|------------------|--------------------|-----------|
| **DPI1** | VD008 | Criança **4–6** anos sem escola/creche | ∃ criança 4≤idade≤6 com escola = não frequenta (3) ou nunca (4) | `IDADE`, `IN_FREQUENTA_ESCOLA_MEMB` | `idade`, `ind_frequenta_escola` |
| **DPI2** | VD009 | Criança **0–6** anos sem escola/creche | ∃ criança 0≤idade≤6 com escola = 3 ou 4 | idem | idem |
| **DPI3** | VD010 | Criança **0–6** não filho/enteado do RF | ∃ criança 0≤idade≤6 com parentesco ≠ filho(3) e ≠ enteado(4) | `IDADE`, `CO_PARENTESCO_RF_PESSOA` | `idade`, `cod_parentesco_rf` |

### 2.1 Domínios de variáveis (dicionário CECAD)

**`ind_frequenta_escola`** (`p_ind_frequenta_escola_memb`):

| Código | Significado | Conta para DPI1/DPI2? |
|--------|-------------|------------------------|
| 1 | Sim, rede pública | ❌ (frequenta) |
| 2 | Sim, rede particular | ❌ (frequenta) |
| 3 | Não, já frequentou | ✅ vulnerável |
| 4 | Nunca frequentou | ✅ vulnerável |

**`cod_parentesco_rf`** (`p_cod_parentesco_rf_pessoa`):

| Código | Significado | Conta para DPI3? |
|--------|-------------|------------------|
| 3 | Filho(a) | ❌ (não vulnerável por parentesco) |
| 4 | Enteado(a) | ❌ |
| Outros (1,2,5…11) | RF, cônjuge, neto, não parente… | ✅ se criança 0–6 |

---

## 3. Regras detalhadas (VD008–VD010)

### DPI1 (VD008)

```
∃ pessoa p na família tal que:
  idade(p) >= 4 AND idade(p) <= 6
  AND ind_frequenta_escola(p) IN ('3', '4')  -- já frequentou / nunca frequentou
→ DPI1 = 1, senão 0
```

### DPI2 (VD009)

```
∃ pessoa p na família tal que:
  idade(p) >= 0 AND idade(p) <= 6
  AND ind_frequenta_escola(p) IN ('3', '4')
→ DPI2 = 1, senão 0
```

### DPI3 (VD010)

```
∃ pessoa p na família tal que:
  idade(p) >= 0 AND idade(p) <= 6
  AND cod_parentesco_rf(p) NOT IN ('3', '4')  -- não filho nem enteado
→ DPI3 = 1, senão 0
```

### Índice da dimensão

```
idx_dpi = (DPI1 + DPI2 + DPI3) / 3.0
```

**Sobreposição:** criança 5 anos fora da escola marca **1** em DPI1 **e** DPI2; criança 4 anos neto do RF pode marcar DPI2 **e** DPI3.

---

## 4. SQL de referência (VigSocial)

```sql
-- Idade operacional (D10): vig.mvw_pessoas.idade
-- Universo IVCAD: elegivel_ivcad = true (ver GUIA-REFERENCIA §3)

WITH pess AS (
  SELECT
    p.codigo_familiar,
    p.idade,
    btrim(COALESCE(p.ind_frequenta_escola::text, '')) AS freq_escola,
    btrim(COALESCE(p.cod_parentesco_rf::text, '')) AS parentesco
  FROM vig.mvw_pessoas p
),
flags AS (
  SELECT
    codigo_familiar,
    MAX(CASE
      WHEN idade BETWEEN 4 AND 6
       AND freq_escola IN ('3', '03', '4', '04')
      THEN 1 ELSE 0
    END) AS dpi1,
    MAX(CASE
      WHEN idade BETWEEN 0 AND 6
       AND freq_escola IN ('3', '03', '4', '04')
      THEN 1 ELSE 0
    END) AS dpi2,
    MAX(CASE
      WHEN idade BETWEEN 0 AND 6
       AND parentesco NOT IN ('3', '03', '4', '04')
       AND parentesco <> ''
      THEN 1 ELSE 0
    END) AS dpi3
  FROM pess
  GROUP BY codigo_familiar
)
SELECT
  codigo_familiar,
  dpi1,
  dpi2,
  dpi3,
  (dpi1 + dpi2 + dpi3) / 3.0 AS idx_dpi
FROM flags;
```

### 4.1 Agregação painel (como Observatório)

```sql
-- % famílias vulneráveis por indicador (universo IVCAD)
SELECT
  ROUND(100.0 * AVG(dpi1), 2) AS pct_dpi1,
  ROUND(100.0 * AVG(dpi2), 2) AS pct_dpi2,
  ROUND(100.0 * AVG(dpi3), 2) AS pct_dpi3,
  ROUND(AVG(idx_dpi)::numeric, 4) AS idx_dpi_medio
FROM core.ivcad_familia iv
JOIN flags f USING (codigo_familiar)
WHERE iv.elegivel_ivcad;
```

---

## 5. Idade (decisão D10)

Mesma regra da dimensão NC:

| Modo | Uso |
|------|-----|
| **Operacional** (`CURRENT_DATE`) | Vigilância municipal — padrão VigSocial |
| **Conciliação MDS** (`DT_EXTRACAO` CECAD) | Validar idx_dpi vs Observatório |

Faixas 0–6 e 4–6 dependem de idade; base defasada ~2 meses reforça uso operacional.

---

## 6. Cobertura VigSocial

| Requisito DPI | Campo / expressão | Disponível |
|---------------|-------------------|------------|
| Idade 0–6 / 4–6 | `mvw_pessoas.idade` | ✅ |
| Frequenta escola | `mvw_pessoas.ind_frequenta_escola` | ✅ |
| Parentesco RF | `mvw_pessoas.cod_parentesco_rf` | ✅ |
| Agregação familiar | `codigo_familiar` | ✅ |
| Território | `mvw_familia.num_cras`, bairro | ✅ |

**Pendências:**

- [ ] Política para `ind_frequenta_escola` NULL ou vazio (MDS não detalha → tratar como **não vulnerável** ou **não informado** — definir)  
- [ ] Política para `idade` NULL em criança  
- [ ] DPI3: parentesco vazio — excluir da condição `NOT IN (3,4)` (SQL acima exige `parentesco <> ''`)

---

## 7. Ficha catálogo (YAML)

```yaml
id: dpi2
codigo_mds: VD009
dimensao: DPI
in079: true
titulo: Criança 0-6 anos que não frequenta ou nunca frequentou escola/creche
versao_ivcad: "1.0.5"
grain: familia
universo: elegivel_ivcad
tipo: binario
valor_1_quando: "Criança 0-6 com ind_frequenta_escola in (3,4)"
fontes:
  - vig.mvw_pessoas
campos:
  - idade
  - ind_frequenta_escola
dimensao_sql: "idx_dpi = (dpi1+dpi2+dpi3)/3"
ivcad_sql: "ivcad = (idx_nc+idx_dpi+idx_dca+idx_tqa+idx_dr+idx_ch)/6"
```

---

## 8. Progresso IVCAD (40 indicadores)

| Dimensão | Indicadores | Status doc |
|----------|-------------|------------|
| NC | 7 (VD001–VD007) | ✅ [03-ivcad-dimensao-nc.md](./03-ivcad-dimensao-nc.md) |
| **DPI** | **3 (VD008–VD010)** | ✅ este documento |
| DCA | 5 (VD011–VD015) | ✅ [05-ivcad-dimensao-dca.md](./05-ivcad-dimensao-dca.md) |
| TQA | 7 (VD016–VD022) | ✅ [06-ivcad-dimensao-tqa.md](./06-ivcad-dimensao-tqa.md) |
| DR | 4 (VD023–VD026) | ✅ [07-ivcad-dimensao-dr.md](./07-ivcad-dimensao-dr.md) |
| CH | 14 (VD027–VD040) | ✅ [08-ivcad-dimensao-ch.md](./08-ivcad-dimensao-ch.md) |
| **Total documentado** | **40 / 40** | ✅ |

---

*Documentação DPI validada a partir de IN079, VD008–VD010 e print Observatório MDS.*
