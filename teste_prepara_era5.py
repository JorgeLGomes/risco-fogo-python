# -*- coding: utf-8 -*-
"""Testes do prepara_era5.py (sem rede): fórmula de UR, leitura do NetCDF
do CDS (nomes curtos/longos, valid_time, latitude N->S, zip) e conversão
para o padrão de leitura do RF (rf_core.ler_temp_ur)."""

import datetime as dt
import os
import shutil
import tempfile
import zipfile

import numpy as np
import xarray as xr

import prepara_era5
import rf_config
import rf_core

TMP = tempfile.mkdtemp(prefix="teste_era5_")


def _cds_sintetico(caminho, tempos, nomes=("t2m", "d2m", "u10", "v10"),
                   eixo_t="valid_time", lat_desc=True):
    """Gera um NetCDF no formato devolvido pelo CDS."""
    lat = np.linspace(20.0, -40.0, 25) if lat_desc \
        else np.linspace(-40.0, 20.0, 25)
    lon = np.linspace(-80.0, -35.0, 19)
    nt = len(tempos)
    rng = np.random.default_rng(42)
    t2m = rng.uniform(280.0, 310.0, (nt, 25, 19)).astype(np.float32)
    d2m = t2m - rng.uniform(0.0, 15.0, (nt, 25, 19)).astype(np.float32)
    u10 = rng.uniform(-10.0, 10.0, (nt, 25, 19)).astype(np.float32)
    v10 = rng.uniform(-10.0, 10.0, (nt, 25, 19)).astype(np.float32)
    dados = dict(zip(("t2m", "d2m", "u10", "v10"), (t2m, d2m, u10, v10)))
    ds = xr.Dataset(
        {nome: ((eixo_t, "latitude", "longitude"), dados[curto])
         for curto, nome in zip(("t2m", "d2m", "u10", "v10"), nomes)},
        coords={eixo_t: np.array(tempos, dtype="datetime64[ns]"),
                "latitude": lat, "longitude": lon},
    )
    ds.to_netcdf(caminho)
    return dados, lat, lon


def teste_umidade_relativa():
    # Td == T -> saturação (100%)
    t = np.array([300.0, 285.0])
    assert np.allclose(prepara_era5.umidade_relativa(t, t), 100.0,
                       atol=1e-3)
    # Td < T -> UR < 100 e decresce com o déficit
    ur1 = prepara_era5.umidade_relativa(np.array([300.0]),
                                        np.array([295.0]))
    ur2 = prepara_era5.umidade_relativa(np.array([300.0]),
                                        np.array([285.0]))
    assert 0.0 < ur2 < ur1 < 100.0
    # Valor de referência: T=30°C, Td=20°C -> UR ~ 55.4%
    ur = prepara_era5.umidade_relativa(np.array([303.15]),
                                       np.array([293.15]))
    assert abs(float(ur[0]) - 55.4) < 1.0, float(ur[0])
    print("Fórmula de Magnus (UR de T e Td) ok")


def teste_leitura_cds():
    tempos = [dt.datetime(2026, 7, 1, 18), dt.datetime(2026, 7, 2, 18)]
    caminho = os.path.join(TMP, "cds.nc")
    dados, lat_in, lon_in = _cds_sintetico(caminho, tempos)
    ts, t2m, d2m, u10, v10, lat, lon = prepara_era5.le_cds_netcdf(caminho)
    assert ts == tempos
    assert lat[0] < lat[-1], "latitude deveria sair sul->norte"
    # o campo foi invertido junto com a latitude
    assert np.allclose(t2m[0], dados["t2m"][0][::-1, :])
    print("Leitura do NetCDF do CDS (valid_time, N->S) ok")

    # Nomes longos + eixo "time" + latitude já ascendente
    caminho2 = os.path.join(TMP, "cds2.nc")
    _cds_sintetico(caminho2, tempos,
                   nomes=("2m_temperature", "2m_dewpoint_temperature",
                          "10m_u_component_of_wind",
                          "10m_v_component_of_wind"),
                   eixo_t="time", lat_desc=False)
    ts2, t2b, _, _, _, lat2, _ = prepara_era5.le_cds_netcdf(caminho2)
    assert ts2 == tempos and lat2[0] < lat2[-1]
    print("Leitura com nomes longos e eixo 'time' ok")

    # Entrega zipada
    caminho_zip = os.path.join(TMP, "cds.zip")
    with zipfile.ZipFile(caminho_zip, "w") as z:
        z.write(caminho, "data.nc")
    ts3, _, _, _, _, _, _ = prepara_era5.le_cds_netcdf(caminho_zip)
    assert ts3 == tempos
    print("Leitura de entrega zipada do CDS ok")


def teste_conversao_pipeline():
    tempos = [dt.datetime(2026, 7, 1, 18), dt.datetime(2026, 7, 2, 18),
              dt.datetime(2026, 7, 2, 6)]        # 06 UTC deve ser ignorado
    caminho = os.path.join(TMP, "cds3.nc")
    _cds_sintetico(caminho, tempos)

    base = os.path.join(TMP, "base")
    caminhos = rf_config.padrao()["caminhos"]
    gravados = prepara_era5.converte_cds(caminho, None, 18, caminhos, base,
                                         log=lambda *a: None)
    assert [g.strftime("%Y%m%d%H") for g in gravados] == \
        ["2026070118", "2026070218"], gravados

    quando = dt.datetime(2026, 7, 1, 18)
    arq = rf_config.caminho_era5(base, caminhos, quando, 18)
    arq_v = rf_config.caminho_era5(base, caminhos, quando, 18, vento=True)
    assert os.path.exists(arq) and os.path.exists(arq_v)
    assert os.path.basename(arq) == "ERA5.OBS.TEMP2m.RH2m.2026070118.nc"
    assert os.path.basename(arq_v) == "ERA5.OBS.U10m.V10m.2026070118.nc"

    # O arquivo térmico é lido pelo leitor do pipeline (TEMP2m K, RH2m %)
    t2m, ur2m, lat, lon = rf_core.ler_temp_ur(arq)
    assert lat[0] < lat[-1]
    assert -60.0 < float(np.nanmean(t2m)) < 60.0          # °C plausível
    assert 0.0 <= float(np.nanmin(ur2m)) and \
        float(np.nanmax(ur2m)) <= 1.0                     # décimos
    with xr.open_dataset(arq_v) as ds:
        assert {"U10m", "V10m"} <= set(ds.data_vars)
    print("Conversão para o padrão do RF (ler_temp_ur) ok")

    # Repetição sem --sobrescrever não regrava
    de_novo = prepara_era5.converte_cds(caminho, None, 18, caminhos, base,
                                        log=lambda *a: None)
    assert len(de_novo) == 2
    print("Idempotência (arquivos existentes preservados) ok")


def teste_periodo():
    class A:                                     # simula argparse
        inicio = fim = data_final = None
        dias = 7
    dias = prepara_era5.resolve_periodo(A)
    assert len(dias) == 7
    assert dias[-1] < dt.datetime.utcnow()
    A.inicio, A.fim = "20260601", "20260603"
    assert len(prepara_era5.resolve_periodo(A)) == 3
    print("Resolução de período ok")


if __name__ == "__main__":
    try:
        teste_umidade_relativa()
        teste_leitura_cds()
        teste_conversao_pipeline()
        teste_periodo()
        print()
        print("TODOS OS TESTES DO PREPARA_ERA5 PASSARAM")
    finally:
        shutil.rmtree(TMP, ignore_errors=True)
