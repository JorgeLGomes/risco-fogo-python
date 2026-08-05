# Aderência do sistema implementado à metodologia proposta

## Risco de Fogo Multi-horizonte — análise do documento `Metodologia_RiscoFogo_Fluxograma.pptx`

**Versão:** 1.0 · 5 de agosto de 2026
**Sistema avaliado:** `risco-fogo-python` (conversão do INPE_FireRiskModel 2.2 + camada multifonte, preparo de dados e RF observado)

---

## 1. Objetivo

Este documento compara, item a item, o que a metodologia proposta descreve (seis lâminas: fluxograma geral, três regimes de horizonte, fundações, calibração e verificação, e implantação em fases) com o que está efetivamente implementado no repositório hoje. O objetivo é separar com clareza três coisas: o que já está pronto, o que está parcialmente pronto e o que ainda não existe — e, para cada lacuna, apontar onde ela se encaixa na arquitetura atual.

## 2. Resumo executivo

A **infraestrutura de dados** do sistema implementado adere bem ao proposto: as três famílias de insumos previstas (observações, previsão de curto prazo e previsão sazonal até 13 meses) já são baixadas, convertidas para um padrão único e consumidas por um mesmo motor de cálculo, com configuração centralizada em YAML e um produto observado contínuo. Nesse eixo, a aderência é alta.

A **metodologia de índice e de tratamento estatístico**, porém, adere apenas em parte. Há uma divergência estrutural — o sistema calcula o **Risco de Fogo do INPE (Setzer/FireRiskModel 2.2)**, e o documento propõe o **FWI canadense** como índice único em todos os horizontes — e há quatro ausências que o próprio documento classifica como essenciais: correção de viés por *quantile mapping*, hindcast, produtos probabilísticos de ensemble e calibração/verificação com fogo observado. Nenhuma delas está implementada.

Em termos das cinco fases de implantação propostas:

| Fase proposta | Situação |
|---|---|
| **Fase 1** — análise observada + climatologia de percentis | **Parcial**: a análise observada diária existe (`rf_observado.py`, IMERG + ERA5) e já agrega médias mensais; a climatologia de percentis não existe |
| **Fase 2** — curto prazo diário D+1 a D+15 | **Atendida com outro modelo**: o fluxo diário roda com GFS (~16 dias); a fonte `eta` está prevista na arquitetura, mas com convenção de arquivos provisória |
| **Fase 3** — sazonal com hindcast, *quantile mapping* e produtos probabilísticos | **Parcial (mínima)**: o horizonte de 1 a 13 meses roda com o BESM T062 determinístico; hindcast, correção de viés e probabilidades não existem |
| **Fase 4** — camada de risco calibrada com focos e área queimada | **Não iniciada** |
| **Fase 5** — verificação sistemática e mapa de skill | **Não iniciada** |

## 3. Aderência item a item

### 3.1 Insumos e observações

| Proposto | Implementado | Situação |
|---|---|---|
| Precipitação observada MERGE/IMERG | `prepara_imerg.py` — IMERG Early/Late/Final V07 do GES DISC, convertido para o padrão do pipeline | **Aderente** (IMERG; MERGE não integrado) |
| T, UR e vento da ERA5 | `prepara_era5.py` — t2m, UR derivada de t2m+td2m (Magnus), u10 e v10 | **Aderente** — inclusive o vento, que o RF não usa, mas o FWI exige |
| Aferição com estações INMET | — | **Não implementado** |
| Previsão de curto prazo (Eta D+1 a D+15) | `prepara_gfs.py` + `rf_previsto.py` com GFS 0,25° até ~16 dias; fonte `eta` declarável em YAML/JSON | **Parcial** — o horizonte é atendido, mas com GFS; o Eta depende da convenção real dos arquivos |
| Ensemble subsazonal (semanas 2–6) | — | **Não implementado** (o sistema é determinístico) |
| Ensemble sazonal 1–13 meses | BESM T062, **um único membro**, série diária de 396 dias | **Parcial** — horizonte atendido, ensemble não |
| Hindcast ≥ 20 anos | — | **Não implementado** |

### 3.2 Núcleo do cálculo

| Proposto | Implementado | Situação |
|---|---|---|
| Índice único **FWI** (FFMC · DMC · DC → ISI · BUI → FWI) | **RF do INPE 2.2**: PSE a partir de 120 dias de precipitação (11 fatores exponenciais), risco básico por classe de vegetação, fatores de umidade (FU), temperatura (FT), latitude (FLAT) e topografia (FTOP) | **Divergente** — ver seção 4 |
| Componentes integradores nunca iniciam do zero; spin-up ~3 meses | A janela de 120 dias de precipitação cumpre exatamente esse papel, e a série mista (IMERG observado até a véspera + previsão a partir da rodada) implementa a "condição inicial herdada da análise" | **Aderente em conceito** — o mecanismo equivalente já existe e está validado |
| Cálculo por membro e por horizonte | Cálculo por horizonte, membro único | **Parcial** |
| Rodada contínua da análise observada | `rf_observado.py` (IMERG + ERA5 às 18 UTC), com períodos por dias, semanas, meses ou intervalo livre | **Aderente** |

### 3.3 Tratamento estatístico

| Proposto | Implementado | Situação |
|---|---|---|
| *Quantile mapping* por variável, mês de validade, lead e ponto de grade | — | **Não implementado** — lacuna crítica no horizonte sazonal |
| Correção prévia da frequência de dias de chuva (*drizzle*) | — | **Não implementado** — especialmente relevante aqui: no RF, chuva fraca e frequente reduz o PSE de forma persistente, do mesmo modo que impede o FFMC de secar |
| Índice expresso em **percentil da climatologia local** (1991–2020) | Classes fixas e absolutas da operação (0,15 / 0,40 / 0,70 / 0,95), conforme o SLD do GeoServer | **Não implementado** — as agregações mensais recém-criadas são o primeiro insumo para construir a climatologia |
| Corrigir as **variáveis**, não o índice | Não aplicável ainda; a arquitetura, porém, tem o ponto de inserção natural (`rf_fontes.serie_precipitacao` e `rf_fontes.temp_ur_previstos`, por onde passam todas as variáveis antes do cálculo) | **Preparado, não feito** |

### 3.4 Do perigo meteorológico ao risco, e verificação

| Proposto | Implementado | Situação |
|---|---|---|
| Calibração com fogo observado (focos VIIRS/BDQueimadas, área queimada MapBiomas/MCD64A1) via GLM/regressão logística por bioma e mês | — | **Não implementado** |
| Classes finais de risco com limiares locais | Classes fixas nacionais (paleta oficial) | **Não implementado** |
| Verificação: correlação e HSS no curto prazo; ROC, Brier Skill Score e diagramas de confiabilidade no probabilístico | Existe validação **numérica** (testes automatizados que comparam o cálculo com a referência fiel ao NCL, ~3×10⁻⁸), mas nenhuma verificação **meteorológica** de skill | **Não implementado** (a validação existente responde a outra pergunta) |
| Mapa de skill publicado junto ao produto | — | **Não implementado** |

### 3.5 Produtos

| Proposto | Implementado | Situação |
|---|---|---|
| Curto prazo: mapas diários de classes de perigo | NetCDF + GeoTIFF por horizonte, na paleta oficial (`rf_figura.py`) | **Aderente** (classes absolutas, não percentis) |
| Subsazonal: anomalia semanal + probabilidade de tercis | Produto semanal determinístico (+7 e +14 dias); sem anomalia e sem probabilidades | **Parcial** |
| Sazonal: probabilidades mensais 1–13 meses | Campos determinísticos mensais 1–13 meses, com **média mensal** a partir da previsão diária do BESM | **Parcial** — o "valor mensal" existe; a probabilidade, não |
| *Blending* operacional (o horizonte mais curto substitui o mais longo para a mesma data-alvo) | — | **Não implementado** (cada produto é gerado e publicado isoladamente) |

## 4. A divergência central: RF do INPE × FWI

O documento propõe o FWI como índice único em todos os horizontes; o sistema implementado calcula o RF operacional do INPE. Não se trata de um detalhe de implementação — são formulações diferentes, com insumos e memórias diferentes:

- O **RF** integra 120 dias de precipitação em 11 janelas exponenciais (PSE), modula por classe de vegetação e aplica fatores de umidade, temperatura, latitude e elevação. **Não usa vento.**
- O **FWI** mantém três códigos de umidade com memórias distintas (FFMC ~2/3 de dia, DMC ~12 dias, DC ~52 dias) e combina-os com vento (ISI) e com o acúmulo de combustível (BUI).

Isso abre uma decisão que precisa ser tomada pela equipe, não pelo código:

1. **Manter o RF** e aplicar a ele o restante da metodologia proposta (correção de viés, percentis, calibração com fogo, verificação, probabilidades). Preserva a continuidade com o produto operacional do Programa Queimadas e a calibração já existente para a vegetação brasileira; diverge do documento apenas no índice.
2. **Adotar o FWI**, como propõe o documento, usando implementações prontas (`cffdrs`, `xclim`, GEFF, citadas na lâmina 6). Exige um motor novo, mas **todos os insumos já estão disponíveis** — inclusive o vento a 10 m, que o `prepara_era5.py` já baixa e grava.
3. **Rodar os dois em paralelo** — tecnicamente o caminho mais informativo: os mesmos arquivos de entrada alimentam ambos, e a verificação da Fase 5 passa a comparar RF e FWI contra focos e área queimada, respondendo com dados qual índice tem mais skill em cada bioma e horizonte.

Vale registrar que a estrutura atual favorece a opção 3: o motor de cálculo é um módulo isolado (`rf_core.py`) que recebe arrays já preparados, e a camada de fontes entrega precipitação diária, temperatura e umidade em grade comum — acrescentar um segundo motor consumindo os mesmos arrays é uma extensão, não uma reescrita.

## 5. Lacunas por ordem de impacto

1. **Correção de viés (quantile mapping) do sazonal.** O próprio documento afirma que sem ela o índice sazonal é inutilizável — e o mesmo vale para o RF, que é fortemente não linear (exponenciais no PSE e seno no risco básico). Sem correção, o RF do BESM a +6 meses carrega o viés de precipitação e umidade do modelo. Ponto de inserção: uma camada entre `rf_fontes` e `rf_core`, corrigindo as variáveis lidas.
2. **Hindcast.** É pré-requisito tanto da correção de viés quanto da climatologia de percentis e da verificação. Depende de dados a serem solicitados ao CPTEC (rodadas retrospectivas do BESM) — é a dependência externa mais longa e deveria ser pedida já.
3. **Climatologia de percentis.** Transformar o índice em percentil local muda a leitura do produto (de "0,7 é alto em qualquer lugar" para "está no percentil 95 *daqui, neste mês*"). Nota técnica importante: **a janela 1991–2020 não é construível com IMERG**, que começa em junho de 2000. Para essa climatologia seria necessário outro insumo de precipitação — ERA5 (1940+), CHIRPS (1981+) ou MERGE (2000+) —, ou aceitar uma janela mais curta (por exemplo 2001–2020, viável com IMERG Final).
4. **Ensemble e produtos probabilísticos.** Exigem que a camada de fontes ganhe uma dimensão de membro e que o cálculo seja repetido por membro; a agregação já implementada (média/máximo por período e por mês) é a base natural para virar probabilidade de exceder um percentil ou tercil.
5. **Calibração com fogo observado e verificação.** É o que separa "perigo meteorológico" de "risco de fogo" no documento, e o que permite publicar o mapa de skill. Depende de focos VIIRS/BDQueimadas e área queimada — dados a que o Programa Queimadas tem acesso direto.
6. **Blending entre horizontes.** Barato de implementar (uma regra de precedência ao publicar), mas só faz sentido depois que houver skill medido para justificar a ordem de preferência.

## 6. O que já existe e pode ser aproveitado

- **Padrão único de arquivos de entrada** para IMERG, GFS, ERA5, BESM e Eta, com grade e orientação normalizadas e regrade automático quando as grades diferem.
- **Configuração centralizada em YAML** (`config.yaml`, `config_besm.yaml`), com precedência CLI > arquivo > ambiente > padrão — todos os scripts do pipeline compartilham o mesmo arquivo.
- **Motor de cálculo isolado e validado numericamente** contra a implementação NCL original, com testes automatizados.
- **Análise observada contínua** (`rf_observado.py`) — a Fase 1 do documento em sua parte de cálculo.
- **Agregações** de média/máximo por período e por mês-calendário, tanto no previsto quanto no observado — insumo direto para climatologia, anomalia e, depois, probabilidade.
- **Vento a 10 m já disponível** na ERA5 convertida, ainda sem uso pelo RF: o único insumo adicional que o FWI exige já está no banco.
- **Análise de sensibilidade** (desligar vegetação e topografia independentemente), útil para atribuir a qual componente se devem as diferenças entre índices e entre horizontes.
- **Saídas na paleta oficial** do GeoServer (`rf_figura.py`), prontas para publicação.

## 7. Caminho sugerido

O documento organiza a implantação em cinco fases; o sistema atual cobre parte das duas primeiras. Uma sequência que aproveita o que já existe:

1. **Fechar a Fase 1.** Rodar o `rf_observado.py` sobre o histórico disponível (IMERG Final desde 2001) e calcular a climatologia de percentis por ponto e por mês. Entrega imediata: o produto observado passa a ser lido em percentil, e a climatologia vira referência para tudo que vem depois.
2. **Solicitar as dependências externas** em paralelo, porque têm prazo longo: hindcast do BESM ao CPTEC, e focos/área queimada à equipe do Queimadas — junto com os arquivos estáticos que ainda faltam (mapa de vegetação de 1 km e topografia).
3. **Definir o índice** (seção 4). Se a opção for rodar RF e FWI em paralelo, o motor FWI pode ser acrescentado consumindo os mesmos arrays, com vento vindo da ERA5.
4. **Implementar o quantile mapping** como camada entre as fontes e o motor, assim que houver hindcast — inclusive a correção de frequência de dias de chuva.
5. **Ensemble e probabilidades**, acrescentando a dimensão de membro à camada de fontes e reaproveitando a agregação existente.
6. **Calibração e verificação** (Fases 4 e 5), fechando o ciclo com o mapa de skill.

## 8. Conclusão

O que existe hoje é uma **base de infraestrutura sólida e aderente** ao fluxograma proposto na metade de cima do fluxograma — observações, previsões de curto prazo e sazonais, motor de cálculo único, produtos determinísticos e figuras na convenção oficial. O que falta está concentrado na metade de baixo: a **camada estatística** (correção de viés, hindcast, percentis, ensemble/probabilidades) e a **camada de validação com fogo real** (calibração e verificação). Somando-se a isso a decisão pendente sobre o índice (RF do INPE × FWI), a aderência metodológica atual pode ser descrita como **parcial**: o pipeline está pronto para receber a metodologia proposta, mas ainda não a implementa por completo.
