#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
prepara_gfs.py  (v2)
====================

Baixa a previsão do GFS 0.25° e prepara os dados de entrada do Risco de
Fogo, gravando os NetCDF na convenção esperada pelo pipeline:

    GFS.PREV.PREC.{modelo}.{valida}.nc         -> prec   (mm/dia)
    GFS.PREV.TEMP2m.RH2m.{modelo}.{valida}.nc  -> TEMP2m (K) e RH2m (%)

em  {base}/data/output/2.2/GFS/netcdf/{modelo}/ .

ATENÇÃO: o serviço OpenDAP ("dods") do NOMADS foi APOSENTADO pela NOAA
(Service Change Notice 25-81, efetivo em 23/02/2026). A própria NOAA
orienta migrar para o "grib filter" ou para o "fast download method"
(HTTPS com byte-range guiado pelo índice .idx) — esta versão implementa
ambos:

  --metodo s3      (padrão) espelho oficial do GFS no AWS Open Data
                   (noaa-gfs-bdp-pds). Para cada horário de previsão são
                   baixadas APENAS as 3 mensagens GRIB necessárias
                   (APCP, TMP 2m, RH 2m) via requisições HTTP com Range,
                   usando o índice .idx (~2 MB por horário). É o "fast
                   download method" da NOAA, no espelho AWS.
  --metodo nomads  o mesmo "fast download method", direto no HTTPS do
                   NOMADS (nomads.ncep.noaa.gov/pub/...). Use se o AWS
                   estiver bloqueado na sua rede.
  --metodo filtro  "grib filter" do NOMADS (recorte de variáveis/região
                   no servidor; URL configurável via --url-filtro).
                   Documentação: nomads.ncep.noaa.gov/info.php?page=gribfilter

Decodificação GRIB2: pygrib  ->  python3 -m pip install pygrib

Precipitação diária: o APCP do GFS vem em "baldes" (acumulados de 6 h até
+240 h e de 12 h de +240 h a +384 h). O acumulado diário de cada validade
é a soma dos baldes que cobrem as 24 h anteriores (--acumulo 24h, padrão)
ou o dia civil da validade (--acumulo dia). O intervalo de cada balde é
lido do próprio GRIB — a mistura 6 h/12 h é tratada automaticamente.
Além de +240 h, só existem validades a cada 12 h (as demais são puladas
com aviso).

Exemplos:

    python3 prepara_gfs.py                       # rodada de hoje, 16 dias
    python3 prepara_gfs.py --data 20260805 --config config.yaml
    python3 prepara_gfs.py --simular             # só lista o plano

Requisitos: numpy, xarray, netCDF4, pygrib.
"""

import argparse
import concurrent.futures
import datetime as dt
import os
import re
import sys
import tempfile
import threading
import time
import urllib.request

import numpy as np

# eccodes (pygrib) e HDF5 (netCDF4) não são thread-safe: os downloads rodam
# em paralelo, mas a decodificação GRIB é serializada por este lock.
_LOCK_DECODE = threading.Lock()

DOMINIO_PADRAO = "-60.05,29.95,-114.95,-30.05"   # latS,latN,lonW,lonE

URL_S3 = ("https://noaa-gfs-bdp-pds.s3.amazonaws.com/"
          "gfs.{data}/{rodada}/atmos/gfs.t{rodada}z.pgrb2.0p25.f{fff}")
URL_NOMADS_PUB = ("https://nomads.ncep.noaa.gov/pub/data/nccf/com/gfs/prod/"
                  "gfs.{data}/{rodada}/atmos/gfs.t{rodada}z.pgrb2.0p25.f{fff}")
URL_FILTRO = ("https://nomads.ncep.noaa.gov/cgi-bin/filter_gfs_0p25.pl"
              "?dir=%2Fgfs.{data}%2F{rodada}%2Fatmos"
              "&file=gfs.t{rodada}z.pgrb2.0p25.f{fff}"
              "&var_APCP=on&var_TMP=on&var_RH=on"
              "&lev_surface=on&lev_2_m_above_ground=on"
              "&subregion=&toplat={latN}&bottomlat={latS}"
              "&leftlon={lonW360}&rightlon={lonE360}")

TENTATIVAS = 4


# ---------------------------------------------------------------------------
# Funções puras (testáveis sem rede e sem pygrib)
# ---------------------------------------------------------------------------

def fhoras_disponiveis(horas_max):
    """Horas de previsão com arquivo no GFS: de 6 em 6 h até +240 h e de
    12 em 12 h de +252 h a +384 h."""
    fhoras = list(range(6, min(horas_max, 240) + 1, 6))
    if horas_max > 240:
        fhoras += list(range(252, min(horas_max, 384) + 1, 12))
    return fhoras


def filtra_validades(validades):
    """Remove (com aviso) validades sem arquivo no GFS (> +240 h fora do
    passo de 12 h) e além do alcance (+384 h)."""
    ok, puladas = [], []
    for v in validades:
        if v > 384 or (v > 240 and v % 12 != 0):
            puladas.append(v)
        else:
            ok.append(v)
    return ok, puladas


_RE_FAIXA = re.compile(r"(\d+)-(\d+)\s+hour\s+acc")


def parse_faixa_acumulo(texto):
    """Extrai (início, fim) em horas de um texto tipo '234-240 hour acc fcst'."""
    m = _RE_FAIXA.search(texto)
    if not m:
        return None
    return int(m.group(1)), int(m.group(2))


def parse_idx(texto):
    """Interpreta um arquivo .idx do GFS.

    Cada linha: num:offset:d=YYYYMMDDHH:VAR:NIVEL:DESCRICAO:
    Retorna lista de dicts com var, nivel, descricao, ini e fim (bytes;
    fim é None na última mensagem).
    """
    entradas = []
    for linha in texto.strip().splitlines():
        p = linha.split(":")
        if len(p) < 6:
            continue
        entradas.append({"ini": int(p[1]), "var": p[3], "nivel": p[4],
                         "descricao": p[5], "fim": None})
    for i in range(len(entradas) - 1):
        entradas[i]["fim"] = entradas[i + 1]["ini"] - 1
    return entradas


def acha_mensagens(idx, alvos):
    """Localiza no índice as mensagens pedidas.

    ``alvos``: lista de (var, nivel, trecho_descricao_ou_None).
    Retorna a lista de entradas correspondentes (uma por alvo).
    """
    achadas = []
    for var, nivel, trecho in alvos:
        cand = [e for e in idx if e["var"] == var and e["nivel"] == nivel
                and (trecho is None or trecho in e["descricao"])]
        if not cand:
            raise RuntimeError(f"Mensagem {var}/{nivel} não encontrada no .idx")
        achadas.append(cand[0])
    return achadas


def soma_janela(baldes, valid_h, acumulo="24h"):
    """Soma os baldes de precipitação que cobrem a janela diária da validade.

    ``baldes``: lista de ((ini_h, fim_h), campo 2D). A janela é
    (valid_h-24, valid_h] no modo "24h" (limitada ao início da rodada) ou
    o dia civil no modo "dia". Os baldes do GFS particionam o tempo, então
    a soma dos que caem inteiramente na janela cobre a janela.
    """
    if acumulo == "24h":
        ini_j = max(0, valid_h - 24)
    elif acumulo == "dia":
        ini_j = valid_h - 24 if valid_h % 24 == 0 \
            else ((valid_h - 1) // 24) * 24
        ini_j = max(0, ini_j)
    else:
        raise ValueError(f"Acúmulo desconhecido: {acumulo}")

    total = None
    cobertos = []
    for (a, b), campo in baldes:
        if a >= ini_j and b <= valid_h:
            total = campo.copy() if total is None else total + campo
            cobertos.append((a, b))
    if total is None:
        raise RuntimeError(
            f"Nenhum balde de precipitação cobre a janela ({ini_j},{valid_h}].")
    return total, cobertos


def indices_dominio(lat, lon, lat_s, lat_n, lon_w, lon_e):
    """Fatias do domínio pedido (lat pode ser decrescente; lon do GFS é
    0–360 e o domínio pode vir em -180..180)."""
    lon360_w, lon360_e = lon_w % 360.0, lon_e % 360.0
    if lon360_w > lon360_e:
        raise ValueError("Domínio de longitude cruza o meridiano 0/360.")
    ilat = np.nonzero((lat >= lat_s) & (lat <= lat_n))[0]
    ilon = np.nonzero((lon >= lon360_w) & (lon <= lon360_e))[0]
    if ilat.size == 0 or ilon.size == 0:
        raise ValueError("Domínio pedido fora da grade do GFS.")
    return int(ilat[0]), int(ilat[-1]) + 1, int(ilon[0]), int(ilon[-1]) + 1


# ---------------------------------------------------------------------------
# Download (urllib, com tentativas)
# ---------------------------------------------------------------------------

def _http(url, faixa=None, timeout=120):
    ultimo = None
    for tentativa in range(1, TENTATIVAS + 1):
        try:
            req = urllib.request.Request(url)
            req.add_header("User-Agent", "prepara_gfs/2.0 (INPE)")
            if faixa:
                req.add_header("Range", f"bytes={faixa[0]}-{faixa[1]}")
            with urllib.request.urlopen(req, timeout=timeout) as r:
                dados = r.read()
            if dados[:6].lower() in (b"<html>", b"<!doct"):
                raise RuntimeError("o servidor devolveu HTML (erro/aviso) "
                                   "em vez de dados")
            return dados
        except Exception as exc:  # noqa: BLE001
            ultimo = exc
            espera = 20 * tentativa
            print(f"  {url.split('/')[-1]}: tentativa {tentativa}/"
                  f"{TENTATIVAS} falhou ({exc}); aguardando {espera}s",
                  file=sys.stderr)
            time.sleep(espera)
    raise RuntimeError(f"Falha definitiva em {url}: {ultimo}")


def baixa_fhora(metodo, data, rodada, fhora, dominio):
    """Baixa as mensagens GRIB (APCP, TMP 2m, RH 2m) de um horário de
    previsão e devolve os bytes GRIB."""
    fff = f"{fhora:03d}"
    if metodo in ("s3", "nomads"):
        modelo_url = URL_S3 if metodo == "s3" else URL_NOMADS_PUB
        url = modelo_url.format(data=data, rodada=rodada, fff=fff)
        idx = parse_idx(_http(url + ".idx").decode())
        alvos = [("APCP", "surface", None),
                 ("TMP", "2 m above ground", None),
                 ("RH", "2 m above ground", None)]
        pedacos = []
        for e in acha_mensagens(idx, alvos):
            fim = e["fim"] if e["fim"] is not None else e["ini"] + 10_000_000
            pedacos.append(_http(url, faixa=(e["ini"], fim)))
        return b"".join(pedacos)

    # metodo == "filtro": o recorte de variáveis/região é feito no servidor
    lat_s, lat_n, lon_w, lon_e = dominio
    url = URL_FILTRO.format(data=data, rodada=rodada, fff=fff,
                            latN=lat_n, latS=lat_s,
                            lonW360=lon_w % 360.0, lonE360=lon_e % 360.0)
    return _http(url)


# ---------------------------------------------------------------------------
# Decodificação GRIB2 (pygrib)
# ---------------------------------------------------------------------------

def decodifica_grib(dados_grib, dominio):
    """Decodifica as mensagens GRIB e recorta o domínio.

    Retorna (prec_baldes, t2m, rh2m, lat_rec, lon_rec_out):
      prec_baldes = lista de ((ini_h, fim_h), campo 2D)
      lat_rec crescente (sul->norte); lon em -180..180.
    """
    import pygrib

    with tempfile.NamedTemporaryFile(suffix=".grib2", delete=False) as f:
        f.write(dados_grib)
        caminho = f.name
    try:
        grbs = pygrib.open(caminho)
        prec_baldes = []
        t2m = rh2m = None
        lat_rec = lon_rec = None
        for g in grbs:
            lats, lons = g.latlons()
            lat1d = lats[:, 0]
            lon1d = lons[0, :]
            ila0, ila1, ilo0, ilo1 = indices_dominio(
                lat1d, lon1d, *dominio)
            campo = np.asarray(g.values[ila0:ila1, ilo0:ilo1],
                               dtype=np.float32)
            la = lat1d[ila0:ila1]
            lo = lon1d[ilo0:ilo1]
            if la[0] > la[-1]:                    # norte->sul: inverte
                la = la[::-1]
                campo = campo[::-1, :]
            if lat_rec is None:
                lat_rec, lon_rec = la, lo

            nome = g.shortName.upper()
            if nome == "APCP" or g.parameterName.lower().startswith("total precip"):
                ini = int(getattr(g, "startStep", 0))
                fim = int(getattr(g, "endStep", 0))
                prec_baldes.append(((ini, fim), campo))
            elif nome in ("2T", "T", "TMP") and "2" in str(g.level):
                t2m = campo
            elif nome in ("2R", "R", "RH") and "2" in str(g.level):
                rh2m = campo
            elif g.parameterName.lower().startswith("temperature"):
                t2m = campo
            elif "humidity" in g.parameterName.lower():
                rh2m = campo
        grbs.close()
    finally:
        os.unlink(caminho)

    if t2m is None or rh2m is None or not prec_baldes:
        raise RuntimeError("GRIB incompleto: APCP/TMP/RH não encontrados.")
    lon_out = np.where(lon_rec > 180.0, lon_rec - 360.0, lon_rec)
    return prec_baldes, t2m, rh2m, lat_rec, lon_out


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
            "lat": ("lat", np.asarray(lat, dtype=np.float64),
                    {"standard_name": "latitude", "units": "degrees_north"}),
            "lon": ("lon", np.asarray(lon, dtype=np.float64),
                    {"standard_name": "longitude", "units": "degrees_east"}),
        },
        attrs={"source": "GFS 0.25 deg (NOAA) - prepara_gfs.py v2",
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
        description="Baixa o GFS (AWS S3 ou grib filter) e prepara as "
                    "entradas do RF.")
    parser.add_argument("--data", default=None,
                        help="Data da rodada YYYYMMDD (padrão: hoje UTC).")
    parser.add_argument("--rodada", default="00",
                        choices=["00", "06", "12", "18"])
    parser.add_argument("--dias", type=int, default=16,
                        help="Alcance em dias (padrão: 16; máx. do GFS).")
    parser.add_argument("--passo", type=int, default=6,
                        help="Passo das validades em horas (padrão: 6).")
    parser.add_argument("--dominio", default=DOMINIO_PADRAO,
                        help=f"latS,latN,lonW,lonE (padrão: {DOMINIO_PADRAO}).")
    parser.add_argument("--base", default=None,
                        help="Diretório base do modelo.")
    parser.add_argument("--config", default=None,
                        help="config.yaml do pipeline (usa 'base' de lá).")
    parser.add_argument("--acumulo", default="24h", choices=["24h", "dia"])
    parser.add_argument("--metodo", default="s3",
                        choices=["s3", "nomads", "filtro"],
                        help="s3 = AWS Open Data (padrão); nomads = fast "
                             "download no HTTPS do NOMADS; filtro = grib "
                             "filter do NOMADS.")
    parser.add_argument("--url-filtro", default=None,
                        help="Modelo de URL do grib filter, se o padrão "
                             "mudar (marcadores {data},{rodada},{fff},"
                             "{latN},{latS},{lonW360},{lonE360}).")
    parser.add_argument("--jobs", type=int, default=4,
                        help="Downloads simultâneos (padrão: 4).")
    parser.add_argument("--sobrescrever", action="store_true")
    parser.add_argument("--simular", action="store_true")
    args = parser.parse_args()

    global URL_FILTRO
    if args.url_filtro:
        URL_FILTRO = args.url_filtro

    import rf_config
    cfg = rf_config.carrega(args.config) if args.config else rf_config.padrao()
    base = (args.base or cfg["base"]).rstrip("/")

    data = args.data or dt.datetime.now(dt.timezone.utc).strftime("%Y%m%d")
    modelo = data + args.rodada
    inicio = dt.datetime.strptime(modelo, "%Y%m%d%H")
    dominio = tuple(float(x) for x in args.dominio.split(","))

    dirout = f"{base}/data/output/2.2/GFS/netcdf/{modelo}"

    validades, puladas = filtra_validades(
        list(range(args.passo, args.dias * 24 + 1, args.passo)))
    fhoras = fhoras_disponiveis(validades[-1])

    print(f"Rodada:  {modelo}   método: {args.metodo}")
    print(f"Saída:   {dirout}")
    print(f"Validades: {len(validades)} (+{validades[0]}h a "
          f"+{validades[-1]}h)"
          + (f" | puladas (sem arquivo no GFS): "
             f"{','.join('+'+str(v)+'h' for v in puladas)}" if puladas else ""))
    print(f"Arquivos GRIB a baixar: {len(fhoras)} horários "
          f"(~2 MB cada no método s3)")
    print(f"Domínio: lat [{dominio[0]}, {dominio[1]}], "
          f"lon [{dominio[2]}, {dominio[3]}] | acúmulo: {args.acumulo}")

    if not args.config and not args.base and base == rf_config.BASE_PADRAO:
        print(f"AVISO: usando o diretório base padrão "
              f"({rf_config.BASE_PADRAO}).\n"
              "       Para outro destino, use --config config.yaml, "
              "--base DIR ou a variável RF_BASE.", file=sys.stderr)
    if not args.simular:
        try:
            os.makedirs(dirout, exist_ok=True)
        except OSError as exc:
            sys.exit(f"Erro: não consigo criar o diretório de saída "
                     f"({exc}).\nConfira o caminho acima — provavelmente "
                     f"falta --config config.yaml (ou --base).")

    if args.simular:
        exemplo = {"s3": URL_S3, "nomads": URL_NOMADS_PUB,
                   "filtro": URL_FILTRO}[args.metodo]
        print("\nExemplo de URL:")
        print("  " + exemplo.format(data=data, rodada=args.rodada, fff="006",
                                    latN=dominio[1], latS=dominio[0],
                                    lonW360=dominio[2] % 360,
                                    lonE360=dominio[3] % 360))
        return

    try:
        import pygrib  # noqa: F401
    except ImportError:
        sys.exit("Erro: pygrib não instalado. Rode: "
                 "python3 -m pip install pygrib")

    os.makedirs(dirout, exist_ok=True)
    t0 = time.time()

    # -----------------------------------------------------------------
    # Baixa e decodifica cada horário de previsão (em paralelo)
    # -----------------------------------------------------------------
    resultados = {}

    def processa(fhora):
        bruto = baixa_fhora(args.metodo, data, args.rodada, fhora, dominio)
        with _LOCK_DECODE:
            return fhora, decodifica_grib(bruto, dominio)

    with concurrent.futures.ThreadPoolExecutor(max_workers=args.jobs) as ex:
        futuros = [ex.submit(processa, h) for h in fhoras]
        feitos = 0
        for fut in concurrent.futures.as_completed(futuros):
            fhora, res = fut.result()
            resultados[fhora] = res
            feitos += 1
            if feitos % 10 == 0 or feitos == len(fhoras):
                print(f"  baixados {feitos}/{len(fhoras)} horários "
                      f"({time.time()-t0:.0f}s)")

    lat_rec = resultados[fhoras[0]][3]
    lon_rec = resultados[fhoras[0]][4]

    # Todos os baldes de precipitação, ordenados
    baldes = sorted(
        (faixa_campo for h in fhoras for faixa_campo in resultados[h][0]),
        key=lambda fc: fc[0])

    # -----------------------------------------------------------------
    # Gera os arquivos por validade
    # -----------------------------------------------------------------
    gerados = pulados = 0
    for v in validades:
        valida_dt = inicio + dt.timedelta(hours=v)
        valida = valida_dt.strftime("%Y%m%d%H")

        prec_dia, _ = soma_janela(baldes, v, args.acumulo)
        _, t2m, rh2m, _, _ = resultados[v]

        novo1 = grava_netcdf(
            os.path.join(dirout, f"GFS.PREV.PREC.{modelo}.{valida}.nc"),
            {"prec": prec_dia}, lat_rec, lon_rec, valida_dt,
            args.sobrescrever)
        novo2 = grava_netcdf(
            os.path.join(dirout,
                         f"GFS.PREV.TEMP2m.RH2m.{modelo}.{valida}.nc"),
            {"TEMP2m": t2m, "RH2m": rh2m},
            lat_rec, lon_rec, valida_dt, args.sobrescrever)

        if novo1 or novo2:
            gerados += 1
        else:
            pulados += 1

    print(f"\nConcluído em {time.time()-t0:.0f}s: {gerados} validades "
          f"gravadas, {pulados} já existiam em {dirout}")


if __name__ == "__main__":
    main()
