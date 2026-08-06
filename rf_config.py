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
    mswep_dir:        pasta raiz do MSWEP diário ORIGINAL (global 0,1°)
    mswep_subpastas:  subpastas por data do MSWEP original
    mswep_padrao:     nome do arquivo MSWEP original ({data} = YYYYMMDD)
    mswep_conv_dir/subpastas/padrao: idem, para os arquivos MSWEP já
                      convertidos ao padrão do pipeline (prepara_mswep.py)
    mapa_vegetacao:   mapa de vegetação 1 km (marcador {ano_veg})
    topografia:       arquivo de topografia 1 km
    log:              pasta de logs

  fontes:    mesmas chaves do --config-fontes (rf_fontes.py): ajusta ou
             acrescenta fontes de previsão (gfs, eta, besm, ...).

  precipitacao: fonte da precipitação OBSERVADA (a janela de 120 dias do
             RF, o RF observado e o FWI observado):
    fonte:     "imerg" (padrão) ou "mswep"
    modo:      "in_loco" (lê os arquivos originais, recortando o domínio
               na leitura) ou "convertido" (usa a cópia gerada pelo
               prepara_mswep.py, no padrão do pipeline)
    variavel:  nome da variável no arquivo ("auto" detecta sozinho)
    dominio:   recorte "latS,latN,lonW,lonE" aplicado na leitura in loco

  era5:      horário das variáveis meteorológicas dos produtos observados
             (RF e FWI observados) — ver era5_tempo.py:
    horario:     "fixo" (uma hora UTC para todo o domínio) ou "solar"
                 (hora solar local, montada por faixas de longitude)
    hora:        hora UTC usada no modo fixo (padrão 18)
    hora_local:  hora solar local usada no modo solar (padrão 15)
    horas:       lista explícita de horas UTC a baixar/usar (opcional)

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

# Diretório base padrão, usado quando não há --base, --config nem a
# variável de ambiente RF_BASE. Precedência:
#   --base (CLI)  >  base do --config  >  RF_BASE (ambiente)  >  este valor
# Na produção do Queimadas o base é /home/queimadas/INPE_FireRiskModel
# (valor mantido nos scripts legados rf_previsto_1_5dias/1_2_semanas).
BASE_PADRAO = (os.environ.get("RF_BASE")
               or "/p/projetos/grpeta/Team/jorge.gomes/risco-fogo-python")

CAMINHOS_PADRAO = {
    "imerg_dir": "data/output/2.2/Precipitation-2_2",
    "imerg_subpastas": "{ano}/{mes}",
    "imerg_padrao": "INPE_FireRiskModel_2.2_Precipitation_{data}.nc",
    # MSWEP original (como está no disco do CPTEC), lido in loco
    "mswep_dir": "/pesq/dados/sismom/SisMOM/sipec/mswep/daily",
    "mswep_subpastas": "{ano}/{mes}",
    "mswep_padrao": "{data}.nc",
    # MSWEP já convertido ao padrão do pipeline (prepara_mswep.py)
    "mswep_conv_dir": "data/output/2.2/MSWEP-2_2",
    "mswep_conv_subpastas": "{ano}/{mes}",
    "mswep_conv_padrao": "INPE_FireRiskModel_2.2_Precipitation_MSWEP_{data}.nc",
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
                   "classe_veg", "media", "media_mensal", "maximo",
                   "correcao_ur", "precipitacao")

# Seção "precipitacao": fonte da precipitação OBSERVADA.
DOMINIO_PADRAO = "-60.05,29.95,-114.95,-30.05"    # latS,latN,lonW,lonE

PRECIPITACAO_PADRAO = {
    "fonte": "imerg",        # "imerg" | "mswep"
    "modo": "in_loco",       # "in_loco" | "convertido"  (só afeta o MSWEP)
    "variavel": "auto",      # nome da variável no arquivo ("auto" detecta)
    "dominio": DOMINIO_PADRAO,   # recorte aplicado na leitura in loco
}

FONTES_PRECIPITACAO = ("imerg", "mswep")

# Seção "era5": horário das variáveis meteorológicas dos produtos
# observados (ver era5_tempo.py).
ERA5_PADRAO = {
    "horario": "fixo",     # "fixo" (uma hora UTC) | "solar" (hora local)
    "hora": 18,            # hora UTC no modo fixo
    "hora_local": 15,      # hora solar local no modo solar
    "horas": None,         # lista explícita de horas UTC a baixar/usar
}

SECOES_VALIDAS = {"base", "caminhos", "fontes", "execucao", "era5",
                  "precipitacao"}


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

    era5 = copy.deepcopy(ERA5_PADRAO)
    extras_era5 = cfg.get("era5") or {}
    invalidas = set(extras_era5) - set(ERA5_PADRAO)
    if invalidas:
        raise ValueError(
            f"Chaves desconhecidas em 'era5': {sorted(invalidas)}. "
            f"Válidas: {sorted(ERA5_PADRAO)}.")
    era5.update(extras_era5)

    precipitacao = copy.deepcopy(PRECIPITACAO_PADRAO)
    extras_prec = cfg.get("precipitacao") or {}
    invalidas = set(extras_prec) - set(PRECIPITACAO_PADRAO)
    if invalidas:
        raise ValueError(
            f"Chaves desconhecidas em 'precipitacao': {sorted(invalidas)}. "
            f"Válidas: {sorted(PRECIPITACAO_PADRAO)}.")
    precipitacao.update(extras_prec)

    execucao = cfg.get("execucao") or {}
    invalidas = set(execucao) - set(EXECUCAO_CHAVES)
    if invalidas:
        raise ValueError(
            f"Chaves desconhecidas em 'execucao': {sorted(invalidas)}. "
            f"Válidas: {sorted(EXECUCAO_CHAVES)}.")

    # "execucao: precipitacao: mswep" é um atalho para "precipitacao: fonte"
    if execucao.get("precipitacao"):
        precipitacao["fonte"] = str(execucao["precipitacao"]).lower()

    valida_precipitacao(precipitacao)

    return {
        "base": cfg.get("base") or BASE_PADRAO,
        "caminhos": caminhos,
        "fontes": cfg.get("fontes") or {},
        "execucao": execucao,
        "era5": era5,
        "precipitacao": precipitacao,
    }


def valida_precipitacao(precipitacao):
    """Confere a seção 'precipitacao' e normaliza os valores."""
    fonte = str(precipitacao.get("fonte") or "imerg").lower()
    if fonte not in FONTES_PRECIPITACAO:
        raise ValueError(
            f"Fonte de precipitação observada desconhecida: '{fonte}'. "
            f"Válidas: {', '.join(FONTES_PRECIPITACAO)}.")
    modo = str(precipitacao.get("modo") or "in_loco").lower()
    if modo not in ("in_loco", "convertido"):
        raise ValueError(
            f"Modo de leitura da precipitação desconhecido: '{modo}'. "
            f"Válidos: in_loco, convertido.")
    precipitacao["fonte"] = fonte
    precipitacao["modo"] = modo
    return precipitacao


def padrao():
    """Configuração padrão (sem arquivo)."""
    return {
        "base": BASE_PADRAO,
        "caminhos": copy.deepcopy(CAMINHOS_PADRAO),
        "fontes": {},
        "execucao": {},
        "era5": copy.deepcopy(ERA5_PADRAO),
        "precipitacao": copy.deepcopy(PRECIPITACAO_PADRAO),
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


def caminho_mswep(base, caminhos, dia, convertido=False):
    """Caminho do arquivo MSWEP diário do dia (datetime).

    ``convertido=False`` devolve o arquivo ORIGINAL (global 0,1°, como
    está no disco do CPTEC); ``True`` devolve a cópia já convertida ao
    padrão do pipeline pelo prepara_mswep.py."""
    ymd = dia.strftime("%Y%m%d")
    p = "mswep_conv_" if convertido else "mswep_"
    sub = caminhos[p + "subpastas"].format(
        ano=ymd[:4], mes=ymd[4:6], dia=ymd[6:8])
    nome = caminhos[p + "padrao"].format(data=ymd)
    return os.path.join(resolve(base, caminhos[p + "dir"]), sub, nome)


def caminho_precipitacao(base, caminhos, dia, precipitacao=None):
    """Caminho do arquivo de precipitação OBSERVADA do dia, conforme a
    seção 'precipitacao' da configuração (IMERG ou MSWEP)."""
    cfg = precipitacao or PRECIPITACAO_PADRAO
    if str(cfg.get("fonte", "imerg")).lower() == "mswep":
        return caminho_mswep(base, caminhos, dia,
                             convertido=cfg.get("modo") == "convertido")
    return caminho_imerg(base, caminhos, dia)


def variavel_precipitacao(precipitacao=None):
    """Nome da variável de precipitação a ler (None = detecção automática).

    Os arquivos do pipeline (IMERG e MSWEP convertido) usam sempre `prec`;
    o MSWEP original é lido com detecção automática, a menos que o nome
    seja declarado em 'precipitacao: variavel:'."""
    cfg = precipitacao or PRECIPITACAO_PADRAO
    declarada = cfg.get("variavel")
    if declarada and str(declarada).lower() not in ("auto", "none", ""):
        return str(declarada)
    if (str(cfg.get("fonte", "imerg")).lower() == "mswep"
            and cfg.get("modo") != "convertido"):
        return None                      # detecta sozinho
    return "prec"


def recorte_precipitacao(precipitacao=None):
    """Recorte (latS, latN, lonW, lonE) a aplicar na leitura, ou None.

    Só é usado na leitura in loco de arquivos globais (MSWEP original);
    os arquivos do pipeline já vêm recortados."""
    cfg = precipitacao or PRECIPITACAO_PADRAO
    if (str(cfg.get("fonte", "imerg")).lower() != "mswep"
            or cfg.get("modo") == "convertido"):
        return None
    dominio = cfg.get("dominio") or DOMINIO_PADRAO
    if isinstance(dominio, str):
        dominio = [float(x) for x in dominio.split(",")]
    valores = tuple(float(x) for x in dominio)
    if len(valores) != 4:
        raise ValueError("'precipitacao: dominio' deve ter 4 valores: "
                         "latS,latN,lonW,lonE.")
    return valores


def descricao_precipitacao(precipitacao=None):
    """Texto curto da fonte de precipitação observada, para os cabeçalhos."""
    cfg = precipitacao or PRECIPITACAO_PADRAO
    fonte = str(cfg.get("fonte", "imerg")).lower()
    if fonte != "mswep":
        return "IMERG (GPM/NASA)"
    modo = ("arquivos originais, recorte na leitura"
            if cfg.get("modo") != "convertido"
            else "cópia convertida (prepara_mswep.py)")
    return f"MSWEP ({modo})"


def sufixo_precipitacao(precipitacao=None):
    """Sufixo do nome do produto quando a fonte não é a padrão (IMERG)."""
    cfg = precipitacao or PRECIPITACAO_PADRAO
    fonte = str(cfg.get("fonte", "imerg")).lower()
    return "" if fonte == "imerg" else "_" + fonte.upper()


def caminho_era5(base, caminhos, dia, hora, vento=False):
    """Caminho completo do arquivo ERA5 do dia (datetime) na hora HH.
    ``vento=True`` devolve o arquivo de U10m/V10m em vez de T/UR."""
    chave = "era5_padrao_vento" if vento else "era5_padrao"
    nome = caminhos[chave].format(data=dia.strftime("%Y%m%d"),
                                  hora=f"{int(hora):02d}")
    return os.path.join(resolve(base, caminhos["era5_dir"]), nome)
