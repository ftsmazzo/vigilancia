# IVCAD — Dimensão DR (Disponibilidade de Recursos)

> **IN082** — dimensão DR · **VD023–VD026** — indicadores binários  
> **Fórmula dimensão:** `idx_dr = (DR1 + DR2 + DR3 + DR4) / 4`  
> **Referência:** [`ivcad/GUIA-REFERENCIA.md`](./ivcad/GUIA-REFERENCIA.md) · [`06-ivcad-dimensao-tqa.md`](./06-ivcad-dimensao-tqa.md)

---

## 1. Interpretação (IN082)

A dimensão **DR** sinaliza vulnerabilidade financeira das famílias: **poucos recursos** ou **pouca capacidade de gerar renda**.

Combina quatro leituras complementares da renda per capita:

| Indicador | O que mede |
|-----------|------------|
| **DR1** | Família **sem renda** (CADU + PBF) |
| **DR2** | Pobreza **mesmo com** PBF na renda |
| **DR3** | Pobreza pela renda CADU (**sem** PBF) |
| **DR4** | Pobreza excluindo PBF **e** BPC da renda |

O **índice sintético** = média dos **4 indicadores binários** (grain **família**).

| Metadado | Valor |
|----------|-------|
| Código dimensão | IN082 |
| Domínio | 0 a 1 |
| Fontes | Cadastro Único + **Folha PBF (SIBEC)** + **Maciça BPC** (DR4) |
| Periodicidade | Mensal |
| Desagregação MDS | Municipal |
| Desagregação VigSocial | Municipal + **CRAS** + **bairro** |

**Limiar de pobreza (VD024–VD026):** renda per capita **≤ R$ 218,00** (valor MDS na documentação analisada; parametrizar por competência se o MDS atualizar).

### 1.1 Exemplo Observatório (Brasil — print DR)

| Elemento | Valor |
|----------|-------|
| **idx_dr** (IVCAD-DR) | 0,409 |
| Famílias no universo IVCAD | 26.373.806 (62,1% do CADU) |
| **DR1** — % famílias vulneráveis | 3,5% (923.526 famílias) |
| **DR2** — % famílias vulneráveis | 12,0% (3.160.515 famílias) |
| **DR3** — % famílias vulneráveis | 70,9% (18.698.763 famílias) |
| **DR4** — % famílias vulneráveis | 77,0% (20.317.056 famílias) |

**Leitura:** DR3 e DR4 concentram a vulnerabilidade — a maioria das famílias do universo IVCAD está abaixo de R$ 218 **sem** contar o PBF; DR2 mostra que, **incluindo** PBF, ainda 12% permanecem em pobreza.

---

## 2. Variáveis de referência

| Variável MDS | Significado | VigSocial |
|--------------|-------------|-----------|
| `VL_RENDA_MEDIA_FAM` | Renda per capita familiar **sem PBF** | `mvw_familia.renda_per_capita` |
| `VL_BENEFICIO` | Valor PBF por membro (folha) | soma `vlrtotal` na folha / por membro† |
| `n` | Membros na família | `COUNT(mvw_pessoas)` ou `qtd_pessoas_domic_fam` |
| `VL_RENDA_APOSENT_MEMB` | Aposentadoria/pensão/BPC declarada no CADU | ⚠️ não materializado (layout tudo: faixa `809_2`) |
| Maciça BPC | Base oficial beneficiários BPC | `raw.sibec__beneficio_prestacao_continuada` |

† Na folha VigSocial, `vlrtotal` já é **soma familiar** na competência (`pbf_agg` em `mvw_familia`).

### 2.1 Notação SQL VigSocial

```sql
-- Por família f:
renda_pc_cadu     := f.renda_per_capita                    -- VL_RENDA_MEDIA_FAM
pbf_total_fam     := COALESCE(f.vlrtotal, 0)               -- SUM(VL_BENEFICIO)
n_membros         := COUNT(pessoas) ou qtd_pessoas_domic
pbf_pc            := pbf_total_fam / NULLIF(n_membros, 0)  -- SUM(VL_BENEFICIO)/n
renda_pc_com_pbf  := renda_pc_cadu + pbf_pc                  -- DR2
```

---

## 3. Matriz de indicadores

| Flag | VD | Indicador | Valor 1 quando | Fontes |
|------|-----|-----------|----------------|--------|
| **DR1** | VD023 | Sem renda ou benefícios | `pbf_total + renda_pc_cadu × n = 0` | CADU + folha PBF |
| **DR2** | VD024 | Pobreza com PBF | `renda_pc_com_pbf ≤ 218` | CADU + folha PBF |
| **DR3** | VD025 | Pobreza sem PBF | `renda_pc_cadu ≤ 218` | CADU |
| **DR4** | VD026 | Pobreza sem PBF e BPC | `(renda_pc_cadu - bpc_pc_retirar) ≤ 218` | CADU + Maciça BPC |

---

## 4. Regras detalhadas (VD023–VD026)

### 4.1 DR1 — Família sem renda ou benefícios (VD023)

```
total_recursos = SUM(VL_BENEFICIO por membro) + VL_RENDA_MEDIA_FAM × n_membros

DR1 = 1  se total_recursos = 0
DR1 = 0  caso contrário
```

Equivalente VigSocial:

```
DR1 = 1  se COALESCE(vlrtotal, 0) + COALESCE(renda_per_capita, 0) × n = 0
```

Inclui PBF na conta — família só com Bolsa Família **não** marca DR1.

### 4.2 DR2 — Pobreza com benefícios (VD024)

```
renda_pc_pos_beneficios = (SUM(VL_BENEFICIO) / n) + VL_RENDA_MEDIA_FAM

DR2 = 1  se renda_pc_pos_beneficios ≤ 218
```

**IVCAD v1.0.4:** fonte do valor PBF passou a ser a **folha de pagamentos** (SIBEC), não estimativa CADU — alinhado ao `vlrtotal` em `mvw_familia` (decisão D8).

### 4.3 DR3 — Pobreza sem PBF (VD025)

```
DR3 = 1  se VL_RENDA_MEDIA_FAM ≤ 218
```

Somente CADU — `renda_per_capita` já **exclui** PBF por definição do campo.

### 4.4 DR4 — Pobreza sem PBF e BPC (VD026)

Para cada membro `p`, construir **`BPC_A_RETIRAR_PES`**:

| Condição | Valor |
|----------|-------|
| `VL_RENDA_APOSENT_MEMB ≥ 1412` **e** pessoa na **Maciça BPC** | 1412 |
| `VL_RENDA_APOSENT_MEMB < 1412` **e** pessoa na Maciça | `VL_RENDA_APOSENT_MEMB` |
| Caso contrário | 0 |

```
bpc_pc_retirar = SUM(BPC_A_RETIRAR_PES) / n_membros
renda_pc_ajustada = VL_RENDA_MEDIA_FAM - bpc_pc_retirar

DR4 = 1  se renda_pc_ajustada ≤ 218
```

**Nota:** 1412 corresponde ao teto BPC referenciado na metodologia MDS (vinculado ao SM da competência na época da norma). Parametrizar `teto_bpc` por competência na implementação.

A renda CADU usada **já não inclui PBF**; DR4 remove adicionalmente a parcela BPC identificada via Maciça + aposentadoria declarada.

### 4.5 Índice da dimensão

```
idx_dr = (DR1 + DR2 + DR3 + DR4) / 4.0
```

**Relações esperadas:** DR3 ≥ DR2 em volume (PBF eleva renda); DR4 ≥ DR3 quando há BPC; DR1 ⊂ casos extremos de DR2/DR3.

---

## 5. SQL de referência (VigSocial)

### 5.1 DR1–DR3

```sql
WITH fam AS (
  SELECT
    f.codigo_familiar,
    f.renda_per_capita,
    COALESCE(f.vlrtotal, 0) AS pbf_total,
    COALESCE(NULLIF(cnt.n, 0), NULLIF(d.qtd_pessoas, 0), 1) AS n_membros
  FROM vig.mvw_familia f
  LEFT JOIN (
    SELECT codigo_familiar, COUNT(*)::numeric AS n
    FROM vig.mvw_pessoas GROUP BY 1
  ) cnt USING (codigo_familiar)
  -- opcional: qtd_pessoas_domic de raw CADU
),
dr AS (
  SELECT
    codigo_familiar,
    CASE
      WHEN pbf_total + COALESCE(renda_per_capita, 0) * n_membros = 0 THEN 1
      ELSE 0
    END AS dr1,
    CASE
      WHEN (COALESCE(renda_per_capita, 0) + pbf_total / n_membros) <= 218 THEN 1
      ELSE 0
    END AS dr2,
    CASE
      WHEN COALESCE(renda_per_capita, 0) <= 218 THEN 1
      ELSE 0
    END AS dr3
  FROM fam
)
SELECT * FROM dr;
```

### 5.2 DR4 (requer Maciça BPC + aposentadoria por membro)

```sql
-- Pseudocódigo após join pessoa ↔ Maciça e VL_RENDA_APOSENT_MEMB
WITH bpc_ret AS (
  SELECT
    p.codigo_familiar,
    SUM(
      CASE
        WHEN macica AND renda_aposent >= 1412 THEN 1412
        WHEN macica AND renda_aposent < 1412 THEN renda_aposent
        ELSE 0
      END
    ) / NULLIF(n_membros, 0) AS bpc_pc
  FROM pess_enriched p
  GROUP BY p.codigo_familiar
)
SELECT
  f.codigo_familiar,
  CASE
    WHEN COALESCE(f.renda_per_capita, 0) - COALESCE(b.bpc_pc, 0) <= 218 THEN 1
    ELSE 0
  END AS dr4
FROM vig.mvw_familia f
LEFT JOIN bpc_ret b USING (codigo_familiar);
```

### 5.3 Índice por família

```sql
SELECT
  codigo_familiar,
  dr1, dr2, dr3, dr4,
  (dr1 + dr2 + dr3 + dr4) / 4.0 AS idx_dr
FROM flags;
```

---

## 6. Satélites e decisão D8

| Indicador | Tronco CADU | Satélite SIBEC |
|-----------|-------------|----------------|
| DR1, DR2 | `renda_per_capita` | folha PBF (`vlrtotal`) |
| DR3 | `renda_per_capita` | — |
| DR4 | `renda_per_capita`, aposent. membro | Maciça BPC |

**Histórico:**

- **v1.0.1:** ajuste DR por ausência folha PBF (jul/2024)  
- **v1.0.4:** DR2 — valor PBF da **folha**, não CADU  

VigSocial já agrega folha em `mvw_familia.vlrtotal` e `marc_pbf`; DR4 exige cruzamento pessoa-a-pessoa com BPC.

---

## 7. Cobertura VigSocial

| Requisito | Campo / fonte | Disponível |
|-----------|---------------|------------|
| Renda PC sem PBF | `mvw_familia.renda_per_capita` | ✅ |
| Soma PBF familiar | `mvw_familia.vlrtotal` | ✅ (se folha ingerida) |
| Nº membros | `COUNT(mvw_pessoas)` | ✅ |
| Limiar R$ 218 | parâmetro | ⚠️ hardcoded VigSocial em faixas |
| Maciça BPC | `raw.sibec__beneficio_prestacao_continuada` | ✅ parcial |
| `VL_RENDA_APOSENT_MEMB` contínuo | CECAD | ⚠️ layout tudo: faixa aposentadoria |
| Teto BPC 1412 | parâmetro/SM | ⚠️ pendente |

**Ações:**

- [ ] `param.limiar_pobreza_ivcad` (218) e `param.teto_bpc` por competência  
- [ ] Materializar `renda_aposent` ou de-para faixa → valor  
- [ ] Join Maciça BPC por NIS/CPF para `BPC_A_RETIRAR_PES`  
- [ ] Tratar `renda_per_capita` NULL (política MDS)  
- [ ] Validar DR2 pós v1.0.4 vs Observatório  

---

## 8. Ficha catálogo (YAML)

```yaml
id: dr2
codigo_mds: VD024
dimensao: DR
in082: true
titulo: Família em pobreza mesmo considerando benefícios socioassistenciais
versao_ivcad: "1.0.5"
grain: familia
universo: elegivel_ivcad
tipo: binario
valor_1_quando: "(renda_per_capita + vlrtotal/n_membros) <= 218"
fontes:
  - vig.mvw_familia
  - raw.sibec__programa_bolsa_familia
campos:
  - renda_per_capita
  - vlrtotal
parametros:
  - limiar_pobreza: 218
notas_versao: "v1.0.4 — valor PBF da folha SIBEC"
dimensao_sql: "idx_dr = (dr1+dr2+dr3+dr4)/4"
ivcad_sql: "ivcad = (idx_nc+idx_dpi+idx_dca+idx_tqa+idx_dr+idx_ch)/6"
```

---

## 9. Progresso IVCAD (40 indicadores)

| Dimensão | Indicadores | Status doc |
|----------|-------------|------------|
| NC | 7 | ✅ [03](./03-ivcad-dimensao-nc.md) |
| DPI | 3 | ✅ [04](./04-ivcad-dimensao-dpi.md) |
| DCA | 5 | ✅ [05](./05-ivcad-dimensao-dca.md) |
| TQA | 7 | ✅ [06](./06-ivcad-dimensao-tqa.md) |
| **DR** | **4 (VD023–VD026)** | ✅ este documento |
| **CH** | **14 (VD027–VD040)** | ✅ [08-ivcad-dimensao-ch.md](./08-ivcad-dimensao-ch.md) |
| **Total documentado** | **40 / 40** | ✅ |

---

*Documentação DR validada a partir de IN082, VD023–VD026 e print Observatório MDS.*
