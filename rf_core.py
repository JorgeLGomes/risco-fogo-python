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
    """
    campos = []
    lat = lon = None
    for arq in lista_arquivos:
        with xr.open_dataset(arq, decode_times=False) as ds:
            var = ds[nome_var]
            dados = np.asarray(var.values, dtype=np.float32)
            if dados.ndim == 2:      # arquivo sem dimensão tempo
                dados = dados[np.newaxis, :, :]
            campos.append(dados)
            if lat is None:
                lat = np.asarray(ds["lat"].values, dtype=np.float64)
                lon = np.asarray(ds["lon"].values, dtype=np.float64)

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
                       log=print):
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

    nd = precip.shape[0]
    if nd < ND_ESPERADO:
        raise RuntimeError(
            f"Número de tempos de precipitação insuficiente: {nd} "
            f"(esperado {ND_ESPERADO}). Verifique os arquivos faltantes.")

    log("")
    log("Abrindo o arquivo de mapa de vegetação.")
    log("")
    mapa_veg, lat_veg, lon_veg = ler_mapa_vegetacao(arquivo_mapa_veg)
    nlat_veg, nlon_veg = mapa_veg.shape

    # Grade de destino de 1 km (equivalente ao fspan do NCL).
    lat_1km = np.linspace(lat_veg[0], lat_veg[-1], nlat_veg)
    lon_1km = np.linspace(lon_veg[0], lon_veg[-1], nlon_veg)

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

    log("")
    log("Abrindo o arquivo de topografia")
    log("")
    elev = ler_topografia(arquivo_topografia)
    if elev.shape != rbf.shape:
        raise RuntimeError(
            f"A topografia {elev.shape} não tem a mesma grade do mapa de "
            f"vegetação {rbf.shape}.")

    log("")
    log("Calculando o fator de elevação")
    log("")
    # Correção do risco de fogo pela topografia (Fator Topográfico - FTOP).
    FTOP = 1.0 + elev.astype(np.float64) * 0.00003

    rbfn = rbf * FLAT_C * FTOP
    rbfn = np.where(rbfn > 1.0, 1.0, rbfn)

    # Arredonda para 2 casas decimais (decimalPlaces do NCL).
    xT = np.round(rbfn, 2).astype(np.float32)

    log("")
    log(f"Gerando o arquivo NetCDF para o dia {data_previsao}")
    log("")
    grava_netcdf_rf(xT, lat_1km, lon_1km, data_previsao, arquivo_saida,
                    titulo=titulo)

    return arquivo_saida


# ---------------------------------------------------------------------------
# Escrita do NetCDF de saída
# ---------------------------------------------------------------------------

def grava_netcdf_rf(rbf, lat, lon, data_previsao, arquivo_saida, titulo=None):
    """Grava o NetCDF do RF previsto, já com o eixo de tempo correto e o
    valor ausente -999 (substitui o "cdo -r -setmissval,-999 -settaxis")."""

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
