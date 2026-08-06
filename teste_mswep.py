# -*- coding: utf-8 -*-
"""Testes da fonte de precipitação observada MSWEP.

Cobre:
  1. detecção automática da variável (o MSWEP traz a variável sem nome
     reconhecível — o `cdo sinfo` mostra "unknown");
  2. leitura in loco com recorte do domínio (grade global norte→sul) e o
     caso da longitude 0..360;
  3. conversão para o padrão do pipeline (prepara_mswep.py), inclusive a
     partir do arquivo mensal;
  4. seleção da fonte pelo config.yaml e pela linha de comando;
  5. ponta a ponta: RF observado com MSWEP in loco == MSWEP convertido, e
     FWI observado lendo a mesma fonte.
"""

import datetime as dt
import os
import shutil
import subprocess
import sys
import tempfile

import numpy as np
import xarray as xr

import rf_config
import rf_core

TMP = tempfile.mkdtemp(prefix="teste_mswep_")
BASE = os.path.join(TMP, "base")
ORIGEM = os.path.join(TMP, "mswep_origem")
FIM = dt.datetime(2026, 7, 31)
HORA = 18
N_DIAS = 3

# Grade "global" do teste: 1° (o MSWEP real é 0,1°), latitude do norte
# para o sul e longitude -179,5..179,5, como nos arquivos originais.
LAT_G = np.arange(89.5, -90.0, -1.0)
LON_G = np.arange(-179.5, 180.0, 1.0)

DOMINIO = (-40.0, 20.0, -80.0, -35.0)     # latS, latN, lonW, lonE


def _campo_global(semente):
    rng = np.random.default_rng(semente)
    return rng.gamma(1.2, 4.0, (LAT_G.size, LON_G.size)).astype(np.float32)


def grava_mswep(caminho, campo, dia, nome_var="unknown", lon_360=False):
    """Grava um arquivo no formato do MSWEP original."""
    os.makedirs(os.path.dirname(caminho), exist_ok=True)
    lon = LON_G % 360.0 if lon_360 else LON_G
    ordem = np.argsort(lon)
    ds = xr.Dataset(
        {nome_var: (("time", "lat", "lon"), campo[np.newaxis, :, ordem])},
        coords={"time": [dia], "lat": LAT_G, "lon": lon[ordem]},
    )
    ds.to_netcdf(caminho)


def recorta_referencia(campo):
    """Recorte esperado, calculado de forma independente."""
    ila = np.nonzero((LAT_G >= DOMINIO[0]) & (LAT_G <= DOMINIO[1]))[0]
    ilo = np.nonzero((LON_G >= DOMINIO[2]) & (LON_G <= DOMINIO[3]))[0]
    sub = campo[np.ix_(ila, ilo)]
    return sub[::-1, :], LAT_G[ila][::-1], LON_G[ilo]   # lat sul→norte


# ---------------------------------------------------------------------------
# 1. Detecção da variável
# ---------------------------------------------------------------------------

def teste_deteccao_variavel():
    caminho = os.path.join(TMP, "det.nc")
    grava_mswep(caminho, _campo_global(1), FIM, nome_var="unknown")
    with xr.open_dataset(caminho) as ds:
        assert rf_core.nome_variavel_precip(ds) == "unknown"
        assert rf_core.nome_variavel_precip(ds, "auto") == "unknown"

    caminho2 = os.path.join(TMP, "det2.nc")
    grava_mswep(caminho2, _campo_global(2), FIM, nome_var="precipitation")
    with xr.open_dataset(caminho2) as ds:
        assert rf_core.nome_variavel_precip(ds) == "precipitation"

    # Duas candidatas -> erro pedindo o nome explícito
    caminho3 = os.path.join(TMP, "det3.nc")
    ds = xr.Dataset(
        {"a": (("lat", "lon"), _campo_global(3)),
         "b": (("lat", "lon"), _campo_global(4))},
        coords={"lat": LAT_G, "lon": LON_G})
    ds.to_netcdf(caminho3)
    with xr.open_dataset(caminho3) as d:
        try:
            rf_core.nome_variavel_precip(d)
            raise AssertionError("deveria exigir o nome da variável")
        except KeyError as exc:
            assert "variavel" in str(exc)
        assert rf_core.nome_variavel_precip(d, "b") == "b"
    print("1. deteccao automatica da variavel (unknown/precipitation) ok")


# ---------------------------------------------------------------------------
# 2. Leitura in loco com recorte
# ---------------------------------------------------------------------------

def teste_recorte():
    campo = _campo_global(5)
    caminho = os.path.join(TMP, "rec.nc")
    grava_mswep(caminho, campo, FIM)

    dados, lat, lon = rf_core.le_precip_arquivo(caminho, None, DOMINIO)
    esperado, lat_e, lon_e = recorta_referencia(campo)
    assert dados.shape == (1,) + esperado.shape, dados.shape
    assert np.allclose(dados[0], esperado)
    assert np.allclose(lat, lat_e) and np.allclose(lon, lon_e)
    assert lat[0] < lat[-1]                       # sul -> norte
    assert lat.min() >= DOMINIO[0] and lat.max() <= DOMINIO[1]

    la2, lo2 = rf_core.le_grade_precip(caminho, DOMINIO)
    assert np.allclose(la2, lat) and np.allclose(lo2, lon)

    # sem recorte: grade global inteira
    dados_g, lat_g, _ = rf_core.le_precip_arquivo(caminho, None, None)
    assert dados_g.shape[1:] == (LAT_G.size, LON_G.size)
    assert lat_g[0] < lat_g[-1]
    print(f"2. recorte na leitura ({dados.shape[1]}x{dados.shape[2]} de "
          f"{LAT_G.size}x{LON_G.size}) ok")


def teste_longitude_0_360():
    campo = _campo_global(6)
    caminho = os.path.join(TMP, "lon360.nc")
    grava_mswep(caminho, campo, FIM, lon_360=True)
    dados, lat, lon = rf_core.le_precip_arquivo(caminho, None, DOMINIO)
    esperado, lat_e, lon_e = recorta_referencia(campo)
    assert np.allclose(lon, lon_e), lon[:5]
    assert np.all(np.diff(lon) > 0)
    assert np.allclose(dados[0], esperado)
    print("2b. arquivo com longitude 0..360 reordenado para -180..180 ok")


# ---------------------------------------------------------------------------
# 3. Conversão (prepara_mswep.py)
# ---------------------------------------------------------------------------

def teste_conversao():
    import prepara_mswep

    campo = _campo_global(7)
    dia = FIM
    origem = os.path.join(ORIGEM, "2026", "07", "20260731.nc")
    grava_mswep(origem, campo, dia)

    prec, lat, lon = prepara_mswep.le_dia(origem, dia, DOMINIO)
    esperado, lat_e, lon_e = recorta_referencia(campo)
    assert np.allclose(prec, esperado)

    destino = os.path.join(TMP, "conv.nc")
    assert prepara_mswep.grava_padrao(destino, prec, lat, lon, dia, origem)
    assert not prepara_mswep.grava_padrao(destino, prec, lat, lon, dia,
                                          origem)          # incremental
    dados, la, lo = rf_core.le_precip_arquivo(destino)      # variável `prec`
    assert np.allclose(dados[0], esperado, atol=1e-5)
    assert np.allclose(la, lat_e) and np.allclose(lo, lon_e)
    print("3. conversao ao padrao do pipeline (incremental) ok")


def teste_conversao_mensal():
    import prepara_mswep

    campos = np.stack([_campo_global(10 + k) for k in range(3)])
    dias = [dt.datetime(2023, 1, 1) + dt.timedelta(days=k) for k in range(3)]
    caminho = os.path.join(ORIGEM, "2023", "01", "jan.nc")
    os.makedirs(os.path.dirname(caminho), exist_ok=True)
    xr.Dataset({"unknown": (("time", "lat", "lon"), campos)},
               coords={"time": dias, "lat": LAT_G, "lon": LON_G}
               ).to_netcdf(caminho)

    assert prepara_mswep.arquivo_mensal(
        os.path.join(os.path.dirname(caminho), "20230102.nc"),
        dias[1]).endswith("jan.nc")

    prec, _, _ = prepara_mswep.le_dia(caminho, dias[1], DOMINIO, mensal=True)
    esperado, _, _ = recorta_referencia(campos[1])
    assert np.allclose(prec, esperado)
    print("3b. leitura de um dia dentro do arquivo mensal (jan.nc) ok")


# ---------------------------------------------------------------------------
# 4. Configuração
# ---------------------------------------------------------------------------

def teste_config():
    caminho = os.path.join(TMP, "config_mswep.yaml")
    with open(caminho, "w") as f:
        f.write(f"""
base: {BASE}
caminhos:
  mswep_dir: {ORIGEM}
precipitacao:
  fonte: mswep
  modo: in_loco
  dominio: "{DOMINIO[0]},{DOMINIO[1]},{DOMINIO[2]},{DOMINIO[3]}"
""")
    cfg = rf_config.carrega(caminho)
    p = cfg["precipitacao"]
    assert p["fonte"] == "mswep" and p["modo"] == "in_loco"
    assert rf_config.variavel_precipitacao(p) is None       # detecção auto
    assert rf_config.recorte_precipitacao(p) == DOMINIO
    assert rf_config.sufixo_precipitacao(p) == "_MSWEP"
    esperado = os.path.join(ORIGEM, "2026", "07", "20260731.nc")
    assert rf_config.caminho_precipitacao(
        BASE, cfg["caminhos"], FIM, p) == esperado

    p2 = dict(p, modo="convertido")
    assert rf_config.variavel_precipitacao(p2) == "prec"
    assert rf_config.recorte_precipitacao(p2) is None
    assert "MSWEP-2_2" in rf_config.caminho_precipitacao(
        BASE, cfg["caminhos"], FIM, p2)

    # padrão continua IMERG, sem sufixo
    padrao = rf_config.padrao()["precipitacao"]
    assert padrao["fonte"] == "imerg"
    assert rf_config.sufixo_precipitacao(padrao) == ""
    assert rf_config.recorte_precipitacao(padrao) is None
    assert rf_config.caminho_precipitacao(
        BASE, rf_config.padrao()["caminhos"], FIM, padrao) == \
        rf_config.caminho_imerg(BASE, rf_config.padrao()["caminhos"], FIM)

    # fonte inválida é recusada
    try:
        rf_config.valida_precipitacao({"fonte": "chirps"})
        raise AssertionError("fonte inválida deveria falhar")
    except ValueError as exc:
        assert "chirps" in str(exc)
    print("4. secao 'precipitacao' do config (fonte/modo/dominio) ok")
    return caminho


# ---------------------------------------------------------------------------
# 5. Ponta a ponta
# ---------------------------------------------------------------------------

def prepara_bancos():
    """Banco MSWEP original (120+ dias) + ERA5 dos dias analisados."""
    caminhos = rf_config.padrao()["caminhos"]
    caminhos = dict(caminhos, mswep_dir=ORIGEM)
    primeiro = FIM - dt.timedelta(days=N_DIAS - 1 + 119)
    d = primeiro
    k = 0
    while d <= FIM:
        grava_mswep(rf_config.caminho_mswep(BASE, caminhos, d),
                    _campo_global(100 + k), d)
        d += dt.timedelta(days=1)
        k += 1

    rng = np.random.default_rng(3)
    lat, lon = recorta_referencia(_campo_global(1))[1:]
    for j in range(N_DIAS):
        dia = FIM - dt.timedelta(days=j)
        quando = dia.replace(hour=HORA)
        campos = {"TEMP2m": rng.uniform(290.0, 308.0, (lat.size, lon.size)),
                  "RH2m": rng.uniform(20.0, 90.0, (lat.size, lon.size))}
        vento = {"U10m": rng.uniform(-6.0, 6.0, (lat.size, lon.size)),
                 "V10m": rng.uniform(-6.0, 6.0, (lat.size, lon.size))}
        for nomes, vento_flag in ((campos, False), (vento, True)):
            caminho = rf_config.caminho_era5(BASE, caminhos, quando, HORA,
                                             vento=vento_flag)
            os.makedirs(os.path.dirname(caminho), exist_ok=True)
            xr.Dataset(
                {n: (("time", "lat", "lon"), v[np.newaxis].astype(np.float32))
                 for n, v in nomes.items()},
                coords={"time": [quando], "lat": lat, "lon": lon},
            ).to_netcdf(caminho)
    return caminhos


def teste_ponta_a_ponta(config):
    de = (FIM - dt.timedelta(days=N_DIAS - 1)).strftime("%Y%m%d")
    ate = FIM.strftime("%Y%m%d")
    comum = ["--config", config, "--de", de, "--ate", ate,
             "--sem-vegetacao", "--sem-topografia", "--sem-tif", "--jobs", "2"]

    r = subprocess.run([sys.executable, "rf_observado.py", *comum],
                       capture_output=True, text=True, timeout=1200)
    saida = r.stdout + r.stderr
    assert r.returncode == 0, saida
    assert "MSWEP" in saida, saida
    dir_out = f"{BASE}/data/output/2.2/RF_OBS_MSWEP_SEMVEG_SEMTOPO/netcdf"
    arquivos = sorted(os.listdir(dir_out))
    assert len(arquivos) == N_DIAS, arquivos
    with xr.open_dataset(os.path.join(dir_out, arquivos[-1]),
                         decode_times=False) as ds:
        rf_in_loco = ds[list(ds.data_vars)[0]].values[0]
    esperado, lat_e, lon_e = recorta_referencia(_campo_global(1))
    assert rf_in_loco.shape == esperado.shape          # grade recortada
    assert np.nanmin(rf_in_loco) >= 0.0 and np.nanmax(rf_in_loco) <= 1.0
    print(f"5. RF observado com MSWEP in loco: {len(arquivos)} dia(s), "
          f"grade {rf_in_loco.shape} ok")

    # ---- mesma coisa via arquivos convertidos: resultado idêntico
    r = subprocess.run([sys.executable, "prepara_mswep.py", "--config",
                        config, "--inicio",
                        (FIM - dt.timedelta(days=N_DIAS - 1 + 119)
                         ).strftime("%Y%m%d"), "--fim", ate],
                       capture_output=True, text=True, timeout=1200)
    saida = r.stdout + r.stderr
    assert r.returncode == 0, saida
    assert "Concluído" in saida, saida

    r = subprocess.run([sys.executable, "rf_observado.py", *comum,
                        "--modo-precipitacao", "convertido"],
                       capture_output=True, text=True, timeout=1200)
    saida = r.stdout + r.stderr
    assert r.returncode == 0, saida
    with xr.open_dataset(os.path.join(dir_out, arquivos[-1]),
                         decode_times=False) as ds:
        rf_convertido = ds[list(ds.data_vars)[0]].values[0]
    dif = np.nanmax(np.abs(rf_in_loco - rf_convertido))
    assert dif <= 0.01, dif        # RF é gravado com 2 casas decimais
    print(f"5b. MSWEP convertido == in loco (dif. máx. {dif:.3f}) ok")

    # ---- FWI observado lendo a mesma fonte
    r = subprocess.run([sys.executable, "fwi_observado.py", "--config",
                        config, "--de", de, "--ate", ate, "--spinup", "2"],
                       capture_output=True, text=True, timeout=1200)
    saida = r.stdout + r.stderr
    assert r.returncode == 0, saida
    assert "MSWEP" in saida, saida
    dir_fwi = f"{BASE}/data/output/2.2/FWI_OBS_MSWEP/netcdf"
    arquivos_fwi = sorted(os.listdir(dir_fwi))
    assert len(arquivos_fwi) == N_DIAS, arquivos_fwi
    with xr.open_dataset(os.path.join(dir_fwi, arquivos_fwi[-1]),
                         decode_times=False) as ds:
        assert "FWI" in ds and "DSR" in ds
        assert ds["FWI"].values.shape[-2:] == esperado.shape
    print(f"5c. FWI observado com MSWEP: {len(arquivos_fwi)} dia(s) ok")


# ---------------------------------------------------------------------------
# 6. Dado REAL (só roda onde o disco do MSWEP existe — ian01/CPTEC)
# ---------------------------------------------------------------------------

MSWEP_REAL = "/pesq/dados/sismom/SisMOM/sipec/mswep/daily"
DOMINIO_REAL = (-60.05, 29.95, -114.95, -30.05)


def teste_mswep_real():
    """Confere a leitura do arquivo verdadeiro: variável detectada, grade
    0,1°, latitude reordenada, recorte e ordem de grandeza da chuva."""
    import glob
    import time as _t

    diarios = sorted(glob.glob(os.path.join(MSWEP_REAL, "*", "*",
                                            "[0-9]" * 8 + ".nc")))
    if not diarios:
        print("6. dado real do MSWEP não encontrado neste servidor "
              f"({MSWEP_REAL}) — teste pulado")
        return

    caminho = diarios[len(diarios) // 2]
    with xr.open_dataset(caminho, decode_times=False) as ds:
        nome = rf_core.nome_variavel_precip(ds)
        forma = ds[nome].shape

    t0 = _t.time()
    dados, lat, lon = rf_core.le_precip_arquivo(caminho, None, DOMINIO_REAL)
    leitura = _t.time() - t0

    assert dados.shape[0] == 1, dados.shape
    assert lat[0] < lat[-1], "latitude deveria sair de sul para norte"
    assert lat.min() >= DOMINIO_REAL[0] and lat.max() <= DOMINIO_REAL[1]
    assert lon.min() >= DOMINIO_REAL[2] and lon.max() <= DOMINIO_REAL[3]
    passo_lat = float(np.median(np.diff(lat)))
    passo_lon = float(np.median(np.diff(lon)))
    assert abs(passo_lat - 0.1) < 0.01 and abs(passo_lon - 0.1) < 0.01, \
        (passo_lat, passo_lon)

    validos = dados[np.isfinite(dados)]
    assert validos.size > 0
    assert validos.min() >= 0.0, validos.min()
    assert validos.max() < 2000.0, validos.max()        # mm/dia plausível

    # A grade recortada tem de casar com a do IMERG do pipeline
    esperado = (901, 850)
    assert dados.shape[1:] == esperado, (dados.shape[1:], esperado)

    print(f"6. dado REAL {os.path.basename(caminho)}: variável '{nome}' "
          f"{forma} -> recorte {dados.shape[1:]} em {leitura:.1f}s; "
          f"passo {passo_lat:.2f}°; chuva {validos.min():.1f}–"
          f"{validos.max():.1f} mm/dia (média {validos.mean():.2f}) ok")

    mensal = os.path.join(os.path.dirname(caminho),
                          prepara_mswep_mes(caminho))
    if os.path.exists(mensal):
        import prepara_mswep
        dia = dt.datetime.strptime(
            os.path.basename(caminho)[:8], "%Y%m%d")
        t0 = _t.time()
        prec_m, _, _ = prepara_mswep.le_dia(mensal, dia, DOMINIO_REAL,
                                            mensal=True)
        dif = np.nanmax(np.abs(prec_m - dados[0]))
        assert dif < 1e-3, dif
        print(f"6b. dado REAL: dia extraído do mensal "
              f"{os.path.basename(mensal)} == arquivo diário "
              f"(dif. {dif:.1e}, {_t.time()-t0:.1f}s) ok")


def prepara_mswep_mes(caminho_diario):
    import prepara_mswep
    dia = dt.datetime.strptime(os.path.basename(caminho_diario)[:8], "%Y%m%d")
    return os.path.basename(prepara_mswep.arquivo_mensal(caminho_diario, dia))


def main():
    print(f"Área de teste: {TMP}\n")
    try:
        teste_deteccao_variavel()
        teste_recorte()
        teste_longitude_0_360()
        teste_conversao()
        teste_conversao_mensal()
        config = teste_config()
        prepara_bancos()
        teste_ponta_a_ponta(config)
        teste_mswep_real()
        print("\nTODOS OS TESTES DO MSWEP PASSARAM")
    finally:
        shutil.rmtree(TMP, ignore_errors=True)


if __name__ == "__main__":
    main()
