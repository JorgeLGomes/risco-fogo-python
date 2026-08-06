# Instruções de Git e GitHub

## Risco de Fogo Previsto em Python — repositório `JorgeLGomes/risco-fogo-python`

**Versão:** 1.3 · 5 de agosto de 2026

Este documento descreve como manter o repositório do projeto no GitHub:
estrutura, fluxo de commits, convenções de mensagem, versões (tags) e
solução dos problemas mais comuns.

---

## 1. Estrutura do repositório

```
risco-fogo-python/
├── rf_core.py                  # Núcleo do cálculo do RF
├── rf_fontes.py                # Camada de fontes (GFS, Eta, BESM)
├── rf_config.py                # Configuração YAML dos dados de entrada
├── config_exemplo.yaml         # Modelo comentado do config
├── ativa_riscofogo.sh          # Ativação do ambiente no cluster (source)
├── rf_previsto_1_5dias.py      # Produto diário (1–5 dias)
├── rf_previsto_1_2_semanas.py  # Produto semanal (7 e 14 dias)
├── rf_previsto.py              # Script genérico (qualquer horizonte/fonte)
├── prepara_gfs.py              # Download/preparo do GFS (pós-SCN 25-81)
├── prepara_imerg.py            # Download/conversão do IMERG (GES DISC)
├── teste_rf.py                 # Teste do núcleo
├── teste_rf_previsto.py        # Teste do script genérico
├── teste_rf_multifonte.py      # Teste do modo multifonte
├── teste_besm_real.py          # Teste com dados reais do BESM T062
├── teste_prepara_gfs.py        # Teste do preparo do GFS
├── teste_prepara_imerg.py      # Teste do preparo do IMERG
├── requirements.txt            # Dependências Python
├── README.md
├── .gitignore                  # Ignora __pycache__, *.nc, *.tif e logs
├── docs/                       # Relatório, manual e estas instruções
└── originais/                  # Scripts bash+NCL originais (referência)
```

O repositório local fica em `C:\Users\jorge\Claude\Projects\risco-fogo-python`
e o remoto em `https://github.com/JorgeLGomes/risco-fogo-python`.

## 2. Fluxo de trabalho para qualquer atualização

Sempre nesta ordem — editar, testar, commitar, enviar:

```powershell
cd C:\Users\jorge\Claude\Projects\risco-fogo-python

# 1. Confira o que mudou
git status
git diff

# 2. Rode os testes antes de commitar
python teste_rf.py
python teste_rf_previsto.py
python teste_rf_multifonte.py

# 3. Adicione e commite (agrupe mudanças relacionadas num mesmo commit)
git add <arquivos>
git commit -m "Mensagem curta no imperativo

Detalhes opcionais em linhas seguintes: o que mudou e por quê."

# 4. Envie ao GitHub
git push origin main
```

## 3. Convenções de mensagem de commit

A primeira linha resume a mudança no imperativo, com até ~70 caracteres
(ex.: "Adiciona fonte Eta", "Corrige agregação de acúmulos de 12h").
Depois de uma linha em branco, detalhe o que mudou e por quê, em itens se
ajudar. Agrupe por assunto: código em um commit, documentação em outro.
Exemplos usados neste projeto:

```
Adiciona suporte multifonte: GFS, Eta e BESM ate 13 meses

- rf_fontes.py: camada de fontes configuravel (padroes de nome, variaveis,
  frequencia dos acumulos 1h/12h/1d, tipo de acumulacao, unidades, alcance)
- Serie diaria de 120 tempos combinando IMERG observado + previsao da fonte
- rf_core: nova calcula_risco_fogo_dados (arrays), mantendo compatibilidade
- rf_previsto.py: --fonte, --config-fontes e horizontes em meses (Nm)
- teste_rf_multifonte.py: 6 cenarios, incluindo Eta 13m e BESM 12h
```

Se o console do Windows não estiver em UTF-8, escreva as mensagens sem
acentos (como acima) para evitar caracteres corrompidos no histórico.

## 4. Versões (tags)

A cada marco, crie uma tag anotada e envie-a (o push de tags é separado):

```powershell
git tag -a v1.2.0 -m "Multifonte: Eta e BESM ate 13 meses"
git push origin v1.2.0

git tag                  # lista as tags locais
git push origin --tags   # envia todas as tags de uma vez (alternativa)
```

Histórico de versões do projeto:

| Tag | Conteúdo |
|---|---|
| `v1.0.0` | Conversão NCL → Python dos dois produtos operacionais + documentação |
| `v1.1.0` | Script genérico de horizontes (`rf_previsto.py`) + documentação v1.1 |
| `v1.2.0` | Multifonte (GFS/Eta/BESM até 13 meses, acúmulos 1h/12h/1d) + documentação v1.2 |
| `v1.3.0` | Config YAML (--config), prepara_gfs.py (pós-SCN 25-81) e documentação v1.4 |
| — | Commit seguinte: prepara_imerg.py (banco IMERG via GES DISC) e manual v1.5 |

No GitHub, cada tag pode virar um "Release": página do repositório →
*Releases* → *Draft a new release* → escolha a tag, descreva e publique.

## 5. Commits pendentes desta atualização

Todos os arquivos já estão no repositório local (gravados diretamente).
Se commits anteriores ainda não subiram, tudo vai junto no mesmo push:

```powershell
cd C:\Users\jorge\Claude\Projects\risco-fogo-python

git status
git add -A
git commit -m "Adiciona ERA5 (prepara_era5) e Risco de Fogo observado (rf_observado)

- prepara_era5.py: baixa t2m, td2m, u10 e v10 da ERA5 (API do CDS/
  Copernicus, requisicoes agrupadas por mes, dominio recortado), calcula a
  UR de t+td (formula de Magnus) e grava no padrao de leitura do RF:
  ERA5.OBS.TEMP2m.RH2m.{data}{hora}.nc e ERA5.OBS.U10m.V10m.{data}{hora}.nc
- rf_observado.py: RF OBSERVADO com IMERG (120 dias, incluindo o dia
  analisado) + ERA5 na hora da analise (18 UTC); periodos --dias/--semanas/
  --meses/--de+--ate; --simular confere as entradas; dias incompletos sao
  pulados com aviso; saidas RF.OBS.* em data/output/2.2/RF_OBS; suporta
  --sem-vegetacao/--sem-topografia
- rf_config: caminhos era5_dir/era5_padrao/era5_padrao_vento e
  caminho_era5(); config_exemplo.yaml atualizado
- requirements.txt: + cdsapi
- Testes: teste_prepara_era5.py e teste_rf_observado.py
- Manual v1.9: secoes 6.3 (ERA5) e 6.4 (RF observado)"

git push origin main
```

Por último, o vento do GFS (insumo do FWI previsto):

```powershell
git add -A
git commit -m "Baixa o vento a 10 m do GFS (insumo do FWI previsto)

- prepara_gfs: UGRD/VGRD a 10 m entram no fast download (.idx) e no grib
  filter; novo arquivo GFS.PREV.U10m.V10m.{modelo}.{valida}.nc no mesmo
  formato do vento da ERA5 (lido pela mesma funcao); --sem-vento mantem o
  download enxuto de quem so precisa do RF (~2 MB/horario contra ~3 MB)
- teste_prepara_gfs: mensagens de vento no .idx, byte-ranges, arquivo
  proprio e conversao para km/h pela leitura do FWI
- prepara_gfs: 404 nao e mais repetido (rodada ainda nao publicada) e a
  mensagem explica o que fazer; --auto-rodada recua de 6 em 6 h ate a
  rodada mais recente disponivel (--voltar-rodadas, padrao 4)
- teste_prepara_gfs: mensagens de vento no .idx e fallback de rodada
- Manual v2.4: secao 6.1 (vento e rodada nao publicada) e 7.4 (roteiro
  do FWI previsto)"

git push origin main
```

Antes disso, o horário do ERA5 e a escala da UR:

```powershell
git add -A
git commit -m "Adiciona horario solar local do ERA5 e chave de escala da UR

- era5_tempo.py: fusos solares por longitude, horas UTC necessarias e
  composicao do campo faixa a faixa
- rf_config: nova secao 'era5' (horario fixo|solar, hora, hora_local,
  horas) e chave correcao_ur em 'execucao'
- prepara_era5: baixa as horas UTC ditadas pela secao 'era5' (uma no modo
  fixo; todas as que cobrem as faixas de longitude no modo solar), com
  --hora aceitando lista explicita
- rf_observado/fwi_observado: modo solar monta T, UR e vento por faixa de
  fuso; produto ganha sufixo _SOLAR e os arquivos sao rotulados pela hora
  local; --horario e --hora-local sobrepoem o config
- rf_core: escala da UR no FU configuravel (FATOR_UR: ncl|decimos|
  percentual); o padrao 'ncl' reproduz a operacao (UR em fracao, FU quase
  constante), as demais sao para analise de sensibilidade e ganham sufixo
  (_URDEC/_URPER) e atributo escala_ur_no_FU no NetCDF
- rf_previsto/rf_observado: --correcao-ur
- teste_era5_horario.py: fusos, composicao por faixa, produtos separados e
  efeito da escala da UR
- Manual v2.2: novas secoes 6.6 (horario) e 6.7 (escala da UR)"

git push origin main
```

Antes disso, o motor FWI:

```powershell
git add -A
git commit -m "Implementa o motor FWI (Canadian Fire Weather Index System)

- fwi_core.py: FFMC, DMC, DC, ISI, BUI, FWI e DSR vetorizados em numpy,
  com ajuste hemisferico por faixas de latitude (tabelas de duracao do
  dia do DMC e do DC) e estado (EstadoFWI) que atravessa os dias
- fwi_observado.py: FWI observado diario a partir do IMERG (chuva) e da
  ERA5 (T, UR e vento 10 m); calculo sequencial com spin-up (padrao 90
  dias), estado salvo/retomado (--estado-inicial/--salvar-estado),
  saida com os 7 componentes por dia e agregacoes (--media/--media-mensal)
- rf_core: le_campo_rf/agrega_campos aceitam nome_var (arquivos com
  varias variaveis, como os do FWI)
- rf_figura: reconhece arquivos FWI.* e usa as classes do indice
  (0-5-12-22-35); --var plota qualquer componente
- teste_fwi.py: tabela de referencia do CFFWIS (inclui o exemplo classico
  de Van Wagner), validacao cruzada com o xclim (<1e-9), propriedades
  fisicas, ponta a ponta e continuidade do estado
- Manual v2.1: nova secao 7 (FWI); requirements: xclim (so para teste)"

git push origin main
```

Antes disso, o RF médio também no previsto (rodadas sazonais do BESM):

```powershell
git add -A
git commit -m "Adiciona RF medio mensal tambem no rf_previsto (rodadas sazonais)

- rf_core: agrega_campos/le_campo_rf/agrupa_por_mes (movidos do
  rf_observado) — agregacao compartilhada pelos dois orquestradores
- rf_previsto: --media-mensal, --media, --maximo e --so-agrega; os campos
  sao agrupados pela data valida, entao com passo diario o resultado e a
  media mensal de fato (BESM/Eta ate 13 meses)
- rf_config: chaves media, media_mensal e maximo na secao execucao
- config_besm.yaml: rodada sazonal pronta (previsao diaria de 396 dias ->
  13 mapas RF.PREV.MEDIA.AAAAMM.nc)
- config_exemplo.yaml: as duas formas de rodar o BESM (instantaneo mensal
  x media mensal) e aviso sobre a unidade do passo
- teste_rf_multifonte: cenario BESM diario -> media mensal conferida
  contra o nanmean dos diarios
- Manual: nova secao 5.7 (agregacoes da rodada e rodada sazonal do BESM)"

git push origin main
```

Antes disso (ou junto, com `git add -A`), o RF médio no observado e as figuras:

```powershell
git add -A
git commit -m "Adiciona RF medio do periodo/mensal e figuras na paleta oficial

- rf_observado: --media, --media-mensal, --maximo, --mergetime e
  --so-agrega (agrega os diarios ja existentes sem recalcular); as medias
  ignoram ausentes ponto a ponto e registram dias_agregados nos atributos
- rf_figura.py: figuras PNG de qualquer campo do pipeline com a paleta
  oficial do SLD do GeoServer (INPE_FireRiskModel_2.2), em rampa ou em
  faixas discretas (--classes), mapa unico ou painel (--painel/--colunas)
- teste_rf_observado: cenarios de agregacao (media conferida contra o
  nanmean dos diarios) e de geracao de figuras
- requirements.txt: + matplotlib e global-land-mask
- Manual v2.0: secao 6.4 (agregacoes) e nova secao 6.5 (figuras)"

git push origin main
```

Se o commit da ERA5 já foi feito, commite só as melhorias seguintes:

```powershell
git add -A
git commit -m "Muda o base padrao para o diretorio do ian01 e melhora os preparos

- rf_config: BASE_PADRAO agora e /p/projetos/grpeta/Team/jorge.gomes/
  risco-fogo-python (sobreposto por --base, base do --config ou variavel
  de ambiente RF_BASE); producao continua nos scripts legados
- prepara_imerg: imprime cada dia concluido (contador, MB, tempo decorrido
  e estimativa do restante) em vez de a cada 10 dias
- prepara_imerg/gfs/era5: avisam qual base esta em uso e falham cedo
  (antes de baixar) se o destino nao for gravavel
- rf_observado/prepara_era5: substitui datetime.utcnow() (obsoleto no
  Python 3.12+) por _hoje_utc() com datetime.now(timezone.utc)
- config_exemplo.yaml e manual atualizados"

git push origin main
```

Por último, o MSWEP como fonte de precipitação observada e os ajustes de
agregação/figuras:

```powershell
git add -A
git commit -m "Adiciona o MSWEP como fonte de precipitacao observada e ajusta agregacoes

MSWEP (fonte alternativa a precipitacao observada do IMERG):
- rf_config: nova secao 'precipitacao' (fonte imerg|mswep, modo in_loco|
  convertido, variavel, dominio), caminhos mswep_* e mswep_conv_*, e as
  funcoes caminho_precipitacao/variavel_precipitacao/recorte_precipitacao/
  sufixo_precipitacao; atalho execucao: precipitacao: mswep
- rf_core: le_precip_arquivo/le_grade_precip com deteccao automatica da
  variavel (o MSWEP vem como 'unknown'), recorte do dominio e selecao do
  passo de tempo aplicados ANTES da leitura (a grade global 3600x1800 e o
  mes inteiro nunca entram na memoria), fatia em vez de vetor de indices
  quando o recorte e contiguo, folga de 1 % do passo na comparacao com os
  limites do dominio (as coordenadas do MSWEP tem ruido de ponto
  flutuante - lat ate -89.95001 - e sem folga a grade saia 900x849 em vez
  de 901x850) e reordenacao de longitude 0..360;
  ler_precipitacao recusa arquivos com varios passos quando a serie
  diaria espera um dia por arquivo
- prepara_mswep.py: converte os arquivos locais do MSWEP para o padrao do
  pipeline (recorte, lat sul->norte, variavel prec), incremental, com
  reserva automatica para o arquivo mensal (jan.nc, feb.nc, ...)
- rf_observado/fwi_observado/rf_previsto: --precipitacao e
  --modo-precipitacao; produtos ganham o sufixo _MSWEP, sem se misturar
  com as rodadas de referencia com IMERG
- rf_fontes: a parte observada da serie de 120 dias le a fonte configurada
- teste_mswep.py: deteccao da variavel, recorte (inclusive lon 0..360),
  conversao, arquivo mensal, config, ponta a ponta (RF observado in loco
  == convertido; FWI com MSWEP) e verificacao com o DADO REAL quando o
  disco do MSWEP existe (grade 0,1 grau, recorte 901x850, faixa de chuva)

Agregacoes e figuras:
- --frequencia/--percentil passam a valer sozinhos (sem exigir --media ou
  --media-mensal) e, nesse caso, agregam o periodo inteiro gerando SO o
  que foi pedido - vale no RF observado, no RF previsto e no FWI
- rf_figura: rotulo correto da barra de cores e do titulo nas figuras de
  frequencia (contagem de dias x percentual) e recusa explicita de
  misturar frequencia com risco 0-1 na mesma figura/painel
- teste_rf_observado: figuras de FREQ e P90, e o caso da mistura recusada
- rf_core: silencia os RuntimeWarning do numpy ("All-NaN slice
  encountered" / "Mean of empty slice") nos pontos sem nenhum dia valido
  (oceano) - o resultado NaN e o esperado, mas o aviso poluia a saida da
  rodada sazonal

Documentacao e utilitarios:
- confere_mswep.py: imprime a grade de um arquivo MSWEP real e o recorte
  resultante (diagnostico rapido no servidor)
- config_mswep.yaml (rodada observada com MSWEP) e config_exemplo.yaml
- manual v2.6: secao 6.9 (MSWEP), 5.7 com frequencia prevista e 6.5
  ampliada (figuras de frequencia e percentil); README e docx/pdf"

git push origin main
```

E no servidor (ian01): `git pull`.

## 6. Comandos úteis do dia a dia

```powershell
git log --oneline --decorate     # histórico resumido com tags
git log --follow -- rf_core.py   # histórico de um arquivo
git diff HEAD~1                  # o que mudou no último commit
git restore <arquivo>            # descarta alterações não commitadas
git pull origin main             # traz mudanças feitas em outra máquina
git remote -v                    # confere o remoto configurado
```

## 7. Problemas comuns

| Sintoma | Causa | Solução |
|---|---|---|
| `fatal: not a git repository` | O comando foi executado fora da pasta do repositório (ou a pasta foi copiada sem a subpasta oculta `.git`) | `cd` até a pasta certa; se o `.git` não existir, re-extraia o zip do repositório completo |
| `remote origin already exists` | O remoto já foi adicionado antes | `git remote set-url origin https://github.com/JorgeLGomes/risco-fogo-python.git` |
| Push rejeitado (`fetch first` / `non-fast-forward`) | O remoto tem commits que o local não tem (ex.: README criado pelo site, edição direta no GitHub) | `git pull origin main --no-rebase` e depois `git push` |
| Pede usuário/senha e a senha da conta falha | O GitHub não aceita senha de conta no git | Use o navegador quando o Git Credential Manager abrir, ou um Personal Access Token como senha (Settings → Developer settings → Personal access tokens) |
| Acentos corrompidos nas mensagens | Console do Windows fora de UTF-8 | `chcp 65001` antes dos commits, ou escreva as mensagens sem acentos |
| Arquivo grande recusado (>100 MB) | NetCDF/GeoTIFF commitado por engano | Os padrões `*.nc` e `*.tif` já estão no `.gitignore`; remova com `git rm --cached <arquivo>` e commite novamente |

## 8. Segurança

Antes de tornar o repositório público, remova as credenciais do `lftp` que
estão em `rf_previsto_1_2_semanas.py` (e nos scripts originais em
`originais/` e nos documentos): mova usuário/senha para variáveis de
ambiente ou `~/.netrc`. Atenção: apagar do arquivo não apaga do histórico
do git — se a senha já foi commitada e o repositório for público, troque a
senha no servidor e reescreva o histórico (ex.: `git filter-repo`) se
necessário.
