# Risco de Fogo Previsto — INPE_FireRiskModel v2.2 (Python)

Cálculo do Risco de Fogo (RF) previsto em 1 km para a América do Sul, convertido
de Bash + NCL para Python puro (numpy / xarray / netCDF4 / rasterio), sem
dependência de NCL, cdo, GDAL (binário) ou GNU parallel.

## Estrutura

```
rf_core.py                    # Núcleo do cálculo do RF (comum aos dois produtos)
rf_previsto_1_5dias.py        # Produto diário: 19 previsões (+6h até +4d 18UTC, a cada 6h)
rf_previsto_1_2_semanas.py    # Produto semanal: 2 previsões (+7 e +14 dias, 18UTC)
teste_rf.py                   # Teste de validação (dados sintéticos + referência fiel ao NCL)
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
```

## Validação

```bash
python3 teste_rf.py    # deve terminar com "TODOS OS TESTES PASSARAM"
```

Documentação completa em `docs/manual_usuario.md` (uso e operação) e
`docs/relatorio_conversao.md` (detalhes técnicos da conversão NCL → Python).

## Créditos

Modelo: Alberto Setzer (INPE) · Código NCL original: Guilherme Martins (INPE) ·
Adaptação semanal: Pedro Lagden · Conversão para Python: 2026.
Programa Queimadas — http://www.inpe.br/queimadas/
