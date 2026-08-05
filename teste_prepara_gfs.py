# -*- coding: utf-8 -*-
"""Teste das funções do prepara_gfs.py (sem rede) + integração com o RF.

1. horas_dos_baldes / soma_baldes: composição correta do acumulado diário
   a partir dos baldes de 6 h do GFS.
2. indices_dominio: conversão -180..180 -> 0..360 e recorte.
3. grava_netcdf + leitura pelo rf_fontes/rf_core: os arquivos gerados são
   aceitos pelo caminho legado do rf_previsto.py (GFS.PREV.*).
"""

import datetime as dt
import os
import shutil

import numpy as np

import prepara_gfs as pg

# ---------------------------------------------------------------------------
# 1. Baldes de 6 h -> acumulado diário
# ---------------------------------------------------------------------------

# Últimas 24 h de uma validade "cheia": 4 baldes
assert pg.horas_dos_baldes(48, "24h") == [30, 36, 42, 48]
assert pg.horas_dos_baldes(96, "24h") == [78, 84, 90, 96]
# Início da rodada: só o que existe
assert pg.horas_dos_baldes(6, "24h") == [6]
assert pg.horas_dos_baldes(18, "24h") == [6, 12, 18]
# Acúmulo "dia" (00 UTC do dia da validade)
assert pg.horas_dos_baldes(18, "dia") == [6, 12, 18]
assert pg.horas_dos_baldes(24, "dia") == [6, 12, 18, 24]
assert pg.horas_dos_baldes(30, "dia") == [30]
assert pg.horas_dos_baldes(42, "dia") == [30, 36, 42]
try:
    pg.horas_dos_baldes(15)
    raise AssertionError("deveria rejeitar validade não múltipla de 6")
except ValueError:
    pass
print("Teste 1a (horas dos baldes) ok")

# soma_baldes com campo sintético: valor do balde = hora do balde
horas_eixo = np.arange(6, 121, 6)
apcp = np.stack([np.full((3, 4), float(h)) for h in horas_eixo])
dia = pg.soma_baldes(apcp, horas_eixo, 48, "24h")
assert np.allclose(dia, 30 + 36 + 42 + 48)
dia = pg.soma_baldes(apcp, horas_eixo, 6, "24h")
assert np.allclose(dia, 6)
print("Teste 1b (soma dos baldes) ok")

# ---------------------------------------------------------------------------
# 2. Recorte de domínio (lon 0-360)
# ---------------------------------------------------------------------------
lat = np.arange(-90, 90.1, 0.25)
lon = np.arange(0, 360, 0.25)
ila0, ila1, ilo0, ilo1 = pg.indices_dominio(lat, lon, -60.05, 29.95,
                                            -114.95, -30.05)
assert -60.05 <= lat[ila0] and lat[ila1 - 1] <= 29.95
# -114.95 -> 245.05 ; -30.05 -> 329.95
assert abs(lon[ilo0] - 245.25) < 0.26 and abs(lon[ilo1 - 1] - 329.75) < 0.26
print("Teste 2 (recorte de domínio) ok")

# ---------------------------------------------------------------------------
# 3. Arquivos gerados são aceitos pelo pipeline (caminho legado do GFS)
# ---------------------------------------------------------------------------
BASE = "/tmp/teste_prepara_gfs"
shutil.rmtree(BASE, ignore_errors=True)
MODELO = "2026080400"
dirout = f"{BASE}/data/output/2.2/GFS/netcdf/{MODELO}"
os.makedirs(dirout, exist_ok=True)

rng = np.random.default_rng(3)
lat_r = np.arange(-20.0, -9.9, 0.25)
lon_r = np.arange(-60.0, -49.9, 0.25)
valida_dt = dt.datetime(2026, 8, 5, 18)
valida = valida_dt.strftime("%Y%m%d%H")

pg.grava_netcdf(
    os.path.join(dirout, f"GFS.PREV.PREC.{MODELO}.{valida}.nc"),
    {"prec": rng.gamma(0.7, 4.0, (lat_r.size, lon_r.size)).astype(np.float32)},
    lat_r, lon_r, valida_dt, sobrescrever=True)
pg.grava_netcdf(
    os.path.join(dirout, f"GFS.PREV.TEMP2m.RH2m.{MODELO}.{valida}.nc"),
    {"TEMP2m": rng.uniform(285, 310, (lat_r.size, lon_r.size)).astype(np.float32),
     "RH2m": rng.uniform(20, 95, (lat_r.size, lon_r.size)).astype(np.float32)},
    lat_r, lon_r, valida_dt, sobrescrever=True)

# Leitura pelos leitores do pipeline
import rf_core
t2m, ur2m, la, lo = rf_core.ler_temp_ur(
    os.path.join(dirout, f"GFS.PREV.TEMP2m.RH2m.{MODELO}.{valida}.nc"))
assert -40 < np.nanmean(t2m) < 45 and 0 <= np.nanmin(ur2m) <= 1
p, la2, lo2 = rf_core.ler_precipitacao(
    [os.path.join(dirout, f"GFS.PREV.PREC.{MODELO}.{valida}.nc")])
assert p.shape == (1, lat_r.size, lon_r.size)
assert la[0] < la[-1]
print("Teste 3 (NetCDF aceito pelos leitores do pipeline) ok")

# grava_netcdf respeita arquivos existentes sem --sobrescrever
assert pg.grava_netcdf(
    os.path.join(dirout, f"GFS.PREV.PREC.{MODELO}.{valida}.nc"),
    {"prec": np.zeros((lat_r.size, lon_r.size), np.float32)},
    lat_r, lon_r, valida_dt, sobrescrever=False) is False
print("Teste 4 (não sobrescreve sem --sobrescrever) ok")

print()
print("TODOS OS TESTES DO PREPARA_GFS PASSARAM")
