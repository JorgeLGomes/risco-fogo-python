# -*- coding: utf-8 -*-
"""Teste de ponta a ponta do rf_previsto.py (script genérico de horizontes).

Monta uma árvore sintética com a MESMA estrutura de diretórios da produção
em /tmp/teste_generico e executa o script real via linha de comando,
verificando lista de horizontes, intervalo --de/--ate/--passo, fallback do
GFS, GeoTIFF e fogograma.
"""

import glob
import os
import shutil
import subprocess
import sys
import datetime as dt

import numpy as np
import xarray as xr

BASE = "/tmp/teste_generico"
DATA_FINAL = "20260804"
HOJE = dt.datetime.strptime(DATA_FINAL, "%Y%m%d")
MODELO = DATA_FINAL + "00"

shutil.rmtree(BASE, ignore_errors=True)

rng = np.random.default_rng(7)

lat_p = np.arange(-20.0, -9.9, 0.5)
lon_p = np.arange(-60.0, -49.9, 0.5)
lat_v = np.arange(-20.0, -10.0 + 1e-9, 0.1)
lon_v = np.arange(-60.0, -50.0 + 1e-9, 0.1)


def grava(caminho, variaveis, coords):
    os.makedirs(os.path.dirname(caminho), exist_ok=True)
    xr.Dataset(variaveis, coords=coords).to_netcdf(caminho)


# IMERG: 119 dias em Precipitation-2_2/AAAA/MM/
for i in range(119):
    d = HOJE - dt.timedelta(days=119 - i)
    ymd = d.strftime("%Y%m%d")
    grava(f"{BASE}/data/output/2.2/Precipitation-2_2/{ymd[:4]}/{ymd[4:6]}/"
          f"INPE_FireRiskModel_2.2_Precipitation_{ymd}.nc",
          {"prec": (("time", "lat", "lon"),
                    rng.gamma(0.7, 4.0, (1, lat_p.size, lon_p.size)).astype(np.float32))},
          {"time": [np.datetime64(d.strftime("%Y-%m-%d"))],
           "lat": lat_p, "lon": lon_p})

# GFS: horários de previsão 24h, 3d e 7d12 (7d18 NÃO existe -> testa fallback)
horarios = ["2026080500", "2026080700", "2026081112"]
for hh in horarios:
    grava(f"{BASE}/data/output/2.2/GFS/netcdf/{MODELO}/GFS.PREV.PREC.{MODELO}.{hh}.nc",
          {"prec": (("time", "lat", "lon"),
                    rng.gamma(0.7, 4.0, (1, lat_p.size, lon_p.size)).astype(np.float32))},
          {"time": [np.datetime64("2026-08-05")], "lat": lat_p, "lon": lon_p})
    grava(f"{BASE}/data/output/2.2/GFS/netcdf/{MODELO}/GFS.PREV.TEMP2m.RH2m.{MODELO}.{hh}.nc",
          {"TEMP2m": (("time", "lat", "lon"),
                      rng.uniform(285, 310, (1, lat_p.size, lon_p.size)).astype(np.float32)),
           "RH2m": (("time", "lat", "lon"),
                    rng.uniform(20, 95, (1, lat_p.size, lon_p.size)).astype(np.float32))},
          {"time": [np.datetime64("2026-08-05")], "lat": lat_p, "lon": lon_p})

# Mapa de vegetação e topografia
grava(f"{BASE}/data/input/Veg_Map_2020/Merge_MapBiomas_V5_IGBP_C6_2019.nc",
      {"Band1": (("lat", "lon"),
                 rng.integers(0, 8, (lat_v.size, lon_v.size)).astype(np.int16))},
      {"lat": lat_v, "lon": lon_v})
grava(f"{BASE}/data/input/topografia/GeoTOPOAmericaSulCentral_V3.nc",
      {"Band1": (("lat", "lon"),
                 rng.uniform(0, 3000, (lat_v.size, lon_v.size)).astype(np.float32))},
      {"lat": lat_v, "lon": lon_v})

AQUI = os.path.dirname(os.path.abspath(__file__))


def roda(*extras):
    cmd = [sys.executable, os.path.join(AQUI, "rf_previsto.py"),
           "--base", BASE, "--data-final", DATA_FINAL, "--jobs", "2"] + list(extras)
    r = subprocess.run(cmd, capture_output=True, text=True)
    print(">>", " ".join(extras))
    print(r.stdout)
    if r.returncode != 0:
        print(r.stderr)
        raise SystemExit(f"rf_previsto.py falhou: {r.returncode}")
    return r


# ---------------------------------------------------------------------------
# 1. Lista de horizontes (24h e 3d) + fogograma
# ---------------------------------------------------------------------------
roda("--horizontes", "24h,3d", "--produto", "TESTE_LISTA", "--fogograma")

saidas = sorted(glob.glob(f"{BASE}/data/output/2.2/TESTE_LISTA/netcdf/{MODELO}/RF.PREV.*.nc"))
assert [os.path.basename(s) for s in saidas] == \
    ["RF.PREV.2026080500.nc", "RF.PREV.2026080700.nc"], saidas
tifs = sorted(glob.glob(f"{BASE}/data/output/2.2/TESTE_LISTA/tif/{MODELO}/*.tif"))
assert len(tifs) == 2, tifs
fogograma = f"{BASE}/data/output/2.2/fogograma/RF.PREV.TESTE_LISTA.{MODELO}.nc"
with xr.open_dataset(fogograma) as fg:
    assert fg["rbf"].shape[0] == 2
with xr.open_dataset(saidas[0]) as ds:
    assert str(ds["time"].values[0])[:13] == "2026-08-05T00"
    v = ds["rbf"].values
    assert np.nanmin(v) >= 0 and np.nanmax(v) <= 1
print("Teste 1 (lista + fogograma) ok")

# ---------------------------------------------------------------------------
# 2. Fallback do GFS: pede 7d18h (2026081118), que não existe; deve copiar 12 UTC
# ---------------------------------------------------------------------------
roda("--horizontes", "7d18h", "--produto", "TESTE_FALLBACK",
     "--rb-max", "0.8", "--fallback-gfs", "--sem-tif")

saida_fb = f"{BASE}/data/output/2.2/TESTE_FALLBACK/netcdf/{MODELO}/RF.PREV.2026081118.nc"
assert os.path.exists(saida_fb)
assert os.path.exists(f"{BASE}/data/output/2.2/GFS/netcdf/{MODELO}/"
                      f"GFS.PREV.PREC.{MODELO}.2026081118.nc")   # cópia criada
assert not glob.glob(f"{BASE}/data/output/2.2/TESTE_FALLBACK/tif/{MODELO}/*.tif")
print("Teste 2 (fallback GFS + --sem-tif + rb 0.8) ok")

# ---------------------------------------------------------------------------
# 3. Intervalo --de/--ate/--passo: 24h até 3d a cada 24h -> 3 previsões,
#    mas só existem GFS para 24h e 3d -> deve falhar com exit 1 no 2d
# ---------------------------------------------------------------------------
cmd = [sys.executable, os.path.join(AQUI, "rf_previsto.py"),
       "--base", BASE, "--data-final", DATA_FINAL, "--jobs", "2",
       "--horizontes", "2d", "--produto", "TESTE_FALHA"]
r = subprocess.run(cmd, capture_output=True, text=True)
assert r.returncode == 1 and "PROBLEMA - FALTAM ARQUIVOS" in r.stdout
print("Teste 3 (horizonte sem GFS -> exit 1) ok")

# ---------------------------------------------------------------------------
# 4. Intervalo válido: --de 24h --ate 3d --passo 48h -> 24h e 3d
# ---------------------------------------------------------------------------
roda("--de", "24h", "--ate", "3d", "--passo", "48h",
     "--produto", "TESTE_INTERVALO", "--sem-tif")
saidas4 = sorted(glob.glob(
    f"{BASE}/data/output/2.2/TESTE_INTERVALO/netcdf/{MODELO}/RF.PREV.*.nc"))
assert [os.path.basename(s) for s in saidas4] == \
    ["RF.PREV.2026080500.nc", "RF.PREV.2026080700.nc"], saidas4
print("Teste 4 (intervalo --de/--ate/--passo) ok")

# ---------------------------------------------------------------------------
# 5. Horizonte absoluto YYYYMMDDHH
# ---------------------------------------------------------------------------
roda("--horizontes", "2026080700", "--produto", "TESTE_ABS", "--sem-tif")
assert os.path.exists(
    f"{BASE}/data/output/2.2/TESTE_ABS/netcdf/{MODELO}/RF.PREV.2026080700.nc")
print("Teste 5 (horizonte absoluto) ok")

print()
print("TODOS OS TESTES DO SCRIPT GENERICO PASSARAM")
