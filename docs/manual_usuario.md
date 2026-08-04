# Manual do Usuário

## Risco de Fogo Previsto em Python — INPE_FireRiskModel v2.2

**Versão:** 1.0 · 4 de agosto de 2026
**Substitui:** `rf_previsto_1-5dias_2023.sh` e `rf_previsto_1-2_semanas_2024.sh` (bash + NCL)

---

## 1. Visão geral

Este pacote calcula o Risco de Fogo (RF) previsto em resolução de 1 km para a América do Sul, combinando a precipitação observada do IMERG (últimos 119 dias), as previsões do GFS (precipitação, temperatura e umidade relativa a 2 m), o mapa de vegetação (MapBiomas/IGBP) e a topografia (GTOPO30). São dois programas:

- **`rf_previsto_1_5dias.py`** — gera 19 previsões, de +6 h até +4 dias 18 UTC, a cada 6 horas (produto `RF_PREV`).
- **`rf_previsto_1_2_semanas.py`** — gera 2 previsões, para +7 e +14 dias às 18 UTC (produto `RF_PREV_SEMANAL`).

Ambos usam o módulo comum **`rf_core.py`** e produzem, para cada horário de previsão, um NetCDF (`RF.PREV.YYYYMMDDHH.nc`) e um GeoTIFF (`RF.PREV.YYYYMMDDHH.tif`), além dos produtos derivados (links D1–D5, cópias T0–T4/T7/T14, fogograma).

## 2. Requisitos

### 2.1 Software

Python 3.9 ou superior e as bibliotecas:

```bash
pip install numpy xarray netCDF4 rasterio
```

Para rodar o teste de validação, instale também o scipy:

```bash
pip install scipy
```

Não são mais necessários: NCL, cdo, gdal (binário), GNU parallel nem o ambiente conda `ncl_stable`.

### 2.2 Dados de entrada

| Dado | Local esperado | Observação |
|---|---|---|
| Precipitação IMERG (diária) | `data/output/2.2/Precipitation-2_2/AAAA/MM/INPE_FireRiskModel_2.2_Precipitation_AAAAMMDD.nc` | 119 dias anteriores à data de execução; variável `prec` |
| Previsões do GFS | `data/output/2.2/GFS/netcdf/AAAAMMDD00/` | `GFS.PREV.PREC.<modelo>.<previsão>.nc` e `GFS.PREV.TEMP2m.RH2m.<modelo>.<previsão>.nc` |
| Mapa de vegetação 1 km | `data/input/Veg_Map_2020/Merge_MapBiomas_V5_IGBP_C6_<ano>.nc` | variável `Band1`, classes 0–7, orientado de sul para norte; anos ≥ 2020 usam o mapa de 2019 |
| Topografia 1 km | `data/input/topografia/GeoTOPOAmericaSulCentral_V3.nc` | variável `Band1` (metros), mesma grade do mapa de vegetação |

Todos os caminhos partem de `/home/queimadas/INPE_FireRiskModel` e estão definidos como constantes no topo de cada script (seção "Configurações"). Para rodar em outra máquina, basta editar a constante `BASE`.

## 3. Instalação

Copie os quatro arquivos para o diretório de scripts do modelo (os três primeiros são obrigatórios; o teste é opcional):

```
rf_core.py
rf_previsto_1_5dias.py
rf_previsto_1_2_semanas.py
teste_rf.py
```

Os três arquivos devem ficar no mesmo diretório (os orquestradores fazem `import rf_core`). Se desejar, torne-os executáveis:

```bash
chmod +x rf_previsto_1_5dias.py rf_previsto_1_2_semanas.py
```

## 4. Uso

### 4.1 Execução operacional (data de hoje)

```bash
python3 rf_previsto_1_5dias.py
python3 rf_previsto_1_2_semanas.py
```

O comportamento é o mesmo dos shell scripts originais: as datas são calculadas a partir do dia corrente, as saídas vão para os mesmos diretórios e, ao final, os arquivos são publicados nos servidores.

### 4.2 Opções de linha de comando

| Opção | Efeito | Padrão |
|---|---|---|
| `--data-final YYYYMMDD` | Executa como se "hoje" fosse a data informada (reprocessamento) | data corrente |
| `--jobs N` | Número de previsões calculadas em paralelo | 20 (diário) / 2 (semanal) |
| `--sem-envio` | Não publica nos servidores (geoserver/lftp/scp) — útil para testes | envio ativado |

Exemplos:

```bash
# Reprocessar o dia 1º de agosto de 2026 sem publicar, usando 8 processos
python3 rf_previsto_1_5dias.py --data-final 20260801 --jobs 8 --sem-envio

# Rodada semanal de teste
python3 rf_previsto_1_2_semanas.py --sem-envio
```

### 4.3 Agendamento (cron)

Substitua as entradas existentes que chamavam os shell scripts, por exemplo:

```cron
30 6 * * * cd /home/queimadas/INPE_FireRiskModel/scr/risco_fogo/RF_Previsto && /usr/bin/python3 rf_previsto_1_5dias.py >> /home/queimadas/INPE_FireRiskModel/log/cron.rf_prev.log 2>&1
```

## 5. Saídas

### 5.1 Produto diário (1 a 5 dias)

| Saída | Local |
|---|---|
| NetCDF por horário (19 arquivos) | `data/output/2.2/RF_PREV/netcdf/<modelo>/RF.PREV.YYYYMMDDHH.nc` |
| GeoTIFF por horário | `data/output/2.2/RF_PREV/tif/<modelo>/RF.PREV.YYYYMMDDHH.tif` |
| Links para o mapserver (D1–D5, horários 18 UTC) | `dados/mapfiles/tmp/RF.PREV.D<dia>.tif` |
| Cópias T0–T4 (18 UTC) | `.../tif/<modelo>/RF.PREV.T<d>.YYYYMMDD18.tif` |
| Fogograma (todos os horários juntos) | `data/output/2.2/fogograma/RF.PREV.<data>00.nc` |

### 5.2 Produto semanal (1 a 2 semanas)

| Saída | Local |
|---|---|
| NetCDF (2 arquivos: +7 e +14 dias) | `data/output/2.2/RF_PREV_SEMANAL/netcdf/<modelo>/` |
| GeoTIFF T7 e T14 | `.../RF_PREV_SEMANAL/tif/<modelo>/RF.PREV.T7.tif` e `RF.PREV.T14.tif` |

### 5.3 Formato dos arquivos

O NetCDF contém a variável `rbf(time, lat, lon)` com o RF em [0, 1], arredondado a 2 casas decimais, valor ausente −999 e eixo de tempo na data/hora da previsão. O GeoTIFF está em EPSG:4326, orientado de norte para sul, com nodata −999, compressão LZW e organização em tiles.

Interpretação usual do RF: mínimo (< 0.15), baixo (0.15–0.40), médio (0.40–0.70), alto (0.70–0.95) e crítico (≥ 0.95).

## 6. Logs e monitoramento

| Log | Conteúdo |
|---|---|
| `log/log.<modelo>.<previsão>` | Progresso e eventuais erros de cada previsão (um por horário) |
| `log.falta.arquivos.prev.prec.txt` (diretório de execução) | Arquivos IMERG esperados e não encontrados |
| Saída padrão | Datas da rodada, horários processados e tempo total |

O código de saída é 0 em caso de sucesso e 1 se alguma previsão não foi gerada (mensagem `PROBLEMA - FALTAM ARQUIVOS EM <dir>`), o que permite monitorar a rodada no cron da mesma forma que antes.

## 7. Solução de problemas

| Sintoma | Causa provável | O que fazer |
|---|---|---|
| `Número de tempos de precipitação insuficiente: N (esperado 120)` | Faltam arquivos IMERG no período de 119 dias | Verifique `log.falta.arquivos.prev.prec.txt` e reponha os arquivos |
| `PROBLEMA - FALTAM ARQUIVOS EM ...` | Uma ou mais previsões falharam | Consulte `log/log.<modelo>.<previsão>` do horário faltante |
| `FileNotFoundError` em arquivo `GFS.PREV.*` | A rodada do GFS ainda não foi processada para o dia | Aguarde/reprocesse a etapa do GFS e rode novamente |
| `A topografia (...) não tem a mesma grade do mapa de vegetação (...)` | Arquivo de topografia ou vegetação trocado | Confira os arquivos em `data/input/` |
| Consumo excessivo de memória / máquina lenta | Muitos processos simultâneos em grade de 1 km | Reduza `--jobs` |
| Falha no envio (lftp/scp) | Rede ou credenciais | O cálculo não é afetado; reenvie manualmente ou rode novamente com envio |
| `ModuleNotFoundError: rasterio` (ou outra biblioteca) | Dependências não instaladas no Python usado | `pip install numpy xarray netCDF4 rasterio` |

## 8. Teste de validação

Após instalar ou alterar qualquer coisa, rode:

```bash
python3 teste_rf.py
```

O teste cria dados sintéticos em `/tmp/teste_rf`, executa o cálculo completo e compara com uma implementação de referência fiel ao NCL. A saída esperada termina com `TODOS OS TESTES PASSARAM`.

## 9. Segurança

O script semanal contém as credenciais do `lftp` (herdadas do shell script original) nas constantes `LFTP_USUARIO` e `LFTP_SENHA`. Recomenda-se movê-las para variáveis de ambiente ou para o arquivo `~/.netrc` e restringir a permissão de leitura dos scripts.

## 10. Suporte

Modelo: Alberto Setzer (alberto.setzer@inpe.br) · Código NCL original: Guilherme Martins (guilherme.martins@inpe.br) · Programa Queimadas: http://www.inpe.br/queimadas/
