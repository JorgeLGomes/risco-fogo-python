# Risco de Fogo Previsto — INPE_FireRiskModel v2.2 (Python)

Cálculo do Risco de Fogo (RF) previsto em 1 km para a América do Sul, convertido
de Bash + NCL para Python puro (numpy / xarray / netCDF4 / rasterio), sem
dependência de NCL, cdo, GDAL (binário) ou GNU parallel.

## Estrutura

```
rf_core.py                    # Núcleo do cálculo do RF (comum aos dois produtos)
rf_previsto_1_5dias.py        # Produto diário: 19 previsões (+6h até +4d 18UTC, a cada 6h)
rf_previsto_1_2_semanas.py    # Produto semanal: 2 previsões (+7 e +14 dias, 18UTC)
rf_previsto.py                # Script genérico: qualquer horizonte e fonte (GFS ~16d; Eta/BESM até 13 meses)
rf_fontes.py                  # Camada de fontes: config por fonte, agregação 1h/12h/1d, série IMERG+previsão
rf_config.py                  # Configuração YAML dos dados de entrada (--config)
prepara_gfs.py                # Download do GFS (fast download .idx / grib filter — pós-SCN 25-81)
prepara_imerg.py              # Download/conversão do IMERG Early Daily V07 (GES DISC, Earthdata)
prepara_era5.py               # Download/conversão da ERA5: t2m, ur2m (de t+td), u10, v10 (CDS/Copernicus)
rf_observado.py               # RF OBSERVADO (IMERG + ERA5): dias/semanas/meses + médias do período
rf_figura.py                  # Figuras PNG na paleta oficial (SLD do GeoServer)
teste_rf.py                   # Teste de validação (dados sintéticos + referência fiel ao NCL)
teste_rf_previsto.py          # Teste de ponta a ponta do script genérico
teste_rf_multifonte.py        # Teste do modo multifonte (Eta 13m, BESM 12h, fonte via JSON)
teste_prepara_gfs.py          # Teste do preparo do GFS (idx, baldes 6h/12h)
config_exemplo.yaml           # Modelo comentado do arquivo de configuração
config_besm.yaml              # Rodada sazonal do BESM: RF médio mensal de +1 a +13 meses
ativa_riscofogo.sh            # Ativação do ambiente no cluster (use com source)
requirements.txt              # Dependências Python
docs/                         # Relatório de conversão e manual do usuário (md, docx, pdf)
originais/                    # Scripts bash+NCL originais, mantidos para referência
```

## Instalação

```bash
pip install -r requirements.txt
```

## Uso

```bash
python3 rf_previsto_1_5dias.py                    # rodada operacional (hoje)
python3 rf_previsto_1_5dias.py --data-final 20260801 --jobs 8 --sem-envio
python3 rf_previsto_1_2_semanas.py --sem-envio

# Script genérico: qualquer horizonte
python3 rf_previsto.py --horizontes 18h,2d18h,7d18h
python3 rf_previsto.py --de 6h --ate 4d18h --passo 6h

# Multifonte: Eta e BESM até 13 meses
python3 rf_previsto.py --fonte eta --de 1m --ate 13m --passo 1m
python3 rf_previsto.py --fonte besm --horizontes 6m

# BESM sazonal: RF MÉDIO de cada mês, +1 a +13 (previsão diária agregada)
python3 rf_previsto.py --config config_besm.yaml
python3 rf_figura.py <saida>/RF.PREV.MEDIA.2026*.nc --painel --colunas 4

# Preparo das entradas (IMERG observado + GFS previsto) + RF
python3 prepara_imerg.py --config config.yaml
python3 prepara_gfs.py --config config.yaml
python3 rf_previsto.py --config config.yaml

# Rodada diária operacional definida só no YAML (execucao: data_final: hoje
# + horizontes pré-estabelecidos) — cada execução usa a data do sistema
python3 rf_previsto.py --config config.yaml

# Análise de sensibilidade: desligar componentes individualmente
python3 rf_previsto.py --horizontes 3d --sem-topografia
python3 rf_previsto.py --horizontes 3d --sem-vegetacao --classe-veg 4
# --sem-vegetacao dispensa o mapa (saída na grade da precipitação);
# com --sem-topografia junto, roda sem NENHUM arquivo estático

# RF OBSERVADO (IMERG + ERA5): últimos dias, semanas ou meses
python3 prepara_era5.py  --config config.yaml --dias 7    # T/UR da ERA5 (requer ~/.cdsapirc)
python3 rf_observado.py  --config config.yaml --dias 7
python3 rf_observado.py  --config config.yaml --meses 3 --sem-vegetacao --sem-topografia

# Um mês fechado (julho/2026) + o risco MÉDIO do mês, e a figura
python3 rf_observado.py --de 20260701 --ate 20260731 --media
python3 rf_figura.py data/output/2.2/RF_OBS/netcdf/RF.OBS.MEDIA.202607.nc
```

## Validação

```bash
python3 teste_rf.py           # núcleo do cálculo — "TODOS OS TESTES PASSARAM"
python3 teste_rf_previsto.py  # script genérico de ponta a ponta
python3 teste_rf_multifonte.py # modo multifonte (Eta/BESM)
```

Documentação completa em `docs/manual_usuario.md` (uso e operação),
`docs/relatorio_conversao.md` (detalhes técnicos da conversão NCL → Python) e
`docs/instrucoes_git_github.md` (fluxo de commits, tags e publicação no GitHub).

## Publicação no GitHub

Repositório: https://github.com/JorgeLGomes/risco-fogo-python

```bash
git status && git diff        # confira as mudanças
python3 teste_rf.py && python3 teste_rf_previsto.py && python3 teste_rf_multifonte.py
git add <arquivos>
git commit -m "Mensagem no imperativo"
git push origin main
```

Convenções, versionamento (tags v1.0.0 → v1.2.0) e solução de problemas:
ver `docs/instrucoes_git_github.md`.

## Créditos

Modelo: Alberto Setzer (INPE) · Código NCL original: Guilherme Martins (INPE) ·
Adaptação semanal: Pedro Lagden · Conversão para Python: 2026.
Programa Queimadas — http://www.inpe.br/queimadas/
