# -*- coding: utf-8 -*-
"""Teste do prepara_imerg.py (sem rede e sem credenciais).

1. converte(): NetCDF global sintético no formato do IMERG V07
   (precipitation em (time, lon, lat), lat sul->norte) -> recorte,
   transposição e limpeza de valores inválidos.
2. Variante com lat norte->sul e variável precipitationCal (V06).
3. grava_padrao(): arquivo aceito pelos leitores do pipeline, no caminho
   do rf_config, sem sobrescrita indevida.
4. Integração: o arquivo gerado entra na lista do modo legado do RF.
"""

import datetime as dt
import io
import os
import shutil

import numpy as np
import xarray as xr

import prepara_imerg as pi
import rf_config
import rf_core

DOMINIO = (-20.0, -10.0, -60.0, -50.0)
rng = np.random.default_rng(5)


def nc4_sintetico(ordem=("time", "lon", "lat"), lat_desc=False,
                  nome_var="precipitation"):
    lat = np.arange(-89.95, 90.0, 0.1)
    if lat_desc:
        lat = lat[::-1]
    lon = np.arange(-179.95, 180.0, 0.1)
    campo = rng.gamma(0.7, 4.0, (1, lon.size, lat.size)).astype(np.float32)
    campo[0, 100, 200] = -9999.9          # valor inválido -> NaN
    if ordem == ("time", "lat", "lon"):
        campo = campo.transpose(0, 2, 1)
    ds = xr.Dataset({nome_var: (ordem, campo)},
                    coords={"time": [np.datetime64("2026-08-01")],
                            "lat": lat, "lon": lon})
    buf = io.BytesIO()
    ds.to_netcdf(buf, format="NETCDF4", engine="h5netcdf") \
        if False else ds.to_netcdf("/tmp/_imerg_sint.nc4")
    with open("/tmp/_imerg_sint.nc4", "rb") as f:
        return f.read()


# ---------------------------------------------------------------------------
# 1. Conversão no formato V07 (lon,lat) com lat crescente
# ---------------------------------------------------------------------------
dia = dt.datetime(2026, 8, 1)
prec, la, lo = pi.converte(nc4_sintetico(), DOMINIO, dia)
assert la[0] < la[-1] and DOMINIO[0] <= la[0] and la[-1] <= DOMINIO[1]
assert DOMINIO[2] <= lo[0] and lo[-1] <= DOMINIO[3]
assert prec.shape == (la.size, lo.size)
assert np.nanmin(prec) >= 0                       # inválidos viraram NaN
print("Teste 1 (conversao V07 lon/lat) ok")

# ---------------------------------------------------------------------------
# 2. Variantes: lat decrescente e nome antigo da variável
# ---------------------------------------------------------------------------
prec2, la2, _ = pi.converte(nc4_sintetico(lat_desc=True), DOMINIO, dia)
assert la2[0] < la2[-1]
prec3, _, _ = pi.converte(
    nc4_sintetico(ordem=("time", "lat", "lon"), nome_var="precipitationCal"),
    DOMINIO, dia)
assert prec3.shape == prec.shape
print("Teste 2 (lat invertida e precipitationCal) ok")

# ---------------------------------------------------------------------------
# 3. Gravação no padrão do pipeline via rf_config
# ---------------------------------------------------------------------------
BASE = "/tmp/teste_prepara_imerg"
shutil.rmtree(BASE, ignore_errors=True)
cfg = rf_config.padrao()
destino = rf_config.caminho_imerg(BASE, cfg["caminhos"], dia)
assert destino.endswith("2026/08/INPE_FireRiskModel_2.2_Precipitation_20260801.nc")

assert pi.grava_padrao(destino, prec, la, lo, dia, "teste", False) is True
assert pi.grava_padrao(destino, prec * 0, la, lo, dia, "teste", False) is False

p_lido, la_lido, lo_lido = rf_core.ler_precipitacao([destino])
assert p_lido.shape == (1, la.size, lo.size)
assert np.allclose(np.nan_to_num(p_lido[0], nan=-1),
                   np.nan_to_num(prec, nan=-1), atol=1e-4)
assert la_lido[0] < la_lido[-1]
print("Teste 3 (gravacao no padrao e leitura pelo rf_core) ok")

# ---------------------------------------------------------------------------
# 4. O arquivo gerado é encontrado pela montagem de caminhos do pipeline
# ---------------------------------------------------------------------------
d2 = dt.datetime(2026, 8, 2)
pi.grava_padrao(rf_config.caminho_imerg(BASE, cfg["caminhos"], d2),
                prec, la, lo, d2, "teste", False)
achados = [d for d in (dia, d2)
           if os.path.exists(rf_config.caminho_imerg(BASE, cfg["caminhos"], d))]
assert len(achados) == 2
print("Teste 4 (caminhos consistentes com o pipeline) ok")

os.remove("/tmp/_imerg_sint.nc4")
print()
print("TODOS OS TESTES DO PREPARA_IMERG PASSARAM")
