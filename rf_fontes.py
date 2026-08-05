# -*- coding: utf-8 -*-
"""
rf_fontes.py
============

Camada de fontes de dados de previsão para o Risco de Fogo (RF).

Permite usar diferentes modelos como forçante — GFS (~16 dias), Eta e
BESM (até 13 meses) — com acúmulos de precipitação fornecidos em
diferentes frequências (1h, 12h, 1 dia).

Cada fonte é descrita por uma configuração (dataclass ``FonteDados``) com:
  - padrões de nome dos arquivos (com marcadores {modelo} e {valida});
  - nomes das variáveis de precipitação, temperatura e umidade relativa;
  - frequência dos acúmulos ("1h", "12h", "1d") e tipo de acumulação
    ("intervalo" = acumulado do próprio intervalo; "desde_inicio" =
    acumulado desde o início da rodada, como no GFS bruto);
  - unidades da temperatura ("K" ou "C") e da umidade ("%" ou "frac");
  - horizonte máximo em dias.

Os arquivos de previsão devem ser NetCDF em grade regular lat/lon
(como os do GFS já pré-processados neste pipeline). As fontes padrão
abaixo (GFS, ETA, BESM) podem ser ajustadas por um arquivo JSON via
``carrega_fontes_json`` — use isso para adequar os padrões de nome à
convenção real dos arquivos sem alterar o código.

Para horizontes longos, a série diária de 120 tempos que alimenta o
cálculo do RF é montada misturando:
  - IMERG observado, para os dias anteriores à rodada do modelo;
  - precipitação PREVISTA da fonte, para os dias entre a rodada e a
    data válida (agregada para o passo diário e interpolada para a
    grade do IMERG quando necessário).
"""

import dataclasses
import datetime as dt
import json
import os

import numpy as np
import xarray as xr

import rf_core


# ---------------------------------------------------------------------------
# Configuração de uma fonte de dados
# ---------------------------------------------------------------------------

@dataclasses.dataclass
class FonteDados:
    """Descrição de uma fonte de previsão (GFS, Eta, BESM, ...)."""

    nome: str
    # Subdiretório da fonte em {base}/data/output/2.2/, com {modelo} disponível.
    subdir: str
    # Layout dos arquivos:
    #   "por_tempo": um arquivo por horário previsto (como o GFS deste
    #                pipeline) — usa padrao_prec e padrao_temp_ur;
    #   "serie":     um arquivo por VARIÁVEL com todos os tempos da rodada
    #                (como o BESM T062) — usa padrao_prec, padrao_temp e
    #                padrao_ur (arquivos separados).
    layout: str = "por_tempo"
    # Padrões de nome dos arquivos. Marcadores: {modelo} = YYYYMMDDHH da
    # rodada; {valida} = YYYYMMDDHH do fim do intervalo/hora prevista
    # (o {valida} não é usado no layout "serie").
    padrao_prec: str = ""
    padrao_temp_ur: str = ""     # layout "por_tempo": T e UR no mesmo arquivo
    padrao_temp: str = ""        # layout "serie": arquivo só de temperatura
    padrao_ur: str = ""          # layout "serie": arquivo só de umidade
    # Nomes das variáveis nos arquivos NetCDF.
    var_prec: str = "prec"
    var_temp: str = "TEMP2m"
    var_ur: str = "RH2m"
    # Frequência dos acúmulos de precipitação: "1h", "12h" ou "1d".
    freq_prec: str = "1d"
    # "intervalo": cada tempo traz o acumulado do próprio intervalo;
    # "desde_inicio": acumulado desde o início da rodada (faz-se a diferença).
    tipo_acumulo: str = "intervalo"
    # Unidades: temperatura em "K" ou "C"; umidade em "%" ou "frac".
    unidade_temp: str = "K"
    unidade_ur: str = "%"
    # Horizonte máximo suportado pela fonte, em dias.
    horizonte_max_dias: int = 16

    # ---------------------------------------------------------------- nomes
    def horas_por_passo(self):
        return {"1h": 1, "12h": 12, "1d": 24}[self.freq_prec]

    def arquivo_prec(self, dirin, modelo, valida=""):
        return os.path.join(dirin, self.padrao_prec.format(
            modelo=modelo, valida=valida))

    def arquivo_temp_ur(self, dirin, modelo, valida=""):
        return os.path.join(dirin, self.padrao_temp_ur.format(
            modelo=modelo, valida=valida))

    def arquivo_temp(self, dirin, modelo):
        return os.path.join(dirin, self.padrao_temp.format(modelo=modelo))

    def arquivo_ur(self, dirin, modelo):
        return os.path.join(dirin, self.padrao_ur.format(modelo=modelo))


# ---------------------------------------------------------------------------
# Fontes padrão (ajuste os padrões de nome à convenção real via JSON)
# ---------------------------------------------------------------------------

FONTES = {
    # GFS pré-processado deste pipeline: 1 arquivo diário de precipitação
    # por horário previsto (acumulado do próprio dia) + arquivo de T/UR.
    "gfs": FonteDados(
        nome="gfs",
        subdir="GFS/netcdf/{modelo}",
        padrao_prec="GFS.PREV.PREC.{modelo}.{valida}.nc",
        padrao_temp_ur="GFS.PREV.TEMP2m.RH2m.{modelo}.{valida}.nc",
        var_prec="prec", var_temp="TEMP2m", var_ur="RH2m",
        freq_prec="1d", tipo_acumulo="intervalo",
        unidade_temp="K", unidade_ur="%",
        horizonte_max_dias=16,
    ),
    # Eta: até 13 meses. Padrões de nome PROVISÓRIOS — ajustar via JSON.
    "eta": FonteDados(
        nome="eta",
        subdir="ETA/netcdf/{modelo}",
        padrao_prec="ETA.PREV.PREC.{modelo}.{valida}.nc",
        padrao_temp_ur="ETA.PREV.TEMP2m.RH2m.{modelo}.{valida}.nc",
        var_prec="prec", var_temp="TEMP2m", var_ur="RH2m",
        freq_prec="1d", tipo_acumulo="intervalo",
        unidade_temp="K", unidade_ur="%",
        horizonte_max_dias=396,          # ~13 meses
    ),
    # BESM T062: até 13 meses. Convenção REAL (besm_queimada do CPTEC):
    # um arquivo por variável com todos os tempos diários da rodada,
    # grade gaussiana ~1.875°, latitude de norte para sul (invertida na
    # leitura), prec em mm/dia (acumulado do dia), t2mt em K (média
    # diária) e rsmt em % (0-100).
    "besm": FonteDados(
        nome="besm",
        subdir="BESM/netcdf/{modelo}",
        layout="serie",
        padrao_prec="tmp_prec.nc",
        padrao_temp="tmp_t2mt.nc",
        padrao_ur="tmp_rsmt.nc",
        var_prec="prec", var_temp="t2mt", var_ur="rsmt",
        freq_prec="1d", tipo_acumulo="intervalo",
        unidade_temp="K", unidade_ur="%",
        horizonte_max_dias=396,          # 13 meses
    ),
}


def carrega_fontes_dict(config):
    """Sobrepõe/acrescenta fontes a partir de um dicionário.

    Formato: {"eta": {"subdir": "...", "padrao_prec": "...", ...}, ...}
    Somente os campos presentes são alterados.
    """
    for nome, campos in config.items():
        nome = nome.lower()
        if nome in FONTES:
            FONTES[nome] = dataclasses.replace(FONTES[nome], **campos)
        else:
            FONTES[nome] = FonteDados(nome=nome, **campos)
    return FONTES


def carrega_fontes_json(caminho):
    """Sobrepõe/acrescenta fontes a partir de um arquivo JSON ou YAML."""
    if caminho.lower().endswith((".yaml", ".yml")):
        import yaml
        with open(caminho) as f:
            config = yaml.safe_load(f) or {}
    else:
        with open(caminho) as f:
            config = json.load(f)
    return carrega_fontes_dict(config)


# ---------------------------------------------------------------------------
# Leitura de um campo de precipitação (qualquer fonte)
# ---------------------------------------------------------------------------

def _le_campo(caminho, nome_var):
    with xr.open_dataset(caminho, decode_times=False) as ds:
        dados = np.asarray(ds[nome_var].values, dtype=np.float32)
        if dados.ndim == 3:
            dados = dados[0]
        lat = np.asarray(ds["lat"].values, dtype=np.float64)
        lon = np.asarray(ds["lon"].values, dtype=np.float64)
    if lat.size > 1 and lat[0] > lat[-1]:      # norte->sul: inverte p/ sul->norte
        lat = lat[::-1]
        dados = dados[::-1, :]
    return dados, lat, lon


# Cache dos arquivos-série (um por variável, todos os tempos): evita
# reabrir o mesmo NetCDF a cada dia da janela de 120 dias.
_CACHE_SERIE = {}


def _le_serie(caminho, nome_var):
    """Lê (com cache) um arquivo-série: retorna (dados[nt,nlat,nlon], lat,
    lon, tempos[nt] em datetime64), com a latitude orientada de sul para
    norte."""
    chave = (os.path.abspath(caminho), nome_var)
    if chave not in _CACHE_SERIE:
        with xr.open_dataset(caminho) as ds:
            dados = np.asarray(ds[nome_var].values, dtype=np.float32)
            lat = np.asarray(ds["lat"].values, dtype=np.float64)
            lon = np.asarray(ds["lon"].values, dtype=np.float64)
            tempos = np.asarray(ds["time"].values)
        if dados.ndim == 2:
            dados = dados[np.newaxis, :, :]
        if lat.size > 1 and lat[0] > lat[-1]:  # norte->sul: inverte
            lat = lat[::-1]
            dados = dados[:, ::-1, :]
        _CACHE_SERIE[chave] = (dados, lat, lon, tempos)
    return _CACHE_SERIE[chave]


def _indices_do_dia(tempos, dia):
    """Índices dos tempos cujo dia-calendário é ``dia`` (datetime, 00 UTC)."""
    dias = tempos.astype("datetime64[D]")
    alvo = np.datetime64(dia.strftime("%Y-%m-%d"))
    return np.nonzero(dias == alvo)[0]


def _regrade_se_preciso(dados, lat, lon, lat_ref, lon_ref):
    """Interpola para a grade de referência (IMERG) quando as grades diferem."""
    if (lat.size == lat_ref.size and lon.size == lon_ref.size
            and np.allclose(lat, lat_ref) and np.allclose(lon, lon_ref)):
        return dados
    return rf_core.interp_bilinear(dados, lat, lon, lat_ref, lon_ref)


# ---------------------------------------------------------------------------
# Precipitação diária prevista de uma fonte (agregação por frequência)
# ---------------------------------------------------------------------------

def precip_diaria_prevista(fonte, dirin, modelo, dia, lat_ref, lon_ref):
    """Acumulado diário previsto (mm/dia) do dia ``dia`` (datetime, 00 UTC),
    na grade de referência.

    - freq "1d": lê 1 arquivo (válido no fim do dia);
    - freq "12h": soma 2 intervalos;
    - freq "1h": soma 24 intervalos;
    - tipo "desde_inicio": diferença entre o acumulado no fim e no início
      do dia (no primeiro passo da rodada, o acumulado inicial é zero).
    """
    passo_h = fonte.horas_por_passo()
    inicio_rodada = dt.datetime.strptime(modelo, "%Y%m%d%H")

    # ------------------------------------------------ layout "serie"
    # (um arquivo por variável, todos os tempos — ex.: BESM T062)
    if fonte.layout == "serie":
        arq = fonte.arquivo_prec(dirin, modelo)
        dados, lat, lon, tempos = _le_serie(arq, fonte.var_prec)
        idx = _indices_do_dia(tempos, dia)
        if idx.size == 0:
            raise RuntimeError(
                f"Sem tempos para o dia {dia:%Y-%m-%d} em {arq} "
                f"(série cobre {tempos[0]} a {tempos[-1]}).")
        if fonte.tipo_acumulo == "desde_inicio":
            fim = dados[idx[-1]]
            idx_ant = _indices_do_dia(tempos, dia - dt.timedelta(days=1))
            ini = dados[idx_ant[-1]] if idx_ant.size else np.zeros_like(fim)
            diario = fim - ini
        else:
            # "intervalo": soma os acúmulos dos tempos do dia
            # (1 tempo se diário; 2 se 12 h; 24 se horário).
            diario = dados[idx].sum(axis=0)
        return _regrade_se_preciso(diario, lat, lon, lat_ref, lon_ref)

    # ------------------------------------------------ layout "por_tempo"
    if fonte.tipo_acumulo == "desde_inicio":
        fim = dia + dt.timedelta(hours=24)
        arq_fim = fonte.arquivo_prec(dirin, modelo, fim.strftime("%Y%m%d%H"))
        campo_fim, lat, lon = _le_campo(arq_fim, fonte.var_prec)
        if dia <= inicio_rodada:
            campo_ini = np.zeros_like(campo_fim)
        else:
            arq_ini = fonte.arquivo_prec(dirin, modelo,
                                         dia.strftime("%Y%m%d%H"))
            campo_ini, _, _ = _le_campo(arq_ini, fonte.var_prec)
        diario = campo_fim - campo_ini
        return _regrade_se_preciso(diario, lat, lon, lat_ref, lon_ref)

    # tipo "intervalo": soma os acúmulos dos passos que compõem o dia.
    diario = None
    lat = lon = None
    t = dia + dt.timedelta(hours=passo_h)      # fim do primeiro intervalo
    fim_dia = dia + dt.timedelta(hours=24)
    while t <= fim_dia:
        arq = fonte.arquivo_prec(dirin, modelo, t.strftime("%Y%m%d%H"))
        campo, lat, lon = _le_campo(arq, fonte.var_prec)
        diario = campo if diario is None else diario + campo
        t += dt.timedelta(hours=passo_h)
    return _regrade_se_preciso(diario, lat, lon, lat_ref, lon_ref)


# ---------------------------------------------------------------------------
# Temperatura e umidade relativa da fonte no horário previsto
# ---------------------------------------------------------------------------

def temp_ur_previstos(fonte, dirin, modelo, data_previsao):
    """Lê T2m (convertida para °C) e UR2m (convertida para décimos) da fonte
    no horário previsto, com as respectivas coordenadas."""

    if fonte.layout == "serie":
        # Arquivos separados, todos os tempos: seleciona o tempo mais
        # próximo da data prevista (ex.: média diária do BESM).
        valida = np.datetime64(
            dt.datetime.strptime(data_previsao, "%Y%m%d%H"))

        def seleciona(caminho, nome_var):
            dados, lat, lon, tempos = _le_serie(caminho, nome_var)
            dif = np.abs(tempos.astype("datetime64[s]").astype("int64")
                         - valida.astype("datetime64[s]").astype("int64"))
            i = int(dif.argmin())
            if dif[i] > 24 * 3600:
                raise RuntimeError(
                    f"Nenhum tempo próximo de {data_previsao} em {caminho} "
                    f"(mais próximo: {tempos[i]}).")
            return dados[i], lat, lon

        t2m, lat, lon = seleciona(fonte.arquivo_temp(dirin, modelo),
                                  fonte.var_temp)
        ur2m, _, _ = seleciona(fonte.arquivo_ur(dirin, modelo), fonte.var_ur)
    else:
        arq = fonte.arquivo_temp_ur(dirin, modelo, data_previsao)
        with xr.open_dataset(arq, decode_times=False) as f:
            t2m = np.asarray(f[fonte.var_temp].values, dtype=np.float32)
            ur2m = np.asarray(f[fonte.var_ur].values, dtype=np.float32)
            if t2m.ndim == 3:
                t2m = t2m[0]
            if ur2m.ndim == 3:
                ur2m = ur2m[0]
            lat = np.asarray(f["lat"].values, dtype=np.float64)
            lon = np.asarray(f["lon"].values, dtype=np.float64)
        if lat.size > 1 and lat[0] > lat[-1]:
            lat = lat[::-1]
            t2m = t2m[::-1, :]
            ur2m = ur2m[::-1, :]

    if fonte.unidade_temp.upper() == "K":
        t2m = t2m - 273.15
    if fonte.unidade_ur == "%":
        ur2m = ur2m / 100.0
    return t2m, ur2m, lat, lon


# ---------------------------------------------------------------------------
# Série diária de 120 tempos: IMERG observado + previsão da fonte
# ---------------------------------------------------------------------------

def _caminho_imerg_padrao(dirin_imerg, dia):
    """Convenção padrão dos arquivos IMERG (pode ser trocada via o
    parâmetro ``caminho_imerg_fn`` de serie_precipitacao — ver rf_config)."""
    ymd = dia.strftime("%Y%m%d")
    return os.path.join(
        dirin_imerg, ymd[:4], ymd[4:6],
        f"INPE_FireRiskModel_2.2_Precipitation_{ymd}.nc")


def serie_precipitacao(fonte, dirin_fonte, dirin_imerg, modelo,
                       data_previsao, n_dias=120, log=print,
                       caminho_imerg_fn=None):
    """Monta a série de ``n_dias`` acumulados diários de precipitação que
    antecedem (e incluem) a data prevista, em ordem cronológica crescente.

    Para cada dia D da janela [data_valida - n_dias + 1, data_valida]:
      - se D for anterior à data da rodada -> IMERG observado;
      - caso contrário -> precipitação prevista da fonte (agregada
        para o passo diário e regradeada para a grade do IMERG).

    Retorna (precip[n_dias, nlat, nlon], lat, lon), pronto para o
    rf_core.calcula_risco_fogo_dados (que espera ordem crescente e faz
    a inversão internamente).
    """
    if caminho_imerg_fn is None:
        def caminho_imerg_fn(dia):
            return _caminho_imerg_padrao(dirin_imerg, dia)

    inicio_rodada = dt.datetime.strptime(modelo, "%Y%m%d%H")
    data_rodada = inicio_rodada.replace(hour=0)
    valida = dt.datetime.strptime(data_previsao, "%Y%m%d%H").replace(hour=0)

    # Grade de referência: a do IMERG (primeiro arquivo disponível).
    lat_ref = lon_ref = None
    campos = []
    faltantes = []

    dia = valida - dt.timedelta(days=n_dias - 1)
    while dia <= valida:
        if dia < data_rodada:
            # Observado: IMERG.
            arq = caminho_imerg_fn(dia)
            if not os.path.exists(arq):
                faltantes.append(arq)
                dia += dt.timedelta(days=1)
                continue
            campo, lat, lon = _le_campo(arq, "prec")
            if lat_ref is None:
                lat_ref, lon_ref = lat, lon
            campos.append(_regrade_se_preciso(campo, lat, lon,
                                              lat_ref, lon_ref))
        else:
            # Previsto: fonte (Eta, BESM, GFS...).
            if lat_ref is None:
                # Sem nenhum IMERG anterior (horizonte >= 120 dias):
                # usa a grade da própria fonte como referência.
                if fonte.layout == "serie":
                    _, lat_ref, lon_ref, _ = _le_serie(
                        fonte.arquivo_prec(dirin_fonte, modelo),
                        fonte.var_prec)
                else:
                    fim = dia + dt.timedelta(hours=fonte.horas_por_passo())
                    arq0 = fonte.arquivo_prec(dirin_fonte, modelo,
                                              fim.strftime("%Y%m%d%H"))
                    _, lat_ref, lon_ref = _le_campo(arq0, fonte.var_prec)
            try:
                campos.append(precip_diaria_prevista(
                    fonte, dirin_fonte, modelo, dia, lat_ref, lon_ref))
            except (RuntimeError, FileNotFoundError):
                # Dia não coberto pela previsão — caso típico: o próprio
                # dia da rodada quando a série da fonte começa em
                # rodada+1 (ex.: BESM T062). Tenta o IMERG observado;
                # se não houver, aproxima pelo dia coberto mais próximo
                # da série (persistência de 24-48 h).
                arq_imerg = caminho_imerg_fn(dia)
                if os.path.exists(arq_imerg):
                    campo, lat, lon = _le_campo(arq_imerg, "prec")
                    campos.append(_regrade_se_preciso(campo, lat, lon,
                                                      lat_ref, lon_ref))
                    log(f"Aviso: dia {dia:%Y-%m-%d} sem previsão na fonte; "
                        f"usado o IMERG observado.")
                elif fonte.layout == "serie":
                    dados, lat, lon, tempos = _le_serie(
                        fonte.arquivo_prec(dirin_fonte, modelo),
                        fonte.var_prec)
                    dias_serie = tempos.astype("datetime64[D]")
                    alvo = np.datetime64(dia.strftime("%Y-%m-%d"))
                    difs = np.abs((dias_serie - alvo).astype("int64"))
                    i = int(difs.argmin())
                    if difs[i] > 2:
                        raise
                    idx = np.nonzero(dias_serie == dias_serie[i])[0]
                    aprox = dados[idx].sum(axis=0)
                    campos.append(_regrade_se_preciso(aprox, lat, lon,
                                                      lat_ref, lon_ref))
                    log(f"Aviso: dia {dia:%Y-%m-%d} sem previsão na fonte "
                        f"nem IMERG; aproximado pelo dia {dias_serie[i]} "
                        f"da série.")
                else:
                    raise
        dia += dt.timedelta(days=1)

    if faltantes:
        log(f"Aviso: {len(faltantes)} arquivo(s) IMERG faltando na janela.")

    if len(campos) < n_dias:
        raise RuntimeError(
            f"Série diária incompleta: {len(campos)} de {n_dias} dias "
            f"(IMERG faltantes: {len(faltantes)}).")

    precip = np.stack(campos, axis=0)
    return precip, lat_ref, lon_ref, faltantes
