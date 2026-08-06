#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
prepara_mswep.py
================

Converte a precipitação diária observada do **MSWEP** (Multi-Source
Weighted-Ensemble Precipitation) para o padrão de leitura do Risco de
Fogo — o mesmo padrão gravado pelo ``prepara_imerg.py``:

    {mswep_conv_dir}/{ano}/{mes}/
        INPE_FireRiskModel_2.2_Precipitation_MSWEP_{AAAAMMDD}.nc
    -> variável `prec` (mm/dia), lat sul→norte, domínio recortado

Diferente do IMERG, o MSWEP **não é baixado**: os arquivos já estão no
disco do CPTEC, por exemplo em

    /pesq/dados/sismom/SisMOM/sipec/mswep/daily/{ano}/{mes}/{AAAAMMDD}.nc

com grade global de 0,1° (3600 x 1800), longitude −179,95..179,95 e
latitude de 89,95 a −89,95 (norte→sul). A conversão recorta o domínio,
inverte a latitude e renomeia a variável.

CONVERTER É OPCIONAL. Com ``precipitacao: modo: in_loco`` (padrão) o
pipeline lê os arquivos originais direto, recortando o domínio na
leitura. A conversão vale a pena quando:
  - a janela de 120 dias é relida muitas vezes (rodadas diárias), pois
    cada arquivo convertido tem ~2 MB em vez de ~7 MB globais;
  - o disco do MSWEP é lento ou fica indisponível na hora da rodada;
  - se quer congelar uma versão do banco para reprocessamento.

Exemplos:

    # Converte a janela de 119 dias que antecede hoje
    python3 prepara_mswep.py --config config.yaml

    # Período explícito
    python3 prepara_mswep.py --config config.yaml \
        --inicio 20230101 --fim 20230131

    # Só listar o que seria convertido
    python3 prepara_mswep.py --config config.yaml --simular

Depois de converter, use no config.yaml:

    precipitacao:
      fonte: mswep
      modo: convertido

Requisitos: numpy, xarray, netCDF4.
"""

import argparse
import datetime as dt
import os
import sys
import time

import numpy as np

import rf_config

MESES_ABREV = ("jan", "feb", "mar", "apr", "may", "jun",
               "jul", "aug", "sep", "oct", "nov", "dec")


# ---------------------------------------------------------------------------
# Leitura do MSWEP original
# ---------------------------------------------------------------------------

def arquivo_mensal(caminho_diario, dia):
    """Caminho do arquivo mensal (jan.nc, feb.nc, ...) que costuma
    acompanhar os diários na mesma pasta — usado como reserva quando o
    arquivo do dia não existe."""
    pasta = os.path.dirname(caminho_diario)
    return os.path.join(pasta, MESES_ABREV[dia.month - 1] + ".nc")


def le_dia(caminho, dia, dominio, nome_var=None, mensal=False):
    """Lê um dia do MSWEP e devolve (prec[lat,lon], lat, lon) já
    recortado no domínio e com a latitude de sul para norte.

    ``mensal=True`` trata o arquivo como um mês inteiro e seleciona o
    passo de tempo correspondente ao dia pedido."""
    import rf_core

    if not mensal:
        dados, lat, lon = rf_core.le_precip_arquivo(caminho, nome_var,
                                                    dominio)
        if dados.shape[0] != 1:
            raise ValueError(
                f"{os.path.basename(caminho)} tem {dados.shape[0]} passos "
                f"de tempo (esperado 1) — use --mensal se for um arquivo "
                f"mensal.")
        return dados[0], lat, lon

    import xarray as xr
    with xr.open_dataset(caminho) as ds:
        nome = rf_core.nome_variavel_precip(ds, nome_var)
        nome_tempo = "time" if "time" in ds.dims else list(ds[nome].dims)[0]
        datas = ds[nome_tempo].values.astype("datetime64[D]")
        alvo = np.datetime64(dia.strftime("%Y-%m-%d"))
        idx = np.nonzero(datas == alvo)[0]
        if idx.size == 0:
            raise ValueError(f"{os.path.basename(caminho)} não contém "
                             f"{dia:%Y-%m-%d}.")
    # O passo de tempo é selecionado ANTES da leitura: um mês do MSWEP tem
    # 31 passos globais e só um deles interessa.
    dados, lat, lon = rf_core.le_precip_arquivo(caminho, nome_var, dominio,
                                                tempo=int(idx[0]))
    return dados[0], lat, lon


def grava_padrao(caminho, prec, lat, lon, dia, origem, sobrescrever=False):
    """Grava no padrão de leitura do pipeline (variável `prec`, mm/dia)."""
    import xarray as xr
    if os.path.exists(caminho) and not sobrescrever:
        return False
    os.makedirs(os.path.dirname(caminho), exist_ok=True)
    prec = np.where(np.isfinite(prec) & (prec >= 0), prec, np.nan)
    ds = xr.Dataset(
        {"prec": (("time", "lat", "lon"),
                  np.asarray(prec, dtype=np.float32)[np.newaxis],
                  {"long_name": "Daily accumulated precipitation (MSWEP)",
                   "units": "mm"})},
        coords={
            "time": [dt.datetime(dia.year, dia.month, dia.day)],
            "lat": ("lat", np.asarray(lat, dtype=np.float64),
                    {"standard_name": "latitude", "units": "degrees_north"}),
            "lon": ("lon", np.asarray(lon, dtype=np.float64),
                    {"standard_name": "longitude", "units": "degrees_east"}),
        },
        attrs={"title": "Precipitacao diaria MSWEP para o Risco de Fogo",
               "source": origem,
               "history": f"prepara_mswep.py em "
                          f"{dt.datetime.now():%Y-%m-%d %H:%M}"},
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
        description="Converte o MSWEP diário para o padrão do Risco de Fogo.")
    parser.add_argument("--inicio", default=None,
                        help="Primeiro dia YYYYMMDD do período.")
    parser.add_argument("--fim", default=None,
                        help="Último dia YYYYMMDD do período.")
    parser.add_argument("--data-final", default=None,
                        help="Alternativa: janela de --dias dias terminando "
                             "na VÉSPERA desta data (a janela do RF).")
    parser.add_argument("--dias", type=int, default=119,
                        help="Tamanho da janela com --data-final (119).")
    parser.add_argument("--dominio", default=None,
                        help="latS,latN,lonW,lonE (padrão: o de "
                             "'precipitacao: dominio' no config).")
    parser.add_argument("--variavel", default=None,
                        help="Nome da variável no arquivo original "
                             "(padrão: detecção automática).")
    parser.add_argument("--mensal", action="store_true",
                        help="Lê os arquivos mensais (jan.nc, feb.nc, ...) "
                             "em vez dos diários.")
    parser.add_argument("--origem", default=None,
                        help="Sobrepõe 'caminhos: mswep_dir'.")
    parser.add_argument("--base", default=None)
    parser.add_argument("--config", default=None,
                        help="config.yaml do pipeline.")
    parser.add_argument("--sobrescrever", action="store_true")
    parser.add_argument("--simular", action="store_true")
    args = parser.parse_args()

    cfg = rf_config.carrega(args.config) if args.config else rf_config.padrao()
    base = (args.base or cfg["base"]).rstrip("/")
    caminhos = dict(cfg["caminhos"])
    if args.origem:
        caminhos["mswep_dir"] = args.origem

    dominio = args.dominio or cfg["precipitacao"].get("dominio") \
        or rf_config.DOMINIO_PADRAO
    if isinstance(dominio, str):
        dominio = [float(x) for x in dominio.split(",")]
    dominio = tuple(float(x) for x in dominio)

    # ------------------------------------------------------------- período
    if args.inicio and args.fim:
        d0 = dt.datetime.strptime(args.inicio, "%Y%m%d")
        d1 = dt.datetime.strptime(args.fim, "%Y%m%d")
    else:
        ref = (dt.datetime.strptime(args.data_final, "%Y%m%d")
               if args.data_final else
               dt.datetime.now().replace(hour=0, minute=0, second=0,
                                         microsecond=0))
        d1 = ref - dt.timedelta(days=1)
        d0 = ref - dt.timedelta(days=args.dias)
    if d1 < d0:
        sys.exit("Erro: fim anterior ao início.")

    dias = [d0 + dt.timedelta(days=i) for i in range((d1 - d0).days + 1)]

    def destino(dia):
        return rf_config.caminho_mswep(base, caminhos, dia, convertido=True)

    faltam = [d for d in dias
              if args.sobrescrever or not os.path.exists(destino(d))]

    print("Produto:  MSWEP diário (arquivos locais)")
    print(f"Origem:   {rf_config.caminho_mswep(base, caminhos, d0)}")
    print(f"Destino:  {destino(d0)}")
    print(f"Período:  {d0:%Y-%m-%d} a {d1:%Y-%m-%d} ({len(dias)} dias; "
          f"{len(faltam)} a converter, {len(dias)-len(faltam)} já existem)")
    print(f"Domínio:  lat [{dominio[0]}, {dominio[1]}], "
          f"lon [{dominio[2]}, {dominio[3]}]")

    if args.simular:
        for d in faltam[:5]:
            origem = rf_config.caminho_mswep(base, caminhos, d)
            marca = "OK " if os.path.exists(origem) else "SEM"
            print(f"  {marca} {origem}")
        if len(faltam) > 5:
            print(f"  ... e mais {len(faltam)-5} dia(s)")
        print("(--simular: nada foi convertido)")
        return

    if not faltam:
        print("Nada a fazer.")
        return

    t0 = time.time()
    erros = []
    feitos = 0
    for d in faltam:
        origem = rf_config.caminho_mswep(base, caminhos, d)
        mensal = args.mensal
        if mensal:                       # --mensal: jan.nc, feb.nc, ...
            origem = arquivo_mensal(origem, d)
        elif not os.path.exists(origem):
            alternativa = arquivo_mensal(origem, d)
            if os.path.exists(alternativa):
                origem, mensal = alternativa, True
        try:
            if not os.path.exists(origem):
                raise FileNotFoundError(origem)
            prec, lat, lon = le_dia(origem, d, dominio, args.variavel, mensal)
            grava_padrao(destino(d), prec, lat, lon, d, origem,
                         args.sobrescrever)
            feitos += 1
            decorrido = time.time() - t0
            resta = decorrido / feitos * (len(faltam) - feitos)
            print(f"  OK   {d:%Y-%m-%d}  ({feitos}/{len(faltam)}, "
                  f"{prec.shape[0]}x{prec.shape[1]} pontos, "
                  f"{decorrido:.0f}s decorridos, restam ~{resta/60:.1f} min)",
                  flush=True)
        except Exception as exc:  # noqa: BLE001
            erros.append((d, str(exc)))
            print(f"  ERRO {d:%Y-%m-%d}: {exc}", file=sys.stderr, flush=True)

    print(f"\nConcluído em {time.time()-t0:.0f}s: {feitos} dia(s) gravados"
          + (f", {len(erros)} com erro" if erros else ""))
    if erros:
        print("Dias com erro:",
              ", ".join(d.strftime("%Y-%m-%d") for d, _ in erros))
        sys.exit(1)


if __name__ == "__main__":
    main()
