# IVCAD — Dimensão DCA (Desenvolvimento de Crianças e Adolescentes)

> **IN080** — dimensão DCA · **VD011–VD015** — indicadores binários  
> **Fórmula dimensão:** `idx_dca = (DCA1 + DCA2 + DCA3 + DCA4 + DCA5) / 5`  
> **Referência:** [`ivcad/GUIA-REFERENCIA.md`](./ivcad/GUIA-REFERENCIA.md) · [`04-ivcad-dimensao-dpi.md`](./04-ivcad-dimensao-dpi.md)

---

## 1. Interpretação (IN080)

A dimensão **DCA** sinaliza vulnerabilidade de **crianças e adolescentes de 7 a 17 anos** em relação a:

1. **Trabalho infantil** (7–15 anos);  
2. **Fora da escola** (7–17 e 15–17);  
3. **Analfabetismo** (10–17);  
4. **Atraso escolar** superior a 2 anos (10–17).

O **índice sintético da dimensão** = proporção média dos **5 indicadores binários** (grain **família**).

| Metadado | Valor |
|----------|-------|
| Código dimensão | IN080 |
| Domínio | 0 a 1 |
| Fonte | Cadastro Único |
| Periodicidade | Mensal |
| Desagregação MDS | Municipal |
| Desagregação VigSocial | Municipal + **CRAS** + **bairro** |

### 1.1 Exemplo Observatório (Brasil — print DCA)

| Elemento | Valor |
|----------|-------|
| **idx_dca** (IVCAD-DCA) | 0,049 |
| Famílias no universo IVCAD | 26.373.806 (62,1% do CADU) |
| **DCA1** — % famílias vulneráveis | 0,01% (3.379 famílias) |
| **DCA2** — % famílias vulneráveis | 0,6% (166.617 famílias) |
| **DCA3** — % famílias vulneráveis | 1,1% (277.808 famílias) |
| **DCA4** — % famílias vulneráveis | 9,7% (2.545.920 famílias) |
| **DCA5** — % famílias vulneráveis | 13,9% |

**Leitura:** DCA4 e DCA5 concentram a vulnerabilidade desta dimensão; DCA1 (trabalho infantil) é raro no universo IVCAD nacional (~0,01%).

---

## 2. Matriz de indicadores

| Flag | VD | Indicador | Faixa etária | Valor 1 quando | Campos CECAD (MDS) | VigSocial |
|------|-----|-----------|--------------|----------------|--------------------|-----------|
| **DCA1** | VD011 | Trabalho infantil | 7–15* | Ver §3.1 (regra composta) | `IDADE`, `IN_TRABALHO_INFANTIL_PESSOA`, `CO_TRABALHOU_SEMANA_MEMB`, `CO_AFASTADO_TRAB_MEMB`, `CO_PRINCIPAL_TRAB_MEMB` | `idade`, `ind_trabalho_infantil`, `cod_trabalhou`†, `cod_afastado_trab`†, `cod_principal_trab` |
| **DCA2** | VD012 | Fora da escola | 15–17 | Escola = 3 ou 4 | `IDADE`, `IN_FREQUENTA_ESCOLA_MEMB` | `idade`, `ind_frequenta_escola` |
| **DCA3** | VD013 | Fora da escola | 7–17 | Escola = 3 ou 4 | idem | idem |
| **DCA4** | VD014 | Analfabeto | 10–17 | Não sabe ler/escrever | `IDADE`, `CO_SABE_LER_ESCREVER_MEMB` | `idade`, `cod_sabe_ler_escrever` |
| **DCA5** | VD015 | Atraso escolar > 2 anos | 10–17 | `idade - (7 + ANOS_ESTUDO) > 2` | `IDADE`, `ANOS_ESTUDO` (VD048) | `idade` + derivar `anos_estudo`‡ |

\* DCA1 v1.0.2 — metodologia MDS usa ramos distintos por faixa; ver §3.1.  
† Campos existem no CECAD bruto; **ainda não** materializados em `vig.mvw_pessoas`.  
‡ `ANOS_ESTUDO` é variável construída (VD048); campos auxiliares já na MV: `grau_instrucao`, `cod_curso_frequentou`, `cod_ano_serie_frequentou`, `cod_concluiu_frequentou`.

---

## 3. Regras detalhadas (VD011–VD015)

### 3.1 DCA1 — Trabalho infantil (VD011)

Família recebe **1** se **qualquer** membro satisfizer **um** dos ramos:

| Ramo | Condição |
|------|----------|
| **A** | `idade < 16` **E** `IN_TRABALHO_INFANTIL_PESSOA = 1` (marcação trabalho infantil no CADU) |
| **B** | `10 ≤ idade ≤ 13` **E** (`CO_TRABALHOU_SEMANA_MEMB = 1` **OU** (`CO_TRABALHOU_SEMANA_MEMB = 2` **E** `CO_AFASTADO_TRAB_MEMB = 1`)) |
| **C** | `14 ≤ idade ≤ 15` **E** mesma regra de trabalho do ramo B **E** `CO_PRINCIPAL_TRAB_MEMB NOT IN (10, 11)` — exclui **estagiário** (10) e **aprendiz** (11) |

Caso contrário: **0**.

**Notas:**

- Idades **7–9** só entram via ramo **A** (flag trabalho infantil).  
- **14–15** em estágio/aprendiz **não** contam como trabalho infantil neste indicador.  
- Alteração **IVCAD v1.0.2** (22/08/2024): DCA1 alinhado ao cálculo nacional de trabalho infantil.

**De-para domínios VigSocial:**

| Campo | CECAD | Significado |
|-------|-------|-------------|
| `ind_trabalho_infantil` | `IN_TRABALHO_INFANTIL_PESSOA` | 1 = sim, 2 = não |
| `cod_trabalhou` | `CO_TRABALHOU_SEMANA_MEMB` | 1 = sim, 2 = não |
| `cod_afastado_trab` | `CO_AFASTADO_TRAB_MEMB` | 1 = sim, 2 = não |
| `cod_principal_trab` | `CO_PRINCIPAL_TRAB_MEMB` | 10 = estagiário, 11 = aprendiz (excluídos no ramo C) |

### 3.2 DCA2 — Adolescente 15–17 fora da escola (VD012)

```
∃ pessoa p: 15 ≤ idade(p) ≤ 17
  AND ind_frequenta_escola(p) IN ('3', '4')
→ DCA2 = 1
```

Mesma codificação de escola da dimensão DPI (3 = já frequentou; 4 = nunca frequentou).

### 3.3 DCA3 — Criança/adolescente 7–17 fora da escola (VD013)

```
∃ pessoa p: 7 ≤ idade(p) ≤ 17
  AND ind_frequenta_escola(p) IN ('3', '4')
→ DCA3 = 1
```

**Sobreposição:** adolescente 16 anos fora da escola marca **DCA3** apenas (fora da faixa DCA2).

### 3.4 DCA4 — Analfabeto 10–17 (VD014)

```
∃ pessoa p: 10 ≤ idade(p) ≤ 17
  AND cod_sabe_ler_escrever(p) IN ('2', '02')  -- não sabe ler e escrever
→ DCA4 = 1
```

### 3.5 DCA5 — Atraso escolar > 2 anos (VD015)

```
∃ pessoa p: 10 ≤ idade(p) ≤ 17
  AND (idade(p) - (7 + anos_estudo(p))) > 2
→ DCA5 = 1
```

Equivalente: **`idade - anos_estudo - 7 > 2`** → atraso superior a **2 anos** em relação à expectativa (início escolar aos 7 anos + anos de estudo declarados).

**Fonte normativa:** variável construída **`ANOS_ESTUDO`** — [VD048](https://wiki-sagi.cidadania.gov.br/home/DS/Cad/VD/VD048) (SAGI). Implementação VigSocial deve replicar VD048 antes de calcular DCA5.

### 3.6 Índice da dimensão

```
idx_dca = (DCA1 + DCA2 + DCA3 + DCA4 + DCA5) / 5.0
```

**Sobreposição intencional:** jovem 15 anos fora da escola marca DCA2 **e** DCA3; jovem 12 analfabeto e fora da escola pode marcar DCA3 **e** DCA4.

---

## 4. SQL de referência (VigSocial)

### 4.1 DCA1–DCA4 (campos já na MV)

```sql
WITH pess AS (
  SELECT
    p.codigo_familiar,
    p.idade,
    btrim(COALESCE(p.ind_trabalho_infantil::text, '')) AS ti,
    btrim(COALESCE(p.ind_frequenta_escola::text, '')) AS freq_escola,
    btrim(COALESCE(p.cod_sabe_ler_escrever::text, '')) AS sabe_ler,
    btrim(COALESCE(p.cod_principal_trab::text, '')) AS principal_trab
    -- TODO: cod_trabalhou, cod_afastado_trab após inclusão na mvw_pessoas
  FROM vig.mvw_pessoas p
),
flags_parcial AS (
  SELECT
    codigo_familiar,
    -- DCA1: ramo A (trabalho infantil < 16) — parcial até cod_trabalhou/afastado
    MAX(CASE
      WHEN idade IS NOT NULL AND idade < 16 AND ti IN ('1', '01')
      THEN 1 ELSE 0
    END) AS dca1_parcial,
    MAX(CASE
      WHEN idade BETWEEN 15 AND 17
       AND freq_escola IN ('3', '03', '4', '04')
      THEN 1 ELSE 0
    END) AS dca2,
    MAX(CASE
      WHEN idade BETWEEN 7 AND 17
       AND freq_escola IN ('3', '03', '4', '04')
      THEN 1 ELSE 0
    END) AS dca3,
    MAX(CASE
      WHEN idade BETWEEN 10 AND 17
       AND sabe_ler IN ('2', '02')
      THEN 1 ELSE 0
    END) AS dca4
  FROM pess
  GROUP BY codigo_familiar
)
SELECT * FROM flags_parcial;
```

### 4.2 DCA1 completo (com campos de trabalho na semana)

```sql
-- Após materializar cod_trabalhou e cod_afastado_trab em mvw_pessoas:
MAX(CASE
  WHEN idade IS NOT NULL AND idade < 16 AND ti IN ('1', '01') THEN 1
  WHEN idade BETWEEN 10 AND 13 AND (
    cod_trabalhou IN ('1', '01')
    OR (cod_trabalhou IN ('2', '02') AND cod_afastado_trab IN ('1', '01'))
  ) THEN 1
  WHEN idade BETWEEN 14 AND 15 AND (
    cod_trabalhou IN ('1', '01')
    OR (cod_trabalhou IN ('2', '02') AND cod_afastado_trab IN ('1', '01'))
  ) AND principal_trab NOT IN ('10', '11') THEN 1
  ELSE 0
END) AS dca1
```

### 4.3 DCA5 (requer `anos_estudo` — VD048)

```sql
-- Pseudocódigo após implementar vig.anos_estudo(p) conforme VD048:
MAX(CASE
  WHEN idade BETWEEN 10 AND 17
   AND anos_estudo IS NOT NULL
   AND (idade - (7 + anos_estudo)) > 2
  THEN 1 ELSE 0
END) AS dca5
```

### 4.4 Índice por família

```sql
SELECT
  codigo_familiar,
  dca1, dca2, dca3, dca4, dca5,
  (dca1 + dca2 + dca3 + dca4 + dca5) / 5.0 AS idx_dca
FROM flags;
```

---

## 5. Idade (decisão D10)

Mesma regra das dimensões NC e DPI: idade **operacional** (`CURRENT_DATE`) para vigilância; idade por **`DT_EXTRACAO`** para conciliação com Observatório MDS.

Faixas 7–17, 10–17, 15–17 e ramos DCA1 dependem de idade precisa.

---

## 6. Cobertura VigSocial

| Requisito | Campo / expressão | Disponível |
|-----------|-------------------|------------|
| Idade | `mvw_pessoas.idade` | ✅ |
| Trabalho infantil (flag) | `ind_trabalho_infantil` | ✅ |
| Trabalhou semana / afastado | `cod_trabalhou_memb`, `cod_afastado_trab_memb` (raw) | ⚠️ raw only |
| Função principal | `cod_principal_trab` | ✅ |
| Frequenta escola | `ind_frequenta_escola` | ✅ |
| Sabe ler/escrever | `cod_sabe_ler_escrever` | ✅ |
| Anos de estudo (VD048) | derivar de curso/série/grau | ⚠️ pendente |
| Agregação familiar | `codigo_familiar` | ✅ |

**Ações de implementação:**

- [ ] Incluir `cod_trabalhou` e `cod_afastado_trab` em `PESSOAS_FIELDS` / `mvw_pessoas`  
- [ ] Implementar função `vig.anos_estudo(...)` conforme VD048  
- [ ] Política para campos NULL (escola, alfabetização, trabalho)  
- [ ] Validar DCA1 ramos B/C vs Observatório municipal  

---

## 7. Ficha catálogo (YAML)

```yaml
id: dca1
codigo_mds: VD011
dimensao: DCA
in080: true
titulo: Criança ou adolescente 7-15 anos trabalhando
versao_ivcad: "1.0.5"
grain: familia
universo: elegivel_ivcad
tipo: binario
notas_versao: "Regra DCA1 ajustada em IVCAD v1.0.2"
valor_1_quando: "Trabalho infantil (<16 flag) OU 10-15 trabalhando/afastado (exc. estagiário/aprendiz 14-15)"
fontes:
  - vig.mvw_pessoas
campos:
  - idade
  - ind_trabalho_infantil
  - cod_trabalhou
  - cod_afastado_trab
  - cod_principal_trab
dimensao_sql: "idx_dca = (dca1+dca2+dca3+dca4+dca5)/5"
ivcad_sql: "ivcad = (idx_nc+idx_dpi+idx_dca+idx_tqa+idx_dr+idx_ch)/6"
```

---

## 8. Progresso IVCAD (40 indicadores)

| Dimensão | Indicadores | Status doc |
|----------|-------------|------------|
| NC | 7 (VD001–VD007) | ✅ [03-ivcad-dimensao-nc.md](./03-ivcad-dimensao-nc.md) |
| DPI | 3 (VD008–VD010) | ✅ [04-ivcad-dimensao-dpi.md](./04-ivcad-dimensao-dpi.md) |
| **DCA** | **5 (VD011–VD015)** | ✅ este documento |
| TQA | 7 (VD016–VD022) | ✅ [06-ivcad-dimensao-tqa.md](./06-ivcad-dimensao-tqa.md) |
| DR | 4 (VD023–VD026) | ✅ [07-ivcad-dimensao-dr.md](./07-ivcad-dimensao-dr.md) |
| CH | 14 (VD027–VD040) | ✅ [08-ivcad-dimensao-ch.md](./08-ivcad-dimensao-ch.md) |
| **Total documentado** | **40 / 40** | ✅ |

---

*Documentação DCA validada a partir de IN080, VD011–VD015 e print Observatório MDS.*
