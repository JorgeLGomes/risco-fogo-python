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

def ler_precipitacao(lista_arquivos, nome_var="prec"):
    """Lê e concatena os arquivos de precipitação na ordem da lista e
    INVERTE a dimensão tempo (equivalente ao ``(::-1,:,:)`` do NCL).

    Após a inversão, o índice 0 corresponde ao tempo mais recente
    (arquivo do GFS) e o último índice ao dia mais antigo.

    Arquivos em GRADE DIFERENTE da do primeiro (ex.: GFS nativo de 0,25°
    junto com IMERG de 0,1°) são regradeados por interpolação bilinear
    para a grade de referência — na operação original essa interpolação
    era feita numa etapa anterior do fluxo.
    """
    campos = []
    lat = lon = None
    for arq in lista_arquivos:
        with xr.open_dataset(arq, decode_times=False) as ds:
            var = ds[nome_var]
            dados = np.asarray(var.values, dtype=np.float32)
            if dados.ndim == 2:      # arquivo sem dimensão tempo
                dados = dados[np.newaxis, :, :]
            la = np.asarray(ds["lat"].values, dtype=np.float64)
            lo = np.asarray(ds["lon"].values, dtype=np.float64)

        if la.size > 1 and la[0] > la[-1]:    # norte->sul: inverte
            la = la[::-1]
            dados = dados[:, ::-1, :]

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
                       titulo=None,
                       log=print,
                       usar_vegetacao=True,
                       usar_topografia=True,
                       classe_veg_uniforme=4):
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
                                                  nome_var_precip)

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
    )


def calcula_risco_fogo_dados(precip_invertida, lat_prec, lon_prec,
                             t2m, ur2m, lat_met, lon_met,
                             arquivo_mapa_veg, arquivo_topografia,
                             arquivo_saida, data_previsao,
                             rb_maximo=0.9, titulo=None, log=print,
                             usar_vegetacao=True, usar_topografia=True,
                             classe_veg_uniforme=4):
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
    # para incluir a sazonalidade do RF.
    FU = (-0.008 * ur2m) + 1.3
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
    grava_netcdf_rf(xT, lat_1km, lon_1km, data_previsao, arquivo_saida,
                    titulo=titulo, atributos_extras=extras or None)

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
