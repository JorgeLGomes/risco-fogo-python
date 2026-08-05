# -*- coding: utf-8 -*-
"""
rf_observado.py
===============

**Risco de Fogo OBSERVADO**: calcula o RF de dias que já passaram usando
apenas dados observados — a precipitação diária do IMERG (os 120 dias que
antecedem e incluem cada dia analisado) e a temperatura/umidade relativa
da reanálise ERA5 na hora da análise (padrão 18 UTC).

É o complemento do rf_previsto.py: a mesma formulação do INPE
FireRiskModel 2.2 (rb_max 0.9, fatores FU/FT/FLAT/FTOP), mas alimentada
por observações, permitindo reconstituir o RF dos últimos dias, semanas
ou meses e comparar com as previsões.

Pré-requisitos (bancos de dados locais):
    python3 prepara_imerg.py --inicio ... --fim ...   # precipitação
    python3 prepara_era5.py  --inicio ... --fim ...   # T2m/UR2m (ERA5)

Uso
---
    # Últimos 7 dias disponíveis (a ERA5 atrasa ~5 dias)
    python3 rf_observado.py --config config.yaml --dias 7

    # Última semana / últimos 2 meses (períodos-calendário)
    python3 rf_observado.py --config config.yaml --semanas 1
    python3 rf_observado.py --config config.yaml --meses 2

    # Período explícito
    python3 rf_observado.py --config config.yaml --de 20260601 --ate 20260731

    # Sem os arquivos estáticos (vegetação/topografia indisponíveis)
    python3 rf_observado.py --config config.yaml --dias 7 \
        --sem-vegetacao --sem-topografia

Saída: RF.OBS.{data}{hora}.nc (e .tif) em
``{base}/data/output/2.2/{produto}/netcdf`` (produto padrão RF_OBS, com
sufixos _SEMVEG/_SEMTOPO quando os fatores são desligados).
"""

import argparse
import datetime as dt
import os
import sys
from concurrent.futures import ProcessPoolExecutor, as_completed

import numpy as np

import rf_config
import rf_core

PRODUTO_PADRAO = "RF_OBS"
ATRASO_ERA5_DIAS = 6


# ---------------------------------------------------------------------------
# Trabalho de um dia (roda em processo separado)
# ---------------------------------------------------------------------------

def processa_dia(parametros):
    """Calcula o RF observado de um dia. Devolve (data, ok, mensagem)."""
    data_analise = parametros["data_analise"]          # "YYYYMMDDHH"
    dir_log = parametros["dir_log"]
    os.makedirs(dir_log, exist_ok=True)
    arquivo_log = os.path.join(dir_log, f"log.rf.obs.{data_analise}.txt")

    with open(arquivo_log, "w") as flog:
        def log(msg=""):
            flog.write(str(msg) + "\n")
            flog.flush()

        try:
            log(f"RF OBSERVADO {data_analise} — IMERG + ERA5 "
                f"({dt.datetime.now():%Y-%m-%d %H:%M:%S})")

            # Precipitação: 120 dias observados terminando no dia analisado.
            lista_imerg = parametros["lista_imerg"]
            log("")
            log(f"Abrindo {len(lista_imerg)} arquivos de precipitação "
                f"(IMERG).")
            precip, lat_prec, lon_prec = rf_core.ler_precipitacao(
                lista_imerg, parametros["nome_var_precip"])

            # Temperatura e umidade: ERA5 na hora da análise.
            log("")
            log(f"Abrindo o ERA5: {parametros['arquivo_era5']}")
            t2m, ur2m, lat_met, lon_met = rf_core.ler_temp_ur(
                parametros["arquivo_era5"])

            arquivo_saida = parametros["arquivo_saida"]
            rf_core.calcula_risco_fogo_dados(
                precip_invertida=precip,
                lat_prec=lat_prec, lon_prec=lon_prec,
                t2m=t2m, ur2m=ur2m,
                lat_met=lat_met, lon_met=lon_met,
                arquivo_mapa_veg=parametros["arquivo_mapa_veg"],
                arquivo_topografia=parametros["arquivo_topografia"],
                arquivo_saida=arquivo_saida,
                data_previsao=data_analise,
                rb_maximo=parametros["rb_maximo"],
                titulo=f"Risco de fogo observado (IMERG+ERA5) "
                       f"{data_analise}",
                log=log,
                usar_vegetacao=parametros["usar_vegetacao"],
                usar_topografia=parametros["usar_topografia"],
                classe_veg_uniforme=parametros["classe_veg_uniforme"],
            )

            if not parametros["sem_tif"]:
                caminho_tif = parametros["arquivo_tif"]
                log("")
                log(f"Gerando o GeoTIFF: {caminho_tif}")
                rf_core.netcdf_para_geotiff(arquivo_saida, caminho_tif)

            log("")
            log("Concluído.")
            return data_analise, True, arquivo_saida
        except Exception as e:                       # noqa: BLE001
            log(f"ERRO: {e}")
            return data_analise, False, str(e)


# ---------------------------------------------------------------------------
# Resolução do período pedido
# ---------------------------------------------------------------------------

def _soma_meses(data, n):
    m = data.month - 1 + n
    ano = data.year + m // 12
    mes = m % 12 + 1
    import calendar
    dia = min(data.day, calendar.monthrange(ano, mes)[1])
    return data.replace(year=ano, month=mes, day=dia)


def resolve_periodo(args):
    """Devolve (data inicial, data final) do período analisado."""
    if args.de or args.ate:
        if not (args.de and args.ate):
            sys.exit("Erro: --de e --ate devem ser usados em conjunto.")
        d0 = dt.datetime.strptime(args.de, "%Y%m%d")
        d1 = dt.datetime.strptime(args.ate, "%Y%m%d")
        if d0 > d1:
            sys.exit("Erro: --de posterior a --ate.")
        return d0, d1

    if args.data_final and str(args.data_final).lower() not in (
            "hoje", "auto", "sistema"):
        fim = dt.datetime.strptime(str(args.data_final), "%Y%m%d")
    else:
        fim = (dt.datetime.utcnow().replace(hour=0, minute=0, second=0,
                                            microsecond=0)
               - dt.timedelta(days=ATRASO_ERA5_DIAS))

    if args.meses:
        inicio = _soma_meses(fim, -args.meses) + dt.timedelta(days=1)
    elif args.semanas:
        inicio = fim - dt.timedelta(days=7 * args.semanas - 1)
    else:
        inicio = fim - dt.timedelta(days=(args.dias or 7) - 1)
    return inicio, fim


# ---------------------------------------------------------------------------
# Programa principal
# ---------------------------------------------------------------------------

def main():
    parser = argparse.ArgumentParser(
        description="Risco de Fogo OBSERVADO (IMERG + ERA5) para os "
                    "últimos dias, semanas ou meses.")
    grupo = parser.add_mutually_exclusive_group()
    grupo.add_argument("--dias", type=int, default=None,
                       help="Analisa os últimos N dias (padrão: 7).")
    grupo.add_argument("--semanas", type=int, default=None,
                       help="Analisa as últimas N semanas (7×N dias).")
    grupo.add_argument("--meses", type=int, default=None,
                       help="Analisa os últimos N meses-calendário.")
    parser.add_argument("--de", default=None,
                        help="Início do período YYYYMMDD (com --ate).")
    parser.add_argument("--ate", default=None,
                        help="Fim do período YYYYMMDD (com --de).")
    parser.add_argument("--data-final", default=None,
                        help="Fim da janela de --dias/--semanas/--meses "
                             f"(padrão: {ATRASO_ERA5_DIAS} dias atrás — "
                             "atraso da ERA5; aceita 'hoje').")
    parser.add_argument("--hora", default="18",
                        help="Hora UTC da análise (padrão: 18).")
    parser.add_argument("--rb-max", type=float, default=0.9,
                        help="Risco básico máximo (padrão: 0.9).")
    parser.add_argument("--produto", default=PRODUTO_PADRAO,
                        help=f"Nome do produto (padrão: {PRODUTO_PADRAO}).")
    parser.add_argument("--base", default=None,
                        help="Diretório base (padrão: da configuração).")
    parser.add_argument("--jobs", type=int, default=4,
                        help="Dias processados em paralelo (padrão: 4).")
    parser.add_argument("--sem-tif", action="store_true",
                        help="Não gera os GeoTIFF.")
    parser.add_argument("--sem-vegetacao", action="store_true",
                        help="Desliga o efeito da vegetação (mapa NÃO é "
                             "lido; classe uniforme --classe-veg; saída na "
                             "grade da precipitação). Sufixo _SEMVEG.")
    parser.add_argument("--sem-topografia", action="store_true",
                        help="Desliga o Fator Topográfico (FTOP=1; arquivo "
                             "dispensado). Sufixo _SEMTOPO.")
    parser.add_argument("--classe-veg", type=int, default=4,
                        help="Classe usada com --sem-vegetacao (padrão 4).")
    parser.add_argument("--config", default=None,
                        help="Arquivo YAML/JSON de configuração (base, "
                             "caminhos do IMERG/ERA5/vegetação etc.).")
    parser.add_argument("--simular", action="store_true",
                        help="Só lista os dias e confere os arquivos de "
                             "entrada (não calcula).")
    args = parser.parse_args()

    cfg = (rf_config.carrega(args.config) if args.config
           else rf_config.padrao())
    base = (args.base or cfg["base"]).rstrip("/")
    caminhos = cfg["caminhos"]
    hora = int(args.hora)

    inicio, fim = resolve_periodo(args)
    dias_analise = [inicio + dt.timedelta(days=i)
                    for i in range((fim - inicio).days + 1)]

    produto = args.produto
    if args.sem_vegetacao:
        produto += "_SEMVEG"
    if args.sem_topografia:
        produto += "_SEMTOPO"

    dir_output_netcdf = f"{base}/data/output/2.2/{produto}/netcdf"
    dir_output_tif = f"{base}/data/output/2.2/{produto}/tif"
    dir_log = rf_config.resolve(base, caminhos["log"])

    ano_mapa_veg = "2019" if fim.year >= 2020 else str(fim.year)
    arquivo_mapa_veg = rf_config.resolve(
        base, caminhos["mapa_vegetacao"].format(ano_veg=ano_mapa_veg))
    arq_topografia = rf_config.resolve(base, caminhos["topografia"])

    print(f"RF OBSERVADO: {inicio:%Y%m%d} a {fim:%Y%m%d} às {hora:02d} UTC "
          f"({len(dias_analise)} dia(s))")
    print(f"produto: >>{produto}")
    print(f"saida: >>>>{dir_output_netcdf}")

    # -----------------------------------------------------------------------
    # Monta os trabalhos, conferindo as entradas de cada dia
    # -----------------------------------------------------------------------
    trabalhos = []
    incompletos = []
    for dia in dias_analise:
        quando = dia.replace(hour=hora)
        data_analise = quando.strftime("%Y%m%d%H")

        faltas = []
        lista_imerg = []
        for k in range(119, -1, -1):                 # ordem cronológica
            d = dia - dt.timedelta(days=k)
            caminho = rf_config.caminho_imerg(base, caminhos, d)
            if os.path.exists(caminho):
                lista_imerg.append(caminho)
            else:
                faltas.append(caminho)

        arquivo_era5 = rf_config.caminho_era5(base, caminhos, quando, hora)
        if not os.path.exists(arquivo_era5):
            faltas.append(arquivo_era5)

        if faltas:
            incompletos.append((data_analise, faltas))
            continue

        trabalhos.append({
            "data_analise": data_analise,
            "lista_imerg": lista_imerg,
            "nome_var_precip": "prec",
            "arquivo_era5": arquivo_era5,
            "arquivo_mapa_veg": arquivo_mapa_veg,
            "arquivo_topografia": arq_topografia,
            "arquivo_saida": os.path.join(
                dir_output_netcdf, f"RF.OBS.{data_analise}.nc"),
            "arquivo_tif": os.path.join(
                dir_output_tif, f"RF.OBS.{data_analise}.tif"),
            "rb_maximo": args.rb_max,
            "dir_log": dir_log,
            "sem_tif": args.sem_tif,
            "usar_vegetacao": not args.sem_vegetacao,
            "usar_topografia": not args.sem_topografia,
            "classe_veg_uniforme": args.classe_veg,
        })

    if incompletos:
        print(f"Aviso: {len(incompletos)} dia(s) sem entradas completas "
              f"serão pulados:", file=sys.stderr)
        for data_analise, faltas in incompletos:
            exemplo = os.path.basename(faltas[0])
            print(f"  {data_analise}: faltam {len(faltas)} arquivo(s) "
                  f"(ex.: {exemplo})", file=sys.stderr)
        print("  -> rode prepara_imerg.py / prepara_era5.py para o "
              "período.", file=sys.stderr)

    if args.simular:
        for t in trabalhos:
            print(f"  {t['data_analise']}: {len(t['lista_imerg'])} IMERG + "
                  f"{os.path.basename(t['arquivo_era5'])}")
        print(f"(--simular: nada foi calculado; {len(trabalhos)} dia(s) "
              f"prontos, {len(incompletos)} incompletos)")
        return

    if not trabalhos:
        sys.exit("Nenhum dia com entradas completas para calcular.")

    os.makedirs(dir_output_netcdf, exist_ok=True)
    if not args.sem_tif:
        os.makedirs(dir_output_tif, exist_ok=True)

    # -----------------------------------------------------------------------
    # Execução em paralelo
    # -----------------------------------------------------------------------
    ok = erros = 0
    with ProcessPoolExecutor(max_workers=args.jobs) as executor:
        futuros = {executor.submit(processa_dia, t): t["data_analise"]
                   for t in trabalhos}
        for futuro in as_completed(futuros):
            data_analise, sucesso, info = futuro.result()
            if sucesso:
                ok += 1
                print(f"OK   {data_analise}: {info}")
            else:
                erros += 1
                print(f"ERRO {data_analise}: {info}", file=sys.stderr)

    print(f"Concluído: {ok} dia(s) calculados, {erros} erro(s), "
          f"{len(incompletos)} pulado(s) por falta de entradas.")
    if erros:
        sys.exit(1)


if __name__ == "__main__":
    main()
