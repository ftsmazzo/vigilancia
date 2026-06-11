# IVCAD — Dimensão CH (Condições Habitacionais)

> **IN083** — dimensão CH · **VD027–VD040** — indicadores binários  
> **Fórmula dimensão:** `idx_ch = (CH1 + CH2 + … + CH14) / 14`  
> **Referência:** [`ivcad/GUIA-REFERENCIA.md`](./ivcad/GUIA-REFERENCIA.md) · [`07-ivcad-dimensao-dr.md`](./07-ivcad-dimensao-dr.md)

---

## 1. Interpretação (IN083)

A dimensão **CH** sinaliza vulnerabilidade habitacional: **déficit habitacional**, **abrigabilidade** e **acesso a serviços** (água, esgoto, lixo, energia).

O **índice sintético** = média dos **14 indicadores binários** (grain **família**).

| Metadado | Valor |
|----------|-------|
| Código dimensão | IN083 |
| Domínio | 0 a 1 |
| Fonte | Cadastro Único |
| Periodicidade | Mensal |
| Desagregação MDS | Municipal |
| Desagregação VigSocial | Municipal + **CRAS** + **bairro** |

### 1.1 Exemplo Observatório (Brasil — print CH)

| Elemento | Valor |
|----------|-------|
| **idx_ch** (IVCAD-CH) | 0,171 |
| Famílias no universo IVCAD | 26.373.806 (62,1% do CADU) |
| **CH1** | 4,5% · **CH2** 10,5% · **CH3** 27,1% · **CH4** 30,3% |
| **CH5** | 6,1% · **CH6** 10,0% · **CH7** 27,4% · **CH8** 8,9% |
| **CH9** | 8,6% · **CH10** 38,1% · **CH11** 26,7% · **CH12** 18,7% |
| **CH13** | 15,6% · **CH14** 7,1% |

**Leitura:** CH10 (esgoto inadequado) e CH4 (despesa com aluguel) são os indicadores mais frequentes.

---

## 2. Variáveis construídas comuns

### 2.1 `SIT_RUA` (situação de rua — família)

Família em situação de rua quando **simultaneamente**:

1. `IN_FORMULARIO_SUP2_FAM = 1` (formulário suplementar 2);  
2. `CO_LOCAL_DOMIC_FAM` **nulo**;  
3. Família presente em **`TB_PESSOA_INDICE_12`** (respondentes FS2).

### 2.2 Espécie do domicílio (`CO_ESPECIE_DOMIC_FAM`)

| Código | Significado |
|--------|-------------|
| 1 | Particular permanente |
| 2 | Particular improvisado |
| 3 | Coletivo |

### 2.3 Atalho “moradia extrema”

Regra transversal em **CH1–CH14**:

```
moradia_extrema = (SIT_RUA = 1) OR (CO_ESPECIE_DOMIC_FAM = 2)
```

Se `moradia_extrema` → **todos** os indicadores CH da família = **1**.

Famílias em improvisado ou situação de rua **não** avaliam demais condições — já são vulneráveis em toda a dimensão.

### 2.4 Dormitórios (CH2)

```
n_dorm = COALESCE(QT_COMODOS_DORMITORIO_FAM, QT_COMODOS_DOMIC_FAM - 2)
```

Se `n_dorm < 1` após fallback → CH2 = **0** (mesmo em particular permanente).

### 2.5 De-para VigSocial (`vig.mvw_familia_domicilio`)

| CECAD | VigSocial |
|-------|-----------|
| `CO_ESPECIE_DOMIC_FAM` | `especie_domicilio` |
| `CO_LOCAL_DOMIC_FAM` | `situacao_domicilio` |
| `QT_COMODOS_DOMIC_FAM` | `qtd_comodos` |
| `QT_COMODOS_DORMITORIO_FAM` | `total_dormitorios` |
| `QT_PESSOAS_DOMIC_FAM` | raw / `total_pessoas`† |
| `CO_MATERIAL_PISO_FAM` | `tipo_piso` |
| `CO_MATERIAL_DOMIC_FAM` | `tipo_parede` |
| `CO_ABASTE_AGUA_DOMIC_FAM` | `abastecimento_agua` |
| `CO_BANHEIRO_DOMIC_FAM` | `existencia_banheiro` |
| `CO_ESCOA_SANITARIO_DOMIC_FAM` | `escoamento_sanitario` |
| `CO_DESTINO_LIXO_DOMIC_FAM` | `coleta_lixo` |
| `CO_ILUMINACAO_DOMIC_FAM` | `tipo_iluminacao` |
| `VL_DESP_ALUGUEL_FAM` | raw `d_val_desp_aluguel_fam`‡ |
| `VL_RENDA_MEDIA_FAM` | `mvw_familia.renda_per_capita` |

† MV usa contagem distinta de CPF; MDS usa `QT_PESSOAS_DOMIC_FAM` — conciliar na implementação.  
‡ Ainda **não** materializado em `mvw_familia_domicilio`.

---

## 3. Matriz de indicadores (VD027–VD040)

| Flag | VD | Indicador | Condição (= 1) em particular permanente (espécie = 1) |
|------|-----|-----------|--------------------------------------------------------|
| **CH1** | VD027 | Improvisado ou situação de rua | `moradia_extrema` |
| **CH2** | VD028 | Densidade > 3 pessoas/dormitório | `QT_PESSOAS / n_dorm > 3` (coletivo → 0) |
| **CH3** | VD029 | Aluguel > 30% da renda pré-PBF | renda total = 0 **ou** `desp_aluguel ≥ 0,30 × renda_total` |
| **CH4** | VD030 | Possui despesa com aluguel | `renda_pc = 0` **ou** `desp_aluguel > 0` |
| **CH5** | VD031 | Sem parede **e** piso permanentes | piso ∈ {1,3,7} **e** parede ∈ {5,6,7,8} |
| **CH6** | VD032 | Sem parede **ou** piso permanente | piso ∈ {1,3,7} **ou** parede ∈ {5,6,7,8} |
| **CH7** | VD033 | Sem água de rede geral | abastecimento ∈ {2,3,4} |
| **CH8** | VD034 | Sem acesso adequado à água | abastecimento = 4 |
| **CH9** | VD035 | Sem banheiro | banheiro = 2 |
| **CH10** | VD036 | Esgotamento inadequado | banheiro = 2 **ou** (banheiro = 1 e escoamento ∈ {3,4,5,6}) |
| **CH11** | VD037 | Lixo não coletado diretamente | lixo ∈ {2,3,4,5,6} |
| **CH12** | VD038 | Lixo não coletado direta/indireta | lixo ∈ {3,4,5,6} |
| **CH13** | VD039 | Sem eletricidade com medidor | iluminação ∈ {3,4,5,6} |
| **CH14** | VD040 | Sem eletricidade | iluminação ∈ {4,5,6} |

**Em todos:** se `moradia_extrema` → **1** (antes das regras acima).

---

## 4. Domínios CECAD (referência)

### Piso (`tipo_piso`) — inadequado CH5/CH6

| Código | Material | CH5/CH6 |
|--------|----------|---------|
| 1 | Terra | inadequado |
| 2 | Cimento | adequado† |
| 3 | Madeira aproveitada | inadequado (VD lista 3 como “Cimento” — seguir **código** VD) |
| 4 | Madeira aparelhada | adequado |
| 5 | Cerâmica/lajota/pedra | adequado |
| 6 | Carpete | adequado |
| 7 | Outro | inadequado |

† VD031/032 citam códigos **1, 3, 7** como piso não permanente — implementar pelos **códigos oficiais**, não pelo rótulo textual do dicionário.

### Parede (`tipo_parede`) — inadequado

Inadequados: **5** taipa não revestida, **6** madeira aproveitada, **7** palha, **8** outro.

### Água (`abastecimento_agua`)

| CH7 (=1 se) | CH8 (=1 se) |
|-------------|-------------|
| 2 poço, 3 cisterna, 4 outra | apenas **4** outra |

Rede geral = **1** → CH7 = 0.

### Esgoto (`escoamento_sanitario`) — CH10

Inadequado: **3** fossa rudimentar, **4** vala, **5** rio/mar, **6** outra (com banheiro = sim).

### Lixo (`coleta_lixo`)

| CH11 (=1) | CH12 (=1) |
|-----------|-----------|
| 2–6 (não coleta direta) | 3–6 (exclui coleta indireta = 2) |

### Iluminação (`tipo_iluminacao`)

| CH13 (=1) | CH14 (=1) |
|-----------|-----------|
| 3–6 (sem medidor próprio/comunitário) | 4–6 (sem elétrica) |

Elétrica com medidor: **1** próprio, **2** comunitário → CH13 = 0.

---

## 5. Regras CH2 e CH3/CH4 (renda e aluguel)

### CH2

```
Se CO_ESPECIE = 3 (coletivo) → CH2 = 0
Se moradia_extrema → CH2 = 1
Se CO_ESPECIE = 1 e n_dorm >= 1 e QT_PESSOAS / n_dorm > 3 → CH2 = 1
Senão → CH2 = 0
```

### CH3 (renda pré-PBF)

```
renda_total = VL_RENDA_MEDIA_FAM × n_membros

Se moradia_extrema → CH3 = 1
Se CO_ESPECIE = 1 e (renda_total = 0 ou VL_DESP_ALUGUEL >= 0.30 × renda_total) → CH3 = 1
Senão → CH3 = 0
```

### CH4

```
Se moradia_extrema → CH4 = 1
Se CO_ESPECIE = 1 e (VL_RENDA_MEDIA_FAM = 0 ou VL_DESP_ALUGUEL > 0) → CH4 = 1
Senão → CH4 = 0
```

---

## 6. Índice da dimensão

```
idx_ch = (CH1 + CH2 + CH3 + CH4 + CH5 + CH6 + CH7 + CH8
        + CH9 + CH10 + CH11 + CH12 + CH13 + CH14) / 14.0
```

**IVCAD completo (40/40 indicadores):**

```
IVCAD(f) = (idx_nc + idx_dpi + idx_dca + idx_tqa + idx_dr + idx_ch) / 6
```

---

## 7. SQL de referência (VigSocial)

```sql
WITH base AS (
  SELECT
    d.codigo_familiar,
    btrim(COALESCE(d.especie_domicilio, '')) AS especie,
    -- sit_rua: implementar SIT_RUA (FS2 + local nulo + TB_PESSOA_INDICE_12)
    FALSE AS sit_rua,  -- placeholder
    (sit_rua OR especie IN ('2', '02')) AS moradia_extrema,
    NULLIF(regexp_replace(COALESCE(d.total_dormitorios, ''), '[^0-9]', '', 'g'), '')::numeric AS dorm_decl,
    NULLIF(regexp_replace(COALESCE(d.qtd_comodos, ''), '[^0-9]', '', 'g'), '')::numeric AS comodos,
    COALESCE(
      NULLIF(regexp_replace(COALESCE(d.total_dormitorios, ''), '[^0-9]', '', 'g'), '')::numeric,
      NULLIF(regexp_replace(COALESCE(d.qtd_comodos, ''), '[^0-9]', '', 'g'), '')::numeric - 2
    ) AS n_dorm,
    d.tipo_piso, d.tipo_parede, d.abastecimento_agua,
    d.existencia_banheiro, d.escoamento_sanitario, d.coleta_lixo, d.tipo_iluminacao,
    f.renda_per_capita,
    -- d.val_desp_aluguel, n_pessoas
    d.total_pessoas AS qtd_pessoas
  FROM vig.mvw_familia_domicilio d
  JOIN vig.mvw_familia f USING (codigo_familiar)
),
flags AS (
  SELECT
    codigo_familiar,
    CASE WHEN moradia_extrema THEN 1 ELSE 0 END AS ch1,
    CASE
      WHEN especie IN ('3', '03') THEN 0
      WHEN moradia_extrema THEN 1
      WHEN especie IN ('1', '01') AND n_dorm >= 1
       AND qtd_pessoas::numeric / n_dorm > 3 THEN 1
      ELSE 0
    END AS ch2
    -- ch3..ch14: aplicar tabelas §3 com moradia_extrema primeiro
  FROM base
)
SELECT * FROM flags;
```

---

## 8. Cobertura VigSocial

| Requisito | Disponível |
|-----------|------------|
| Espécie, cômodos, materiais, água, esgoto, lixo, luz | ✅ `mvw_familia_domicilio` |
| Renda PC (CH3, CH4) | ✅ `mvw_familia.renda_per_capita` |
| Despesa aluguel | ⚠️ raw `val_desp_aluguel_fam` |
| `SIT_RUA` completo | ⚠️ requer FS2 + Maciça/índice 12 |
| `QT_PESSOAS_DOMIC_FAM` | ⚠️ usar raw ou validar vs `total_pessoas` MV |

**Ações:**

- [ ] Função `vig.sit_rua_familia(...)` conforme MDS  
- [ ] Incluir `val_desp_aluguel` e `qtd_pessoas_domic` na MV domicílio  
- [ ] Helper `moradia_extrema` reutilizado em CH1–CH14  
- [ ] Validar idx_ch vs Observatório municipal  

---

## 9. Ficha catálogo (YAML)

```yaml
id: ch10
codigo_mds: VD036
dimensao: CH
in083: true
titulo: Domicilio sem esgotamento sanitario adequado
versao_ivcad: "1.0.5"
grain: familia
universo: elegivel_ivcad
tipo: binario
valor_1_quando: "moradia_extrema OR (especie=1 AND (banheiro=2 OR escoamento in (3,4,5,6)))"
fontes:
  - vig.mvw_familia_domicilio
precondicao: moradia_extrema_forca_1_em_todos_ch
dimensao_sql: "idx_ch = (ch1+...+ch14)/14"
ivcad_sql: "ivcad = (idx_nc+idx_dpi+idx_dca+idx_tqa+idx_dr+idx_ch)/6"
```

---

## 10. Progresso IVCAD — **completo**

| Dimensão | Indicadores | Doc |
|----------|-------------|-----|
| NC | 7 (VD001–007) | [03](./03-ivcad-dimensao-nc.md) |
| DPI | 3 (VD008–010) | [04](./04-ivcad-dimensao-dpi.md) |
| DCA | 5 (VD011–015) | [05](./05-ivcad-dimensao-dca.md) |
| TQA | 7 (VD016–022) | [06](./06-ivcad-dimensao-tqa.md) |
| DR | 4 (VD023–026) | [07](./07-ivcad-dimensao-dr.md) |
| **CH** | **14 (VD027–040)** | ✅ este documento |
| **Total** | **40 / 40** | ✅ |

---

*Documentação CH validada a partir de IN083, VD027–VD040 e print Observatório MDS. Com isto, a matriz completa dos 40 indicadores IVCAD v1.0.5 está documentada.*
