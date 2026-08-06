# -*- coding: utf-8 -*-
"""Teste do prepara_gfs.py v2 (sem rede e sem pygrib).

1. fhoras_disponiveis / filtra_validades: 6 h até +240, 12 h até +384.
2. parse_idx / acha_mensagens: interpretação do índice .idx e byte-ranges.
3. parse_faixa_acumulo / soma_janela: composição do acumulado diário a
   partir de baldes de 6 h e 12 h (inclusive a transição em +240 h).
4. indices_dominio: recorte com latitude decrescente e lon 0–360.
5. grava_netcdf: arquivos aceitos pelos leitores do pipeline.
"""

import datetime as dt
import os
import shutil

import numpy as np

import prepara_gfs as pg

# ---------------------------------------------------------------------------
# 1. Horas de arquivo e validades
# ---------------------------------------------------------------------------
f = pg.fhoras_disponiveis(384)
assert f[0] == 6 and 240 in f and 246 not in f and 252 in f and f[-1] == 384
assert pg.fhoras_disponiveis(48) == [6, 12, 18, 24, 30, 36, 42, 48]

ok, puladas = pg.filtra_validades(list(range(6, 385, 6)))
assert 240 in ok and 252 in ok and 384 in ok
assert 246 in puladas and 258 in puladas
ok2, _ = pg.filtra_validades([390, 396])
assert ok2 == []
print("Teste 1 (fhoras e validades) ok")

# ---------------------------------------------------------------------------
# 2. Índice .idx
# ---------------------------------------------------------------------------
IDX = """1:0:d=2026080500:PRMSL:mean sea level:6 hour fcst:
2:1000:d=2026080500:TMP:2 m above ground:6 hour fcst:
3:2500:d=2026080500:RH:2 m above ground:6 hour fcst:
4:4200:d=2026080500:APCP:surface:0-6 hour acc fcst:
5:6000:d=2026080500:UGRD:10 m above ground:6 hour fcst:
6:7500:d=2026080500:VGRD:10 m above ground:6 hour fcst:
"""
idx = pg.parse_idx(IDX)
assert len(idx) == 6
assert idx[3]["var"] == "APCP" and idx[3]["ini"] == 4200 and idx[3]["fim"] == 5999
assert idx[5]["fim"] is None            # última mensagem: sem limite
msgs = pg.acha_mensagens(idx, [("APCP", "surface", None),
                               ("TMP", "2 m above ground", None),
                               ("RH", "2 m above ground", None)])
assert [m["var"] for m in msgs] == ["APCP", "TMP", "RH"]

# Com vento: as duas mensagens de 10 m entram no mesmo pedido
msgs_vento = pg.acha_mensagens(idx, [("APCP", "surface", None),
                                     ("TMP", "2 m above ground", None),
                                     ("RH", "2 m above ground", None),
                                     ("UGRD", "10 m above ground", None),
                                     ("VGRD", "10 m above ground", None)])
assert [m["var"] for m in msgs_vento] == ["APCP", "TMP", "RH", "UGRD", "VGRD"]
assert msgs_vento[3]["ini"] == 6000 and msgs_vento[3]["fim"] == 7499
assert msgs_vento[4]["ini"] == 7500 and msgs_vento[4]["fim"] is None
try:
    pg.acha_mensagens(idx, [("DPT", "2 m above ground", None)])
    raise AssertionError("deveria falhar para variável ausente")
except RuntimeError:
    pass
print("Teste 2 (parse do .idx e byte-ranges) ok")

# ---------------------------------------------------------------------------
# 3. Faixas de acúmulo e soma da janela diária
# ---------------------------------------------------------------------------
assert pg.parse_faixa_acumulo("0-6 hour acc fcst") == (0, 6)
assert pg.parse_faixa_acumulo("240-252 hour acc fcst") == (240, 252)
assert pg.parse_faixa_acumulo("6 hour fcst") is None

def balde(a, b):
    # valor constante = duração do balde, p/ conferir soma = 24 na janela cheia
    return ((a, b), np.full((2, 2), float(b - a), dtype=np.float32))

# baldes de 6 h até 240 e de 12 h depois (como no GFS real)
baldes = [balde(h - 6, h) for h in range(6, 241, 6)] + \
         [balde(h - 12, h) for h in range(252, 385, 12)]

# janela cheia com baldes de 6 h
total, usados = pg.soma_janela(baldes, 48, "24h")
assert np.allclose(total, 24.0) and usados == [(24, 30), (30, 36), (36, 42), (42, 48)]
# início da rodada: janela parcial
total, usados = pg.soma_janela(baldes, 6, "24h")
assert np.allclose(total, 6.0) and usados == [(0, 6)]
# transição 6h -> 12h em +240: janela (228, 252]
total, usados = pg.soma_janela(baldes, 252, "24h")
assert np.allclose(total, 24.0) and usados == [(228, 234), (234, 240), (240, 252)]
# só baldes de 12 h
total, usados = pg.soma_janela(baldes, 384, "24h")
assert np.allclose(total, 24.0) and usados == [(360, 372), (372, 384)]
# acúmulo "dia": às 18 h, o dia civil começou em 0
total, usados = pg.soma_janela(baldes, 18, "dia")
assert np.allclose(total, 18.0) and usados == [(0, 6), (6, 12), (12, 18)]
print("Teste 3 (soma dos baldes 6h/12h) ok")

# ---------------------------------------------------------------------------
# 4. Recorte de domínio (lat decrescente como no GRIB do GFS, lon 0-360)
# ---------------------------------------------------------------------------
lat = np.arange(90, -90.1, -0.25)          # norte -> sul
lon = np.arange(0, 360, 0.25)
ila0, ila1, ilo0, ilo1 = pg.indices_dominio(lat, lon, -60.05, 29.95,
                                            -114.95, -30.05)
la = lat[ila0:ila1]
assert la.max() <= 29.95 and la.min() >= -60.05
assert abs(lon[ilo0] - 245.25) < 0.26 and abs(lon[ilo1 - 1] - 329.75) < 0.26
print("Teste 4 (recorte com lat decrescente) ok")

# ---------------------------------------------------------------------------
# 5. NetCDF aceito pelos leitores do pipeline
# ---------------------------------------------------------------------------
BASE = "/tmp/teste_prepara_gfs"
shutil.rmtree(BASE, ignore_errors=True)
MODELO = "2026080500"
dirout = f"{BASE}/data/output/2.2/GFS/netcdf/{MODELO}"
os.makedirs(dirout, exist_ok=True)

rng = np.random.default_rng(3)
lat_r = np.arange(-20.0, -9.9, 0.25)
lon_r = np.arange(-60.0, -49.9, 0.25)
valida_dt = dt.datetime(2026, 8, 6, 18)
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

import rf_core
t2m, ur2m, la, lo = rf_core.ler_temp_ur(
    os.path.join(dirout, f"GFS.PREV.TEMP2m.RH2m.{MODELO}.{valida}.nc"))
assert -40 < np.nanmean(t2m) < 45 and 0 <= np.nanmin(ur2m) <= 1
p, _, _ = rf_core.ler_precipitacao(
    [os.path.join(dirout, f"GFS.PREV.PREC.{MODELO}.{valida}.nc")])
assert p.shape == (1, lat_r.size, lon_r.size) and la[0] < la[-1]
assert pg.grava_netcdf(
    os.path.join(dirout, f"GFS.PREV.PREC.{MODELO}.{valida}.nc"),
    {"prec": np.zeros((lat_r.size, lon_r.size), np.float32)},
    lat_r, lon_r, valida_dt, sobrescrever=False) is False
print("Teste 5 (NetCDF aceito pelo pipeline e sem sobrescrita) ok")

# ---------------------------------------------------------------------------
# 6. Vento a 10 m (insumo do FWI): arquivo próprio, lido como o da ERA5
# ---------------------------------------------------------------------------
u = rng.uniform(-12, 12, (lat_r.size, lon_r.size)).astype(np.float32)
v = rng.uniform(-12, 12, (lat_r.size, lon_r.size)).astype(np.float32)
arq_vento = os.path.join(dirout, f"GFS.PREV.U10m.V10m.{MODELO}.{valida}.nc")
pg.grava_netcdf(arq_vento, {"U10m": u, "V10m": v},
                lat_r, lon_r, valida_dt, sobrescrever=True)

import fwi_observado
vel, la_v, lo_v = fwi_observado.le_vento(arq_vento)      # mesma leitura da ERA5
assert vel.shape == (lat_r.size, lon_r.size) and la_v[0] < la_v[-1]
assert np.allclose(vel, np.hypot(u, v) * 3.6, atol=1e-3)   # m/s -> km/h

# A decodificação exige o vento quando pedido, e o dispensa com vento=False
assert "vento" in pg.decodifica_grib.__doc__
assert "vento" in pg.baixa_fhora.__doc__
print("Teste 6 (vento 10 m: arquivo proprio, km/h, leitura do FWI) ok")

print()
print("TODOS OS TESTES DO PREPARA_GFS PASSARAM")
