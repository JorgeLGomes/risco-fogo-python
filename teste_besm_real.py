# -*- coding: utf-8 -*-
"""Teste do RF com os dados REAIS do BESM T062 (besm_queimada, CPTEC).

Estrutura real: um arquivo por variável com todos os 396 tempos diários
(rodada 2026-08-04, previsões 2026-08-05 a 2027-09-04), grade gaussiana
~1.875° com latitude norte->sul, prec em mm/dia, t2mt em K, rsmt em %.

Cenários:
  1. Horizonte de 13 meses (janela 100% prevista) — RF gerado com os
     campos reais do BESM.
  2. Horizonte de 30 dias — janela mista: IMERG sintético (90 dias) +
     BESM real (30 dias).
  3. Conferência da agregação: o dia previsto D deve ser exatamente o
     campo do índice correspondente do arquivo real (freq 1d).
  4. Conferência de unidades: t2mt K->°C e rsmt %->décimos.
"""

import datetime as dt
import os
import shutil
import subprocess
import sys

import numpy as np
import xarray as xr

BASE = "/tmp/teste_besm_real"
DATA_FINAL = "20260804"          # data da rodada real do BESM
HOJE = dt.datetime.strptime(DATA_FINAL, "%Y%m%d")
MODELO = DATA_FINAL + "00"
DADOS_REAIS = "/mnt/user-data/uploads/besm_queimada"

shutil.rmtree(BASE, ignore_errors=True)
rng = np.random.default_rng(21)

# --------------------------------------------------------------------------
# BESM real no lugar esperado pela fonte
# --------------------------------------------------------------------------
dir_besm = f"{BASE}/data/output/2.2/BESM/netcdf/{MODELO}"
os.makedirs(dir_besm, exist_ok=True)
for arq in ["tmp_prec.nc", "tmp_t2mt.nc", "tmp_rsmt.nc"]:
    shutil.copy2(os.path.join(DADOS_REAIS, arq), os.path.join(dir_besm, arq))

# --------------------------------------------------------------------------
# IMERG sintético (119 dias antes da rodada) em grade 0.1° regional
# --------------------------------------------------------------------------
lat_p = np.arange(-20.0, -9.9, 0.1)
lon_p = np.arange(-60.0, -49.9, 0.1)
for i in range(119):
    d = HOJE - dt.timedelta(days=119 - i)
    ymd = d.strftime("%Y%m%d")
    ds = xr.Dataset(
        {"prec": (("time", "lat", "lon"),
                  rng.gamma(0.7, 4.0, (1, lat_p.size, lon_p.size)).astype(np.float32))},
        coords={"time": [np.datetime64(d.strftime("%Y-%m-%d"))],
                "lat": lat_p, "lon": lon_p})
    destino = (f"{BASE}/data/output/2.2/Precipitation-2_2/{ymd[:4]}/{ymd[4:6]}/"
               f"INPE_FireRiskModel_2.2_Precipitation_{ymd}.nc")
    os.makedirs(os.path.dirname(destino), exist_ok=True)
    ds.to_netcdf(destino)

# --------------------------------------------------------------------------
# Vegetação e topografia sintéticas (1 km) no domínio regional
# --------------------------------------------------------------------------
lat_v = np.arange(-20.0, -10.0 + 1e-9, 0.01)[:601]   # recorte p/ agilidade
lon_v = np.arange(-60.0, -50.0 + 1e-9, 0.01)[:601]
veg = rng.integers(0, 8, (lat_v.size, lon_v.size)).astype(np.int16)
os.makedirs(f"{BASE}/data/input/Veg_Map_2020", exist_ok=True)
os.makedirs(f"{BASE}/data/input/topografia", exist_ok=True)
xr.Dataset({"Band1": (("lat", "lon"), veg)},
           coords={"lat": lat_v, "lon": lon_v}).to_netcdf(
    f"{BASE}/data/input/Veg_Map_2020/Merge_MapBiomas_V5_IGBP_C6_2019.nc")
xr.Dataset({"Band1": (("lat", "lon"),
                      rng.uniform(0, 3000, (lat_v.size, lon_v.size)).astype(np.float32))},
           coords={"lat": lat_v, "lon": lon_v}).to_netcdf(
    f"{BASE}/data/input/topografia/GeoTOPOAmericaSulCentral_V3.nc")

AQUI = os.path.dirname(os.path.abspath(__file__))


def roda(*extras):
    cmd = [sys.executable, os.path.join(AQUI, "rf_previsto.py"),
           "--base", BASE, "--data-final", DATA_FINAL, "--jobs", "1",
           "--fonte", "besm", "--sem-tif"] + list(extras)
    r = subprocess.run(cmd, capture_output=True, text=True)
    print(">>", " ".join(extras))
    if r.returncode != 0:
        print(r.stdout)
        print(r.stderr)
        raise SystemExit(f"rf_previsto.py falhou: {r.returncode}")
    return r


# ==========================================================================
# 1. Horizonte de 13 meses com dados reais
# ==========================================================================
roda("--horizontes", "13m")
saida_13m = f"{BASE}/data/output/2.2/RF_PREV_BESM/netcdf/{MODELO}/RF.PREV.2027090400.nc"
assert os.path.exists(saida_13m), saida_13m
with xr.open_dataset(saida_13m) as ds:
    v = ds["rbf"].values
    assert str(ds["time"].values[0])[:10] == "2027-09-04"
    validos = v[~np.isnan(v)]
    assert validos.size > 0 and validos.min() >= 0 and validos.max() <= 1
    frac_validos = validos.size / v.size
    print(f"Teste 1 (13 meses, BESM real) ok — RF médio "
          f"{validos.mean():.3f}, {frac_validos:.0%} de pontos válidos")

# ==========================================================================
# 2. Horizonte de 30 dias: janela mista IMERG sintético + BESM real
# ==========================================================================
roda("--horizontes", "30d")
saida_30d = f"{BASE}/data/output/2.2/RF_PREV_BESM/netcdf/{MODELO}/RF.PREV.2026090300.nc"
assert os.path.exists(saida_30d)
print("Teste 2 (30 dias, janela mista IMERG+BESM) ok")

# ==========================================================================
# 3. Agregação/seleção do dia correto na série real
# ==========================================================================
sys.path.insert(0, AQUI)
import rf_fontes  # noqa: E402

fonte = rf_fontes.FONTES["besm"]
assert fonte.layout == "serie" and fonte.freq_prec == "1d"

with xr.open_dataset(f"{DADOS_REAIS}/tmp_prec.nc") as ds:
    lat_besm = ds["lat"].values[::-1].astype(float)   # sul->norte
    lon_besm = ds["lon"].values.astype(float)
    bruto = ds["prec"].values[:, ::-1, :]
    tempos = ds["time"].values

dia_teste = dt.datetime(2027, 3, 15)
diario = rf_fontes.precip_diaria_prevista(
    fonte, dir_besm, MODELO, dia_teste, lat_besm, lon_besm)
i = int(np.nonzero(tempos.astype("datetime64[D]")
                   == np.datetime64("2027-03-15"))[0][0])
assert np.allclose(diario, bruto[i], atol=1e-5), "seleção do dia incorreta"
print(f"Teste 3 (dia 2027-03-15 = índice {i} da série real) ok")

# ==========================================================================
# 4. Unidades: K->°C e %->décimos
# ==========================================================================
t2m, ur2m, la, lo = rf_fontes.temp_ur_previstos(
    fonte, dir_besm, MODELO, "2027090400")
assert -40 < np.nanmean(t2m) < 45, f"t2m média suspeita: {np.nanmean(t2m)}"
assert 0 <= np.nanmin(ur2m) and np.nanmax(ur2m) <= 1.0001, "ur2m fora de décimos"
assert la[0] < la[-1], "latitude deveria estar sul->norte após a leitura"
print(f"Teste 4 (unidades) ok — t2m média {np.nanmean(t2m):.1f} °C, "
      f"ur2m média {np.nanmean(ur2m):.2f}")

print()
print("TODOS OS TESTES COM O BESM REAL PASSARAM")
