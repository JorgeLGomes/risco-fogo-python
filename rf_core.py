# -*- coding: utf-8 -*-
"""
rf_core.py
==========

Núcleo do cálculo do Risco de Fogo (RF) previsto do INPE_FireRiskModel (v2.2),
convertido do NCL para Python puro (numpy + xarray + netCDF4 + rasterio).

Substituições das funções NCL:
  - addfile / addfiles + ListSetType("cat")  -> xarray.open_dataset / concatenação numpy
  - linint2_Wrap                             -> interpolação bilinear vetorizada em numpy
  - conform_dims                             -> broadcasting do numpy
  - decimalPlaces                            -> numpy.round
  - where                                    -> numpy.where / numpy.minimum
  - escrita NetCDF (addfile "c")             -> xarray.Dataset.to_netcdf
  - cdo -setmissval,-999 -settaxis           -> feito diretamente na escrita do NetCDF
  - gdal_translate (NetCDF -> GeoTIFF)       -> rasterio

Dados de entrada (diário) necessários para o cálculo do risco de fogo (RF):
  1 - Precipitação (mm/dia);
  2 - Temperatura do Ar (°C);
  3 - Umidade Relativa do Ar (décimos).

Autores do modelo:
  Alberto Setzer  - alberto.setzer@inpe.br
  Guilherme Martins - guilherme.martins@inpe.br (código NCL original)
Link: http://www.inpe.br/queimadas/
"""

import datetime as dt
import os
import sys

import numpy as np
import xarray as xr

# ---------------------------------------------------------------------------
# Constantes do modelo
# ---------------------------------------------------------------------------

# Constantes da função exponencial utilizadas para calcular o fator de
# precipitação (fp): fp1, fp2, fp3, fp4, fp5, fp6a10, fp11a15, fp16a30,
# fp31a60, fp61a90 e fp91a120.
CTE = np.array([-0.14, -0.07, -0.04, -0.03, -0.02, -0.01,
                -0.008, -0.004, -0.002, -0.001, -0.0007], dtype=np.float64)

# Valores da constante "A" para cada classe de vegetação (índice = classe).
# A classe 0 (superfícies líquidas) é tratada como valor ausente (NaN).
A_VEG = np.array([np.nan, 6, 4, 3, 2.4, 2, 1.72, 1.5], dtype=np.float64)

# Valores de PSE máximo para cada classe de vegetação (índice = classe).
PSE_MAX_VEG = np.array([np.nan, 30, 45, 60, 75, 90, 105, 120], dtype=np.float64)

# Valor ausente (missing value / NODATA) usado nos arquivos de saída
# (equivalente ao "cdo -setmissval,-999").
FILL_VALUE = -999.0

# Número de dias/tempos de precipitação esperados (119 IMERG + 1 GFS).
ND_ESPERADO = 120

# Escala da umidade relativa no Fator de Umidade FU = -0.008*UR + 1.3.
#
# O NCL original converte a UR de % para FRAÇÃO (ur2m = ur2m/100.) antes
# de aplicar essa equação; com UR entre 0 e 1, o FU fica praticamente
# constante (1,292–1,300) e a umidade quase não modula o RF. Os
# coeficientes (-0,008 e 1,3), porém, foram claramente pensados para a UR
# em PORCENTAGEM (FU = 1,14 a 20 % e 0,58 a 90 %).
#
# O padrão do pacote é "ncl" — reproduzir a operação exatamente. As outras
# opções existem para quantificar o efeito dessa escolha (e para uma
# eventual correção, depois de validada com o autor do modelo).
FATOR_UR = {
    "ncl": 1.0,          # UR em fração 0–1 (idêntico ao NCL/operação)
    "decimos": 10.0,     # UR em décimos 0–10
    "percentual": 100.0,  # UR em % 0–100 (o que a equação parece supor)
}


# ---------------------------------------------------------------------------
# Interpolação bilinear (substitui a função linint2_Wrap do NCL)
# ---------------------------------------------------------------------------

def interp_bilinear(dados, lat_orig, lon_orig, lat_novo, lon_novo):
    """Interpolação bilinear de uma grade retilínea para outra.

    Equivalente à função ``linint2_Wrap`` do NCL para grades regionais.

    Parameters
    ----------
    dados : ndarray 2D (nlat, nlon)
    lat_orig, lon_orig : coordenadas 1D crescentes da grade original
    lat_novo, lon_novo : coordenadas 1D crescentes da grade de destino

    Returns
    -------
    ndarray 2D (nlat_novo, nlon_novo), float32
    """
    lat_orig = np.asarray(lat_orig, dtype=np.float64)
    lon_orig = np.asarray(lon_orig, dtype=np.float64)
    lat_novo = np.asarray(lat_novo, dtype=np.float64)
    lon_novo = np.asarray(lon_novo, dtype=np.float64)

    # Índices das células envolventes (com "clamp" nas bordas do domínio).
    ix1 = np.clip(np.searchsorted(lon_orig, lon_novo), 1, lon_orig.size - 1)
    ix0 = ix1 - 1
    iy1 = np.clip(np.searchsorted(lat_orig, lat_novo), 1, lat_orig.size - 1)
    iy0 = iy1 - 1

    # Pesos da interpolação (limitados a [0,1] para pontos na borda).
    wx = (lon_novo - lon_orig[ix0]) / (lon_orig[ix1] - lon_orig[ix0])
    wy = (lat_novo - lat_orig[iy0]) / (lat_orig[iy1] - lat_orig[iy0])
    wx = np.clip(wx, 0.0, 1.0)
    wy = np.clip(wy, 0.0, 1.0)

    d = np.asarray(dados, dtype=np.float64)

    # Combinação bilinear dos 4 vizinhos.
    d00 = d[np.ix_(iy0, ix0)]
    d01 = d[np.ix_(iy0, ix1)]
    d10 = d[np.ix_(iy1, ix0)]
    d11 = d[np.ix_(iy1, ix1)]

    wxg = wx[np.newaxis, :]
    wyg = wy[:, np.newaxis]

    out = ((1.0 - wyg) * ((1.0 - wxg) * d00 + wxg * d01)
           + wyg * ((1.0 - wxg) * d10 + wxg * d11))

    return out.astype(np.float32)


# ---------------------------------------------------------------------------
# Leitura dos dados de entrada
# ---------------------------------------------------------------------------

# Nomes usuais da variável de precipitação, na ordem de preferência da
# detecção automática (o MSWEP às vezes traz a variável sem long_name, e
# o nome muda entre versões: precipitation, precip, pr...).
NOMES_PRECIP = ("prec", "precipitation", "precipitationCal", "precip",
                "precipitationUncal", "pr", "tp", "rr")

# Nomes usuais dos eixos horizontais.
NOMES_LAT = ("lat", "latitude", "y")
NOMES_LON = ("lon", "longitude", "x")


def _nome_eixo(ds, candidatos):
    for nome in candidatos:
        if nome in ds.variables or nome in ds.coords or nome in ds.dims:
            return nome
    raise KeyError(f"Nenhum eixo {candidatos[0]} encontrado no arquivo "
                   f"(variáveis: {list(ds.variables)}).")


def nome_variavel_precip(ds, preferido=None):
    """Descobre o nome da variável de precipitação em um NetCDF aberto.

    Com ``preferido`` informado (e presente no arquivo), devolve-o direto.
    Senão tenta os nomes usuais e, por último, a única variável de dados
    com pelo menos duas dimensões — o caso do MSWEP, cujo nome muda entre
    versões e cujo ``cdo sinfo`` mostra "unknown"."""
    if preferido and str(preferido).lower() not in ("auto", "") \
            and preferido in ds.variables:
        return preferido
    for nome in NOMES_PRECIP:
        if nome in ds.data_vars:
            return nome
    eixos = set(NOMES_LAT) | set(NOMES_LON) | {"time", "valid_time", "bnds"}
    candidatas = [n for n, v in ds.data_vars.items()
                  if v.ndim >= 2 and n not in eixos
                  and not n.endswith("_bnds")]
    if len(candidatas) == 1:
        return candidatas[0]
    if candidatas:
        raise KeyError(
            f"Mais de uma variável candidata a precipitação "
            f"({sorted(candidatas)}); informe o nome em "
            f"'precipitacao: variavel:' no config.yaml.")
    raise KeyError(f"Nenhuma variável de precipitação encontrada "
                   f"(variáveis: {list(ds.data_vars)}).")


def _indices_recorte(la, lo, recorte):
    """Índices (fatia em lat, vetor em lon) do recorte espacial pedido.

    ``recorte`` = (lat_sul, lat_norte, lon_oeste, lon_leste) em graus, com
    longitude em -180..180. Trata arquivos com longitude 0..360 (MSWEP e
    outros globais) reordenando o eixo. Devolve (idx_lat, idx_lon) ou
    (None, None) quando não há recorte a fazer."""
    if recorte is None:
        return None, None
    lat_s, lat_n, lon_w, lon_e = (float(x) for x in recorte)

    crescente = la.size < 2 or la[0] <= la[-1]
    mla = (la >= lat_s) & (la <= lat_n)
    ila = np.nonzero(mla)[0]

    lo180 = ((np.asarray(lo, dtype=np.float64) + 180.0) % 360.0) - 180.0
    mlo = (lo180 >= lon_w) & (lo180 <= lon_e)
    ilo = np.nonzero(mlo)[0]
    if ilo.size:
        ilo = ilo[np.argsort(lo180[ilo])]     # garante longitude crescente

    if ila.size == 0 or ilo.size == 0:
        raise ValueError(
            f"Recorte {recorte} fora da grade do arquivo "
            f"(lat {la.min():.2f}..{la.max():.2f}, "
            f"lon {lo180.min():.2f}..{lo180.max():.2f}).")

    fatia_lat = slice(int(ila[0]), int(ila[-1]) + 1)
    del crescente
    return fatia_lat, ilo


def le_precip_arquivo(caminho, nome_var=None, recorte=None):
    """Lê um arquivo de precipitação diária no padrão do pipeline OU num
    arquivo global bruto (MSWEP), devolvendo (dados[nt,nlat,nlon], lat,
    lon) com a latitude de sul para norte, longitude crescente em
    -180..180 e recorte espacial opcional.

    O recorte é aplicado **antes** de carregar os dados (isel preguiçoso),
    de modo que ler o domínio da América do Sul de um arquivo global
    3600x1800 não traz a grade inteira para a memória."""
    with xr.open_dataset(caminho, decode_times=False) as ds:
        nome = nome_variavel_precip(ds, nome_var)
        nome_lat = _nome_eixo(ds, NOMES_LAT)
        nome_lon = _nome_eixo(ds, NOMES_LON)
        la = np.asarray(ds[nome_lat].values, dtype=np.float64)
        lo = np.asarray(ds[nome_lon].values, dtype=np.float64)

        var = ds[nome]
        if var.dims[-2:] == (nome_lon, nome_lat):     # (time, lon, lat)
            var = var.transpose(..., nome_lat, nome_lon)

        fatia_lat, idx_lon = _indices_recorte(la, lo, recorte)
        if fatia_lat is not None:
            var = var.isel({nome_lat: fatia_lat, nome_lon: idx_lon})
            la = la[fatia_lat]
            lo = ((lo[idx_lon] + 180.0) % 360.0) - 180.0
        else:
            lo = np.asarray(lo, dtype=np.float64)

        dados = np.asarray(var.values, dtype=np.float32)

    if dados.ndim == 2:                  # arquivo sem dimensão tempo
        dados = dados[np.newaxis, :, :]
    elif dados.ndim > 3:                 # dimensões extras de tamanho 1
        dados = dados.reshape((-1,) + dados.shape[-2:])

    if la.size > 1 and la[0] > la[-1]:   # norte->sul: inverte
        la = la[::-1]
        dados = dados[:, ::-1, :]

    return dados, la, lo


def le_grade_precip(caminho, recorte=None):
    """Latitudes e longitudes (já recortadas e ordenadas) de um arquivo de
    precipitação, sem ler o campo — usado para descobrir o domínio do
    banco (ex.: as faixas de longitude do modo de hora solar)."""
    with xr.open_dataset(caminho, decode_times=False) as ds:
        la = np.asarray(ds[_nome_eixo(ds, NOMES_LAT)].values,
                        dtype=np.float64)
        lo = np.asarray(ds[_nome_eixo(ds, NOMES_LON)].values,
                        dtype=np.float64)
    fatia_lat, idx_lon = _indices_recorte(la, lo, recorte)
    if fatia_lat is not None:
        la = la[fatia_lat]
        lo = ((lo[idx_lon] + 180.0) % 360.0) - 180.0
    if la.size > 1 and la[0] > la[-1]:
        la = la[::-1]
    return la, lo


def ler_precipitacao(lista_arquivos, nome_var="prec", recorte=None):
    """Lê e concatena os arquivos de precipitação na ordem da lista e
    INVERTE a dimensão tempo (equivalente ao ``(::-1,:,:)`` do NCL).

    Após a inversão, o índice 0 corresponde ao tempo mais recente
    (arquivo do GFS) e o último índice ao dia mais antigo.

    Arquivos em GRADE DIFERENTE da do primeiro (ex.: GFS nativo de 0,25°
    junto com IMERG de 0,1°) são regradeados por interpolação bilinear
    para a grade de referência — na operação original essa interpolação
    era feita numa etapa anterior do fluxo.

    ``nome_var=None`` detecta a variável automaticamente (MSWEP lido no
    lugar); ``recorte=(latS,latN,lonW,lonE)`` recorta o domínio na
    leitura, o que permite usar arquivos globais sem conversão prévia.
    """
    campos = []
    lat = lon = None
    for arq in lista_arquivos:
        dados, la, lo = le_precip_arquivo(arq, nome_var, recorte)

        if lat is None:
            lat, lon = la, lo                 # grade de referência (1º arquivo)
        elif (la.size != lat.size or lo.size != lon.size
              or not (np.allclose(la, lat) and np.allclose(lo, lon))):
            dados = np.stack([interp_bilinear(dados[t], la, lo, lat, lon)
                              for t in range(dados.shape[0])])
        campos.append(dados)

    precip = np.concatenate(campos, axis=0)   # concatenação ("cat" do NCL)
    precip = precip[::-1, :, :]               # inversão da dimensão tempo
    return precip, lat, lon


def ler_temp_ur(arquivo_temp_ur):
    """Lê o arquivo de previsão do GFS com temperatura (K) e umidade
    relativa (%) a 2 m, já convertendo para °C e décimos."""
    with xr.open_dataset(arquivo_temp_ur, decode_times=False) as f:
        t2m = np.asarray(f["TEMP2m"].values, dtype=np.float32)
        ur2m = np.asarray(f["RH2m"].values, dtype=np.float32)
        if t2m.ndim == 3:
            t2m = t2m[0, :, :]
        if ur2m.ndim == 3:
            ur2m = ur2m[0, :, :]
        lat = np.asarray(f["lat"].values, dtype=np.float64)
        lon = np.asarray(f["lon"].values, dtype=np.float64)

    t2m = t2m - 273.15    # Kelvin -> Celsius
    ur2m = ur2m / 100.0   # % -> décimos
    return t2m, ur2m, lat, lon


def ler_mapa_vegetacao(arquivo_mapa_veg):
    """Lê o mapa de vegetação (variável Band1). O arquivo deve estar
    orientado de sul para norte. A classe 0 (superfícies líquidas) é
    tratada como valor ausente no cálculo."""
    with xr.open_dataset(arquivo_mapa_veg, decode_times=False) as h:
        mapa_veg = np.asarray(h["Band1"].values)
        lat = np.asarray(h["lat"].values, dtype=np.float64)
        lon = np.asarray(h["lon"].values, dtype=np.float64)
    # Conversão para inteiro (equivalente ao floattoint do NCL).
    mapa_veg = np.nan_to_num(mapa_veg, nan=0.0).astype(np.int32)
    return mapa_veg, lat, lon


def ler_topografia(arquivo_topografia):
    """Lê o arquivo de topografia (Band1, em metros), já interpolado para a
    mesma resolução do mapa de vegetação."""
    with xr.open_dataset(arquivo_topografia, decode_times=False) as m:
        elev = np.asarray(m["Band1"].values, dtype=np.float32)
    return elev


def ler_topografia_grade(arquivo_topografia):
    """Como ``ler_topografia``, mas devolve também as coordenadas
    (elev, lat, lon) — necessário quando a grade de saída não é a do mapa
    de vegetação (ex.: ``--sem-vegetacao``) e a topografia precisa ser
    regradeada."""
    with xr.open_dataset(arquivo_topografia, decode_times=False) as m:
        elev = np.asarray(m["Band1"].values, dtype=np.float32)
        lat = np.asarray(m["lat"].values, dtype=np.float64)
        lon = np.asarray(m["lon"].values, dtype=np.float64)
    return elev, lat, lon


# ---------------------------------------------------------------------------
# Cálculo do Risco de Fogo
# ---------------------------------------------------------------------------

def calcula_risco_fogo(arquivo_temp_ur,
                       lista_arquivos_prec,
                       arquivo_mapa_veg,
                       arquivo_topografia,
                       arquivo_saida,
                       data_previsao,
                       rb_maximo=0.9,
                       nome_var_precip="prec",
                       recorte_precip=None,
                       titulo=None,
                       log=print,
                       usar_vegetacao=True,
                       usar_topografia=True,
                       classe_veg_uniforme=4,
                       correcao_ur="ncl"):
    """Calcula o Risco de Fogo previsto em 1 km e grava o NetCDF de saída.

    Parameters
    ----------
    arquivo_temp_ur : str
        Arquivo GFS com TEMP2m (K) e RH2m (%).
    lista_arquivos_prec : list[str]
        Lista com os 120 arquivos de precipitação (119 IMERG + 1 GFS),
        em ordem cronológica crescente (o GFS por último).
    arquivo_mapa_veg : str
        Mapa de vegetação em 1 km (Band1).
    arquivo_topografia : str
        Topografia em 1 km (Band1, metros), mesma grade do mapa de vegetação.
    arquivo_saida : str
        Caminho do NetCDF de saída (RF.PREV.YYYYMMDDHH.nc).
    data_previsao : str
        Data/hora da previsão no formato YYYYMMDDHH (usada no eixo de tempo).
    rb_maximo : float
        Valor máximo do risco básico: 0.9 (script 1-5 dias) ou
        0.8 (script 1-2 semanas).
    """

    log("")
    log("Abrindo o arquivo de temperatura e umidade relativa.")
    log("")
    t2m, ur2m, lat_gfs, lon_gfs = ler_temp_ur(arquivo_temp_ur)

    log("")
    log("Abrindo os arquivos de precipitação.")
    log("")
    precip, lat_prec, lon_prec = ler_precipitacao(lista_arquivos_prec,
                                                  nome_var_precip,
                                                  recorte_precip)

    return calcula_risco_fogo_dados(
        precip_invertida=precip,
        lat_prec=lat_prec, lon_prec=lon_prec,
        t2m=t2m, ur2m=ur2m,
        lat_met=lat_gfs, lon_met=lon_gfs,
        arquivo_mapa_veg=arquivo_mapa_veg,
        arquivo_topografia=arquivo_topografia,
        arquivo_saida=arquivo_saida,
        data_previsao=data_previsao,
        rb_maximo=rb_maximo,
        titulo=titulo,
        log=log,
        usar_vegetacao=usar_vegetacao,
        usar_topografia=usar_topografia,
        classe_veg_uniforme=classe_veg_uniforme,
        correcao_ur=correcao_ur,
    )


def calcula_risco_fogo_dados(precip_invertida, lat_prec, lon_prec,
                             t2m, ur2m, lat_met, lon_met,
                             arquivo_mapa_veg, arquivo_topografia,
                             arquivo_saida, data_previsao,
                             rb_maximo=0.9, titulo=None, log=print,
                             usar_vegetacao=True, usar_topografia=True,
                             classe_veg_uniforme=4, correcao_ur="ncl"):
    """Calcula o RF a partir de arrays já carregados (qualquer fonte).

    Parameters
    ----------
    precip_invertida : ndarray (nd, nlat, nlon)
        Acumulados diários de precipitação com o TEMPO INVERTIDO
        (índice 0 = dia previsto/mais recente; último = dia mais antigo),
        como no NCL original. Use ``precip[::-1]`` se a série estiver em
        ordem cronológica crescente.
    t2m, ur2m : ndarray (nlat_met, nlon_met)
        Temperatura a 2 m em °C e umidade relativa em décimos.
    lat_met, lon_met : coordenadas 1D da grade de t2m/ur2m.
    usar_vegetacao : bool
        False = desliga o efeito da vegetação e DISPENSA o arquivo do mapa
        (não é lido): todos os pontos recebem a MESMA classe
        (``classe_veg_uniforme``) e a grade de saída passa a ser a grade da
        precipitação (sem interpolação para 1 km e sem máscara d'água).
    usar_topografia : bool
        False = desliga o Fator Topográfico (FTOP = 1 em toda parte); o
        arquivo de topografia nem é lido. Se ligado e a grade da topografia
        for diferente da grade de saída (caso ``--sem-vegetacao``), o campo
        é regradeado automaticamente.
    classe_veg_uniforme : int
        Classe usada quando ``usar_vegetacao=False`` (padrão 4:
        A = 2.4, PSE_max = 75 — valores intermediários).
    Demais parâmetros como em ``calcula_risco_fogo``.
    """

    precip = np.asarray(precip_invertida, dtype=np.float32)

    nd = precip.shape[0]
    if nd < ND_ESPERADO:
        raise RuntimeError(
            f"Número de tempos de precipitação insuficiente: {nd} "
            f"(esperado {ND_ESPERADO}). Verifique os arquivos faltantes.")

    lat_gfs, lon_gfs = lat_met, lon_met

    if usar_vegetacao:
        log("")
        log("Abrindo o arquivo de mapa de vegetação.")
        log("")
        mapa_veg, lat_veg, lon_veg = ler_mapa_vegetacao(arquivo_mapa_veg)
        nlat_veg, nlon_veg = mapa_veg.shape

        # Grade de destino de 1 km (equivalente ao fspan do NCL).
        lat_1km = np.linspace(lat_veg[0], lat_veg[-1], nlat_veg)
        lon_1km = np.linspace(lon_veg[0], lon_veg[-1], nlon_veg)
    else:
        # Vegetação desligada: o mapa NÃO é lido (o arquivo é dispensado).
        # A grade de saída passa a ser a grade da precipitação e todos os
        # pontos recebem a mesma classe — sem máscara d'água.
        log("")
        log(f"AVISO: fator de VEGETACAO desligado — arquivo do mapa NAO "
            f"lido; classe uniforme {classe_veg_uniforme} em todos os "
            f"pontos; grade de saida = grade da precipitacao (sem mascara "
            f"d'agua e sem interpolacao para 1 km).")
        lat_1km = np.asarray(lat_prec, dtype=np.float64)
        lon_1km = np.asarray(lon_prec, dtype=np.float64)
        mapa_veg = np.full((lat_1km.size, lon_1km.size),
                           classe_veg_uniforme, dtype=np.int32)

    log("")
    log("Calculando a precipitação acumulada")
    log("")
    # Precipitação acumulada olhando para trás no tempo
    # (equivalente ao laço "do while" do NCL): vprec(i) = vprec(i-1) + precip(i)
    vprec = np.cumsum(precip.astype(np.float64), axis=0)

    log("")
    log("Calculando o fator de precipitação (fp)")
    log("")
    nlat_prec = precip.shape[1]
    nlon_prec = precip.shape[2]
    fp = np.empty((11, nlat_prec, nlon_prec), dtype=np.float64)

    fp[0] = np.exp(CTE[0] * vprec[0])                       # fp1
    for j in range(1, 5):                                   # fp2 a fp5
        fp[j] = np.exp(CTE[j] * (vprec[j] - vprec[j - 1]))
    fp[5] = np.exp(CTE[5] * (vprec[9] - vprec[4]))          # fp6a10
    fp[6] = np.exp(CTE[6] * (vprec[14] - vprec[9]))         # fp11a15
    fp[7] = np.exp(CTE[7] * (vprec[29] - vprec[14]))        # fp16a30
    fp[8] = np.exp(CTE[8] * (vprec[59] - vprec[29]))        # fp31a60
    fp[9] = np.exp(CTE[9] * (vprec[89] - vprec[59]))        # fp61a90
    fp[10] = np.exp(CTE[10] * (vprec[119] - vprec[89]))     # fp91a120

    log("")
    log("Calculando o fator PSE")
    log("")
    # Dias de secura (PSE) = 105 * produto de todos os fp.
    pse = 105.0 * np.prod(fp, axis=0)

    # Interpolação do PSE de ~10 km para 1 km na grade do mapa de vegetação.
    pse_int_1km = interp_bilinear(pse, lat_prec, lon_prec, lat_1km, lon_1km)

    log("")
    log("Calculando o risco básico de fogo (rb)")
    log("")
    # Vetorização do duplo laço do NCL: os vetores A e PSE_max são indexados
    # pela classe de vegetação de cada ponto de grade. Classes fora do
    # intervalo válido e a classe 0 (água) resultam em NaN (valor ausente).
    veg = np.clip(mapa_veg, 0, len(A_VEG) - 1)
    veg = np.where((mapa_veg >= 0) & (mapa_veg < len(A_VEG)), veg, 0)

    a_pix = A_VEG[veg]
    pse_max_pix = PSE_MAX_VEG[veg]

    pse1 = pse_int_1km.astype(np.float64)

    # Se pse > pse_max -> rb = rb_maximo; caso contrário, usa a equação senoidal.
    cond = (~np.isnan(pse1)) & (~np.isnan(pse_max_pix)) & (pse1 > pse_max_pix)
    with np.errstate(invalid="ignore"):
        rb_eq = (rb_maximo * (1.0 + np.sin((a_pix * pse1 - 90.0)
                                           * (3.1416 / 180.0)))) / 2.0
    rb = np.where(cond, rb_maximo, rb_eq)

    log("")
    log("Calculando o fator FU")
    log("")
    # Fator de Umidade (FU). Alterado em 11/04/2019 de "-0.006" para "-0.008"
    # para incluir a sazonalidade do RF. A escala da UR é configurável
    # (ver FATOR_UR): "ncl" reproduz a operação (UR em fração).
    if correcao_ur not in FATOR_UR:
        raise ValueError(f"correcao_ur inválida: '{correcao_ur}'. "
                         f"Use uma de {sorted(FATOR_UR)}.")
    if correcao_ur != "ncl":
        log(f"AVISO: escala da UR no FU alterada para '{correcao_ur}' "
            f"(fator {FATOR_UR[correcao_ur]:.0f}x) — difere da operação.")
    FU = (-0.008 * ur2m * FATOR_UR[correcao_ur]) + 1.3
    FU_int_1km = interp_bilinear(FU, lat_gfs, lon_gfs, lat_1km, lon_1km)

    log("")
    log("Calculando o fator FT")
    log("")
    FT = (0.02 * t2m) + 0.4   # Fator de Temperatura (FT).
    FT_int_1km = interp_bilinear(FT, lat_gfs, lon_gfs, lat_1km, lon_1km)

    log("")
    log("Calculando o risco de fogo final (rbf)")
    log("")
    rbf = rb * FT_int_1km.astype(np.float64) * FU_int_1km.astype(np.float64)
    rbf = np.where(rbf > 1.0, 1.0, rbf)   # limita o RF ao valor máximo 1.

    log("")
    log("Calculando o fator de latitude")
    log("")
    # Correção do risco de fogo pela latitude (Fator Latitude - FL).
    # Equação desenvolvida pelo Setzer em 05/04/2019.
    FLAT = 1.0 + np.abs(lat_1km) * 0.003
    FLAT_C = FLAT[:, np.newaxis]          # 1D -> 2D (conform_dims do NCL)

    if usar_topografia:
        log("")
        log("Abrindo o arquivo de topografia")
        log("")
        elev, lat_topo, lon_topo = ler_topografia_grade(arquivo_topografia)
        if elev.shape != rbf.shape:
            if usar_vegetacao:
                raise RuntimeError(
                    f"A topografia {elev.shape} não tem a mesma grade do "
                    f"mapa de vegetação {rbf.shape}.")
            # Sem vegetação a grade de saída é a da precipitação:
            # regradeia a topografia automaticamente.
            log("")
            log(f"AVISO: topografia {elev.shape} regradeada para a grade "
                f"de saida {rbf.shape}.")
            elev = interp_bilinear(elev, lat_topo, lon_topo,
                                   lat_1km, lon_1km).astype(np.float32)

        log("")
        log("Calculando o fator de elevação")
        log("")
        # Correção do risco de fogo pela topografia (Fator Topográfico - FTOP).
        FTOP = 1.0 + elev.astype(np.float64) * 0.00003
    else:
        log("")
        log("AVISO: fator de TOPOGRAFIA desligado (FTOP = 1; arquivo não lido).")
        FTOP = 1.0

    rbfn = rbf * FLAT_C * FTOP
    rbfn = np.where(rbfn > 1.0, 1.0, rbfn)

    # Arredonda para 2 casas decimais (decimalPlaces do NCL).
    xT = np.round(rbfn, 2).astype(np.float32)

    log("")
    log(f"Gerando o arquivo NetCDF para o dia {data_previsao}")
    log("")
    extras = {}
    if not usar_vegetacao:
        extras["fator_vegetacao"] = (
            f"DESLIGADO (mapa nao lido; classe uniforme "
            f"{classe_veg_uniforme}; grade da precipitacao)")
    if not usar_topografia:
        extras["fator_topografia"] = "DESLIGADO (FTOP = 1)"
    if correcao_ur != "ncl":
        extras["escala_ur_no_FU"] = (f"{correcao_ur} (UR x "
                                     f"{FATOR_UR[correcao_ur]:.0f})")
    grava_netcdf_rf(xT, lat_1km, lon_1km, data_previsao, arquivo_saida,
                    titulo=titulo, atributos_extras=extras or None)

    return arquivo_saida


# ---------------------------------------------------------------------------
# Agregações de campos de RF (média/máximo de vários arquivos)
# ---------------------------------------------------------------------------

def le_campo_rf(caminho, nome_var=None):
    """Lê um campo 2D de um arquivo do pipeline (RF.OBS/RF.PREV/FWI.OBS):
    devolve (campo com NaN nos ausentes, lat, lon, nome da variável).

    ``nome_var`` escolhe a variável em arquivos com mais de uma (ex.: os
    componentes do FWI); por padrão usa a primeira."""
    with xr.open_dataset(caminho, decode_times=False) as ds:
        nome = nome_var if nome_var else next(iter(ds.data_vars))
        if nome not in ds.data_vars:
            raise KeyError(f"Variável '{nome}' não existe em "
                           f"{os.path.basename(caminho)} "
                           f"(disponíveis: {sorted(ds.data_vars)}).")
        v = ds[nome]
        dados = np.asarray(v.values, dtype=np.float32)
        if dados.ndim == 3:
            dados = dados[0]
        preenche = v.attrs.get("_FillValue", ds[nome].encoding.get(
            "_FillValue", -999.0))
        dados = np.where(dados <= (preenche + 1e-3), np.nan, dados)
        lat = np.asarray(ds["lat"].values, dtype=np.float64)
        lon = np.asarray(ds["lon"].values, dtype=np.float64)
    return dados, lat, lon, nome


def le_fatia_rf(caminho, nome_var=None, i0=None, i1=None):
    """Lê apenas as linhas [i0:i1] do campo (para o percentil, que precisa
    de todos os dias em memória e é calculado por blocos de latitude)."""
    with xr.open_dataset(caminho, decode_times=False) as ds:
        nome = nome_var if nome_var else next(iter(ds.data_vars))
        v = ds[nome]
        fatia = v[..., i0:i1, :] if (i0 is not None) else v
        dados = np.asarray(fatia.values, dtype=np.float32)
        if dados.ndim == 3:
            dados = dados[0]
        preenche = v.attrs.get("_FillValue",
                               v.encoding.get("_FillValue", -999.0))
        return np.where(dados <= (preenche + 1e-3), np.nan, dados)


def agrega_campos(caminhos_dias, arquivo_saida, operacao="media", titulo=None,
                  data_ref=None, log=print, nome_var=None,
                  limiar=None, percentil=None, linhas_bloco=400):
    """Agrega vários campos diários num único arquivo.

    ``operacao``:
      ``media``       média dos dias válidos (padrão);
      ``maximo``      máximo dos dias válidos;
      ``frequencia``  nº de dias com valor >= ``limiar`` e o respectivo
                      percentual dos dias válidos (duas variáveis);
      ``percentil``   percentil ``percentil`` (0–100) da distribuição dos
                      dias, calculado por blocos de latitude para não
                      carregar toda a série na memória.

    Valores ausentes são ignorados ponto a ponto. Devolve
    (arquivo_saida, número de dias usados)."""
    if operacao not in ("media", "maximo", "frequencia", "percentil"):
        raise ValueError(f"Operação desconhecida: '{operacao}'.")
    if operacao == "frequencia" and limiar is None:
        raise ValueError("A operação 'frequencia' exige um limiar.")
    if operacao == "percentil" and percentil is None:
        raise ValueError("A operação 'percentil' exige o valor (0–100).")

    # --- percentil: passa por blocos de linhas, guardando só o bloco ------
    if operacao == "percentil":
        return _agrega_percentil(caminhos_dias, arquivo_saida, percentil,
                                 titulo, data_ref, log, nome_var,
                                 linhas_bloco)

    soma = contagem = maximo = acima = None
    lat = lon = None
    usados = 0

    for caminho in caminhos_dias:
        dados, la, lo, _ = le_campo_rf(caminho, nome_var)
        if lat is None:
            lat, lon = la, lo
            soma = np.zeros_like(dados, dtype=np.float64)
            contagem = np.zeros(dados.shape, dtype=np.int32)
            acima = np.zeros(dados.shape, dtype=np.int32)
            maximo = np.full(dados.shape, np.nan, dtype=np.float32)
        elif dados.shape != soma.shape:
            log(f"AVISO: {os.path.basename(caminho)} tem grade "
                f"{dados.shape} (esperado {soma.shape}) — ignorado.")
            continue
        valido = ~np.isnan(dados)
        soma[valido] += dados[valido]
        contagem[valido] += 1
        maximo = np.where(valido & (np.isnan(maximo) | (dados > maximo)),
                          dados, maximo)
        if limiar is not None:
            acima += (valido & (dados >= float(limiar))).astype(np.int32)
        usados += 1

    if usados == 0:
        raise RuntimeError("Nenhum arquivo diário disponível para agregar.")

    if data_ref is None:
        data_ref = dt.datetime.now()
    extras = {"agregacao": operacao, "dias_agregados": str(usados)}

    if operacao == "frequencia":
        with np.errstate(invalid="ignore"):
            dias = np.where(contagem > 0, acima, np.nan)
            pct = np.where(contagem > 0,
                           100.0 * acima / np.maximum(contagem, 1), np.nan)
        extras["limiar"] = f"{float(limiar):g}"
        grava_netcdf_campos(
            {"dias": (np.round(dias, 0).astype(np.float32),
                      f"Dias com valor >= {float(limiar):g}", "dia"),
             "frequencia": (np.round(pct, 1).astype(np.float32),
                            f"Percentual de dias com valor >= "
                            f"{float(limiar):g}", "%")},
            lat, lon, data_ref, arquivo_saida, titulo=titulo,
            atributos_extras=extras)
        return arquivo_saida, usados

    with np.errstate(invalid="ignore"):
        # Arredondamento feito em float64 (o RF diário já tem 2 decimais,
        # então a média cai com frequência exatamente em 0,xx5).
        media = np.where(contagem > 0, soma / np.maximum(contagem, 1),
                         np.nan)
    campo = media if operacao == "media" else maximo.astype(np.float64)
    campo = np.round(campo, 2).astype(np.float32)

    grava_netcdf_rf(campo, lat, lon, data_ref.strftime("%Y%m%d%H"),
                    arquivo_saida, titulo=titulo, atributos_extras=extras)
    return arquivo_saida, usados


def _agrega_percentil(caminhos_dias, arquivo_saida, percentil, titulo,
                      data_ref, log, nome_var, linhas_bloco):
    """Percentil da distribuição diária, por blocos de latitude."""
    primeiro, lat, lon, _ = le_campo_rf(caminhos_dias[0], nome_var)
    nlat = lat.size
    saida = np.full(primeiro.shape, np.nan, dtype=np.float64)
    usados = len(caminhos_dias)

    for i0 in range(0, nlat, int(linhas_bloco)):
        i1 = min(i0 + int(linhas_bloco), nlat)
        pilha = []
        for caminho in caminhos_dias:
            fatia = le_fatia_rf(caminho, nome_var, i0, i1)
            if fatia.shape != (i1 - i0, lon.size):
                log(f"AVISO: {os.path.basename(caminho)} em grade "
                    f"diferente — ignorado.")
                continue
            pilha.append(fatia)
        if not pilha:
            continue
        with np.errstate(invalid="ignore", all="ignore"):
            saida[i0:i1] = np.nanpercentile(
                np.stack(pilha).astype(np.float64), float(percentil), axis=0)

    if data_ref is None:
        data_ref = dt.datetime.now()
    grava_netcdf_rf(
        np.round(saida, 2).astype(np.float32), lat, lon,
        data_ref.strftime("%Y%m%d%H"), arquivo_saida, titulo=titulo,
        atributos_extras={"agregacao": f"percentil {float(percentil):g}",
                          "dias_agregados": str(usados)})
    return arquivo_saida, usados


def operacoes_pedidas(args):
    """Lista de (rótulo, operação, kwargs) conforme as opções da linha de
    comando — compartilhada pelo RF previsto, RF observado e FWI.

    ``--maximo`` substitui a média; ``--frequencia`` e ``--percentil``
    geram arquivos ADICIONAIS, nos mesmos agrupamentos (período e/ou mês).
    """
    base = ("MAXIMO", "maximo", {}) if getattr(args, "maximo", False) \
        else ("MEDIA", "media", {})
    ops = [base]
    limiar = getattr(args, "frequencia", None)
    if limiar is not None:
        ops.append((f"FREQ{float(limiar):g}", "frequencia",
                    {"limiar": float(limiar)}))
    pct = getattr(args, "percentil", None)
    if pct is not None:
        ops.append((f"P{int(pct)}", "percentil", {"percentil": float(pct)}))
    return ops


def agrupa_por_mes(dias):
    """Agrupa datetimes por (ano, mês), preservando a ordem."""
    grupos = {}
    for d in dias:
        grupos.setdefault((d.year, d.month), []).append(d)
    return sorted(grupos.items())


def grava_netcdf_campos(variaveis, lat, lon, quando, arquivo_saida,
                        titulo=None, atributos_extras=None):
    """Grava um NetCDF com várias variáveis 2D.

    ``variaveis``: dict {nome: (campo, descricao, unidade)}."""
    dados = {nome: (("time", "lat", "lon"),
                    np.asarray(campo, dtype=np.float32)[np.newaxis],
                    {"long_name": desc, "units": unidade})
             for nome, (campo, desc, unidade) in variaveis.items()}
    ds = xr.Dataset(
        dados,
        coords={
            "time": [quando],
            "lat": ("lat", np.asarray(lat, dtype=np.float64),
                    {"standard_name": "latitude", "units": "degrees_north"}),
            "lon": ("lon", np.asarray(lon, dtype=np.float64),
                    {"standard_name": "longitude", "units": "degrees_east"}),
        },
        attrs={"title": titulo or "Agregacao do Risco de Fogo",
               "history": f"gerado em {dt.datetime.now():%Y-%m-%d %H:%M}"},
    )
    if atributos_extras:
        ds.attrs.update(atributos_extras)
    enc = {nome: {"dtype": "float32", "zlib": True, "complevel": 4,
                  "_FillValue": FILL_VALUE} for nome in variaveis}
    enc["time"] = {"units": "hours since 1900-01-01 00:00:00",
                   "calendar": "standard", "dtype": "float64"}
    os.makedirs(os.path.dirname(os.path.abspath(arquivo_saida)),
                exist_ok=True)
    ds.to_netcdf(arquivo_saida, format="NETCDF4_CLASSIC", encoding=enc)
    return arquivo_saida


# ---------------------------------------------------------------------------
# Escrita do NetCDF de saída
# ---------------------------------------------------------------------------

def grava_netcdf_rf(rbf, lat, lon, data_previsao, arquivo_saida, titulo=None,
                    atributos_extras=None):
    """Grava o NetCDF do RF previsto, já com o eixo de tempo correto e o
    valor ausente -999 (substitui o "cdo -r -setmissval,-999 -settaxis").

    ``atributos_extras``: dict opcional de atributos globais adicionais
    (ex.: fatores desligados numa análise de sensibilidade)."""

    tempo = dt.datetime.strptime(data_previsao, "%Y%m%d%H")

    if titulo is None:
        titulo = f"Risco de fogo previsto para o dia {data_previsao}"

    ds = xr.Dataset(
        {
            "rbf": (("time", "lat", "lon"),
                    rbf[np.newaxis, :, :].astype(np.float32)),
        },
        coords={
            "time": [tempo],
            "lat": ("lat", np.asarray(lat, dtype=np.float64),
                    {"standard_name": "latitude",
                     "long_name": "latitude",
                     "units": "degrees_north", "axis": "Y"}),
            "lon": ("lon", np.asarray(lon, dtype=np.float64),
                    {"standard_name": "longitude",
                     "long_name": "longitude",
                     "units": "degrees_east", "axis": "X"}),
        },
        attrs={
            "title": titulo,
            "Conventions": "None",
            "codigo": "Guilherme Martins - guilherme.martins@inpe.br",
            "author": "Alberto Setzer - alberto.setzer@inpe.br",
            "link": "http://www.inpe.br/queimadas/",
            "source": ("Codigo convertido de NCL para Python "
                       f"{sys.version.split()[0]} (numpy/xarray)"),
            "creation_date": dt.datetime.now().strftime("%a %b %d %H:%M:%S %Z %Y"),
            **(atributos_extras or {}),
        },
    )

    if os.path.exists(arquivo_saida):
        os.remove(arquivo_saida)

    ds.to_netcdf(
        arquivo_saida,
        format="NETCDF4_CLASSIC",
        unlimited_dims=["time"],
        encoding={
            "rbf": {"_FillValue": np.float32(FILL_VALUE),
                    "missing_value": np.float32(FILL_VALUE),
                    "dtype": "float32"},
            "time": {"units": "hours since 1900-01-01 00:00:00",
                     "calendar": "standard", "dtype": "float64"},
        },
    )


# ---------------------------------------------------------------------------
# Geração do GeoTIFF (substitui o gdal_translate)
# ---------------------------------------------------------------------------

def netcdf_para_geotiff(arquivo_netcdf, arquivo_tif, nome_var="rbf"):
    """Converte o NetCDF do RF em GeoTIFF EPSG:4326 (tiled, LZW), como o
    "gdal_translate -of GTiff -a_srs EPSG:4326 -co TILED=YES -co COMPRESS=LZW".
    """
    import rasterio
    from rasterio.transform import from_origin

    with xr.open_dataset(arquivo_netcdf, decode_times=False) as ds:
        var = ds[nome_var]
        dados = np.asarray(var.values, dtype=np.float32)
        if dados.ndim == 3:
            dados = dados[0]
        lat = np.asarray(ds["lat"].values, dtype=np.float64)
        lon = np.asarray(ds["lon"].values, dtype=np.float64)

    # GeoTIFF é orientado de norte para sul: inverte a latitude se necessário.
    if lat[0] < lat[-1]:
        dados = dados[::-1, :]
        lat = lat[::-1]

    dx = abs(lon[1] - lon[0])
    dy = abs(lat[1] - lat[0])
    transform = from_origin(lon.min() - dx / 2.0, lat.max() + dy / 2.0, dx, dy)

    dados = np.where(np.isnan(dados), FILL_VALUE, dados)

    perfil = dict(
        driver="GTiff",
        height=dados.shape[0],
        width=dados.shape[1],
        count=1,
        dtype="float32",
        crs="EPSG:4326",
        transform=transform,
        nodata=FILL_VALUE,
        tiled=True,
        compress="LZW",
    )

    with rasterio.open(arquivo_tif, "w", **perfil) as dst:
        dst.write(dados, 1)

    return arquivo_tif


# ---------------------------------------------------------------------------
# Junção dos horários de previsão (substitui o "cdo mergetime")
# ---------------------------------------------------------------------------

def mergetime(arquivos_netcdf, arquivo_saida, nome_var="rbf"):
    """Cria um único arquivo com todos os horários de previsão
    (equivalente ao "cdo -O mergetime")."""
    datasets = [xr.open_dataset(a) for a in sorted(arquivos_netcdf)]
    try:
        combinado = xr.concat(datasets, dim="time",
                              data_vars="minimal", coords="minimal",
                              compat="override")
        combinado = combinado.sortby("time")
        if os.path.exists(arquivo_saida):
            os.remove(arquivo_saida)
        combinado.to_netcdf(
            arquivo_saida,
            format="NETCDF4_CLASSIC",
            unlimited_dims=["time"],
            encoding={
                nome_var: {"_FillValue": np.float32(FILL_VALUE),
                           "missing_value": np.float32(FILL_VALUE),
                           "dtype": "float32"},
                "time": {"units": "hours since 1900-01-01 00:00:00",
                         "calendar": "standard", "dtype": "float64"},
            },
        )
    finally:
        for d in datasets:
            d.close()
    return arquivo_saida
