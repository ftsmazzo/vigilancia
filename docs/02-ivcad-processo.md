# IVCAD — IN084 (documentação oficial + extensão VigSocial)

> **Status:** documentação oficial incorporada · aguardando composição dos 40 indicadores e sintaxe  
> **Fonte primária:** **IN084** — Índice de Vulnerabilidade das Famílias do Cadastro Único (IVCAD)  
> **Autoria:** DMA/SAGICAD/MDS  
> **Versão de referência VigSocial:** **1.0.5** (06/03/2025) — alinhada ao Observatório no print  
> **Decisão D5:** desagregação MDS = **municipal**; VigSocial estende para **CRAS** e **bairro**

Documentos relacionados: [`01-home-e-modelo-dados.md`](./01-home-e-modelo-dados.md) · **[Guia de referência completo](./ivcad/GUIA-REFERENCIA.md)**

---

## 1. Ficha do indicador (IN084)

| Campo | Valor oficial |
|-------|----------------|
| **Código** | IN084 |
| **Nome** | Índice de Vulnerabilidade das Famílias do Cadastro Único (IVCAD) |
| **Unidade de medida** | **Família** |
| **Domínio** | 0 a 1 |
| **Fonte** | **Cadastro Único** |
| **Periodicidade** | **Mensal** |
| **Desagregação territorial (MDS)** | **Municipal** |
| **Autoria** | DMA/SAGICAD/MDS |

### 1.1 Descrição e interpretação (texto IN084)

O IVCAD mede vulnerabilidades das famílias inscritas no Cadastro Único.

- **40 indicadores** sintetizam **6 dimensões** de vulnerabilidade.  
- Cada indicador representa uma **condição de vulnerabilidade**.  
- Se a família tem a vulnerabilidade → **1**; caso contrário → **0**.  
- Para cada **dimensão**: índice = **proporção de valores 1** entre os indicadores da dimensão.  
- **IVCAD** = **média** dos índices das 6 dimensões.  
- Resultado = **proporção média de indicadores vulneráveis** nas 6 dimensões.  
- Quanto **maior** o valor, **maior** a vulnerabilidade (mais próximo de 1).

### 1.2 Fórmula (IN084)

```
Para cada família f elegível ao universo:

  Para cada dimensão D ∈ {NC, DPI, DCA, TQA, DR, CH}:
    idx_D(f) = média(indicadores binários da dimensão D)

  IVCAD(f) = média(idx_NC, idx_DPI, idx_DCA, idx_TQA, idx_DR, idx_CH)
```

Agregação territorial (MDS): média de `IVCAD(f)` ou das dimensões sobre famílias do recorte.

> **VigSocial:** mesma fórmula em **família**; agregação adicional por `num_cras` e `bairro`.

---

## 2. As seis dimensões

| Sigla | Nome completo |
|-------|----------------|
| **NC** | Necessidade de Cuidados |
| **DPI** | Desenvolvimento na Primeira Infância |
| **DCA** | Desenvolvimento de Crianças e Adolescentes |
| **TQA** | Trabalho e Qualificação de Adultos |
| **DR** | Disponibilidade de Recursos |
| **CH** | Condições Habitacionais |

**Total:** 40 indicadores binários — **documentação completa** em `docs/03`–`08` e [`ivcad/GUIA-REFERENCIA.md`](./ivcad/GUIA-REFERENCIA.md).

### 2.1 Exemplo Observatório (Brasil — print 1)

| Dimensão | Índice médio | % famílias acima da média da dimensão |
|----------|--------------|----------------------------------------|
| NC | 0,364 | 57% |
| DPI | 0,078 | 19% |
| DCA | 0,049 | 14% |
| TQA | 0,638 | 45% |
| DR | 0,409 | 71% |
| CH | 0,171 | 32% |
| **IVCAD** | **0,283** | — |

---

## 3. Universo de famílias elegíveis

O IVCAD **não** é calculado para todo o CADU municipal — apenas para famílias no **universo elegível**. Regra evoluiu por versão:

| Versão | Data | Universo |
|--------|------|----------|
| **1.0.0** | 10/07/2024 | Cadastro atualizado em **até 2 anos** **e** renda per capita **até ½ salário mínimo** |
| **1.0.3** | 18/09/2024 | **Todas** as famílias **beneficiárias PBF** **+** não beneficiárias com cadastro ≤ 2 anos **e** renda per capita ≤ ½ SM |
| **1.0.5** | 06/03/2025 | (mantém 1.0.3) + ajuste indicador **NC7** |
| **1.0.6** | prevista 2026 | Inclui também famílias PBF **Suspensas** com cadastro **> 24 meses desatualizado** **ou** renda per capita **> ½ SM** |

### 3.1 Regra vigente para implementação (v1.0.5)

Família entra no universo se:

```
É beneficiária do PBF
OU
(
  cadastro atualizado em até 24 meses
  E
  renda familiar per capita ≤ meio salário mínimo
)
```

### 3.2 Implicações VigSocial

| Conceito | Fonte provável | Observação |
|----------|----------------|------------|
| Beneficiária PBF | Folha SIBEC + marcador CADU | cruzar com satélite `raw.sibec__programa_bolsa_familia` |
| Cadastro ≤ 24 meses | `meses_desatualizado` / `data_atualizacao` | já em `mvw_familia` |
| Renda per capita ≤ ½ SM | `renda_per_capita` + parâmetro SM vigente | SM é parâmetro mensal — **tabela de referência** |
| PBF Suspenso (v1.0.6) | manutenções / situação folha | aguardar versão |

**Decisão D7 (reforço):** KPI “total famílias CADU” ≠ “famílias no universo IVCAD”.

---

## 4. Histórico metodológico (IN084)

Alterações que impactam implementação:

| Versão | Data | Alteração relevante |
|--------|------|-------------------|
| 1.0.6 | XX/XX/2026 | Universo ampliado: PBF **Suspenso** + desatualizado > 24m ou renda > ½ SM passam a ter IVCAD |
| 1.0.6 | XX/XX/2026 | **TQA5:** empresário **deixa** de contar como emprego formal; permanecem: CLT, doméstico com carteira, militar/servidor, estagiário/aprendiz |
| 1.0.5 | 06/03/2025 | **NC7:** vulnerável se **metade ou menos** dos adultos 18–59 são mulheres **e** há membro ≤ 12 anos, ou ≥ 60, ou PCD |
| 1.0.4 | 08/01/2025 | **DR2:** mudança da **fonte do valor PBF** recebido pela família |
| 1.0.3 | 18/09/2024 | Universo: todas famílias PBF + não PBF (atualizadas ≤ 2a, renda ≤ ½ SM) |
| 1.0.2 | 22/08/2024 | **DCA1** (criança 7–15 trabalhando): ajuste alinhado ao cálculo nacional de trabalho infantil |
| 1.0.1 | 15/08/2024 | Ajuste indicadores dimensão **DR** (ausência folha PBF jul/2024) |
| 1.0.0 | 10/07/2024 | Lançamento IVCAD |

**Decisão D6:** implementar **v1.0.5** primeiro; planejar migração **1.0.6** quando estável e quando satélites SIBEC suportarem “Suspenso”.

---

## 5. Sintaxe e composição

| Item | Status IN084 | Status VigSocial |
|------|--------------|------------------|
| Composição dos 40 indicadores | Link “Composição do IVCAD” no IN084 | ✅ `docs/03`–`08` + [`ivcad/GUIA-REFERENCIA.md`](./ivcad/GUIA-REFERENCIA.md) |
| Ficha de sintaxe de cálculo | Disponível **apenas consulta interna MDS** | ⏳ reconstruir SQL a partir docs + CECAD |
| Validação cruzada municipal | Observatório MDS | ⏳ após `core.ivcad_familia` |

> Matriz **40/40** fechada na documentação; próximo passo é implementação e conciliação.

---

## 6. Granulação: MDS vs VigSocial

```
IN084 / Observatório                 VigSocial (extensão)
────────────────────                 ────────────────────
Municipal (oficial)                  Municipal ✅
                                     CRAS (f.num_cras) ✅ alvo
                                     Bairro (GEO/CADU) ✅ alvo
```

| Nível | IN084 | VigSocial | Chave |
|-------|-------|-----------|-------|
| Município | ✅ | ✅ | IBGE / config |
| CRAS | ❌ | ✅ | `vig.mvw_familia.num_cras` |
| Bairro | ❌ | ✅ | `tbl_geo` + CEP / `bairro` |

Agregação: `AVG(ivcad)` ou `AVG(idx_dimensao)` sobre famílias elegíveis do recorte.

---

## 7. Pipeline de dados (desenho)

```
CECAD (mensal)
  → staging
  → vig.mvw_familia | mvw_pessoas | mvw_familia_domicilio
  → [satélite] folha PBF (DR2, universo PBF) — raw.sibec__*
  → core.ivcad_familia
       · elegivel_universo (bool)
       · flag_001 … flag_040 (0/1)
       · idx_nc, idx_dpi, idx_dca, idx_tqa, idx_dr, idx_ch
       · ivcad
       · cras_cod, bairro_norm (dimensões territoriais)
  → mart.ivcad_agregado (grain: municipio | cras | bairro)
```

### 7.1 Mapeamento preliminar dimensão → tronco VigSocial

| Dimensão | Visões / satélites | Notas IN084 |
|----------|-------------------|-------------|
| NC | `mvw_pessoas`, domicílio | NC7 alterado v1.0.5 |
| DPI | `mvw_pessoas` (0–6, escola, parentesco) | ✅ [04-ivcad-dimensao-dpi.md](./04-ivcad-dimensao-dpi.md) |
| DCA | `mvw_pessoas` (7–17, escola, alfabetização, trabalho infantil) | ✅ [05-ivcad-dimensao-dca.md](./05-ivcad-dimensao-dca.md) |
| TQA | `mvw_pessoas` (18–59, escolaridade, ocupação, renda) | ✅ [06-ivcad-dimensao-tqa.md](./06-ivcad-dimensao-tqa.md) |
| DR | `mvw_familia`, folha PBF, Maciça BPC | ✅ [07-ivcad-dimensao-dr.md](./07-ivcad-dimensao-dr.md) |
| CH | `mvw_familia_domicilio` | ✅ [08-ivcad-dimensao-ch.md](./08-ivcad-dimensao-ch.md) |

---

## 8. Produto e UI

| Superfície | Conteúdo |
|------------|----------|
| **Home** | IVCAD municipal + 6 dimensões (print Observatório) |
| **Painel IVCAD** | Drill-down 40 indicadores + metodologia IN084 |
| **Filtros** | CRAS, bairro (extensão VigSocial) |
| **Agente** | Métricas canônicas `ivcad`, `ivcad_nc`, … com SQL |
| **Enriquecimento** | SISC, manutenções SIBEC cruzados ao universo IVCAD |

---

## 9. Checklist documentação

### Recebido ✅

- [x] IN084 — descrição, interpretação, fórmula, metadados  
- [x] Histórico de versões 1.0.0 → 1.0.6  
- [x] Universo v1.0.3 / v1.0.5  
- [x] Print Observatório (home + dimensões)  

### Pendente ⏳

- [x] **Composição do IVCAD** — 40 indicadores · 6 dimensões ✅  
- [x] Regra binária de **cada** indicador (VD001–VD040) ✅  
- [x] Dimensão **NC** (VD001–VD007) — [`03-ivcad-dimensao-nc.md`](./03-ivcad-dimensao-nc.md)  
- [x] Dimensão **DPI** (VD008–VD010) — [`04-ivcad-dimensao-dpi.md`](./04-ivcad-dimensao-dpi.md)  
- [x] Dimensão **DCA** (VD011–VD015) — [`05-ivcad-dimensao-dca.md`](./05-ivcad-dimensao-dca.md)  
- [x] Dimensão **TQA** (VD016–VD022) — [`06-ivcad-dimensao-tqa.md`](./06-ivcad-dimensao-tqa.md)  
- [x] Dimensão **DR** (VD023–VD026) — [`07-ivcad-dimensao-dr.md`](./07-ivcad-dimensao-dr.md)  
- [x] Dimensão **CH** (VD027–VD040) — [`08-ivcad-dimensao-ch.md`](./08-ivcad-dimensao-ch.md)  
- [x] **40 / 40** indicadores documentados ✅  
- [ ] De-para **campo CECAD** → indicador  
- [ ] Valor **meio salário mínimo** — parâmetro mensal ou campo CADU  
- [ ] Prints das abas / drill-down Observatório  
- [ ] IVCAD municipal publicado MDS para **validação**  

---

## 10. Decisões registradas

| ID | Decisão |
|----|---------|
| D5 | IVCAD = primeiro processo grande; grain **família**; agregação **município + CRAS + bairro** |
| D6 | Implementar **v1.0.5** antes de 1.0.6 |
| D7 | Universo elegível aplicado **antes** dos 40 flags |
| D8 | Fonte IVCAD = **CADU**; satélite **SIBEC** só onde metodologia exige (DR2, universo PBF) |
| D9 | Documentação organizada: **print + IN084** por entrega |
| D10 | Idade **operacional** = `CURRENT_DATE` (base CECAD estática/atrasada); idade **conciliação IVCAD** = `DT_EXTRACAO` do CECAD — ver [`03-ivcad-dimensao-nc.md`](./03-ivcad-dimensao-nc.md) |

---

## 11. Próximo passo

1. ~~Documentar dimensão CH~~ → [`08-ivcad-dimensao-ch.md`](./08-ivcad-dimensao-ch.md) ✅  
2. Implementar `core.ivcad_familia` (40 flags + 6 idx + ivcad)  
3. Auditar gaps: SIT_RUA, VD048, despesa aluguel, Maciça BPC, faixas renda  
4. Validar vs Observatório municipal (modo conciliação D10)  
5. API + painel IVCAD + métricas canônicas agente  

---

*Atualizado com IN084 (Pedro Henrique Monteiro Ribeiro Ferreira, 28/04/2026).*
