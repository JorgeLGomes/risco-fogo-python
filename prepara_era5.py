# -*- coding: utf-8 -*-
"""
prepara_era5.py
===============

Baixa a reanálise **ERA5** (Copernicus/ECMWF) e converte para o padrão de
leitura do Risco de Fogo. Variáveis: temperatura a 2 m (t2m), umidade
relativa a 2 m (calculada de t2m + ponto de orvalho td2m) e vento a 10 m
(u10, v10).

Arquivos gerados (convenção do pipeline, lidos por rf_core.ler_temp_ur):

    ERA5.OBS.TEMP2m.RH2m.{data}{hora}.nc  -> TEMP2m (K) e RH2m (%)
    ERA5.OBS.U10m.V10m.{data}{hora}.nc    -> U10m e V10m (m/s)

em ``{base}/data/output/2.2/ERA5/netcdf`` (configurável via --config:
chaves ``era5_dir``, ``era5_padrao`` e ``era5_padrao_vento``).

Acesso ao CDS (Climate Data Store)
----------------------------------
O download usa a API oficial do CDS (``pip install cdsapi``). É preciso:

1. Criar conta em https://cds.climate.copernicus.eu e aceitar a licença
   do dataset "ERA5 hourly data on single levels" (uma única vez, no site).
2. Criar o arquivo ``~/.cdsapirc`` com o token pessoal (página do usuário):

       url: https://cds.climate.copernicus.eu/api
       key: SEU-TOKEN-PESSOAL

   (``chmod 600 ~/.cdsapirc``)

A ERA5 tem atraso de ~5 dias (dados recentes vêm do produto preliminar
ERA5T, mesmo dataset). Por isso o padrão da janela termina 6 dias atrás.

Uso
---
    # Últimos 7 dias disponíveis (termina 6 dias atrás), 18 UTC
    python3 prepara_era5.py --config config.yaml

    # Período explícito
    python3 prepara_era5.py --inicio 20260601 --fim 20260731

    # Janela de N dias terminando numa data (p/ compor com rf_observado)
    python3 prepara_era5.py --data-final 20260730 --dias 120

    # Só mostrar o plano (sem baixar)
    python3 prepara_era5.py --inicio 20260601 --fim 20260731 --simular

As requisições ao CDS são agrupadas por mês (mais eficiente na fila do
Copernicus). Dias cujos dois arquivos de saída já existem são pulados
(use --sobrescrever para refazer).
"""

import argparse
import datetime as dt
import os
import sys
import tempfile
import zipfile

import numpy as np

import rf_config

# ---------------------------------------------------------------------------
# Constantes
# ---------------------------------------------------------------------------

DATASET_CDS = "reanalysis-era5-single-levels"
VARIAVEIS_CDS = [
    "2m_temperature",
    "2m_dewpoint_temperature",
    "10m_u_component_of_wind",
    "10m_v_component_of_wind",
]
DOMINIO_PADRAO = "-60.05,29.95,-114.95,-30.05"   # latS,latN,lonW,lonE
ATRASO_ERA5_DIAS = 6      # ERA5/ERA5T: ~5 dias de atraso; margem de 1

# Candidatos de nome por variável nos NetCDF do CDS (curto e longo).
CANDIDATOS = {
    "t2m": ("t2m", "2m_temperature", "VAR_2T", "2t"),
    "d2m": ("d2m", "2m_dewpoint_temperature", "VAR_2D", "2d"),
    "u10": ("u10", "10m_u_component_of_wind", "VAR_10U", "10u"),
    "v10": ("v10", "10m_v_component_of_wind", "VAR_10V", "10v"),
}


# ---------------------------------------------------------------------------
# Umidade relativa a partir de T e Td (fórmula de Magnus, sobre água)
# ---------------------------------------------------------------------------

def umidade_relativa(t2m_K, td2m_K):
    """UR (%) a partir da temperatura e do ponto de orvalho em Kelvin.
    Magnus (Alduchov & Eskridge 1996): es(T) = 6.1094*exp(17.625*T/(T+243.04)),
    T em °C; UR = 100*es(Td)/es(T), limitada a [0, 100]."""
    t = np.asarray(t2m_K, dtype=np.float64) - 273.15
    td = np.asarray(td2m_K, dtype=np.float64) - 273.15
    ur = 100.0 * (np.exp(17.625 * td / (td + 243.04)) /
                  np.exp(17.625 * t / (t + 243.04)))
    return np.clip(ur, 0.0, 100.0).astype(np.float32)


# ---------------------------------------------------------------------------
# Leitura do NetCDF vindo do CDS
# ---------------------------------------------------------------------------

def _acha_var(ds, chave):
    """Encontra a variável no dataset pelos nomes candidatos."""
    for nome in CANDIDATOS[chave]:
        if nome in ds.variables:
            return ds[nome]
    raise RuntimeError(
        f"Variável '{chave}' não encontrada no NetCDF do CDS "
        f"(candidatos: {CANDIDATOS[chave]}; presentes: "
        f"{sorted(ds.data_vars)}).")


def _eixo_tempo(ds):
    for nome in ("valid_time", "time"):
        if nome in ds.variables or nome in ds.coords:
            return nome
    raise RuntimeError("Eixo de tempo não encontrado (time/valid_time).")


def le_cds_netcdf(caminho):
    """Lê o NetCDF (possivelmente zipado) devolvido pelo CDS e devolve
    (tempos [datetime], t2m, d2m, u10, v10, lat S->N, lon), com os campos
    em (nt, nlat, nlon) e a latitude já invertida para sul->norte."""
    import xarray as xr

    if zipfile.is_zipfile(caminho):
        # CDS pode entregar um .zip com um ou mais .nc dentro.
        with zipfile.ZipFile(caminho) as z:
            membros = [m for m in z.namelist() if m.endswith(".nc")]
            if not membros:
                raise RuntimeError("ZIP do CDS sem arquivos .nc.")
            destino = tempfile.mkdtemp(prefix="era5_")
            extraidos = [z.extract(m, destino) for m in membros]
        conjuntos = [xr.open_dataset(c, decode_times=True)
                     for c in extraidos]
        ds = conjuntos[0] if len(conjuntos) == 1 else xr.merge(conjuntos)
    else:
        ds = xr.open_dataset(caminho, decode_times=True)

    with ds:
        nome_t = _eixo_tempo(ds)
        tempos = list(np.asarray(ds[nome_t].values,
                                 dtype="datetime64[s]").tolist())
        nome_lat = "latitude" if "latitude" in ds.coords else "lat"
        nome_lon = "longitude" if "longitude" in ds.coords else "lon"
        lat = np.asarray(ds[nome_lat].values, dtype=np.float64)
        lon = np.asarray(ds[nome_lon].values, dtype=np.float64)
        lon = np.where(lon > 180.0, lon - 360.0, lon)

        campos = {}
        for chave in ("t2m", "d2m", "u10", "v10"):
            v = _acha_var(ds, chave)
            dados = np.asarray(v.values, dtype=np.float32)
            # Descarta eixos extras (ex.: expver do ERA5T) ficando com
            # (tempo, lat, lon): eixos de tamanho 1 são espremidos; se o
            # expver tiver 2 membros, combina preferindo o valor válido.
            while dados.ndim > 3:
                if dados.shape[1] == 1:
                    dados = dados[:, 0]
                else:
                    dados = np.where(np.isnan(dados[:, 0]),
                                     dados[:, 1], dados[:, 0])
            campos[chave] = dados

    if lat[0] > lat[-1]:          # ERA5 vem norte->sul: inverte
        lat = lat[::-1]
        for chave in campos:
            campos[chave] = campos[chave][:, ::-1, :]

    return (tempos, campos["t2m"], campos["d2m"],
            campos["u10"], campos["v10"], lat, lon)


# ---------------------------------------------------------------------------
# Escrita na convenção do pipeline
# ---------------------------------------------------------------------------

def grava_netcdf(caminho, variaveis, lat, lon, valida_dt, origem,
                 sobrescrever=False):
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
        attrs={"source": origem,
               "history": f"gerado em {dt.datetime.now():%Y-%m-%d %H:%M}"},
    )
    enc = {nome: {"dtype": "float32", "zlib": True, "complevel": 4}
           for nome in variaveis}
    enc["time"] = {"units": "hours since 1900-01-01 00:00:00",
                   "calendar": "standard", "dtype": "float64"}
    ds.to_netcdf(caminho, format="NETCDF4_CLASSIC", encoding=enc)
    return True


def converte_cds(caminho_cds, dir_saida, hora, caminhos, base,
                 sobrescrever=False, log=print):
    """Converte um NetCDF do CDS nos arquivos diários do pipeline.
    Devolve a lista de dias gravados."""
    tempos, t2m, d2m, u10, v10, lat, lon = le_cds_netcdf(caminho_cds)
    ur2m = umidade_relativa(t2m, d2m)
    gravados = []
    for i, quando in enumerate(tempos):
        if quando.hour != int(hora):
            continue
        arq_termo = rf_config.caminho_era5(base, caminhos, quando, hora)
        arq_vento = rf_config.caminho_era5(base, caminhos, quando, hora,
                                           vento=True)
        os.makedirs(os.path.dirname(arq_termo), exist_ok=True)
        novo1 = grava_netcdf(arq_termo,
                             {"TEMP2m": t2m[i], "RH2m": ur2m[i]},
                             lat, lon, quando,
                             "ERA5 (Copernicus CDS) - prepara_era5.py",
                             sobrescrever)
        novo2 = grava_netcdf(arq_vento,
                             {"U10m": u10[i], "V10m": v10[i]},
                             lat, lon, quando,
                             "ERA5 (Copernicus CDS) - prepara_era5.py",
                             sobrescrever)
        estado = "ok" if (novo1 or novo2) else "já existia"
        log(f"  {quando:%Y%m%d %H} UTC: {os.path.basename(arq_termo)} + "
            f"{os.path.basename(arq_vento)} ({estado})")
        gravados.append(quando)
    return gravados


# ---------------------------------------------------------------------------
# Download via cdsapi (agrupado por mês)
# ---------------------------------------------------------------------------

def agrupa_por_mes(dias):
    """[(ano, mes, [dias do mês])] em ordem cronológica."""
    grupos = {}
    for d in dias:
        grupos.setdefault((d.year, d.month), []).append(d.day)
    return [(a, m, sorted(ds)) for (a, m), ds in sorted(grupos.items())]


def baixa_mes(cliente, ano, mes, dias_do_mes, hora, dominio, destino):
    lat_s, lat_n, lon_w, lon_e = dominio
    pedido = {
        "product_type": ["reanalysis"],
        "variable": VARIAVEIS_CDS,
        "year": [f"{ano:04d}"],
        "month": [f"{mes:02d}"],
        "day": [f"{d:02d}" for d in dias_do_mes],
        "time": [f"{int(hora):02d}:00"],
        "area": [lat_n, lon_w, lat_s, lon_e],     # N, W, S, E
        "data_format": "netcdf",
        "download_format": "unarchived",
    }
    cliente.retrieve(DATASET_CDS, pedido, destino)
    return destino


# ---------------------------------------------------------------------------
# Programa principal
# ---------------------------------------------------------------------------

def _hoje_utc():
    """Data de hoje em UTC, à meia-noite (sem fuso, como o resto do
    pipeline). Substitui datetime.utcnow(), obsoleto no Python 3.12+."""
    return dt.datetime.now(dt.timezone.utc).replace(
        tzinfo=None, hour=0, minute=0, second=0, microsecond=0)


def resolve_periodo(args):
    """Devolve a lista de datas (datetime) pedidas."""
    if args.inicio or args.fim:
        if not (args.inicio and args.fim):
            sys.exit("Erro: --inicio e --fim devem ser usados em conjunto.")
        d0 = dt.datetime.strptime(args.inicio, "%Y%m%d")
        d1 = dt.datetime.strptime(args.fim, "%Y%m%d")
    else:
        if args.data_final:
            fim = dt.datetime.strptime(str(args.data_final), "%Y%m%d")
        else:
            fim = (_hoje_utc() - dt.timedelta(days=ATRASO_ERA5_DIAS))
        d1 = fim
        d0 = fim - dt.timedelta(days=args.dias - 1)
    if d0 > d1:
        sys.exit("Erro: período inválido (início depois do fim).")
    return [d0 + dt.timedelta(days=i) for i in range((d1 - d0).days + 1)]


def main():
    parser = argparse.ArgumentParser(
        description="Baixa a ERA5 (t2m, ur2m via td2m, u10, v10) do CDS e "
                    "converte para o padrão de leitura do RF.")
    parser.add_argument("--inicio", default=None,
                        help="Início do período YYYYMMDD (com --fim).")
    parser.add_argument("--fim", default=None,
                        help="Fim do período YYYYMMDD (com --inicio).")
    parser.add_argument("--data-final", default=None,
                        help="Fim da janela de --dias (padrão: "
                             f"{ATRASO_ERA5_DIAS} dias atrás — atraso da "
                             "ERA5/ERA5T).")
    parser.add_argument("--dias", type=int, default=7,
                        help="Tamanho da janela quando não há "
                             "--inicio/--fim (padrão: 7).")
    parser.add_argument("--hora", default="18",
                        help="Hora UTC da análise diária (padrão: 18, "
                             "compatível com os produtos do RF).")
    parser.add_argument("--dominio", default=DOMINIO_PADRAO,
                        help=f"latS,latN,lonW,lonE (padrão: "
                             f"{DOMINIO_PADRAO}).")
    parser.add_argument("--base", default=None,
                        help="Diretório base (padrão: da configuração).")
    parser.add_argument("--config", default=None,
                        help="Arquivo YAML/JSON de configuração "
                             "(chaves era5_dir/era5_padrao em caminhos).")
    parser.add_argument("--sobrescrever", action="store_true",
                        help="Regrava arquivos que já existem.")
    parser.add_argument("--simular", action="store_true",
                        help="Só mostra o plano (não baixa nada).")
    args = parser.parse_args()

    cfg = (rf_config.carrega(args.config) if args.config
           else rf_config.padrao())
    base = (args.base or cfg["base"]).rstrip("/")
    caminhos = cfg["caminhos"]

    dias = resolve_periodo(args)
    hora = int(args.hora)
    dominio = tuple(float(x) for x in args.dominio.split(","))

    # Pula dias completos (os dois arquivos já existem).
    pendentes = []
    for d in dias:
        quando = d.replace(hour=hora)
        arq1 = rf_config.caminho_era5(base, caminhos, quando, hora)
        arq2 = rf_config.caminho_era5(base, caminhos, quando, hora,
                                      vento=True)
        if args.sobrescrever or not (os.path.exists(arq1)
                                     and os.path.exists(arq2)):
            pendentes.append(d)

    print(f"ERA5: {dias[0]:%Y%m%d} a {dias[-1]:%Y%m%d} às {hora:02d} UTC "
          f"({len(dias)} dia(s); {len(dias) - len(pendentes)} já "
          f"existem, {len(pendentes)} a baixar)")
    print(f"Domínio: lat [{dominio[0]}, {dominio[1]}], "
          f"lon [{dominio[2]}, {dominio[3]}]")
    print(f"Destino: {rf_config.resolve(base, caminhos['era5_dir'])}")

    if not args.config and not args.base and base == rf_config.BASE_PADRAO:
        print(f"AVISO: usando o diretório base padrão "
              f"({rf_config.BASE_PADRAO}).\n"
              "       Para outro destino, use --config config.yaml, "
              "--base DIR ou a variável RF_BASE.", file=sys.stderr)
    if pendentes and not args.simular:
        try:
            os.makedirs(rf_config.resolve(base, caminhos["era5_dir"]),
                        exist_ok=True)
        except OSError as exc:
            sys.exit(f"Erro: não consigo criar o diretório de destino "
                     f"({exc}).\nConfira o caminho acima — provavelmente "
                     f"falta --config config.yaml (ou --base).")

    if not pendentes:
        print("Nada a fazer.")
        return
    grupos = agrupa_por_mes(pendentes)
    if args.simular:
        for ano, mes, ds in grupos:
            print(f"  requisição CDS: {ano:04d}-{mes:02d}, "
                  f"{len(ds)} dia(s): {ds}")
        print("(--simular: nada foi baixado)")
        return

    try:
        import cdsapi
    except ImportError:
        sys.exit("Erro: cdsapi não instalado — python3 -m pip install "
                 "cdsapi. É preciso também o ~/.cdsapirc com o token do "
                 "CDS (ver cabeçalho deste script).")

    try:
        cliente = cdsapi.Client()
    except Exception as e:
        sys.exit(f"Erro ao iniciar o cliente do CDS: {e}\n"
                 f"Confira o ~/.cdsapirc (url + key) — instruções no "
                 f"cabeçalho deste script.")

    total = 0
    for ano, mes, dias_do_mes in grupos:
        print(f"Baixando {ano:04d}-{mes:02d} ({len(dias_do_mes)} dia(s)) "
              f"— a fila do CDS pode levar alguns minutos...")
        bruto = os.path.join(tempfile.gettempdir(),
                             f"era5_{ano:04d}{mes:02d}_{hora:02d}.nc")
        try:
            baixa_mes(cliente, ano, mes, dias_do_mes, hora, dominio, bruto)
            gravados = converte_cds(bruto, None, hora, caminhos, base,
                                    args.sobrescrever)
            total += len(gravados)
        except Exception as e:
            print(f"ERRO em {ano:04d}-{mes:02d}: {e}", file=sys.stderr)
        finally:
            if os.path.exists(bruto):
                os.unlink(bruto)

    print(f"Concluído: {total} dia(s) convertidos.")


if __name__ == "__main__":
    main()
