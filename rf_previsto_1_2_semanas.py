#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
rf_previsto_1_2_semanas.py
==========================

Risco de fogo previsto de 1 km utilizando a temperatura, umidade relativa e a
precipitação do GFS, para os horizontes de 1 e 2 semanas (7 e 14 dias).

Conversão para Python do script "rf_previsto_1-2_semanas_2024.sh" (bash + NCL),
substituindo todas as bibliotecas NCL, o cdo e o gdal_translate por Python
(numpy/xarray/netCDF4/rasterio).

Adaptação original por Pedro Lagden para rodar na máquina popore.met.inpe.br.

Uso:
    python3 rf_previsto_1_2_semanas.py [--data-final YYYYMMDD] [--jobs N] [--sem-envio]

Tempo total de execução original: aproximadamente 3h00.
"""

import argparse
import datetime as dt
import glob
import os
import shutil
import subprocess
import sys
import time
from concurrent.futures import ProcessPoolExecutor

import rf_core

# ---------------------------------------------------------------------------
# Configurações (mesmos diretórios do script original)
# ---------------------------------------------------------------------------

BASE = "/home/queimadas/INPE_FireRiskModel"

# Previsão do GFS de Temperatura (K), Umidade Relativa (%) e precipitação (mm/dia).
DIRIN_GFS_BASE = f"{BASE}/data/output/2.2/GFS/netcdf"
# Dado observado de precipitação do IMERG (mm/dia).
DIRIN_IMERG = f"{BASE}/data/output/2.2/Precipitation-2_2"
# Diretórios de saída das previsões (NetCDF e GeoTIFF).
DIR_OUTPUT_NETCDF_BASE = f"{BASE}/data/output/2.2/RF_PREV_SEMANAL/netcdf"
DIR_OUTPUT_TIF_BASE = f"{BASE}/data/output/2.2/RF_PREV_SEMANAL/tif"
DIR_TMP = f"{BASE}/tmp"          # Diretório temporário.
DIR_LOG = f"{BASE}/log"          # Arquivos de log para verificação de erros.
DIR_MAPFILES_TMP = f"{BASE}/dados/mapfiles/tmp"

# Mapa de vegetação e topografia (1 km).
DIR_MAPA_VEG = f"{BASE}/data/input/Veg_Map_2020"
ARQ_TOPOGRAFIA = f"{BASE}/data/input/topografia/GeoTOPOAmericaSulCentral_V3.nc"

RB_MAXIMO = 0.8        # Valor máximo do risco básico neste script.
N_PREVISOES = 2        # São geradas 2 previsões (7 e 14 dias).
JOBS_PADRAO = 2        # Equivalente ao "parallel -j 2".

# Envio para o geoserver terrabrasilis (lftp) e para o volume cianorte (scp).
LFTP_USUARIO = "helder"
LFTP_SENHA = "HelQuEim@da5"
LFTP_SERVIDOR = "sftp://150.163.2.29"
LFTP_DIR_REMOTO = ("/dados/vms/cluster/geoserver/cluster/"
                   "gs_datadir/data_file")
SCP_DESTINO = ("pedro.lagden@150.163.212.54:"
               "/prod_qmd2/INPE_FireRiskModel/data/output/2.2/RF_PREV/tif/")


# ---------------------------------------------------------------------------
# Função executada em paralelo para cada horário de previsão
# ---------------------------------------------------------------------------

def processa_previsao(parametros):
    """Calcula o RF de um horário de previsão (substitui um script NCL)."""
    data_modelo = parametros["data_modelo"]
    data_previsao = parametros["data_previsao"]
    arquivo_log = os.path.join(DIR_LOG, f"log.{data_modelo}.{data_previsao}")

    try:
        with open(arquivo_log, "a") as flog:
            def log(msg=""):
                flog.write(str(msg) + "\n")
                flog.flush()

            rf_core.calcula_risco_fogo(
                arquivo_temp_ur=parametros["arquivo_temp_ur"],
                lista_arquivos_prec=parametros["lista_arquivos_prec"],
                arquivo_mapa_veg=parametros["arquivo_mapa_veg"],
                arquivo_topografia=ARQ_TOPOGRAFIA,
                arquivo_saida=parametros["arquivo_saida"],
                data_previsao=data_previsao,
                rb_maximo=RB_MAXIMO,
                log=log,
            )
        return (data_previsao, True, "")
    except Exception as exc:  # noqa: BLE001 - registra qualquer falha no log
        with open(arquivo_log, "a") as flog:
            flog.write(f"ERRO: {exc}\n")
        return (data_previsao, False, str(exc))


# ---------------------------------------------------------------------------
# Programa principal
# ---------------------------------------------------------------------------

def main():
    parser = argparse.ArgumentParser(
        description="Risco de fogo previsto (1 a 2 semanas) em Python.")
    parser.add_argument("--data-final", default=None,
                        help="Data final YYYYMMDD (padrão: hoje).")
    parser.add_argument("--jobs", type=int, default=JOBS_PADRAO,
                        help=f"Número de processos paralelos (padrão: {JOBS_PADRAO}).")
    parser.add_argument("--sem-envio", action="store_true",
                        help="Não envia os arquivos para os servidores (lftp/scp).")
    args = parser.parse_args()

    tempo_inicial = time.time()  # NÃO DELETAR: usado no tempo de máquina.

    # -----------------------------------------------------------------------
    # Datas (equivalentes às do script original)
    # -----------------------------------------------------------------------
    if args.data_final:
        hoje = dt.datetime.strptime(args.data_final, "%Y%m%d")
    else:
        hoje = dt.datetime.now().replace(hour=0, minute=0, second=0,
                                         microsecond=0)

    data_final = hoje.strftime("%Y%m%d")
    data_inicial_dt = hoje - dt.timedelta(days=119)
    data_modelo = data_final + "00"
    ultima_previsao_dt = hoje + dt.timedelta(days=14, hours=18)
    # Prazo: dia seguinte às 18 UTC.
    data_prazo_dt = hoje + dt.timedelta(days=1, hours=18)

    ano = int(data_final[:4])
    # Ano do mapa de vegetação (disponível de 2001 até 2019).
    ano_mapa_veg = "2019" if ano >= 2020 else str(ano)
    arquivo_mapa_veg = os.path.join(
        DIR_MAPA_VEG, f"Merge_MapBiomas_V5_IGBP_C6_{ano_mapa_veg}.nc")

    dirin_gfs = os.path.join(DIRIN_GFS_BASE, data_modelo)
    dir_output_netcdf = os.path.join(DIR_OUTPUT_NETCDF_BASE, data_modelo)
    dir_output_tif = os.path.join(DIR_OUTPUT_TIF_BASE, data_modelo)

    os.makedirs(dir_output_netcdf, exist_ok=True)
    os.makedirs(dir_output_tif, exist_ok=True)
    os.makedirs(DIR_LOG, exist_ok=True)

    print("inicio: >>>" + data_inicial_dt.strftime("%Y%m%d"))
    print("fim: >>>>>>" + data_final)
    print("modelo: >>>" + data_modelo)
    print("ult prev: >>>>>>" + ultima_previsao_dt.strftime("%Y%m%d%H"))

    # -----------------------------------------------------------------------
    # Lista dos 119 arquivos diários de precipitação do IMERG
    # -----------------------------------------------------------------------
    lista_imerg = []
    faltantes = []
    data_corrente = data_inicial_dt
    while data_corrente < hoje:
        ymd = data_corrente.strftime("%Y%m%d")
        nome = f"INPE_FireRiskModel_2.2_Precipitation_{ymd}.nc"
        caminho = os.path.join(DIRIN_IMERG, ymd[:4], ymd[4:6], nome)
        if os.path.exists(caminho):
            lista_imerg.append(caminho)
        else:
            faltantes.append(os.path.join(DIRIN_IMERG, nome))
        data_corrente += dt.timedelta(days=1)

    if faltantes:
        with open("log.falta.arquivos.prev.prec.txt", "a") as flog:
            flog.write("\n".join(faltantes) + "\n")

    # -----------------------------------------------------------------------
    # Monta a lista de trabalhos: 2 previsões (14 e 7 dias), de 7 em 7 dias.
    # -----------------------------------------------------------------------
    trabalhos = []
    previsao_dt = ultima_previsao_dt
    k = 1
    while previsao_dt >= data_prazo_dt:
        data_previsao = previsao_dt.strftime("%Y%m%d%H")
        print(data_previsao)

        arquivo_prec_gfs = os.path.join(
            dirin_gfs, f"GFS.PREV.PREC.{data_modelo}.{data_previsao}.nc")
        arquivo_temp_ur = os.path.join(
            dirin_gfs, f"GFS.PREV.TEMP2m.RH2m.{data_modelo}.{data_previsao}.nc")

        # As previsões do GFS para até 10 dias são a cada 6 horas e, do dia 11
        # até o dia 17, a cada 12 horas. A ideia foi copiar o arquivo das
        # 12 UTC para 18 UTC para não alterar a estrutura do script.
        if k == 1:
            data_12utc = (hoje + dt.timedelta(days=14, hours=12)).strftime("%Y%m%d%H")
            origem_prec = os.path.join(
                dirin_gfs, f"GFS.PREV.PREC.{data_modelo}.{data_12utc}.nc")
            origem_temp = os.path.join(
                dirin_gfs, f"GFS.PREV.TEMP2m.RH2m.{data_modelo}.{data_12utc}.nc")
            if os.path.exists(origem_prec):
                shutil.copy2(origem_prec, arquivo_prec_gfs)
            else:
                print(f"Aviso: arquivo não encontrado: {origem_prec}",
                      file=sys.stderr)
            if os.path.exists(origem_temp):
                shutil.copy2(origem_temp, arquivo_temp_ur)
            else:
                print(f"Aviso: arquivo não encontrado: {origem_temp}",
                      file=sys.stderr)
        k += 1

        # Lista com os 120 arquivos de precipitação (IMERG + GFS no final).
        lista_arquivos_prec = lista_imerg + [arquivo_prec_gfs]

        trabalhos.append({
            "data_modelo": data_modelo,
            "data_previsao": data_previsao,
            "arquivo_temp_ur": arquivo_temp_ur,
            "lista_arquivos_prec": lista_arquivos_prec,
            "arquivo_mapa_veg": arquivo_mapa_veg,
            "arquivo_saida": os.path.join(
                dir_output_netcdf, f"RF.PREV.{data_previsao}.nc"),
        })

        previsao_dt -= dt.timedelta(days=7)

    # -----------------------------------------------------------------------
    # Executa todos os cálculos de forma paralela
    # (substitui o "parallel -j 2" + scripts NCL).
    # -----------------------------------------------------------------------
    with ProcessPoolExecutor(max_workers=args.jobs) as executor:
        resultados = list(executor.map(processa_previsao, trabalhos))

    falhas = [r for r in resultados if not r[1]]
    for data_previsao, _, erro in falhas:
        print(f"ERRO na previsão {data_previsao}: {erro}", file=sys.stderr)

    # Verifica se as 2 previsões foram geradas.
    arquivos_gerados = sorted(
        glob.glob(os.path.join(dir_output_netcdf, "RF.PREV.*")))
    if len(arquivos_gerados) != N_PREVISOES:
        print(f" PROBLEMA - FALTAM ARQUIVOS EM {dir_output_netcdf}")
        sys.exit(1)

    # -----------------------------------------------------------------------
    # Geração dos GeoTIFF e links D1..D2
    # (o ajuste do eixo de tempo e do valor ausente, antes feito pelo cdo,
    #  já é feito na escrita do NetCDF em rf_core.grava_netcdf_rf).
    # -----------------------------------------------------------------------
    dia = 2
    previsao_dt = ultima_previsao_dt
    while previsao_dt >= data_prazo_dt:
        data_previsao = previsao_dt.strftime("%Y%m%d%H")
        print(data_previsao)

        arquivo_rf_prev = os.path.join(
            dir_output_netcdf, f"RF.PREV.{data_previsao}.nc")
        arquivo_tif = os.path.join(
            dir_output_tif, f"RF.PREV.{data_previsao}.tif")

        # Gera o arquivo TIF a partir do NetCDF (substitui o gdal_translate).
        rf_core.netcdf_para_geotiff(arquivo_rf_prev, arquivo_tif)

        if previsao_dt.hour == 18:
            os.makedirs(DIR_MAPFILES_TMP, exist_ok=True)
            link = os.path.join(DIR_MAPFILES_TMP, f"RF.PREV.D{dia}.tif")
            if os.path.lexists(link):
                os.remove(link)
            os.symlink(arquivo_tif, link)

            # A pedido do Jonatas - GM: 10/03/2021.
            shutil.copy2(arquivo_tif, os.path.join(
                dir_output_tif, f"RF.PREV.T{dia - 1}.{data_previsao}.tif"))

            print(f"{data_previsao} --- {dia}")
            dia -= 1

        previsao_dt -= dt.timedelta(days=7)

    # -----------------------------------------------------------------------
    # Renomeia: T0 (7 dias) -> RF.PREV.T7.tif e T1 (14 dias) -> RF.PREV.T14.tif
    # -----------------------------------------------------------------------
    tif_t7 = os.path.join(dir_output_tif, "RF.PREV.T7.tif")
    tif_t14 = os.path.join(dir_output_tif, "RF.PREV.T14.tif")

    for padrao, destino in ((r"RF.PREV.T0.*18.tif", tif_t7),
                            (r"RF.PREV.T1.*18.tif", tif_t14)):
        encontrados = glob.glob(os.path.join(dir_output_tif, padrao))
        if encontrados:
            shutil.copy2(encontrados[0], destino)
        else:
            print(f"Aviso: nenhum arquivo encontrado para {padrao}",
                  file=sys.stderr)

    # Remove os GeoTIFF com data no nome (rm RF.PREV.2*.tif).
    for arq in glob.glob(os.path.join(dir_output_tif, "RF.PREV.2*.tif")):
        os.remove(arq)

    # -----------------------------------------------------------------------
    # Envio dos arquivos para os servidores.
    # -----------------------------------------------------------------------
    if not args.sem_envio:
        # Envio via lftp para a área do geoserver terrabrasilis.
        for tif in (tif_t7, tif_t14):
            comando = (f'cd {LFTP_DIR_REMOTO}; put "{tif}" ; quit')
            subprocess.run(
                ["lftp", "-u", f"{LFTP_USUARIO},{LFTP_SENHA}",
                 LFTP_SERVIDOR, "-e", comando],
                check=False)

        # Envio via scp para a área de dados do volume cianorte / geoserver.
        for tif in (tif_t7, tif_t14):
            subprocess.run(["scp", tif, SCP_DESTINO], check=False)

    # Tempo de máquina utilizado.
    decorrido = int(time.time() - tempo_inicial)
    print(" Tempo gasto: "
          + str(dt.timedelta(seconds=decorrido)).rjust(8, "0"))


if __name__ == "__main__":
    main()
