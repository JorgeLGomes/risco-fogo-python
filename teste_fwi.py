# -*- coding: utf-8 -*-
"""Validação do motor FWI (fwi_core.py) e do fwi_observado.py.

Três níveis:
  1. Tabela de referência do sistema canadense (inclui o exemplo clássico
     de Van Wagner & Pickett 1985: T=17 °C, UR=42 %, vento=25 km/h,
     chuva=0, FFMC=85, DMC=6, DC=15 -> FFMC 87,7 · DMC 8,5 · DC 19,0 ·
     ISI 10,9 · BUI 8,5 · FWI 10,1);
  2. Validação cruzada contra o xclim (implementação de referência do
     CFFWIS), quando instalado — pulada se ausente;
  3. Propriedades físicas e teste de ponta a ponta do fwi_observado.py
     (spin-up, continuidade do estado salvo/retomado, agregações).
"""

import datetime as dt
import os
import shutil
import subprocess
import sys
import tempfile

import numpy as np
import xarray as xr

import fwi_core
import rf_config

TMP = tempfile.mkdtemp(prefix="teste_fwi_")

# t, ur, vento, chuva, ffmc0, dmc0, dc0, mes, lat -> FFMC, DMC, DC, ISI, BUI, FWI
REFERENCIA = [
    ((17.0, 42.0, 25.0, 0.0, 85.0, 6.0, 15.0, 4, 45.0),
     (87.69298, 8.545051, 19.014, 10.853661, 8.490427, 10.096371)),
    ((30.0, 25.0, 10.0, 0.0, 85.0, 6.0, 15.0, 8, -10.0),
     (93.053334, 9.97598, 21.599, 10.942306, 9.908152, 10.873955)),
    ((28.0, 80.0, 5.0, 12.0, 90.0, 40.0, 300.0, 1, -15.0),
     (48.999042, 19.695137, 271.571673, 0.18626, 33.344655, 0.236238)),
    ((35.0, 15.0, 30.0, 0.0, 92.0, 120.0, 700.0, 9, -20.0),
     (96.82472, 125.172448, 706.004, 50.264429, 173.460012, 101.549228)),
    ((5.0, 95.0, 2.0, 3.0, 60.0, 3.0, 10.0, 6, -30.0),
     (35.110636, 1.475289, 8.149182, 0.013784, 2.031256, 0.004288)),
    ((-5.0, 70.0, 15.0, 0.0, 80.0, 10.0, 50.0, 7, -35.0),
     (80.06362, 10.0, 50.0, 2.437679, 13.333333, 2.923564)),
    ((22.0, 55.0, 0.0, 1.0, 85.0, 33.0, 400.0, 12, 0.0),
     (80.704861, 34.771932, 405.159, 1.226581, 57.25861, 4.03913)),
    ((40.0, 5.0, 50.0, 0.5, 101.0, 200.0, 900.0, 10, -25.0),
     (100.613722, 206.951416, 908.154, 226.05171, 263.682169, 239.103464)),
]


def teste_referencia():
    for entrada, esperado in REFERENCIA:
        t, ur, vento, chuva, f0, p0, d0, mes, lat = entrada
        lat_a = np.array([[lat]])
        f = fwi_core.ffmc(t, ur, vento, chuva, f0)
        p = fwi_core.dmc(t, ur, chuva, mes, lat_a, p0)
        d = fwi_core.dc(t, chuva, mes, lat_a, d0)
        r = fwi_core.isi(vento, f)
        u = fwi_core.bui(p, d)
        s = fwi_core.fwi(r, u)
        obtido = tuple(float(np.asarray(x).ravel()[0])
                       for x in (f, p, d, r, u, s))
        for nome, a, b in zip(("FFMC", "DMC", "DC", "ISI", "BUI", "FWI"),
                              obtido, esperado):
            assert abs(a - b) < 1e-4, (nome, entrada, a, b)
    print(f"Tabela de referencia do CFFWIS ok ({len(REFERENCIA)} casos, "
          f"inclui o exemplo classico de Van Wagner)")


def teste_xclim():
    try:
        from xclim.indices.fire import _cffwis as X
    except ImportError:
        print("Validacao cruzada com xclim: PULADA (xclim nao instalado)")
        return

    rng = np.random.default_rng(2026)
    n = 2000
    t = np.concatenate([rng.uniform(-15, 45, n), [-2.8, -1.1, 0, 21.1, 50]])
    h = np.concatenate([rng.uniform(1, 100, n), [0, 50, 100, 99.9, 1]])
    w = np.concatenate([rng.uniform(0, 60, n), [0, 0, 100, 5, 5]])
    p = np.concatenate([np.where(rng.random(n) < 0.4,
                                 rng.gamma(1.2, 6.0, n), 0.0),
                        [0, 0.5, 1.5, 2.8, 200]])
    f0 = np.concatenate([rng.uniform(0, 101, n), [0, 85, 101, 50, 85]])
    p0 = np.concatenate([rng.uniform(0, 200, n), [0, 33, 65, 6, 300]])
    d0 = np.concatenate([rng.uniform(0, 900, n), [0, 15, 400, 800, 1200]])

    ref = np.array([X._fine_fuel_moisture_code(a, b, c, d, e)
                    for a, b, c, d, e in zip(t, p, w, h, f0)])
    assert np.nanmax(np.abs(ref - fwi_core.ffmc(t, h, w, p, f0))) < 1e-9

    for lat in (-35.0, -20.0, -5.0, 20.0, 45.0):
        for mes in (1, 4, 7, 10):
            lat_a = np.full(t.shape, lat)
            ref_dmc = np.array([X._duff_moisture_code(a, b, c, mes, lat, e)
                                for a, b, c, e in zip(t, p, h, p0)])
            ref_dc = np.array([X._drought_code(a, b, mes, lat, e)
                               for a, b, e in zip(t, p, d0)])
            assert np.nanmax(np.abs(
                ref_dmc - fwi_core.dmc(t, h, p, mes, lat_a, p0))) < 1e-9
            assert np.nanmax(np.abs(
                ref_dc - fwi_core.dc(t, p, mes, lat_a, d0))) < 1e-9

    isi_ref = np.asarray(X.initial_spread_index(w, ref))
    bui_ref = np.asarray(X.build_up_index(p0, d0))
    assert np.nanmax(np.abs(isi_ref - fwi_core.isi(w, ref))) < 1e-9
    assert np.nanmax(np.abs(bui_ref - fwi_core.bui(p0, d0))) < 1e-9
    fwi_ref = np.asarray(X.fire_weather_index(isi_ref, bui_ref))
    assert np.nanmax(np.abs(fwi_ref - fwi_core.fwi(isi_ref, bui_ref))) < 1e-9
    print("Validacao cruzada com xclim ok (FFMC, DMC, DC, ISI, BUI, FWI; "
          "5 faixas de latitude x 4 meses)")


def teste_propriedades():
    lat = np.array([[-10.0]])
    # Mais seco e mais quente -> FFMC maior
    f_seco = fwi_core.ffmc(35.0, 15.0, 10.0, 0.0, 85.0)
    f_umido = fwi_core.ffmc(20.0, 90.0, 10.0, 0.0, 85.0)
    assert f_seco > f_umido

    # Chuva reduz o FFMC e o DC
    assert fwi_core.ffmc(30, 40, 10, 20.0, 90.0) < \
        fwi_core.ffmc(30, 40, 10, 0.0, 90.0)
    assert fwi_core.dc(30, 30.0, 8, lat, 500.0) < \
        fwi_core.dc(30, 0.0, 8, lat, 500.0)

    # Vento aumenta o ISI e o FWI
    assert fwi_core.isi(40.0, 90.0) > fwi_core.isi(5.0, 90.0)

    # Hemisférios opostos: em julho o fator de dia do DC é negativo no HS
    # (inverno) e positivo no HN (verão)
    assert fwi_core.fator_dia_luz(np.array([-20.0]), 7)[0] < 0
    assert fwi_core.fator_dia_luz(np.array([45.0]), 7)[0] > 0
    # Faixa equatorial: fator constante
    assert fwi_core.fator_dia_luz(np.array([-5.0]), 7)[0] == 1.39

    # Vetorização == laço ponto a ponto
    rng = np.random.default_rng(3)
    t = rng.uniform(0, 40, (7, 5)); h = rng.uniform(5, 100, (7, 5))
    w = rng.uniform(0, 30, (7, 5)); p = rng.gamma(1, 3, (7, 5))
    f0 = rng.uniform(20, 95, (7, 5))
    campo = fwi_core.ffmc(t, h, w, p, f0)
    for i in range(7):
        for j in range(5):
            um = fwi_core.ffmc(t[i, j], h[i, j], w[i, j], p[i, j], f0[i, j])
            assert abs(float(um) - campo[i, j]) < 1e-12
    print("Propriedades fisicas e vetorizacao ok")


def teste_memoria_dc():
    """O DC deve acumular seca lentamente (memória longa) e o FFMC,
    rapidamente (memória curta)."""
    lat = np.array([[-12.0]])
    estado = fwi_core.EstadoFWI.inicial((1, 1))
    ffmc_dia1 = None
    for dia in range(30):                     # 30 dias secos e quentes
        estado, ind = fwi_core.passo_diario(
            estado, np.array([[32.0]]), np.array([[30.0]]),
            np.array([[12.0]]), np.array([[0.0]]), 8, lat)
        if dia == 0:
            ffmc_dia1 = float(np.asarray(ind["FFMC"]).ravel()[0])
    dc_30 = float(np.asarray(estado.dc).ravel()[0])
    ffmc_30 = float(np.asarray(estado.ffmc).ravel()[0])
    assert dc_30 > 100, dc_30                  # seca acumulada
    assert abs(ffmc_30 - ffmc_dia1) < 3.0      # FFMC já saturou no 1º dia

    # Um dia de chuva forte derruba o FFMC, mas não zera o DC
    estado2, _ = fwi_core.passo_diario(
        estado, np.array([[25.0]]), np.array([[95.0]]), np.array([[3.0]]),
        np.array([[40.0]]), 8, lat)
    assert float(np.asarray(estado2.ffmc).ravel()[0]) < ffmc_30 - 20
    # o FFMC despenca no mesmo dia; o DC guarda mais da metade da
    # seca acumulada (memoria longa)
    assert float(np.asarray(estado2.dc).ravel()[0]) > dc_30 * 0.5
    print(f"Memorias distintas ok (DC {dc_30:.0f} apos 30 dias secos; "
          f"FFMC responde em 1 dia)")


# ---------------------------------------------------------------------------
# Ponta a ponta: fwi_observado.py com bancos sintéticos
# ---------------------------------------------------------------------------

BASE = os.path.join(TMP, "base")
FIM = dt.datetime(2026, 7, 31)
HORA = 18
LAT = np.linspace(-35.0, 10.0, 24)
LON = np.linspace(-75.0, -35.0, 21)


def _grava(caminho, variaveis, quando):
    os.makedirs(os.path.dirname(caminho), exist_ok=True)
    xr.Dataset(
        {n: (("time", "lat", "lon"), d[np.newaxis].astype(np.float32))
         for n, d in variaveis.items()},
        coords={"time": [quando], "lat": LAT, "lon": LON},
    ).to_netcdf(caminho)


def prepara_bancos(dias=40):
    rng = np.random.default_rng(5)
    caminhos = rf_config.padrao()["caminhos"]
    for k in range(dias):
        dia = FIM - dt.timedelta(days=k)
        quando = dia.replace(hour=HORA)
        _grava(rf_config.caminho_imerg(BASE, caminhos, dia),
               {"prec": rng.gamma(0.8, 3.0, (LAT.size, LON.size))}, dia)
        _grava(rf_config.caminho_era5(BASE, caminhos, quando, HORA),
               {"TEMP2m": rng.uniform(293, 310, (LAT.size, LON.size)),
                "RH2m": rng.uniform(20, 95, (LAT.size, LON.size))}, quando)
        _grava(rf_config.caminho_era5(BASE, caminhos, quando, HORA,
                                      vento=True),
               {"U10m": rng.uniform(-8, 8, (LAT.size, LON.size)),
                "V10m": rng.uniform(-8, 8, (LAT.size, LON.size))}, quando)
    return caminhos


def roda(*extra):
    r = subprocess.run([sys.executable, "fwi_observado.py", "--base", BASE,
                        "--hora", str(HORA), *extra],
                       capture_output=True, text=True, timeout=900)
    return r.returncode, r.stdout + r.stderr


def teste_ponta_a_ponta():
    ini = (FIM - dt.timedelta(days=4)).strftime("%Y%m%d")
    rc, out = roda("--de", ini, "--ate", FIM.strftime("%Y%m%d"),
                   "--spinup", "20", "--media", "--media-mensal")
    assert rc == 0, out
    dir_out = f"{BASE}/data/output/2.2/FWI_OBS/netcdf"
    diarios = sorted(a for a in os.listdir(dir_out)
                     if a.startswith("FWI.OBS.2"))
    assert len(diarios) == 5, diarios

    with xr.open_dataset(os.path.join(dir_out, diarios[-1]),
                         decode_times=False) as ds:
        assert set(fwi_observado_vars()) <= set(ds.data_vars), list(ds.data_vars)
        fwi = ds["FWI"].values[0]
        assert fwi.shape == (LAT.size, LON.size)
        assert np.nanmin(fwi) >= 0.0
        assert np.isfinite(fwi).all()
    assert any("MEDIA.202607" in a for a in os.listdir(dir_out))
    print(f"fwi_observado ponta a ponta ok (5 dias + spin-up de 20; "
          f"7 componentes; medias geradas)")


def fwi_observado_vars():
    import fwi_observado
    return fwi_observado.VARIAVEIS


def teste_continuidade_estado():
    """Rodar 6 dias de uma vez == rodar 3 + 3 retomando o estado."""
    d0 = FIM - dt.timedelta(days=5)
    d2 = FIM - dt.timedelta(days=3)
    d3 = FIM - dt.timedelta(days=2)

    rc, out = roda("--de", d0.strftime("%Y%m%d"),
                   "--ate", FIM.strftime("%Y%m%d"),
                   "--spinup", "15", "--produto", "FWI_INTEIRO")
    assert rc == 0, out

    estado = os.path.join(TMP, "estado.nc")
    rc, out = roda("--de", d0.strftime("%Y%m%d"), "--ate", d2.strftime("%Y%m%d"),
                   "--spinup", "15", "--produto", "FWI_PARTIDO",
                   "--salvar-estado", estado)
    assert rc == 0, out
    rc, out = roda("--de", d3.strftime("%Y%m%d"), "--ate", FIM.strftime("%Y%m%d"),
                   "--produto", "FWI_PARTIDO", "--estado-inicial", estado)
    assert rc == 0, out

    nome = f"FWI.OBS.{FIM.replace(hour=HORA):%Y%m%d%H}.nc"
    a = f"{BASE}/data/output/2.2/FWI_INTEIRO/netcdf/{nome}"
    b = f"{BASE}/data/output/2.2/FWI_PARTIDO/netcdf/{nome}"
    with xr.open_dataset(a, decode_times=False) as da, \
            xr.open_dataset(b, decode_times=False) as db:
        for var in ("FFMC", "DMC", "DC", "FWI"):
            assert np.allclose(da[var].values, db[var].values,
                               equal_nan=True), var
    print("Continuidade do estado ok (rodada inteira == rodada retomada)")


if __name__ == "__main__":
    try:
        teste_referencia()
        teste_xclim()
        teste_propriedades()
        teste_memoria_dc()
        prepara_bancos()
        teste_ponta_a_ponta()
        teste_continuidade_estado()
        print()
        print("TODOS OS TESTES DO FWI PASSARAM")
    finally:
        shutil.rmtree(TMP, ignore_errors=True)
