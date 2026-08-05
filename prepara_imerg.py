#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
prepara_imerg.py
================

Baixa a precipitação diária observada do IMERG (GPM, NASA) e converte para
o padrão de leitura do Risco de Fogo:

    {imerg_dir}/{ano}/{mes}/INPE_FireRiskModel_2.2_Precipitation_{AAAAMMDD}.nc
    -> variável `prec` (mm/dia), grade 0,1°, lat sul→norte, domínio recortado

Produto usado: IMERG Early Daily V07 (GPM_3IMERGDE) do GES DISC/NASA —
o mesmo usado pela operação do Programa Queimadas (latência ~4 h). Com
--produto final, usa o Final Run (GPM_3IMERGDF, mais preciso, latência de
meses — útil para reprocessamentos históricos).

AUTENTICAÇÃO (uma única vez) — dois modos, o token é o mais robusto:

  MODO A (recomendado) — token do Earthdata:
    1. Conta gratuita em https://urs.earthdata.nasa.gov
    2. No perfil, aba "Generate Token" -> copie o token
    3. No servidor:  echo 'SEU_TOKEN' > ~/.edl_token && chmod 600 ~/.edl_token
       (ou exporte a variável EARTHDATA_TOKEN)

  MODO B — usuário/senha via ~/.netrc:
    1. Conta gratuita em https://urs.earthdata.nasa.gov
    2. No perfil, em "Applications > Authorized Apps", autorize
       "NASA GESDISC DATA ARCHIVE"  (OBRIGATÓRIO neste modo)
    3. Crie o arquivo ~/.netrc (chmod 600) com:
         machine urs.earthdata.nasa.gov login SEU_USUARIO password SUA_SENHA
       (login = nome de usuário do Earthdata, NÃO o e-mail)

Exemplos:

    # Os 119 dias anteriores a hoje (a janela do RF), rodada operacional
    python3 prepara_imerg.py --config config.yaml

    # Período explícito
    python3 prepara_imerg.py --inicio 20260407 --fim 20260803

    # Janela de 119 dias terminando na véspera de uma rodada antiga
    python3 prepara_imerg.py --data-final 20260804

    # Só listar o que seria baixado
    python3 prepara_imerg.py --simular

Cada arquivo diário global tem ~25 MB; o NetCDF recortado gravado fica com
~2–3 MB. Requisitos: numpy, xarray, netCDF4.
"""

import argparse
import concurrent.futures
import datetime as dt
import http.cookiejar
import netrc
import os
import sys
import tempfile
import threading
import time
import urllib.request

import numpy as np

# A HDF5 (por trás do netCDF4/xarray) NÃO é thread-safe: o download roda em
# paralelo, mas a conversão/gravação NetCDF é serializada por este lock
# (sem ele, lotes grandes morrem com "Segmentation fault").
_LOCK_NETCDF = threading.Lock()

DOMINIO_PADRAO = "-60.05,29.95,-114.95,-30.05"   # latS,latN,lonW,lonE

# Sufixos de versão do V07 em ordem de preferência (a letra muda com
# reprocessamentos da NASA); o script tenta cada um até achar o arquivo.
VERSOES = ["V07D", "V07C", "V07B", "V07A"]

URLS = {
    "early": ("https://gpm1.gesdisc.eosdis.nasa.gov/data/GPM_L3/"
              "GPM_3IMERGDE.07/{ano}/{mes}/"
              "3B-DAY-E.MS.MRG.3IMERG.{data}-S000000-E235959.{versao}.nc4"),
    "late": ("https://gpm1.gesdisc.eosdis.nasa.gov/data/GPM_L3/"
             "GPM_3IMERGDL.07/{ano}/{mes}/"
             "3B-DAY-L.MS.MRG.3IMERG.{data}-S000000-E235959.{versao}.nc4"),
    "final": ("https://gpm2.gesdisc.eosdis.nasa.gov/data/GPM_L3/"
              "GPM_3IMERGDF.07/{ano}/{mes}/"
              "3B-DAY.MS.MRG.3IMERG.{data}-S000000-E235959.{versao}.nc4"),
}

TENTATIVAS = 3


# ---------------------------------------------------------------------------
# Autenticação Earthdata (via ~/.netrc) com cookies e redirecionamentos
# ---------------------------------------------------------------------------

_TOKEN = None


def monta_opener():
    """urllib opener autenticado no Earthdata.

    Preferência: token (variável EARTHDATA_TOKEN ou arquivo ~/.edl_token),
    enviado como 'Authorization: Bearer'. Sem token, usa usuário/senha do
    ~/.netrc com autenticação básica + cookies (exige o app
    'NASA GESDISC DATA ARCHIVE' autorizado no perfil)."""
    global _TOKEN
    _TOKEN = os.environ.get("EARTHDATA_TOKEN")
    if not _TOKEN:
        caminho = os.path.expanduser("~/.edl_token")
        if os.path.exists(caminho):
            with open(caminho) as f:
                _TOKEN = f.read().strip()
    if _TOKEN:
        print("Autenticação: token Earthdata (Bearer).")
        return urllib.request.build_opener(
            urllib.request.HTTPCookieProcessor(http.cookiejar.CookieJar()))

    gerente = urllib.request.HTTPPasswordMgrWithDefaultRealm()
    try:
        credenciais = netrc.netrc()
        auth = credenciais.authenticators("urs.earthdata.nasa.gov")
    except (FileNotFoundError, netrc.NetrcParseError):
        auth = None
    if auth is None:
        sys.exit("Erro: credenciais Earthdata não encontradas.\n"
                 "Opção A (recomendada): gere um token no perfil do "
                 "Earthdata ('Generate Token') e salve com:\n"
                 "  echo 'SEU_TOKEN' > ~/.edl_token && chmod 600 ~/.edl_token\n"
                 "Opção B: crie ~/.netrc (chmod 600) com:\n"
                 "  machine urs.earthdata.nasa.gov login USUARIO password SENHA")
    usuario, _, senha = auth
    print(f"Autenticação: usuário/senha do ~/.netrc (login: {usuario}).")
    gerente.add_password(None, "https://urs.earthdata.nasa.gov",
                         usuario, senha)
    return urllib.request.build_opener(
        urllib.request.HTTPBasicAuthHandler(gerente),
        urllib.request.HTTPCookieProcessor(http.cookiejar.CookieJar()))


def _diagnostico_html(dados):
    """Explica a página HTML devolvida no lugar do dado."""
    trecho = dados[:4000].decode("utf-8", "ignore").lower()
    if "authorize" in trecho or "approve" in trecho:
        return ("o Earthdata pediu AUTORIZAÇÃO do aplicativo: entre no seu "
                "perfil em urs.earthdata.nasa.gov > Applications > "
                "Authorized Apps e aprove 'NASA GESDISC DATA ARCHIVE'")
    if "login" in trecho or "password" in trecho or "sign in" in trecho:
        return ("o Earthdata devolveu a página de LOGIN: usuário/senha do "
                "~/.netrc incorretos (o login é o nome de usuário, não o "
                "e-mail) — ou use um token (~/.edl_token)")
    return "resposta HTML inesperada (veja as opções de autenticação no cabeçalho do script)"


def baixa(opener, url, timeout=180):
    ultimo = None
    for tentativa in range(1, TENTATIVAS + 1):
        try:
            req = urllib.request.Request(url)
            req.add_header("User-Agent", "prepara_imerg/1.1 (INPE)")
            if _TOKEN:
                req.add_header("Authorization", "Bearer " + _TOKEN)
            with opener.open(req, timeout=timeout) as r:
                dados = r.read()
            if dados[:6].lower() in (b"<html>", b"<!doct"):
                raise RuntimeError(_diagnostico_html(dados))
            return dados
        except urllib.error.HTTPError as exc:
            if exc.code == 404:
                raise                       # versão errada: deixa o chamador tentar outra
            if exc.code == 401:
                raise RuntimeError(
                    "401 não autorizado: token inválido/expirado ou "
                    "usuário/senha incorretos no ~/.netrc") from exc
            ultimo = exc
        except Exception as exc:  # noqa: BLE001
            ultimo = exc
        time.sleep(15 * tentativa)
    raise RuntimeError(f"Falha em {url}: {ultimo}")


def baixa_dia(opener, produto, dia):
    """Baixa o arquivo diário global, tentando as versões conhecidas."""
    for versao in VERSOES:
        url = URLS[produto].format(ano=dia.strftime("%Y"),
                                   mes=dia.strftime("%m"),
                                   data=dia.strftime("%Y%m%d"),
                                   versao=versao)
        try:
            return baixa(opener, url), url
        except urllib.error.HTTPError as exc:
            if exc.code != 404:
                raise
    raise RuntimeError(
        f"Nenhuma versão encontrada para {dia:%Y-%m-%d} "
        f"(tentadas: {', '.join(VERSOES)}). O dia pode ainda não estar "
        f"publicado ou a letra de versão mudou — confira no GES DISC.")


# ---------------------------------------------------------------------------
# Conversão para o padrão do pipeline (testável sem rede)
# ---------------------------------------------------------------------------

def converte(dados_nc4, dominio, dia):
    """Converte o NetCDF diário global do IMERG para o padrão do RF.

    O IMERG vem com a variável `precipitation` (mm/dia) nas dimensões
    (time, lon, lat) — transposta em relação ao padrão — com lat de sul
    para norte e lon -180..180. Retorna (prec[lat,lon], lat, lon) já
    recortado no domínio.
    """
    import xarray as xr

    with tempfile.NamedTemporaryFile(suffix=".nc4", delete=False) as f:
        f.write(dados_nc4)
        caminho = f.name
    try:
        with xr.open_dataset(caminho) as ds:
            nome_var = ("precipitation" if "precipitation" in ds
                        else "precipitationCal")
            var = ds[nome_var]
            if var.dims[-2:] == ("lon", "lat"):
                var = var.transpose(..., "lat", "lon")
            prec = np.asarray(var.values, dtype=np.float32)
            if prec.ndim == 3:
                prec = prec[0]
            lat = np.asarray(ds["lat"].values, dtype=np.float64)
            lon = np.asarray(ds["lon"].values, dtype=np.float64)
    finally:
        os.unlink(caminho)

    if lat[0] > lat[-1]:                    # garante sul -> norte
        lat = lat[::-1]
        prec = prec[::-1, :]

    lat_s, lat_n, lon_w, lon_e = dominio
    ila = np.nonzero((lat >= lat_s) & (lat <= lat_n))[0]
    ilo = np.nonzero((lon >= lon_w) & (lon <= lon_e))[0]
    if ila.size == 0 or ilo.size == 0:
        raise ValueError("Domínio fora da grade do IMERG.")

    prec = prec[ila[0]:ila[-1] + 1, ilo[0]:ilo[-1] + 1]
    prec = np.where(np.isfinite(prec) & (prec >= 0), prec, np.nan)
    return prec, lat[ila[0]:ila[-1] + 1], lon[ilo[0]:ilo[-1] + 1]


def grava_padrao(caminho, prec, lat, lon, dia, origem, sobrescrever):
    """Grava no padrão de leitura do pipeline (variável `prec`, mm/dia)."""
    import xarray as xr
    if os.path.exists(caminho) and not sobrescrever:
        return False
    os.makedirs(os.path.dirname(caminho), exist_ok=True)
    ds = xr.Dataset(
        {"prec": (("time", "lat", "lon"), prec[np.newaxis].astype(np.float32),
                  {"long_name": "Daily accumulated precipitation (IMERG)",
                   "units": "mm"})},
        coords={
            "time": [dt.datetime(dia.year, dia.month, dia.day)],
            "lat": ("lat", lat, {"standard_name": "latitude",
                                 "units": "degrees_north"}),
            "lon": ("lon", lon, {"standard_name": "longitude",
                                 "units": "degrees_east"}),
        },
        attrs={"title": "Precipitacao diaria IMERG para o Risco de Fogo",
               "source": origem,
               "history": f"prepara_imerg.py em {dt.datetime.now():%Y-%m-%d %H:%M}"},
    )
    ds.to_netcdf(caminho, format="NETCDF4_CLASSIC",
                 encoding={"prec": {"dtype": "float32", "zlib": True,
                                    "complevel": 4},
                           "time": {"units": "hours since 1900-01-01",
                                    "calendar": "standard",
                                    "dtype": "float64"}})
    return True


# ---------------------------------------------------------------------------
# Programa principal
# ---------------------------------------------------------------------------

def main():
    parser = argparse.ArgumentParser(
        description="Baixa o IMERG diário (GES DISC) e converte para o "
                    "padrão do Risco de Fogo.")
    parser.add_argument("--inicio", default=None,
                        help="Primeiro dia YYYYMMDD do período.")
    parser.add_argument("--fim", default=None,
                        help="Último dia YYYYMMDD do período.")
    parser.add_argument("--data-final", default=None,
                        help="Alternativa: gera a janela de --dias dias "
                             "terminando na VÉSPERA desta data (a janela "
                             "do RF para uma rodada).")
    parser.add_argument("--dias", type=int, default=119,
                        help="Tamanho da janela com --data-final "
                             "(padrão: 119).")
    parser.add_argument("--produto", default="early",
                        choices=["early", "late", "final"],
                        help="early (padrão, ~4 h de latência), late "
                             "(~14 h) ou final (pesquisa, meses).")
    parser.add_argument("--dominio", default=DOMINIO_PADRAO,
                        help=f"latS,latN,lonW,lonE (padrão: {DOMINIO_PADRAO}).")
    parser.add_argument("--base", default=None)
    parser.add_argument("--config", default=None,
                        help="config.yaml do pipeline (destino: seção "
                             "'caminhos' — imerg_dir/subpastas/padrão).")
    parser.add_argument("--jobs", type=int, default=4,
                        help="Downloads simultâneos (padrão: 4).")
    parser.add_argument("--sobrescrever", action="store_true")
    parser.add_argument("--simular", action="store_true")
    args = parser.parse_args()

    import rf_config
    cfg = rf_config.carrega(args.config) if args.config else rf_config.padrao()
    base = (args.base or cfg["base"]).rstrip("/")
    caminhos = cfg["caminhos"]

    # ------------------------------------------------------------- período
    if args.inicio and args.fim:
        d0 = dt.datetime.strptime(args.inicio, "%Y%m%d")
        d1 = dt.datetime.strptime(args.fim, "%Y%m%d")
    else:
        ref = (dt.datetime.strptime(args.data_final, "%Y%m%d")
               if args.data_final else
               dt.datetime.now(dt.timezone.utc).replace(tzinfo=None,
                                                        hour=0, minute=0,
                                                        second=0,
                                                        microsecond=0))
        d1 = ref - dt.timedelta(days=1)          # véspera da rodada
        d0 = ref - dt.timedelta(days=args.dias)
    if d1 < d0:
        sys.exit("Erro: fim anterior ao início.")

    dias = [d0 + dt.timedelta(days=i) for i in range((d1 - d0).days + 1)]
    dominio = tuple(float(x) for x in args.dominio.split(","))

    faltam = [d for d in dias if args.sobrescrever or
              not os.path.exists(rf_config.caminho_imerg(base, caminhos, d))]

    print(f"Produto:  IMERG {args.produto} diário V07 (GES DISC)")
    print(f"Período:  {d0:%Y-%m-%d} a {d1:%Y-%m-%d} ({len(dias)} dias; "
          f"{len(faltam)} a baixar, {len(dias)-len(faltam)} já existem)")
    print(f"Destino:  {rf_config.caminho_imerg(base, caminhos, d0)}")
    print(f"Domínio:  lat [{dominio[0]}, {dominio[1]}], "
          f"lon [{dominio[2]}, {dominio[3]}]")

    if not args.config and not args.base and base == rf_config.BASE_PADRAO:
        print("AVISO: rodando com o diretório base PADRÃO da produção "
              f"({rf_config.BASE_PADRAO}).\n"
              "       Se este não é o destino desejado, use "
              "--config config.yaml (ou --base DIR).", file=sys.stderr)

    # Falha cedo se o destino não for gravável (antes de baixar qualquer
    # coisa) — evita descobrir o problema só no fim do primeiro download.
    if faltam and not args.simular:
        destino_teste = rf_config.caminho_imerg(base, caminhos, faltam[0])
        try:
            os.makedirs(os.path.dirname(destino_teste), exist_ok=True)
        except OSError as exc:
            sys.exit(f"Erro: não consigo criar o diretório de destino "
                     f"({exc}).\nConfira o caminho acima — provavelmente "
                     f"falta --config config.yaml (ou --base).")

    if args.simular:
        for d in faltam[:3] + (["..."] if len(faltam) > 5 else []) + faltam[-2:]:
            if d == "...":
                print("  ...")
                continue
            print("  " + URLS[args.produto].format(
                ano=d.strftime("%Y"), mes=d.strftime("%m"),
                data=d.strftime("%Y%m%d"), versao=VERSOES[0]))
        return
    if not faltam:
        print("Nada a fazer.")
        return

    opener = monta_opener()
    t0 = time.time()
    erros = []

    print(f"Baixando com {args.jobs} conexão(ões) — cada dia transfere "
          f"~25 MB do arquivo global e grava ~2–3 MB recortados...",
          flush=True)

    def processa(d):
        bruto, url = baixa_dia(opener, args.produto, d)     # rede: paralelo
        with _LOCK_NETCDF:                                   # HDF5: serializado
            prec, la, lo = converte(bruto, dominio, d)
            destino = rf_config.caminho_imerg(base, caminhos, d)
            grava_padrao(destino, prec, la, lo, d, url, args.sobrescrever)
        return len(bruto) if hasattr(bruto, "__len__") else 0

    with concurrent.futures.ThreadPoolExecutor(max_workers=args.jobs) as ex:
        futuros = {ex.submit(processa, d): d for d in faltam}
        feitos = 0
        for fut in concurrent.futures.as_completed(futuros):
            d = futuros[fut]
            feitos += 1
            decorrido = time.time() - t0
            resta = decorrido / feitos * (len(faltam) - feitos)
            try:
                nbytes = fut.result()
                print(f"  OK   {d:%Y-%m-%d}  ({feitos}/{len(faltam)}, "
                      f"{nbytes/1e6:.0f} MB, {decorrido:.0f}s decorridos, "
                      f"restam ~{resta/60:.0f} min)", flush=True)
            except Exception as exc:  # noqa: BLE001
                erros.append((d, str(exc)))
                print(f"  ERRO {d:%Y-%m-%d}  ({feitos}/{len(faltam)}): "
                      f"{exc}", file=sys.stderr, flush=True)

    ok = len(faltam) - len(erros)
    print(f"\nConcluído em {time.time()-t0:.0f}s: {ok} dias gravados"
          + (f", {len(erros)} com erro" if erros else ""))
    if erros:
        print("Dias com erro (rode novamente para completar):",
              ", ".join(d.strftime("%Y-%m-%d") for d, _ in erros))
        sys.exit(1)


if __name__ == "__main__":
    main()
