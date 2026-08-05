# -*- coding: utf-8 -*-
"""Testes do horário do ERA5 (fixo x hora solar local) e da escala da UR
no Fator de Umidade do RF.

Cobre:
  1. era5_tempo: fusos por longitude, horas UTC necessárias, composição
     por faixas e as opções da seção ``era5`` do config;
  2. rf_observado / fwi_observado no modo solar: os campos são montados
     com a hora UTC certa de cada faixa (a temperatura sintética carrega
     a hora, o que permite conferir ponto a ponto);
  3. --correcao-ur: produto separado, atributo no NetCDF e efeito
     esperado no RF (UR em % reduz o risco em relação à convenção do NCL).
"""

import datetime as dt
import os
import shutil
import subprocess
import sys
import tempfile

import numpy as np
import xarray as xr

import era5_tempo
import rf_config

TMP = tempfile.mkdtemp(prefix="teste_era5h_")
BASE = os.path.join(TMP, "base")
FIM = dt.datetime(2026, 7, 31)
LAT = np.linspace(-30.0, 5.0, 15)
LON = np.linspace(-75.0, -35.0, 17)
CAMINHOS = rf_config.padrao()["caminhos"]


def teste_helpers():
    lon = np.array([-75.0, -60.0, -45.0, -37.0])
    assert list(era5_tempo.offset_utc(lon)) == [-5, -4, -3, -2]
    assert list(era5_tempo.hora_utc_por_longitude(lon, 15)) == [20, 19, 18, 17]
    assert list(era5_tempo.hora_utc_por_longitude(lon, 12)) == [17, 16, 15, 14]

    # Horas a baixar conforme a configuração
    assert era5_tempo.horas_para_baixar({"horario": "fixo", "hora": 18},
                                        -75, -35) == [18]
    assert era5_tempo.horas_para_baixar(
        {"horario": "solar", "hora_local": 15}, -75, -35) == [17, 18, 19, 20]
    assert era5_tempo.horas_para_baixar(
        {"horario": "solar", "hora_local": 12}, -75, -35) == [14, 15, 16, 17]
    assert era5_tempo.horas_para_baixar(
        {"horario": "solar", "horas": [18, 19]}, -75, -35) == [18, 19]

    # Rótulo dos arquivos: hora UTC no fixo, hora local no solar
    assert era5_tempo.rotulo_hora({"horario": "fixo", "hora": 18}) == 18
    assert era5_tempo.rotulo_hora({"horario": "solar",
                                   "hora_local": 12}) == 12

    # Composição: cada coluna vem do campo da sua hora
    campos = {h: np.full((3, LON.size), float(h)) for h in (17, 18, 19, 20)}
    montado = era5_tempo.compoe_por_longitude(campos, LON, 15)
    esperado = era5_tempo.hora_utc_por_longitude(LON, 15)
    assert np.array_equal(montado[0].astype(int), esperado)

    # Modo inválido é recusado
    try:
        era5_tempo.normaliza({"horario": "meia-noite"})
        raise SystemExit("deveria ter recusado o modo invalido")
    except ValueError:
        pass
    print("era5_tempo: fusos, horas necessarias, composicao e config ok")


def prepara_bancos():
    rng = np.random.default_rng(9)

    def grava(caminho, variaveis, quando):
        os.makedirs(os.path.dirname(caminho), exist_ok=True)
        xr.Dataset(
            {n: (("time", "lat", "lon"), d[np.newaxis].astype(np.float32))
             for n, d in variaveis.items()},
            coords={"time": [quando], "lat": LAT, "lon": LON},
        ).to_netcdf(caminho)

    for k in range(125):
        dia = FIM - dt.timedelta(days=k)
        grava(rf_config.caminho_imerg(BASE, CAMINHOS, dia),
              {"prec": rng.gamma(1.0, 3.0, (LAT.size, LON.size))}, dia)
        for h in (17, 18, 19, 20):
            quando = dia.replace(hour=h)
            # TEMP2m carrega a hora (K = 273,15 + h) para rastrear a origem
            grava(rf_config.caminho_era5(BASE, CAMINHOS, quando, h),
                  {"TEMP2m": np.full((LAT.size, LON.size), 273.15 + h),
                   "RH2m": np.full((LAT.size, LON.size), 3.0 * h)}, quando)
            grava(rf_config.caminho_era5(BASE, CAMINHOS, quando, h,
                                         vento=True),
                  {"U10m": np.full((LAT.size, LON.size), 1.0 * h),
                   "V10m": np.zeros((LAT.size, LON.size))}, quando)


def roda(script, *extra):
    r = subprocess.run([sys.executable, script, *extra],
                       capture_output=True, text=True, timeout=900)
    return r.returncode, r.stdout + r.stderr


def teste_modo_solar():
    ini = (FIM - dt.timedelta(days=1)).strftime("%Y%m%d")
    cfg = os.path.join(TMP, "cfg_solar.yaml")
    with open(cfg, "w") as f:
        f.write(f"base: {BASE}\nera5:\n  horario: solar\n  hora_local: 15\n")

    rc, out = roda("rf_observado.py", "--config", cfg, "--de", ini,
                   "--ate", FIM.strftime("%Y%m%d"), "--sem-vegetacao",
                   "--sem-topografia", "--sem-tif")
    assert rc == 0, out
    assert "horas UTC 17, 18, 19, 20" in out, out

    dir_out = f"{BASE}/data/output/2.2/RF_OBS_SEMVEG_SEMTOPO_SOLAR/netcdf"
    arquivos = sorted(os.listdir(dir_out))
    assert len(arquivos) == 2 and arquivos[0].endswith("15.nc"), arquivos

    # A temperatura montada deve trazer, em cada coluna, a hora UTC do fuso
    import fwi_observado
    entradas, _ = fwi_observado.entradas_do_dia(
        BASE, CAMINHOS, FIM, {"horario": "solar", "hora_local": 15})
    t2m = entradas[0]
    esperado = era5_tempo.hora_utc_por_longitude(LON, 15)
    assert np.array_equal(np.round(t2m[0]).astype(int), esperado)

    # E o vento também (U = hora, V = 0 -> velocidade = hora em m/s)
    vento = entradas[2]
    assert np.allclose(vento[0], esperado * 3.6, atol=1e-3)
    print("Modo solar ok (RF e FWI montam T, UR e vento por faixa de fuso)")


def teste_correcao_ur():
    ini = (FIM - dt.timedelta(days=1)).strftime("%Y%m%d")
    comum = ["--base", BASE, "--de", ini, "--ate", FIM.strftime("%Y%m%d"),
             "--hora", "18", "--sem-vegetacao", "--sem-topografia",
             "--sem-tif"]
    rc, out = roda("rf_observado.py", *comum)
    assert rc == 0, out
    rc, out = roda("rf_observado.py", *comum, "--correcao-ur", "percentual")
    assert rc == 0, out
    assert "difere da operacao" in out or "difere da operação" in out, out

    dir_ncl = f"{BASE}/data/output/2.2/RF_OBS_SEMVEG_SEMTOPO/netcdf"
    dir_pct = f"{BASE}/data/output/2.2/RF_OBS_SEMVEG_SEMTOPO_URPER/netcdf"
    nome = sorted(os.listdir(dir_ncl))[-1]
    with xr.open_dataset(os.path.join(dir_ncl, nome),
                         decode_times=False) as a, \
            xr.open_dataset(os.path.join(dir_pct, nome),
                            decode_times=False) as b:
        rf_ncl = a[list(a.data_vars)[0]].values
        rf_pct = b[list(b.data_vars)[0]].values
        assert "percentual" in b.attrs.get("escala_ur_no_FU", "")
        assert "escala_ur_no_FU" not in a.attrs
    # Com UR em %, o FU cai de ~1,3 para <1 na maior parte do domínio:
    # o RF resultante é menor.
    assert np.nanmean(rf_pct) < np.nanmean(rf_ncl)
    print(f"Correcao da UR ok (RF medio {np.nanmean(rf_ncl):.3f} 'ncl' -> "
          f"{np.nanmean(rf_pct):.3f} 'percentual'; produtos separados)")


def teste_fator_ur_nucleo():
    import rf_core
    # FU = -0.008*UR*fator + 1.3 — confere as três escalas
    ur_frac = 0.40                      # 40 %
    assert abs((-0.008 * ur_frac * rf_core.FATOR_UR["ncl"] + 1.3)
               - 1.2968) < 1e-4
    assert abs((-0.008 * ur_frac * rf_core.FATOR_UR["decimos"] + 1.3)
               - 1.2680) < 1e-4
    assert abs((-0.008 * ur_frac * rf_core.FATOR_UR["percentual"] + 1.3)
               - 0.9800) < 1e-4
    print("Escalas da UR no FU ok (ncl 1,297 · decimos 1,268 · "
          "percentual 0,980 a 40 % de UR)")


if __name__ == "__main__":
    try:
        teste_helpers()
        teste_fator_ur_nucleo()
        prepara_bancos()
        teste_modo_solar()
        teste_correcao_ur()
        print()
        print("TODOS OS TESTES DE HORARIO/UR PASSARAM")
    finally:
        shutil.rmtree(TMP, ignore_errors=True)
