#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
rf_previsto.py
==============

Risco de fogo previsto de 1 km para QUALQUER horizonte de previsão e
diferentes fontes de dados (GFS, Eta, BESM).

Generalização dos scripts rf_previsto_1_5dias.py (19 previsões a cada 6 h)
e rf_previsto_1_2_semanas.py (7 e 14 dias): os horizontes são informados na
linha de comando, como lista ou como intervalo, e todos os demais parâmetros
(fonte, rb máximo, diretório base, nome do produto, GeoTIFF, fogograma) são
configuráveis. Usa o mesmo núcleo de cálculo (rf_core.py).

Fontes de dados (--fonte, ver rf_fontes.py):
  - gfs  : até ~16 dias;
  - eta  : até 13 meses;
  - besm : até 13 meses.
Os acúmulos de precipitação de cada fonte podem vir em diferentes
frequências (1h, 12h, 1 dia) — são agregados para o passo diário.

SEM --fonte, o script usa a composição ORIGINAL dos produtos operacionais
(119 dias de IMERG observado + o acumulado do GFS do dia previsto).
COM --fonte, a série diária de 120 tempos que antecede cada data prevista
é montada de forma completa: IMERG observado até a véspera da rodada e
precipitação PREVISTA da fonte da rodada até a data válida — necessário
para horizontes longos (semanas a meses).

Exemplos de uso:

    # Um único horizonte: 36 horas após as 00 UTC de hoje
    python3 rf_previsto.py --horizontes 36h

    # Lista de horizontes: 1, 3, 7 e 14 dias às 18 UTC
    python3 rf_previsto.py --horizontes 18h,2d18h,6d18h,13d18h

    # Intervalo: de +6 h até +4 dias 18 UTC, a cada 6 h
    python3 rf_previsto.py --de 6h --ate 4d18h --passo 6h

    # Equivalente ao produto semanal, com fallback do GFS de 12 UTC
    python3 rf_previsto.py --horizontes 7d18h,14d18h --rb-max 0.8 --fallback-gfs

    # Eta: previsões mensais de 1 a 13 meses
    python3 rf_previsto.py --fonte eta --de 1m --ate 13m --passo 1m

    # BESM (acúmulos de 12 h agregados automaticamente): 6 meses
    python3 rf_previsto.py --fonte besm --horizontes 6m

    # Ajustando os padrões de nome/variáveis das fontes via JSON
    python3 rf_previsto.py --fonte eta --horizontes 3m --config-fontes fontes.json

Formato dos horizontes: "Nh" (horas), "Nd" (dias), "Nm" (meses de
calendário) e combinações "NmNdMh" — sempre contados a partir das 00 UTC
da data do modelo — ou uma data/hora absoluta "YYYYMMDDHH".
"""

import argparse
import datetime as dt
import os
import re
import shutil
import sys
import time
from concurrent.futures import ProcessPoolExecutor

import rf_config
import rf_core
import rf_fontes

# ---------------------------------------------------------------------------
# Valores padrão (mesma estrutura de diretórios da produção)
# ---------------------------------------------------------------------------

BASE_PADRAO = "/home/queimadas/INPE_FireRiskModel"
PRODUTO_PADRAO = "RF_PREV_CUSTOM"   # subdiretório de saída em data/output/2.2/
RB_MAXIMO_PADRAO = 0.9
JOBS_PADRAO = 4

_REGEX_HORIZONTE = re.compile(r"^(?:(\d+)m)?(?:(\d+)d)?(?:(\d+)h)?$")


# ---------------------------------------------------------------------------
# Interpretação dos horizontes
# ---------------------------------------------------------------------------

def soma_meses(data, meses):
    """Soma meses de calendário a um datetime (o dia é limitado ao último
    dia do mês de destino quando necessário, ex.: 31/jan + 1m = 28/fev)."""
    total = data.month - 1 + meses
    ano = data.year + total // 12
    mes = total % 12 + 1
    # último dia do mês de destino
    if mes == 12:
        ultimo = 31
    else:
        ultimo = (dt.datetime(ano, mes + 1, 1) - dt.timedelta(days=1)).day
    return data.replace(year=ano, month=mes, day=min(data.day, ultimo))


class Horizonte:
    """Horizonte relativo: meses de calendário + dias + horas."""

    def __init__(self, meses=0, dias=0, horas=0):
        self.meses = meses
        self.delta = dt.timedelta(days=dias, hours=horas)

    def aplica(self, inicio):
        return soma_meses(inicio, self.meses) + self.delta

    def positivo(self):
        return self.meses > 0 or self.delta > dt.timedelta(0)


def parse_horizonte(token):
    """Converte um token de horizonte em Horizonte (relativo) ou datetime
    (absoluto YYYYMMDDHH)."""
    token = token.strip().lower()
    if re.fullmatch(r"\d{10}", token):          # data/hora absoluta
        return dt.datetime.strptime(token, "%Y%m%d%H")
    m = _REGEX_HORIZONTE.fullmatch(token)
    if not m or all(g is None for g in m.groups()):
        raise argparse.ArgumentTypeError(
            f"Horizonte inválido: '{token}'. Use Nh, Nd, Nm e combinações "
            f"(ex.: 36h, 5d, 4d18h, 6m, 13m, 1m15d) ou YYYYMMDDHH.")
    return Horizonte(meses=int(m.group(1) or 0),
                     dias=int(m.group(2) or 0),
                     horas=int(m.group(3) or 0))


def resolve_horizontes(args, inicio_modelo):
    """Monta a lista de datetimes de previsão a partir de --horizontes ou
    do intervalo --de/--ate/--passo."""
    previsoes = []

    if args.horizontes:
        for token in args.horizontes.split(","):
            h = parse_horizonte(token)
            previsoes.append(h if isinstance(h, dt.datetime)
                             else h.aplica(inicio_modelo))

    if args.de or args.ate:
        if not (args.de and args.ate):
            sys.exit("Erro: --de e --ate devem ser usados em conjunto.")
        de = parse_horizonte(args.de)
        ate = parse_horizonte(args.ate)
        passo = parse_horizonte(args.passo or "6h")
        for v in (de, ate, passo):
            if isinstance(v, dt.datetime):
                sys.exit("Erro: --de/--ate/--passo aceitam apenas horizontes "
                         "relativos (Nh, Nd, Nm e combinações).")
        if not passo.positivo():
            sys.exit("Erro: --passo deve ser positivo.")
        limite = ate.aplica(inicio_modelo)
        n = 0
        while True:
            # aplica o passo n vezes a partir de --de (preserva meses de
            # calendário: 1m,2m,3m... e não 30d,60d,90d)
            t = de.aplica(inicio_modelo)
            t = soma_meses(t, passo.meses * n) + passo.delta * n
            if t > limite:
                break
            previsoes.append(t)
            n += 1

    if not previsoes:
        sys.exit("Erro: informe os horizontes com --horizontes e/ou "
                 "--de/--ate/--passo. Ex.: --horizontes 24h,3d ou "
                 "--de 6h --ate 4d18h --passo 6h")

    # Remove duplicados preservando a ordem e valida.
    unicos = list(dict.fromkeys(previsoes))
    for prev in unicos:
        if prev <= inicio_modelo:
            sys.exit(f"Erro: a previsão {prev:%Y%m%d%H} não é posterior à "
                     f"rodada do modelo ({inicio_modelo:%Y%m%d%H}).")
    return unicos


# ---------------------------------------------------------------------------
# Localização dos arquivos do GFS (com fallback opcional)
# ---------------------------------------------------------------------------

def localiza_arquivo_gfs(dirin_gfs, prefixo, data_modelo, data_previsao,
                         fallback):
    """Retorna o caminho do arquivo do GFS para o horário pedido.

    Se o arquivo exato não existir e ``fallback`` estiver ativo, procura o
    mesmo dia em horários anteriores (de 6 em 6 h) e copia o arquivo
    encontrado para o nome esperado — generalização da cópia 12 UTC → 18 UTC
    do script semanal (o GFS fornece saídas apenas a cada 12 h após o
    10º dia de previsão).
    """
    esperado = os.path.join(
        dirin_gfs, f"{prefixo}.{data_modelo}.{data_previsao}.nc")
    if os.path.exists(esperado) or not fallback:
        return esperado

    valido = dt.datetime.strptime(data_previsao, "%Y%m%d%H")
    candidato_dt = valido - dt.timedelta(hours=6)
    while candidato_dt.date() == valido.date():
        candidato = os.path.join(
            dirin_gfs,
            f"{prefixo}.{data_modelo}.{candidato_dt:%Y%m%d%H}.nc")
        if os.path.exists(candidato):
            shutil.copy2(candidato, esperado)
            print(f"Fallback GFS: {os.path.basename(candidato)} -> "
                  f"{os.path.basename(esperado)}")
            return esperado
        candidato_dt -= dt.timedelta(hours=6)

    return esperado   # não encontrado: o worker registrará o erro no log


# ---------------------------------------------------------------------------
# Função executada em paralelo para cada horário de previsão
# ---------------------------------------------------------------------------

def processa_previsao(parametros):
    """Calcula o RF de um horário de previsão.

    Dois modos:
      - legado (sem --fonte): composição original — lista de arquivos com
        119 IMERG + o acumulado do GFS do dia previsto;
      - multifonte (com --fonte): série diária completa de 120 tempos
        montada pelo rf_fontes (IMERG observado + previsão da fonte),
        com T/UR lidos da própria fonte.
    """
    data_modelo = parametros["data_modelo"]
    data_previsao = parametros["data_previsao"]
    arquivo_log = os.path.join(parametros["dir_log"],
                               f"log.{data_modelo}.{data_previsao}")

    try:
        with open(arquivo_log, "a") as flog:
            def log(msg=""):
                flog.write(str(msg) + "\n")
                flog.flush()

            if parametros.get("fonte") is None:
                # ----- modo legado (idêntico aos produtos operacionais)
                rf_core.calcula_risco_fogo(
                    arquivo_temp_ur=parametros["arquivo_temp_ur"],
                    lista_arquivos_prec=parametros["lista_arquivos_prec"],
                    arquivo_mapa_veg=parametros["arquivo_mapa_veg"],
                    arquivo_topografia=parametros["arquivo_topografia"],
                    arquivo_saida=parametros["arquivo_saida"],
                    data_previsao=data_previsao,
                    rb_maximo=parametros["rb_maximo"],
                    log=log,
                )
            else:
                # ----- modo multifonte (GFS/Eta/BESM, qualquer frequência)
                if parametros.get("config"):
                    cfg_w = rf_config.carrega(parametros["config"])
                    if cfg_w["fontes"]:
                        rf_fontes.carrega_fontes_dict(cfg_w["fontes"])
                if parametros.get("config_fontes"):
                    rf_fontes.carrega_fontes_json(parametros["config_fontes"])
                fonte = rf_fontes.FONTES[parametros["fonte"]]

                def caminho_imerg_fn(dia):
                    return rf_config.caminho_imerg(
                        parametros["base"], parametros["caminhos"], dia)

                log("")
                log(f"Montando a série diária de precipitação "
                    f"(fonte: {fonte.nome}, freq: {fonte.freq_prec}).")
                precip, lat_prec, lon_prec, _ = rf_fontes.serie_precipitacao(
                    fonte=fonte,
                    dirin_fonte=parametros["dirin_fonte"],
                    dirin_imerg=parametros["dirin_imerg"],
                    modelo=data_modelo,
                    data_previsao=data_previsao,
                    n_dias=rf_core.ND_ESPERADO,
                    log=log,
                    caminho_imerg_fn=caminho_imerg_fn,
                )

                log("")
                log("Lendo temperatura e umidade relativa da fonte.")
                t2m, ur2m, lat_met, lon_met = rf_fontes.temp_ur_previstos(
                    fonte, parametros["dirin_fonte"], data_modelo,
                    data_previsao)

                rf_core.calcula_risco_fogo_dados(
                    precip_invertida=precip[::-1],   # NCL: tempo invertido
                    lat_prec=lat_prec, lon_prec=lon_prec,
                    t2m=t2m, ur2m=ur2m,
                    lat_met=lat_met, lon_met=lon_met,
                    arquivo_mapa_veg=parametros["arquivo_mapa_veg"],
                    arquivo_topografia=parametros["arquivo_topografia"],
                    arquivo_saida=parametros["arquivo_saida"],
                    data_previsao=data_previsao,
                    rb_maximo=parametros["rb_maximo"],
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
    # ------------------------------------------------------------------
    # Fase 1: só o --config, para carregar o YAML antes dos demais
    # argumentos (precedência: linha de comando > YAML > padrões).
    # ------------------------------------------------------------------
    pre = argparse.ArgumentParser(add_help=False)
    pre.add_argument("--config", default=None)
    args_pre, _ = pre.parse_known_args()

    if args_pre.config:
        cfg = rf_config.carrega(args_pre.config)
    else:
        cfg = rf_config.padrao()
    if cfg["fontes"]:
        rf_fontes.carrega_fontes_dict(cfg["fontes"])

    parser = argparse.ArgumentParser(
        description="Risco de fogo previsto para qualquer horizonte de "
                    "previsão.",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog=(
            "Exemplos:\n"
            "  rf_previsto.py --horizontes 36h\n"
            "  rf_previsto.py --horizontes 18h,2d18h,6d18h,13d18h\n"
            "  rf_previsto.py --de 6h --ate 4d18h --passo 6h\n"
            "  rf_previsto.py --horizontes 7d18h,14d18h --rb-max 0.8 "
            "--fallback-gfs\n"))
    parser.add_argument("--horizontes", default=None,
                        help="Lista de horizontes separados por vírgula "
                             "(Nh, Nd, NdMh ou YYYYMMDDHH). "
                             "Ex.: 24h,3d,7d18h")
    parser.add_argument("--de", default=None,
                        help="Início do intervalo de horizontes (ex.: 6h).")
    parser.add_argument("--ate", default=None,
                        help="Fim do intervalo de horizontes (ex.: 4d18h).")
    parser.add_argument("--passo", default=None,
                        help="Passo do intervalo (padrão: 6h).")
    parser.add_argument("--data-final", default=None,
                        help="Data da rodada YYYYMMDD (padrão: hoje). "
                             "O modelo é sempre a rodada das 00 UTC.")
    parser.add_argument("--fonte", default=None,
                        help="Fonte de previsão (gfs, eta, besm ou outra "
                             "definida via --config-fontes). Sem esta "
                             "opção, usa a composição original dos produtos "
                             "operacionais (GFS, horizonte de até ~16 dias). "
                             "Com ela, monta a série diária completa "
                             "IMERG+previsão — necessário para horizontes "
                             "longos (Eta/BESM até 13 meses).")
    parser.add_argument("--config-fontes", default=None,
                        help="Arquivo JSON que ajusta/acrescenta fontes "
                             "(padrões de nome, variáveis, frequência dos "
                             "acúmulos, unidades). Ver rf_fontes.py.")
    parser.add_argument("--rb-max", type=float, default=RB_MAXIMO_PADRAO,
                        help=f"Risco básico máximo (padrão: "
                             f"{RB_MAXIMO_PADRAO}; o produto semanal usa 0.8).")
    parser.add_argument("--produto", default=PRODUTO_PADRAO,
                        help=f"Nome do subdiretório de saída em "
                             f"data/output/2.2/ (padrão: {PRODUTO_PADRAO}).")
    parser.add_argument("--base", default=BASE_PADRAO,
                        help=f"Diretório base do modelo (padrão: {BASE_PADRAO}).")
    parser.add_argument("--jobs", type=int, default=JOBS_PADRAO,
                        help=f"Número de processos paralelos (padrão: "
                             f"{JOBS_PADRAO}).")
    parser.add_argument("--fallback-gfs", action="store_true",
                        help="Se o arquivo do GFS do horário exato não "
                             "existir, usa o horário anterior do mesmo dia "
                             "(ex.: 12 UTC no lugar de 18 UTC, como no "
                             "produto semanal).")
    parser.add_argument("--sem-tif", action="store_true",
                        help="Não gera os GeoTIFF (apenas NetCDF).")
    parser.add_argument("--fogograma", action="store_true",
                        help="Gera também um único NetCDF com todos os "
                             "horizontes (mergetime).")
    parser.add_argument("--config", default=None,
                        help="Arquivo de configuração YAML (ou JSON) dos "
                             "dados de entrada: base, caminhos (IMERG, "
                             "vegetação, topografia), fontes e padrões de "
                             "execução. A linha de comando prevalece sobre "
                             "o arquivo. Ver rf_config.py e "
                             "config_exemplo.yaml.")

    # Aplica os padrões vindos da seção "execucao" do YAML: eles substituem
    # os padrões embutidos, mas continuam sendo sobrepostos pela CLI.
    exec_cfg = dict(cfg["execucao"])
    if "base" not in exec_cfg:
        exec_cfg["base"] = cfg["base"]
    parser.set_defaults(**exec_cfg)

    args = parser.parse_args()

    tempo_inicial = time.time()

    if args.config_fontes:
        rf_fontes.carrega_fontes_json(args.config_fontes)

    fonte = None
    if args.fonte:
        nome_fonte = args.fonte.lower()
        if nome_fonte not in rf_fontes.FONTES:
            sys.exit(f"Erro: fonte '{args.fonte}' desconhecida. Disponíveis: "
                     f"{', '.join(sorted(rf_fontes.FONTES))} "
                     f"(acrescente outras via --config-fontes).")
        fonte = rf_fontes.FONTES[nome_fonte]

    base = args.base.rstrip("/")
    caminhos = cfg["caminhos"]
    dirin_imerg = rf_config.resolve(base, caminhos["imerg_dir"])
    dir_log = rf_config.resolve(base, caminhos["log"])
    arq_topografia = rf_config.resolve(base, caminhos["topografia"])

    # -----------------------------------------------------------------------
    # Datas
    # -----------------------------------------------------------------------
    if args.data_final:
        hoje = dt.datetime.strptime(args.data_final, "%Y%m%d")
    else:
        hoje = dt.datetime.now().replace(hour=0, minute=0, second=0,
                                         microsecond=0)

    data_final = hoje.strftime("%Y%m%d")
    data_inicial_dt = hoje - dt.timedelta(days=119)
    data_modelo = data_final + "00"

    previsoes = resolve_horizontes(args, hoje)

    # Valida o alcance da fonte.
    if fonte is not None:
        for prev in previsoes:
            alcance = (prev - hoje).days
            if alcance > fonte.horizonte_max_dias:
                sys.exit(f"Erro: a previsão {prev:%Y%m%d%H} (+{alcance} dias) "
                         f"excede o alcance da fonte '{fonte.nome}' "
                         f"({fonte.horizonte_max_dias} dias).")

    ano = int(data_final[:4])
    ano_mapa_veg = "2019" if ano >= 2020 else str(ano)
    arquivo_mapa_veg = rf_config.resolve(
        base, caminhos["mapa_vegetacao"].format(ano_veg=ano_mapa_veg))

    # Nome do produto: com fonte, o padrão passa a incluir o nome dela.
    produto = args.produto
    if fonte is not None and produto == PRODUTO_PADRAO:
        produto = f"RF_PREV_{fonte.nome.upper()}"

    dirin_gfs = f"{base}/data/output/2.2/GFS/netcdf/{data_modelo}"
    if fonte is not None:
        dirin_fonte = f"{base}/data/output/2.2/" + fonte.subdir.format(
            modelo=data_modelo)
    else:
        dirin_fonte = dirin_gfs
    dir_output_netcdf = f"{base}/data/output/2.2/{produto}/netcdf/{data_modelo}"
    dir_output_tif = f"{base}/data/output/2.2/{produto}/tif/{data_modelo}"
    dir_fogograma = f"{base}/data/output/2.2/fogograma"

    os.makedirs(dir_output_netcdf, exist_ok=True)
    if not args.sem_tif:
        os.makedirs(dir_output_tif, exist_ok=True)
    os.makedirs(dir_log, exist_ok=True)

    print("inicio: >>>" + data_inicial_dt.strftime("%Y%m%d"))
    print("fim: >>>>>>" + data_final)
    print("modelo: >>>" + data_modelo)
    print("fonte: >>>>" + (fonte.nome if fonte else "gfs (composição legada)"))
    print("previsoes: >" + ", ".join(p.strftime("%Y%m%d%H")
                                     for p in previsoes))
    print("rb_max: >>>" + str(args.rb_max))
    print("produto: >>" + produto)

    # -----------------------------------------------------------------------
    # Modo legado: lista dos 119 arquivos diários do IMERG
    # (no modo multifonte a série é montada dentro de cada trabalho)
    # -----------------------------------------------------------------------
    lista_imerg = []
    if fonte is None:
        faltantes = []
        data_corrente = data_inicial_dt
        while data_corrente < hoje:
            caminho = rf_config.caminho_imerg(base, caminhos, data_corrente)
            if os.path.exists(caminho):
                lista_imerg.append(caminho)
            else:
                faltantes.append(caminho)
            data_corrente += dt.timedelta(days=1)

        if faltantes:
            with open("log.falta.arquivos.prev.prec.txt", "a") as flog:
                flog.write("\n".join(faltantes) + "\n")
            print(f"Aviso: {len(faltantes)} arquivo(s) IMERG faltando "
                  f"(ver log.falta.arquivos.prev.prec.txt)", file=sys.stderr)

    # -----------------------------------------------------------------------
    # Monta a lista de trabalhos, um por horizonte pedido
    # -----------------------------------------------------------------------
    trabalhos = []
    for previsao_dt in previsoes:
        data_previsao = previsao_dt.strftime("%Y%m%d%H")

        trabalho = {
            "data_modelo": data_modelo,
            "data_previsao": data_previsao,
            "arquivo_mapa_veg": arquivo_mapa_veg,
            "arquivo_topografia": arq_topografia,
            "arquivo_saida": os.path.join(
                dir_output_netcdf, f"RF.PREV.{data_previsao}.nc"),
            "rb_maximo": args.rb_max,
            "dir_log": dir_log,
            "fonte": fonte.nome if fonte else None,
            "config_fontes": args.config_fontes,
            "config": args.config,
            "dirin_fonte": dirin_fonte,
            "dirin_imerg": dirin_imerg,
            "base": base,
            "caminhos": caminhos,
        }

        if fonte is None:
            trabalho["arquivo_temp_ur"] = localiza_arquivo_gfs(
                dirin_gfs, "GFS.PREV.TEMP2m.RH2m", data_modelo,
                data_previsao, args.fallback_gfs)
            arquivo_prec_gfs = localiza_arquivo_gfs(
                dirin_gfs, "GFS.PREV.PREC", data_modelo, data_previsao,
                args.fallback_gfs)
            trabalho["lista_arquivos_prec"] = lista_imerg + [arquivo_prec_gfs]

        trabalhos.append(trabalho)

    # -----------------------------------------------------------------------
    # Executa os cálculos em paralelo
    # -----------------------------------------------------------------------
    with ProcessPoolExecutor(max_workers=args.jobs) as executor:
        resultados = list(executor.map(processa_previsao, trabalhos))

    falhas = [r for r in resultados if not r[1]]
    for data_previsao, _, erro in falhas:
        print(f"ERRO na previsão {data_previsao}: {erro}", file=sys.stderr)

    gerados = [t["arquivo_saida"] for t in trabalhos
               if os.path.exists(t["arquivo_saida"])]
    if len(gerados) != len(trabalhos):
        print(f" PROBLEMA - FALTAM ARQUIVOS EM {dir_output_netcdf}")
        sys.exit(1)

    # -----------------------------------------------------------------------
    # GeoTIFF por horizonte
    # -----------------------------------------------------------------------
    if not args.sem_tif:
        for trabalho in trabalhos:
            data_previsao = trabalho["data_previsao"]
            arquivo_tif = os.path.join(
                dir_output_tif, f"RF.PREV.{data_previsao}.tif")
            rf_core.netcdf_para_geotiff(trabalho["arquivo_saida"], arquivo_tif)
            print(f"TIF gerado: {arquivo_tif}")

    # -----------------------------------------------------------------------
    # Fogograma opcional (todos os horizontes em um único NetCDF)
    # -----------------------------------------------------------------------
    if args.fogograma:
        os.makedirs(dir_fogograma, exist_ok=True)
        arquivo_fogograma = os.path.join(
            dir_fogograma, f"RF.PREV.{produto}.{data_modelo}.nc")
        rf_core.mergetime(gerados, arquivo_fogograma)
        print(f"Fogograma gerado: {arquivo_fogograma}")

    decorrido = int(time.time() - tempo_inicial)
    print(" Tempo gasto: "
          + str(dt.timedelta(seconds=decorrido)).rjust(8, "0"))


if __name__ == "__main__":
    main()
