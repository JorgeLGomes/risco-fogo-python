# -*- coding: utf-8 -*-
"""Teste do rf_core com dados sintéticos + IMERG real.

1. Gera 119 arquivos IMERG sintéticos (recortados do arquivo real) + 1 GFS
   de precipitação + 1 GFS de TEMP2m/RH2m + mapa de vegetação + topografia.
2. Roda calcula_risco_fogo e valida contra uma implementação de referência
   "linha a linha" fiel ao NCL (laços explícitos).
3. Valida a interpolação bilinear contra scipy.RegularGridInterpolator.
4. Testa netcdf_para_geotiff e mergetime.
"""

import math
import os
import shutil

import numpy as np
import xarray as xr

import rf_core

RAIZ = "/tmp/teste_rf"
shutil.rmtree(RAIZ, ignore_errors=True)
os.makedirs(RAIZ, exist_ok=True)

rng = np.random.default_rng(42)

# ---------------------------------------------------------------------------
# 1. Dados sintéticos
# ---------------------------------------------------------------------------

# Grade "IMERG/GFS" pequena (0.5 graus)
lat_p = np.arange(-20.0, -9.9, 0.5)
lon_p = np.arange(-60.0, -49.9, 0.5)
nlat_p, nlon_p = lat_p.size, lon_p.size

# Grade "1 km" (0.1 graus) para o mapa de vegetação/topografia
lat_v = np.arange(-20.0, -10.0 + 1e-9, 0.1)
lon_v = np.arange(-60.0, -50.0 + 1e-9, 0.1)
nlat_v, nlon_v = lat_v.size, lon_v.size

lista_prec = []
for i in range(119):
    prec = rng.gamma(0.7, 4.0, size=(1, nlat_p, nlon_p)).astype(np.float32)
    ds = xr.Dataset({"prec": (("time", "lat", "lon"), prec)},
                    coords={"time": [np.datetime64("2026-04-07") + np.timedelta64(i, "D")],
                            "lat": lat_p, "lon": lon_p})
    arq = f"{RAIZ}/IMERG_{i:03d}.nc"
    ds.to_netcdf(arq)
    lista_prec.append(arq)

# GFS precipitação (o 120º arquivo)
prec_gfs = rng.gamma(0.7, 4.0, size=(1, nlat_p, nlon_p)).astype(np.float32)
xr.Dataset({"prec": (("time", "lat", "lon"), prec_gfs)},
           coords={"time": [np.datetime64("2026-08-04")],
                   "lat": lat_p, "lon": lon_p}).to_netcdf(f"{RAIZ}/GFS_PREC.nc")
lista_prec.append(f"{RAIZ}/GFS_PREC.nc")

# GFS TEMP2m (K) / RH2m (%)
t2m = (rng.uniform(285.0, 310.0, size=(1, nlat_p, nlon_p))).astype(np.float32)
rh2m = (rng.uniform(20.0, 95.0, size=(1, nlat_p, nlon_p))).astype(np.float32)
xr.Dataset({"TEMP2m": (("time", "lat", "lon"), t2m),
            "RH2m": (("time", "lat", "lon"), rh2m)},
           coords={"time": [np.datetime64("2026-08-04")],
                   "lat": lat_p, "lon": lon_p}).to_netcdf(f"{RAIZ}/GFS_T_UR.nc")

# Mapa de vegetação (classes 0 a 7, com água=0)
veg = rng.integers(0, 8, size=(nlat_v, nlon_v)).astype(np.int16)
xr.Dataset({"Band1": (("lat", "lon"), veg)},
           coords={"lat": lat_v, "lon": lon_v}).to_netcdf(f"{RAIZ}/VEG.nc")

# Topografia (metros)
topo = rng.uniform(0.0, 3000.0, size=(nlat_v, nlon_v)).astype(np.float32)
xr.Dataset({"Band1": (("lat", "lon"), topo)},
           coords={"lat": lat_v, "lon": lon_v}).to_netcdf(f"{RAIZ}/TOPO.nc")

# ---------------------------------------------------------------------------
# 2. Roda o rf_core
# ---------------------------------------------------------------------------

saida = f"{RAIZ}/RF.PREV.2026080418.nc"
rf_core.calcula_risco_fogo(
    arquivo_temp_ur=f"{RAIZ}/GFS_T_UR.nc",
    lista_arquivos_prec=lista_prec,
    arquivo_mapa_veg=f"{RAIZ}/VEG.nc",
    arquivo_topografia=f"{RAIZ}/TOPO.nc",
    arquivo_saida=saida,
    data_previsao="2026080418",
    rb_maximo=0.9,
    log=lambda *a: None,
)

with xr.open_dataset(saida) as ds_out:
    rbf_py = ds_out["rbf"].values[0]
    assert ds_out["rbf"].shape == (1, nlat_v, nlon_v)
    t = ds_out["time"].values[0]
    assert str(t)[:13] == "2026-08-04T18", t

# ---------------------------------------------------------------------------
# 3. Implementação de referência fiel ao NCL (laços explícitos)
# ---------------------------------------------------------------------------

# precip concatenada e invertida no tempo
campos = []
for arq in lista_prec:
    with xr.open_dataset(arq) as d:
        campos.append(d["prec"].values.astype(np.float32))
precip = np.concatenate(campos, axis=0)[::-1]

nd = precip.shape[0]
vprec = np.empty_like(precip, dtype=np.float64)
vprec[0] = precip[0]
for i in range(1, nd):
    vprec[i] = vprec[i - 1] + precip[i]

cte = [-0.14, -0.07, -0.04, -0.03, -0.02, -0.01,
       -0.008, -0.004, -0.002, -0.001, -0.0007]
fp = np.empty((11, nlat_p, nlon_p))
fp[0] = np.exp(cte[0] * vprec[0])
for j in range(1, 5):
    fp[j] = np.exp(cte[j] * (vprec[j] - vprec[j - 1]))
fp[5] = np.exp(cte[5] * (vprec[9] - vprec[4]))
fp[6] = np.exp(cte[6] * (vprec[14] - vprec[9]))
fp[7] = np.exp(cte[7] * (vprec[29] - vprec[14]))
fp[8] = np.exp(cte[8] * (vprec[59] - vprec[29]))
fp[9] = np.exp(cte[9] * (vprec[89] - vprec[59]))
fp[10] = np.exp(cte[10] * (vprec[119] - vprec[89]))

pse = 105.0 * fp[0] * fp[1] * fp[2] * fp[3] * fp[4] * fp[5] * fp[6] * fp[7] * fp[8] * fp[9] * fp[10]

# interpolação bilinear de referência (scipy)
from scipy.interpolate import RegularGridInterpolator
interp = RegularGridInterpolator((lat_p, lon_p), pse, method="linear",
                                 bounds_error=False, fill_value=None)
pts = np.array(np.meshgrid(lat_v, lon_v, indexing="ij")).reshape(2, -1).T
pse_1km_ref = interp(pts).reshape(nlat_v, nlon_v)

pse_1km_py = rf_core.interp_bilinear(pse, lat_p, lon_p, lat_v, lon_v)
err = np.nanmax(np.abs(pse_1km_py.astype(np.float64) - pse_1km_ref))
print(f"interp_bilinear vs scipy: erro máximo = {err:.3e}")
assert err < 1e-3, err

# rb com laços explícitos (como o NCL)
A = [-999.9, 6, 4, 3, 2.4, 2, 1.72, 1.5]
pse_max = [-999.9, 30, 45, 60, 75, 90, 105, 120]
rb_ref = np.full((nlat_v, nlon_v), np.nan)
for i in range(nlat_v):
    for k in range(nlon_v):
        v = int(veg[i, k])
        p = pse_1km_py[i, k]          # usa a mesma interpolação do rf_core
        if v == 0:                    # água -> ausente
            continue
        if not math.isnan(p) and pse_max[v] != -999.9 and p > pse_max[v]:
            rb_ref[i, k] = 0.9
        else:
            rb_ref[i, k] = (0.9 * (1 + math.sin((A[v] * p - 90) * (3.1416 / 180)))) / 2.0

FU = (-0.008 * (rh2m[0] / 100.0)) + 1.3
FT = (0.02 * (t2m[0] - 273.15)) + 0.4
FU_1km = rf_core.interp_bilinear(FU, lat_p, lon_p, lat_v, lon_v)
FT_1km = rf_core.interp_bilinear(FT, lat_p, lon_p, lat_v, lon_v)

rbf_ref = rb_ref * FT_1km * FU_1km
rbf_ref = np.where(rbf_ref > 1, 1, rbf_ref)
FLAT = 1 + np.abs(lat_v) * 0.003
rbfn_ref = rbf_ref * FLAT[:, None] * (1 + topo * 0.00003)
rbfn_ref = np.where(rbfn_ref > 1, 1, rbfn_ref)
rbfn_ref = np.round(rbfn_ref, 2)

dif = np.abs(np.nan_to_num(rbf_py, nan=-999.0)
             - np.nan_to_num(rbfn_ref, nan=-999.0))
print(f"rbf rf_core vs referência NCL: erro máximo = {np.max(dif):.3e}")
assert np.max(dif) <= 0.011, np.max(dif)   # tolerância de arredondamento float32

# água (classe 0) deve ser ausente
assert np.all(np.isnan(rbf_py[veg == 0])), "classe 0 deveria ser NaN"
# valores válidos entre 0 e 1
validos = rbf_py[~np.isnan(rbf_py)]
assert validos.min() >= 0.0 and validos.max() <= 1.0

# ---------------------------------------------------------------------------
# 4. GeoTIFF e mergetime
# ---------------------------------------------------------------------------

tif = f"{RAIZ}/RF.PREV.2026080418.tif"
rf_core.netcdf_para_geotiff(saida, tif)

import rasterio
with rasterio.open(tif) as src:
    assert src.crs.to_string() == "EPSG:4326"
    assert src.nodata == -999.0
    banda = src.read(1)
    # banda invertida (norte para sul) deve bater com o NetCDF
    b = np.where(banda == -999.0, np.nan, banda)[::-1]
    assert np.allclose(np.nan_to_num(b, nan=-1), np.nan_to_num(rbf_py, nan=-1),
                       atol=1e-6)
    print("GeoTIFF ok:", src.profile["compress"], "tiled =", src.profile["tiled"],
          "bounds =", tuple(round(x, 3) for x in src.bounds))

# segundo horário para testar o mergetime
saida2 = f"{RAIZ}/RF.PREV.2026080412.nc"
rf_core.grava_netcdf_rf(rbf_py, lat_v, lon_v, "2026080412", saida2)
fogograma = f"{RAIZ}/FOGOGRAMA.nc"
rf_core.mergetime([saida, saida2], fogograma)
with xr.open_dataset(fogograma) as fg:
    assert fg["rbf"].shape[0] == 2
    tempos = [str(t)[:13] for t in fg["time"].values]
    assert tempos == ["2026-08-04T12", "2026-08-04T18"], tempos
    print("mergetime ok:", tempos)

# ---------------------------------------------------------------------------
# 5. Teste com o arquivo IMERG real (variável prec, grade 0.1°)
# ---------------------------------------------------------------------------

imerg_real = "/mnt/user-data/uploads/Risco Fogo/IMERG.YYYYMMDD.nc"
p, la, lo = rf_core.ler_precipitacao([imerg_real])
assert p.shape == (1, 901, 850) and la[0] < la[-1]
print("Leitura do IMERG real ok:", p.shape,
      f"lat {la[0]:.2f}..{la[-1]:.2f} lon {lo[0]:.2f}..{lo[-1]:.2f}")

print()
print("TODOS OS TESTES PASSARAM")
