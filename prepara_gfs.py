#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
prepara_gfs.py
==============

Baixa a previsão do GFS 0.25° (NOMADS/NCEP) e prepara os dados de entrada
do Risco de Fogo, gravando os NetCDF na convenção esperada pelo pipeline:

    GFS.PREV.PREC.{modelo}.{valida}.nc         -> prec   (mm/dia)
    GFS.PREV.TEMP2m.RH2m.{modelo}.{valida}.nc  -> TEMP2m (K) e RH2m (%)

em  {base}/data/output/2.2/GFS/netcdf/{modelo}/ .

O acesso é feito via OpenDAP (servidor "dods" do NOMADS), o que dispensa
bibliotecas GRIB (eccodes/pygrib): basta o netCDF4 com suporte a DAP, que
já é dependência do pipeline. Cada variável é baixada em UMA requisição
(recorte de domínio + todos os tempos), o que reduz o tráfego a ~30 MB
por rodada.

Precipitação diária: o campo apcpsfc do GFS é acumulado em "baldes" de
6 horas (o valor no passo h, com h múltiplo de 6, é o acumulado das
6 horas anteriores). O acumulado diário de cada validade é a soma dos
4 baldes das últimas 24 h (--acumulo 24h, padrão) ou dos baldes desde as
00 UTC do dia da validade (--acumulo dia). Para validades nas primeiras
24 h da rodada, soma-se o que existe desde o início.

Exemplos:

    # Rodada de hoje 00 UTC, 16 dias, validades a cada 6 h
    python3 prepara_gfs.py

    # Rodada específica, domínio e destino do config.yaml
    python3 prepara_gfs.py --data 20260804 --config config.yaml

    # Só listar o que seria feito
    python3 prepara_gfs.py --simular

Requisitos: numpy, xarray, netCDF4 (com DAP — padrão nos wheels do pip).
"""

import argparse
import datetime as dt
import os
import sys
import time

import numpy as np

# Domínio padrão: o mesmo do IMERG do pipeline (América do Sul/Central).
DOMINIO_PADRAO = "-60.05,29.95,-114.95,-30.05"   # latS,latN,lonW,lonE
URL_PADRAO = "https://nomads.ncep.noaa.gov/dods/gfs_0p25/gfs{data}/gfs_0p25_{rodada}z"
TENTATIVAS = 4


# ---------------------------------------------------------------------------
# Funções puras (testáveis sem rede)
# ---------------------------------------------------------------------------

def indices_dominio(lat, lon, lat_s, lat_n, lon_w, lon_e):
    """Índices (fatias) do domínio pedido nas coordenadas do GFS.

    A longitude do GFS é 0–360; o domínio pode vir em -180..180.
    Retorna (ilat0, ilat1, ilon0, ilon1) para fatias [i0:i1].
    """
    lon360_w = lon_w % 360.0
    lon360_e = lon_e % 360.0
    if lon360_w > lon360_e:
        raise ValueError("Domínio de longitude cruza o meridiano 0/360 — "
                         "não suportado (divida em dois domínios).")
    ilat = np.nonzero((lat >= lat_s) & (lat <= lat_n))[0]
    ilon = np.nonzero((lon >= lon360_w) & (lon <= lon360_e))[0]
    if ilat.size == 0 or ilon.size == 0:
        raise ValueError("Domínio pedido fora da grade do GFS.")
    return int(ilat[0]), int(ilat[-1]) + 1, int(ilon[0]), int(ilon[-1]) + 1


def horas_dos_baldes(valid_h, acumulo="24h"):
    """Horas de previsão (múltiplas de 6) cujos baldes de 6 h compõem o
    acumulado diário da validade ``valid_h`` (horas desde a rodada).

    - "24h": baldes que terminam em (valid_h-18, valid_h-12, valid_h-6,
      valid_h), limitados ao início da rodada;
    - "dia": baldes desde as 00 UTC do dia da validade (para rodada 00 UTC,
      equivale aos baldes após o último múltiplo de 24 h).
    """
    if valid_h % 6 != 0:
        raise ValueError(f"Validade {valid_h}h não é múltipla de 6 h.")
    if acumulo == "24h":
        inicio = max(0, valid_h - 24)
    elif acumulo == "dia":
        inicio = ((valid_h - 1) // 24) * 24 if valid_h % 24 != 0 \
            else valid_h - 24
        inicio = max(0, inicio)
    else:
        raise ValueError(f"Acúmulo desconhecido: {acumulo}")
    return list(range(inicio + 6, valid_h + 1, 6))


def soma_baldes(apcp, horas_eixo, valid_h, acumulo="24h"):
    """Soma os baldes de 6 h do campo ``apcp`` (nt, nlat, nlon) para obter
    o acumulado diário (mm) da validade ``valid_h``.

    ``horas_eixo`` são as horas de previsão de cada índice do eixo tempo.
    """
    alvos = horas_dos_baldes(valid_h, acumulo)
    idx = [int(np.nonzero(horas_eixo == h)[0][0]) for h in alvos]
    return apcp[idx].sum(axis=0)


# ---------------------------------------------------------------------------
# Download via OpenDAP
# ---------------------------------------------------------------------------

def abre_dataset(url):
    import xarray as xr
    ultimo_erro = None
    for tentativa in range(1, TENTATIVAS + 1):
        try:
            return xr.open_dataset(url)
        except Exception as exc:  # noqa: BLE001
            ultimo_erro = exc
            espera = 30 * tentativa
            print(f"Tentativa {tentativa}/{TENTATIVAS} falhou: {exc}\n"
                  f"Aguardando {espera}s...", file=sys.stderr)
            time.sleep(espera)
    raise RuntimeError(f"Não foi possível abrir {url}: {ultimo_erro}")


def baixa_variavel(ds, nome, it0, it1, ilat, ilon, passo_t=1):
    """Baixa uma variável do dataset DAP em uma única requisição."""
    ultimo_erro = None
    for tentativa in range(1, TENTATIVAS + 1):
        try:
            var = ds[nome].isel(
                time=slice(it0, it1, passo_t),
                lat=slice(ilat[0], ilat[1]),
                lon=slice(ilon[0], ilon[1]),
            )
            return np.asarray(var.values, dtype=np.float32)
        except Exception as exc:  # noqa: BLE001
            ultimo_erro = exc
            espera = 30 * tentativa
            print(f"Download de {nome}: tentativa {tentativa}/{TENTATIVAS} "
                  f"falhou: {exc}\nAguardando {espera}s...", file=sys.stderr)
            time.sleep(espera)
    raise RuntimeError(f"Falha ao baixar {nome}: {ultimo_erro}")


# ---------------------------------------------------------------------------
# Escrita dos NetCDF na convenção do pipeline
# ---------------------------------------------------------------------------

def grava_netcdf(caminho, variaveis, lat, lon, valida_dt, sobrescrever):
    import xarray as xr
    if os.path.exists(caminho) and not sobrescrever:
        return False
    ds = xr.Dataset(
        {nome: (("time", "lat", "lon"),
                dados[np.newaxis].astype(np.float32))
         for nome, dados in variaveis.items()},
        coords={
            "time": [valida_dt],
            "lat": ("lat", lat, {"standard_name": "latitude",
                                 "units": "degrees_north"}),
            "lon": ("lon", lon, {"standard_name": "longitude",
                                 "units": "degrees_east"}),
        },
        attrs={"source": "GFS 0.25 deg (NOMADS/NCEP) - prepara_gfs.py",
               "history": f"gerado em {dt.datetime.now():%Y-%m-%d %H:%M}"},
    )
    enc = {nome: {"dtype": "float32", "zlib": True, "complevel": 4}
           for nome in variaveis}
    enc["time"] = {"units": "hours since 1900-01-01 00:00:00",
                   "calendar": "standard", "dtype": "float64"}
    ds.to_netcdf(caminho, format="NETCDF4_CLASSIC", encoding=enc)
    return True


# ---------------------------------------------------------------------------
# Programa principal
# ---------------------------------------------------------------------------

def main():
    parser = argparse.ArgumentParser(
        description="Baixa o GFS (NOMADS) e prepara as entradas do RF.")
    parser.add_argument("--data", default=None,
                        help="Data da rodada YYYYMMDD (padrão: hoje).")
    parser.add_argument("--rodada", default="00", choices=["00", "06", "12", "18"],
                        help="Hora da rodada (padrão: 00).")
    parser.add_argument("--dias", type=int, default=16,
                        help="Alcance em dias (padrão: 16; máx. do GFS).")
    parser.add_argument("--passo", type=int, default=6,
                        help="Passo das validades em horas (padrão: 6).")
    parser.add_argument("--dominio", default=DOMINIO_PADRAO,
                        help=f"latS,latN,lonW,lonE (padrão: {DOMINIO_PADRAO}).")
    parser.add_argument("--base", default=None,
                        help="Diretório base do modelo (padrão: o do config "
                             "ou o da produção).")
    parser.add_argument("--config", default=None,
                        help="config.yaml do pipeline (usa 'base' de lá).")
    parser.add_argument("--acumulo", default="24h", choices=["24h", "dia"],
                        help="Precipitação diária: últimas 24 h (padrão) ou "
                             "desde as 00 UTC do dia da validade.")
    parser.add_argument("--url", default=URL_PADRAO,
                        help="Modelo de URL OpenDAP ({data}, {rodada}).")
    parser.add_argument("--sobrescrever", action="store_true",
                        help="Regrava arquivos que já existem.")
    parser.add_argument("--simular", action="store_true",
                        help="Só lista o que seria baixado/gerado.")
    args = parser.parse_args()

    import rf_config
    cfg = rf_config.carrega(args.config) if args.config else rf_config.padrao()
    base = (args.base or cfg["base"]).rstrip("/")

    if args.data:
        data = args.data
    else:
        data = dt.datetime.utcnow().strftime("%Y%m%d")
    modelo = data + args.rodada
    inicio = dt.datetime.strptime(modelo, "%Y%m%d%H")

    lat_s, lat_n, lon_w, lon_e = (float(x) for x in args.dominio.split(","))

    dirout = f"{base}/data/output/2.2/GFS/netcdf/{modelo}"
    url = args.url.format(data=data, rodada=args.rodada)

    validades = list(range(args.passo, args.dias * 24 + 1, args.passo))

    print(f"Rodada:  {modelo}")
    print(f"URL:     {url}")
    print(f"Saída:   {dirout}")
    print(f"Validades: +{validades[0]}h a +{validades[-1]}h "
          f"(passo {args.passo}h, {len(validades)} arquivos de cada tipo)")
    print(f"Domínio: lat [{lat_s}, {lat_n}], lon [{lon_w}, {lon_e}] "
          f"| acúmulo: {args.acumulo}")

    if args.simular:
        for h in validades[:3] + ["..."] + validades[-2:]:
            if h == "...":
                print("  ...")
                continue
            v = (inicio + dt.timedelta(hours=h)).strftime("%Y%m%d%H")
            print(f"  GFS.PREV.PREC.{modelo}.{v}.nc + "
                  f"GFS.PREV.TEMP2m.RH2m.{modelo}.{v}.nc")
        return

    os.makedirs(dirout, exist_ok=True)

    # -----------------------------------------------------------------
    # Abre o dataset remoto e define os recortes
    # -----------------------------------------------------------------
    print("\nAbrindo o dataset remoto (OpenDAP)...")
    ds = abre_dataset(url)

    lat = np.asarray(ds["lat"].values, dtype=np.float64)
    lon = np.asarray(ds["lon"].values, dtype=np.float64)
    ila0, ila1, ilo0, ilo1 = indices_dominio(lat, lon, lat_s, lat_n,
                                             lon_w, lon_e)
    lat_rec = lat[ila0:ila1]
    lon_rec = lon[ilo0:ilo1]
    lon_rec_out = np.where(lon_rec > 180.0, lon_rec - 360.0, lon_rec)

    # Eixo de tempo do dataset em horas de previsão.
    tempos = ds["time"].values
    horas_eixo = ((tempos - np.datetime64(inicio)) /
                  np.timedelta64(1, "h")).astype(int)
    # Índices dos tempos de 6 em 6 h até o alcance pedido.
    precisa = sorted(set(h for v in validades
                         for h in horas_dos_baldes(v, args.acumulo))
                     | set(validades))
    if max(precisa) > horas_eixo.max():
        sys.exit(f"Erro: alcance pedido (+{max(precisa)}h) além do "
                 f"disponível no GFS (+{horas_eixo.max()}h).")
    it6 = np.nonzero((horas_eixo % 6 == 0) & (horas_eixo > 0)
                     & (horas_eixo <= max(precisa)))[0]
    it0, it1 = int(it6[0]), int(it6[-1]) + 1
    passo_t = int(np.diff(it6).min()) if it6.size > 1 else 1
    horas_6h = horas_eixo[it0:it1:passo_t]

    # -----------------------------------------------------------------
    # Baixa as 3 variáveis (uma requisição por variável)
    # -----------------------------------------------------------------
    t0 = time.time()
    print("Baixando apcpsfc (precipitação em baldes de 6 h)...")
    apcp = baixa_variavel(ds, "apcpsfc", it0, it1, (ila0, ila1),
                          (ilo0, ilo1), passo_t)
    print("Baixando tmp2m (temperatura a 2 m)...")
    t2m = baixa_variavel(ds, "tmp2m", it0, it1, (ila0, ila1),
                         (ilo0, ilo1), passo_t)
    print("Baixando rh2m (umidade relativa a 2 m)...")
    rh2m = baixa_variavel(ds, "rh2m", it0, it1, (ila0, ila1),
                          (ilo0, ilo1), passo_t)
    ds.close()
    print(f"Download concluído em {time.time()-t0:.0f}s "
          f"({apcp.nbytes*3/1e6:.0f} MB).")

    # -----------------------------------------------------------------
    # Gera os arquivos por validade
    # -----------------------------------------------------------------
    gerados = pulados = 0
    for v_h in validades:
        valida_dt = inicio + dt.timedelta(hours=v_h)
        valida = valida_dt.strftime("%Y%m%d%H")
        iv = int(np.nonzero(horas_6h == v_h)[0][0])

        prec_dia = soma_baldes(apcp, horas_6h, v_h, args.acumulo)

        novo1 = grava_netcdf(
            os.path.join(dirout, f"GFS.PREV.PREC.{modelo}.{valida}.nc"),
            {"prec": prec_dia}, lat_rec, lon_rec_out, valida_dt,
            args.sobrescrever)
        novo2 = grava_netcdf(
            os.path.join(dirout,
                         f"GFS.PREV.TEMP2m.RH2m.{modelo}.{valida}.nc"),
            {"TEMP2m": t2m[iv], "RH2m": rh2m[iv]},
            lat_rec, lon_rec_out, valida_dt, args.sobrescrever)

        if novo1 or novo2:
            gerados += 1
            print(f"  {valida}  ok")
        else:
            pulados += 1

    print(f"\nConcluído: {gerados} validades gravadas, {pulados} já "
          f"existiam em {dirout}")


if __name__ == "__main__":
    main()
