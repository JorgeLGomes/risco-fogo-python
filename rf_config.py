# -*- coding: utf-8 -*-
"""
rf_config.py
============

Arquivo de configuração dos DADOS DE ENTRADA do Risco de Fogo, em YAML
(ou JSON), usado pelo rf_previsto.py via ``--config arquivo.yaml``.

O arquivo tem três seções, todas opcionais — o que não for informado usa
os padrões da produção:

  base:      diretório base do modelo (ex.: /home/queimadas/INPE_FireRiskModel)

  caminhos:  onde estão os dados de entrada. Caminhos relativos são
             resolvidos a partir de ``base``; absolutos são usados como estão.
    imerg_dir:        pasta raiz do IMERG diário
    imerg_subpastas:  subpastas por data (marcadores {ano}, {mes}, {dia})
    imerg_padrao:     nome do arquivo IMERG (marcador {data} = YYYYMMDD)
    mapa_vegetacao:   mapa de vegetação 1 km (marcador {ano_veg})
    topografia:       arquivo de topografia 1 km
    log:              pasta de logs

  fontes:    mesmas chaves do --config-fontes (rf_fontes.py): ajusta ou
             acrescenta fontes de previsão (gfs, eta, besm, ...).

  execucao:  valores padrão da linha de comando (a CLI sempre prevalece):
             fonte, horizontes, de, ate, passo, data_final, rb_max,
             produto, jobs, fallback_gfs, sem_tif, fogograma.

Precedência: linha de comando > YAML > padrões embutidos.

Exemplo completo em ``config_exemplo.yaml``.
"""

import copy
import json
import os

try:
    import yaml
except ImportError:          # PyYAML é opcional se o arquivo for JSON
    yaml = None

# ---------------------------------------------------------------------------
# Padrões (idênticos aos valores da produção)
# ---------------------------------------------------------------------------

BASE_PADRAO = "/home/queimadas/INPE_FireRiskModel"

CAMINHOS_PADRAO = {
    "imerg_dir": "data/output/2.2/Precipitation-2_2",
    "imerg_subpastas": "{ano}/{mes}",
    "imerg_padrao": "INPE_FireRiskModel_2.2_Precipitation_{data}.nc",
    "mapa_vegetacao": "data/input/Veg_Map_2020/"
                      "Merge_MapBiomas_V5_IGBP_C6_{ano_veg}.nc",
    "topografia": "data/input/topografia/GeoTOPOAmericaSulCentral_V3.nc",
    "era5_dir": "data/output/2.2/ERA5/netcdf",
    "era5_padrao": "ERA5.OBS.TEMP2m.RH2m.{data}{hora}.nc",
    "era5_padrao_vento": "ERA5.OBS.U10m.V10m.{data}{hora}.nc",
    "log": "log",
}

# Chaves aceitas em "execucao" -> nome do atributo do argparse.
EXECUCAO_CHAVES = ("fonte", "horizontes", "de", "ate", "passo", "data_final",
                   "rb_max", "produto", "jobs", "fallback_gfs", "sem_tif",
                   "fogograma", "sem_vegetacao", "sem_topografia",
                   "classe_veg")

SECOES_VALIDAS = {"base", "caminhos", "fontes", "execucao"}


def carrega(caminho):
    """Lê o arquivo YAML (ou JSON) e devolve o dicionário de configuração
    já validado e com os padrões preenchidos."""
    if caminho.lower().endswith((".yaml", ".yml")):
        if yaml is None:
            raise RuntimeError(
                "PyYAML não instalado (pip install pyyaml) — ou use JSON.")
        with open(caminho) as f:
            cfg = yaml.safe_load(f) or {}
    else:
        with open(caminho) as f:
            cfg = json.load(f)

    if not isinstance(cfg, dict):
        raise ValueError(f"Configuração inválida em {caminho}: esperado um "
                         f"mapeamento no nível raiz.")

    desconhecidas = set(cfg) - SECOES_VALIDAS
    if desconhecidas:
        raise ValueError(
            f"Seções desconhecidas em {caminho}: {sorted(desconhecidas)}. "
            f"Válidas: {sorted(SECOES_VALIDAS)}.")

    caminhos = copy.deepcopy(CAMINHOS_PADRAO)
    extras = cfg.get("caminhos") or {}
    invalidas = set(extras) - set(CAMINHOS_PADRAO)
    if invalidas:
        raise ValueError(
            f"Chaves desconhecidas em 'caminhos': {sorted(invalidas)}. "
            f"Válidas: {sorted(CAMINHOS_PADRAO)}.")
    caminhos.update(extras)

    execucao = cfg.get("execucao") or {}
    invalidas = set(execucao) - set(EXECUCAO_CHAVES)
    if invalidas:
        raise ValueError(
            f"Chaves desconhecidas em 'execucao': {sorted(invalidas)}. "
            f"Válidas: {sorted(EXECUCAO_CHAVES)}.")

    return {
        "base": cfg.get("base") or BASE_PADRAO,
        "caminhos": caminhos,
        "fontes": cfg.get("fontes") or {},
        "execucao": execucao,
    }


def padrao():
    """Configuração padrão (sem arquivo)."""
    return {
        "base": BASE_PADRAO,
        "caminhos": copy.deepcopy(CAMINHOS_PADRAO),
        "fontes": {},
        "execucao": {},
    }


def resolve(base, caminho):
    """Resolve um caminho da configuração: absoluto fica como está;
    relativo é ancorado no diretório base."""
    return caminho if os.path.isabs(caminho) else os.path.join(base, caminho)


def caminho_imerg(base, caminhos, dia):
    """Caminho completo do arquivo IMERG do dia (datetime)."""
    ymd = dia.strftime("%Y%m%d")
    sub = caminhos["imerg_subpastas"].format(
        ano=ymd[:4], mes=ymd[4:6], dia=ymd[6:8])
    nome = caminhos["imerg_padrao"].format(data=ymd)
    return os.path.join(resolve(base, caminhos["imerg_dir"]), sub, nome)


def caminho_era5(base, caminhos, dia, hora, vento=False):
    """Caminho completo do arquivo ERA5 do dia (datetime) na hora HH.
    ``vento=True`` devolve o arquivo de U10m/V10m em vez de T/UR."""
    chave = "era5_padrao_vento" if vento else "era5_padrao"
    nome = caminhos[chave].format(data=dia.strftime("%Y%m%d"),
                                  hora=f"{int(hora):02d}")
    return os.path.join(resolve(base, caminhos["era5_dir"]), nome)
