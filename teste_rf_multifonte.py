# -*- coding: utf-8 -*-
"""Teste de ponta a ponta do modo multifonte do rf_previsto.py.

Cenários:
  1. Eta (freq 1d), horizonte de 13 meses — verifica a montagem da série
     mista IMERG+previsão e o alcance longo.
  2. BESM (freq 12h) — verifica a agregação sub-diária: dois acúmulos de
     12 h devem somar exatamente o acumulado diário.
  3. Horizonte além do alcance da fonte (gfs 16 dias) — deve falhar.
  4. Fonte configurada via JSON (--config-fontes) com freq 1h.
  5. Validação numérica: com os MESMOS campos, o resultado multifonte
     deve bater com o cálculo direto do rf_core.
"""

import datetime as dt
import glob
import json
import os
import shutil
import subprocess
import sys

import numpy as np
import xarray as xr

BASE = "/tmp/teste_multifonte"
DATA_FINAL = "20260804"
HOJE = dt.datetime.strptime(DATA_FINAL, "%Y%m%d")
MODELO = DATA_FINAL + "00"

shutil.rmtree(BASE, ignore_errors=True)
rng = np.random.default_rng(11)

lat_p = np.arange(-20.0, -9.9, 0.5)      # grade IMERG do teste
lon_p = np.arange(-60.0, -49.9, 0.5)
lat_m = np.arange(-20.0, -9.9, 1.0)      # grade da fonte (mais grossa)
lon_m = np.arange(-60.0, -49.9, 1.0)
lat_v = np.arange(-20.0, -10.0 + 1e-9, 0.1)
lon_v = np.arange(-60.0, -50.0 + 1e-9, 0.1)


def grava(caminho, variaveis, coords):
    os.makedirs(os.path.dirname(caminho), exist_ok=True)
    xr.Dataset(variaveis, coords=coords).to_netcdf(caminho)


def campo(shape_lat, shape_lon, escala=4.0):
    return rng.gamma(0.7, escala, (1, shape_lat, shape_lon)).astype(np.float32)


# --------------------------------------------------------------------------
# IMERG observado: 119 dias antes da rodada
# --------------------------------------------------------------------------
for i in range(119):
    d = HOJE - dt.timedelta(days=119 - i)
    ymd = d.strftime("%Y%m%d")
    grava(f"{BASE}/data/output/2.2/Precipitation-2_2/{ymd[:4]}/{ymd[4:6]}/"
          f"INPE_FireRiskModel_2.2_Precipitation_{ymd}.nc",
          {"prec": (("time", "lat", "lon"), campo(lat_p.size, lon_p.size))},
          {"time": [np.datetime64(d.strftime("%Y-%m-%d"))],
           "lat": lat_p, "lon": lon_p})

# --------------------------------------------------------------------------
# Eta: previsão diária por 13 meses (freq 1d, acumulado do próprio dia)
# na grade mais grossa; T/UR no horário previsto
# --------------------------------------------------------------------------
VALIDA_13M = dt.datetime(2027, 9, 4)     # 2026-08-04 + 13 meses
dia = HOJE
while dia <= VALIDA_13M:            # inclui o dia da própria data válida
    fim = dia + dt.timedelta(days=1)     # arquivo válido no fim do dia
    grava(f"{BASE}/data/output/2.2/ETA/netcdf/{MODELO}/"
          f"ETA.PREV.PREC.{MODELO}.{fim:%Y%m%d%H}.nc",
          {"prec": (("time", "lat", "lon"), campo(lat_m.size, lon_m.size))},
          {"time": [np.datetime64(fim.strftime("%Y-%m-%dT%H"))],
           "lat": lat_m, "lon": lon_m})
    dia = fim

grava(f"{BASE}/data/output/2.2/ETA/netcdf/{MODELO}/"
      f"ETA.PREV.TEMP2m.RH2m.{MODELO}.{VALIDA_13M:%Y%m%d%H}.nc",
      {"TEMP2m": (("time", "lat", "lon"),
                  rng.uniform(285, 310, (1, lat_m.size, lon_m.size)).astype(np.float32)),
       "RH2m": (("time", "lat", "lon"),
                rng.uniform(20, 95, (1, lat_m.size, lon_m.size)).astype(np.float32))},
      {"time": [np.datetime64(VALIDA_13M.strftime("%Y-%m-%dT%H"))],
       "lat": lat_m, "lon": lon_m})

# --------------------------------------------------------------------------
# BESM: acúmulos de 12 h por 40 dias (freq 12h)
# --------------------------------------------------------------------------
VALIDA_BESM = HOJE + dt.timedelta(days=30)
t = HOJE
while t < VALIDA_BESM + dt.timedelta(days=1):
    fim = t + dt.timedelta(hours=12)
    grava(f"{BASE}/data/output/2.2/BESM/netcdf/{MODELO}/"
          f"BESM.PREV.PREC.{MODELO}.{fim:%Y%m%d%H}.nc",
          {"prec": (("time", "lat", "lon"), campo(lat_m.size, lon_m.size, 2.0))},
          {"time": [np.datetime64(fim.strftime("%Y-%m-%dT%H"))],
           "lat": lat_m, "lon": lon_m})
    t = fim

grava(f"{BASE}/data/output/2.2/BESM/netcdf/{MODELO}/"
      f"BESM.PREV.TEMP2m.RH2m.{MODELO}.{VALIDA_BESM:%Y%m%d%H}.nc",
      {"TEMP2m": (("time", "lat", "lon"),
                  rng.uniform(285, 310, (1, lat_m.size, lon_m.size)).astype(np.float32)),
       "RH2m": (("time", "lat", "lon"),
                rng.uniform(20, 95, (1, lat_m.size, lon_m.size)).astype(np.float32))},
      {"time": [np.datetime64(VALIDA_BESM.strftime("%Y-%m-%dT%H"))],
       "lat": lat_m, "lon": lon_m})

# --------------------------------------------------------------------------
# Mapa de vegetação e topografia (1 km)
# --------------------------------------------------------------------------
veg = rng.integers(0, 8, (lat_v.size, lon_v.size)).astype(np.int16)
grava(f"{BASE}/data/input/Veg_Map_2020/Merge_MapBiomas_V5_IGBP_C6_2019.nc",
      {"Band1": (("lat", "lon"), veg)}, {"lat": lat_v, "lon": lon_v})
grava(f"{BASE}/data/input/topografia/GeoTOPOAmericaSulCentral_V3.nc",
      {"Band1": (("lat", "lon"),
                 rng.uniform(0, 3000, (lat_v.size, lon_v.size)).astype(np.float32))},
      {"lat": lat_v, "lon": lon_v})

AQUI = os.path.dirname(os.path.abspath(__file__))

# Fonte sintética "besm12" (por_tempo, 12h) — o "besm" padrão agora segue a
# convenção REAL do BESM T062 (layout serie), testada em teste_besm_real.py.
CONFIG_12H = {
    "besm12": {
        "subdir": "BESM/netcdf/{modelo}",
        "layout": "por_tempo",
        "padrao_prec": "BESM.PREV.PREC.{modelo}.{valida}.nc",
        "padrao_temp_ur": "BESM.PREV.TEMP2m.RH2m.{modelo}.{valida}.nc",
        "var_prec": "prec", "var_temp": "TEMP2m", "var_ur": "RH2m",
        "freq_prec": "12h", "tipo_acumulo": "intervalo",
        "unidade_temp": "K", "unidade_ur": "%",
        "horizonte_max_dias": 396,
    }
}
os.makedirs(BASE, exist_ok=True)
with open(f"{BASE}/fontes12.json", "w") as _f:
    json.dump(CONFIG_12H, _f)


def roda(*extras, deve_falhar=False):
    cmd = [sys.executable, os.path.join(AQUI, "rf_previsto.py"),
           "--base", BASE, "--data-final", DATA_FINAL, "--jobs", "2",
           "--sem-tif"] + list(extras)
    r = subprocess.run(cmd, capture_output=True, text=True)
    print(">>", " ".join(extras))
    if deve_falhar:
        assert r.returncode != 0, "deveria ter falhado"
        return r
    if r.returncode != 0:
        print(r.stdout)
        print(r.stderr)
        raise SystemExit(f"rf_previsto.py falhou: {r.returncode}")
    return r


# ==========================================================================
# 1. Eta, 13 meses
# ==========================================================================
roda("--fonte", "eta", "--horizontes", "13m")
saida_eta = (f"{BASE}/data/output/2.2/RF_PREV_ETA/netcdf/{MODELO}/"
             f"RF.PREV.{VALIDA_13M:%Y%m%d%H}.nc")
assert os.path.exists(saida_eta), saida_eta
with xr.open_dataset(saida_eta) as ds:
    assert str(ds["time"].values[0])[:10] == "2027-09-04"
    v = ds["rbf"].values
    assert ds["rbf"].shape == (1, lat_v.size, lon_v.size)
    assert np.nanmin(v) >= 0 and np.nanmax(v) <= 1
    assert np.all(np.isnan(v[0][veg == 0]))
print("Teste 1 (Eta, 13 meses, serie mista) ok")

# ==========================================================================
# 2. BESM 12h: agregação sub-diária correta
# ==========================================================================
roda("--fonte", "besm12", "--horizontes", "30d",
     "--config-fontes", f"{BASE}/fontes12.json")
saida_besm = (f"{BASE}/data/output/2.2/RF_PREV_BESM12/netcdf/{MODELO}/"
              f"RF.PREV.{VALIDA_BESM:%Y%m%d%H}.nc")
assert os.path.exists(saida_besm)

# agregação: soma dos 2 campos de 12 h de um dia == diário calculado
sys.path.insert(0, AQUI)
import rf_fontes  # noqa: E402

rf_fontes.carrega_fontes_json(f"{BASE}/fontes12.json")
fonte_besm = rf_fontes.FONTES["besm12"]
dia_teste = HOJE + dt.timedelta(days=3)
diario = rf_fontes.precip_diaria_prevista(
    fonte_besm, f"{BASE}/data/output/2.2/BESM/netcdf/{MODELO}", MODELO,
    dia_teste, lat_m, lon_m)
soma_manual = None
for h in (12, 24):
    arq = (f"{BASE}/data/output/2.2/BESM/netcdf/{MODELO}/BESM.PREV.PREC."
           f"{MODELO}.{dia_teste + dt.timedelta(hours=h):%Y%m%d%H}.nc")
    with xr.open_dataset(arq) as d:
        c = d["prec"].values[0]
    soma_manual = c if soma_manual is None else soma_manual + c
assert np.allclose(diario, soma_manual, atol=1e-5)
print("Teste 2 (BESM 12h, agregacao diaria) ok")

# ==========================================================================
# 3. Alcance da fonte: gfs com 30 dias deve falhar na validação
# ==========================================================================
r = roda("--fonte", "gfs", "--horizontes", "30d", deve_falhar=True)
assert "excede o alcance" in (r.stdout + r.stderr)
print("Teste 3 (alcance da fonte validado) ok")

# ==========================================================================
# 4. Fonte via JSON: BESM reconfigurado para freq 1h (3 dias de arquivos)
# ==========================================================================
VALIDA_1H = HOJE + dt.timedelta(days=2)
t = HOJE
while t < VALIDA_1H + dt.timedelta(days=1):
    fim = t + dt.timedelta(hours=1)
    grava(f"{BASE}/data/output/2.2/HORARIO/netcdf/{MODELO}/"
          f"HOR.PREV.PREC.{MODELO}.{fim:%Y%m%d%H}.nc",
          {"chuva": (("time", "lat", "lon"), campo(lat_m.size, lon_m.size, 0.3))},
          {"time": [np.datetime64(fim.strftime("%Y-%m-%dT%H"))],
           "lat": lat_m, "lon": lon_m})
    t = fim
grava(f"{BASE}/data/output/2.2/HORARIO/netcdf/{MODELO}/"
      f"HOR.PREV.T.UR.{MODELO}.{VALIDA_1H:%Y%m%d%H}.nc",
      {"t2": (("time", "lat", "lon"),
              rng.uniform(12, 37, (1, lat_m.size, lon_m.size)).astype(np.float32)),
       "ur2": (("time", "lat", "lon"),
               rng.uniform(0.2, 0.95, (1, lat_m.size, lon_m.size)).astype(np.float32))},
      {"time": [np.datetime64(VALIDA_1H.strftime("%Y-%m-%dT%H"))],
       "lat": lat_m, "lon": lon_m})

config = {
    "horario": {
        "subdir": "HORARIO/netcdf/{modelo}",
        "padrao_prec": "HOR.PREV.PREC.{modelo}.{valida}.nc",
        "padrao_temp_ur": "HOR.PREV.T.UR.{modelo}.{valida}.nc",
        "var_prec": "chuva", "var_temp": "t2", "var_ur": "ur2",
        "freq_prec": "1h", "tipo_acumulo": "intervalo",
        "unidade_temp": "C", "unidade_ur": "frac",
        "horizonte_max_dias": 3,
    }
}
with open(f"{BASE}/fontes.json", "w") as f:
    json.dump(config, f)

roda("--fonte", "horario", "--horizontes", "2d",
     "--config-fontes", f"{BASE}/fontes.json")
assert os.path.exists(
    f"{BASE}/data/output/2.2/RF_PREV_HORARIO/netcdf/{MODELO}/"
    f"RF.PREV.{VALIDA_1H:%Y%m%d%H}.nc")
print("Teste 4 (fonte via JSON, freq 1h, unidades C/frac) ok")

# ==========================================================================
# 5. Validação numérica: multifonte vs cálculo direto do rf_core
# ==========================================================================
import rf_core  # noqa: E402

fonte_eta = rf_fontes.FONTES["eta"]
dirin_eta = f"{BASE}/data/output/2.2/ETA/netcdf/{MODELO}"
precip, la, lo, _ = rf_fontes.serie_precipitacao(
    fonte_eta, dirin_eta, f"{BASE}/data/output/2.2/Precipitation-2_2",
    MODELO, f"{VALIDA_13M:%Y%m%d%H}", log=lambda *a: None)
t2m, ur2m, lam, lom = rf_fontes.temp_ur_previstos(
    fonte_eta, dirin_eta, MODELO, f"{VALIDA_13M:%Y%m%d%H}")

ref = f"{BASE}/ref.nc"
rf_core.calcula_risco_fogo_dados(
    precip_invertida=precip[::-1], lat_prec=la, lon_prec=lo,
    t2m=t2m, ur2m=ur2m, lat_met=lam, lon_met=lom,
    arquivo_mapa_veg=f"{BASE}/data/input/Veg_Map_2020/Merge_MapBiomas_V5_IGBP_C6_2019.nc",
    arquivo_topografia=f"{BASE}/data/input/topografia/GeoTOPOAmericaSulCentral_V3.nc",
    arquivo_saida=ref, data_previsao=f"{VALIDA_13M:%Y%m%d%H}",
    rb_maximo=0.9, log=lambda *a: None)

with xr.open_dataset(saida_eta) as a, xr.open_dataset(ref) as b:
    va = np.nan_to_num(a["rbf"].values, nan=-999)
    vb = np.nan_to_num(b["rbf"].values, nan=-999)
    assert np.allclose(va, vb), "resultado multifonte difere do rf_core direto"
print("Teste 5 (equivalencia numerica) ok")

# Série de 13 meses: a janela de 120 dias é toda POSTERIOR à rodada, logo
# não entra IMERG e a grade de referência é a da própria fonte.
assert precip.shape == (120, lat_m.size, lon_m.size)

# Já para um horizonte curto (30 dias), a janela mistura ~90 dias de IMERG
# com ~30 de previsão, e a grade de referência é a do IMERG (mais fina).
precip30, la30, lo30, _ = rf_fontes.serie_precipitacao(
    fonte_besm, f"{BASE}/data/output/2.2/BESM/netcdf/{MODELO}",
    f"{BASE}/data/output/2.2/Precipitation-2_2", MODELO,
    f"{VALIDA_BESM:%Y%m%d%H}", log=lambda *a: None)
assert precip30.shape == (120, lat_p.size, lon_p.size)
print("Serie mista: grades de referencia corretas (fonte no 13m, IMERG no 30d) ok")

print()
print("TODOS OS TESTES MULTIFONTE PASSARAM")
