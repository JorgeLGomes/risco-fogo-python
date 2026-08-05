# -*- coding: utf-8 -*-
"""Teste de ponta a ponta do rf_observado.py: banco IMERG + ERA5
sintéticos -> RF.OBS diários, incluindo períodos (--dias/--semanas/--meses),
--simular, dias incompletos pulados e modo sem arquivos estáticos."""

import datetime as dt
import os
import shutil
import subprocess
import sys
import tempfile

import numpy as np
import xarray as xr

import rf_config

TMP = tempfile.mkdtemp(prefix="teste_rfobs_")
BASE = os.path.join(TMP, "base")
FIM = dt.datetime(2026, 7, 31)
HORA = 18

LAT = np.linspace(-40.0, 20.0, 31)
LON = np.linspace(-80.0, -35.0, 25)


def _grava(caminho, variaveis, quando):
    os.makedirs(os.path.dirname(caminho), exist_ok=True)
    ds = xr.Dataset(
        {n: (("time", "lat", "lon"), d[np.newaxis].astype(np.float32))
         for n, d in variaveis.items()},
        coords={"time": [quando], "lat": LAT, "lon": LON},
    )
    ds.to_netcdf(caminho)


def prepara_bancos(n_dias_rf=5):
    rng = np.random.default_rng(7)
    caminhos = rf_config.padrao()["caminhos"]
    # IMERG: 120 dias antes do primeiro dia analisado até FIM
    primeiro = FIM - dt.timedelta(days=n_dias_rf - 1 + 119)
    d = primeiro
    while d <= FIM:
        prec = rng.gamma(1.2, 4.0, (LAT.size, LON.size))
        _grava(rf_config.caminho_imerg(BASE, caminhos, d),
               {"prec": prec}, d)
        d += dt.timedelta(days=1)
    # ERA5: só os dias analisados (o penúltimo fica FALTANDO de propósito)
    for k in range(n_dias_rf):
        dia = FIM - dt.timedelta(days=k)
        if k == 1:
            continue                                # dia incompleto
        quando = dia.replace(hour=HORA)
        t2m = rng.uniform(290.0, 308.0, (LAT.size, LON.size))
        ur = rng.uniform(20.0, 90.0, (LAT.size, LON.size))
        _grava(rf_config.caminho_era5(BASE, caminhos, quando, HORA),
               {"TEMP2m": t2m, "RH2m": ur}, quando)
    return caminhos


def roda(*extra):
    cmd = [sys.executable, "rf_observado.py", "--base", BASE,
           "--de", (FIM - dt.timedelta(days=4)).strftime("%Y%m%d"),
           "--ate", FIM.strftime("%Y%m%d"),
           "--sem-vegetacao", "--sem-topografia", "--sem-tif",
           "--jobs", "2", *extra]
    r = subprocess.run(cmd, capture_output=True, text=True, timeout=600)
    return r.returncode, r.stdout + r.stderr


def teste_simular():
    rc, out = roda("--simular")
    assert rc == 0, out
    assert "4 dia(s) prontos, 1 incompletos" in out, out
    assert "prepara_era5" in out
    print("--simular lista dias prontos e incompletos ok")


def teste_calculo():
    rc, out = roda()
    assert rc == 0, out
    assert "4 dia(s) calculados, 0 erro(s), 1 pulado(s)" in out, out
    dir_out = f"{BASE}/data/output/2.2/RF_OBS_SEMVEG_SEMTOPO/netcdf"
    arquivos = sorted(os.listdir(dir_out))
    assert len(arquivos) == 4, arquivos
    assert arquivos[0].startswith("RF.OBS.") and \
        arquivos[0].endswith("18.nc")
    with xr.open_dataset(os.path.join(dir_out, arquivos[-1]),
                         decode_times=False) as ds:
        var = list(ds.data_vars)[0]
        rf = ds[var].values
        assert rf.shape[-2:] == (LAT.size, LON.size)   # grade da precip
        assert np.nanmin(rf) >= 0.0 and np.nanmax(rf) <= 1.0
        assert "DESLIGADO" in ds.attrs.get("fator_vegetacao", "")
    print("RF observado calculado (4 dias; valores em [0,1]; "
          "dia sem ERA5 pulado) ok")


def teste_periodos():
    import rf_observado

    class A:
        de = ate = None
        data_final = FIM.strftime("%Y%m%d")
        dias = semanas = meses = None

    A.dias = 7
    i, f = rf_observado.resolve_periodo(A)
    assert (f - i).days + 1 == 7 and f == FIM
    A.dias, A.semanas = None, 2
    i, f = rf_observado.resolve_periodo(A)
    assert (f - i).days + 1 == 14
    A.semanas, A.meses = None, 2
    i, f = rf_observado.resolve_periodo(A)
    assert i == dt.datetime(2026, 6, 1) and f == FIM   # 2 meses-calendário
    A.meses = None
    A.de, A.ate = "20260601", "20260630"
    i, f = rf_observado.resolve_periodo(A)
    assert (f - i).days + 1 == 30
    print("Períodos (--dias/--semanas/--meses/--de+--ate) ok")




def teste_agregacoes():
    """--media, --media-mensal e --mergetime sobre os diários existentes."""
    dir_out = f"{BASE}/data/output/2.2/RF_OBS_SEMVEG_SEMTOPO/netcdf"
    cmd = [sys.executable, "rf_observado.py", "--base", BASE,
           "--de", (FIM - dt.timedelta(days=4)).strftime("%Y%m%d"),
           "--ate", FIM.strftime("%Y%m%d"),
           "--sem-vegetacao", "--sem-topografia", "--so-agrega",
           "--media", "--media-mensal", "--mergetime"]
    r = subprocess.run(cmd, capture_output=True, text=True, timeout=600)
    out = r.stdout + r.stderr
    assert r.returncode == 0, out

    ini = (FIM - dt.timedelta(days=4)).strftime("%Y%m%d")
    media = os.path.join(dir_out, f"RF.OBS.MEDIA.{ini}-{FIM:%Y%m%d}.nc")
    mensal = os.path.join(dir_out, f"RF.OBS.MEDIA.{FIM:%Y%m}.nc")
    serie = os.path.join(dir_out, f"RF.OBS.SERIE.{ini}-{FIM:%Y%m%d}.nc")
    for arq in (media, mensal, serie):
        assert os.path.exists(arq), arq

    # a média confere com o nanmean dos diários existentes
    diarios = sorted(f for f in os.listdir(dir_out)
                     if f.startswith("RF.OBS.2") and f.endswith("18.nc"))
    pilha = []
    for nome in diarios:
        with xr.open_dataset(os.path.join(dir_out, nome),
                             decode_times=False) as ds:
            v = ds[list(ds.data_vars)[0]].values[0]
        pilha.append(np.where(v <= -998, np.nan, v))
    # Acumulação em float64, como no rf_observado.agrega (o arredondamento
    # para 2 casas é sensível ao tipo quando a média cai exatamente em
    # 0,xx5 — o RF diário já vem com 2 decimais).
    esperado = np.round(np.nanmean(np.stack(pilha).astype(np.float64),
                                   axis=0), 2)
    with xr.open_dataset(media, decode_times=False) as ds:
        obtido = ds[list(ds.data_vars)[0]].values[0]
        obtido = np.where(obtido <= -998, np.nan, obtido)
        assert ds.attrs.get("agregacao") == "media"
        assert ds.attrs.get("dias_agregados") == str(len(diarios))
    assert np.allclose(esperado, obtido, equal_nan=True, atol=1e-6)

    with xr.open_dataset(serie) as ds:
        assert ds.sizes["time"] == len(diarios)
    print(f"Agregacoes (--media/--media-mensal/--mergetime) ok "
          f"({len(diarios)} dias)")


def teste_figura():
    """rf_figura.py gera PNG a partir dos NetCDF do RF."""
    dir_out = f"{BASE}/data/output/2.2/RF_OBS_SEMVEG_SEMTOPO/netcdf"
    ini = (FIM - dt.timedelta(days=4)).strftime("%Y%m%d")
    media = os.path.join(dir_out, f"RF.OBS.MEDIA.{ini}-{FIM:%Y%m%d}.nc")
    png = os.path.join(TMP, "figura.png")
    r = subprocess.run([sys.executable, "rf_figura.py", media,
                        "--saida", png], capture_output=True, text=True,
                       timeout=600)
    assert r.returncode == 0, r.stdout + r.stderr
    assert os.path.exists(png) and os.path.getsize(png) > 10000

    # painel com todos os diários + paleta discreta
    painel = os.path.join(TMP, "painel.png")
    r = subprocess.run([sys.executable, "rf_figura.py",
                        os.path.join(dir_out, "RF.OBS.2*18.nc"),
                        "--painel", "--classes", "--colunas", "2",
                        "--saida", painel],
                       capture_output=True, text=True, timeout=600)
    assert r.returncode == 0, r.stdout + r.stderr
    assert os.path.exists(painel)

    import rf_figura
    cmap, _ = rf_figura.escala()
    assert rf_figura.CORES[0] == "#17b617" and rf_figura.CORES[-1] == "#a70000"
    print("rf_figura (mapa, painel e paleta oficial do SLD) ok")



if __name__ == "__main__":
    try:
        prepara_bancos()
        teste_periodos()
        teste_simular()
        teste_calculo()
        teste_agregacoes()
        teste_figura()
        print()
        print("TODOS OS TESTES DO RF_OBSERVADO PASSARAM")
    finally:
        shutil.rmtree(TMP, ignore_errors=True)
