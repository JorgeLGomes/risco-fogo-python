# -*- coding: utf-8 -*-
"""
fwi_observado.py
================

**FWI observado** (Canadian Fire Weather Index System) a partir das
observações já preparadas pelo pipeline: precipitação diária observada
(IMERG, padrão, ou MSWEP via ``--precipitacao mswep``) e temperatura,
umidade relativa e vento da ERA5.

É a "análise de fogo contínua" da metodologia multi-horizonte: roda dia a
dia, mantendo os três códigos de umidade (FFMC, DMC, DC) de um dia para o
outro. Diferente do RF — que é independente por dia e pode ser calculado
em paralelo —, o FWI é **sequencial**: cada dia parte do estado do dia
anterior. Por isso o script sempre roda um período de aquecimento
(*spin-up*) antes do primeiro dia pedido, e pode salvar/retomar o estado.

Saídas, um arquivo por dia, com todos os componentes:

    FWI.OBS.{data}{hora}.nc  ->  FFMC, DMC, DC, ISI, BUI, FWI, DSR

em ``{base}/data/output/2.2/FWI_OBS/netcdf`` (produto ajustável).

Uso
---
    # Últimos 30 dias, com 90 dias de spin-up antes
    python3 fwi_observado.py --config config.yaml --dias 30

    # Um mês fechado + a média mensal do FWI
    python3 fwi_observado.py --de 20260701 --ate 20260731 --media-mensal

    # Rodada contínua: retoma do estado salvo e grava o novo estado
    python3 fwi_observado.py --de 20260801 --ate 20260805 \
        --estado-inicial estado_fwi.nc --salvar-estado estado_fwi.nc

    # Conferir as entradas sem calcular
    python3 fwi_observado.py --de 20260701 --ate 20260731 --simular

    # Produto mensal recomendado do sistema canadense: MSR = média do DSR
    # (o FWI nao deve ser promediado — ver Van Wagner 1987)
    python3 fwi_observado.py --de 20260701 --ate 20260731 \
        --media-mensal --var-agrega DSR

    # Frequencia de dias de perigo alto e percentil 90 do mes
    python3 fwi_observado.py --de 20260701 --ate 20260731 --media-mensal \
        --frequencia 22 --percentil 90

Pré-requisitos (bancos locais):
    python3 prepara_imerg.py --inicio ... --fim ...   # precipitação (IMERG)
    python3 prepara_era5.py  --inicio ... --fim ...   # T2m, UR2m, U10m, V10m

Convenção de hora: o sistema canadense usa as condições do **meio-dia
local**. Sobre o Brasil (UTC−3) isso corresponde a ~15 UTC; o padrão deste
script é 18 UTC apenas para casar com o banco já baixado dos produtos de
RF — use ``--hora 15`` (baixando a ERA5 nessa hora) para seguir a
convenção à risca.
"""

import argparse
import datetime as dt
import os
import sys

import numpy as np

import era5_tempo
import fwi_core
import rf_config
import rf_core

PRODUTO_PADRAO = "FWI_OBS"
ATRASO_ERA5_DIAS = 6
SPINUP_PADRAO = 90          # dias (memória do DC ~52 dias)

VARIAVEIS = ("FFMC", "DMC", "DC", "ISI", "BUI", "FWI", "DSR")

UNIDADES = {"FFMC": "1", "DMC": "1", "DC": "1", "ISI": "1", "BUI": "1",
            "FWI": "1", "DSR": "1"}
DESCRICOES = {
    "FFMC": "Fine Fuel Moisture Code",
    "DMC": "Duff Moisture Code",
    "DC": "Drought Code",
    "ISI": "Initial Spread Index",
    "BUI": "Build Up Index",
    "FWI": "Fire Weather Index",
    "DSR": "Daily Severity Rating",
}


# ---------------------------------------------------------------------------
# Leitura das entradas de um dia
# ---------------------------------------------------------------------------

def le_precipitacao(caminho, nome_var="prec", recorte=None):
    """Precipitação diária observada (mm), com lat sul->norte.

    Serve tanto para os arquivos do pipeline (IMERG e MSWEP convertido,
    variável `prec`) quanto para o MSWEP original global, com
    ``nome_var=None`` (detecção automática) e ``recorte`` do domínio."""
    dados, lat, lon = rf_core.le_precip_arquivo(caminho, nome_var, recorte)
    return np.asarray(dados[0], dtype=np.float64), lat, lon


def le_vento(caminho):
    """Velocidade do vento a 10 m (km/h) a partir de U10m/V10m da ERA5."""
    import xarray as xr
    with xr.open_dataset(caminho, decode_times=False) as ds:
        u = np.asarray(ds["U10m"].values, dtype=np.float64)
        v = np.asarray(ds["V10m"].values, dtype=np.float64)
        if u.ndim == 3:
            u, v = u[0], v[0]
        lat = np.asarray(ds["lat"].values, dtype=np.float64)
        lon = np.asarray(ds["lon"].values, dtype=np.float64)
    if lat.size > 1 and lat[0] > lat[-1]:
        lat = lat[::-1]
        u, v = u[::-1, :], v[::-1, :]
    return fwi_core.velocidade_vento(u, v), lat, lon


_LON_BANCO = {}          # cache das longitudes do banco por diretório


def _lon_do_banco(base, caminhos, dia, cfg_precip=None):
    """Longitudes do arquivo de precipitação do dia (para saber quais
    horas UTC o modo solar precisa). Devolve None se não existir."""
    caminho = rf_config.caminho_precipitacao(base, caminhos, dia, cfg_precip)
    if caminho in _LON_BANCO:
        return _LON_BANCO[caminho]
    if not os.path.exists(caminho):
        return None
    _, lon = rf_core.le_grade_precip(
        caminho, rf_config.recorte_precipitacao(cfg_precip))
    _LON_BANCO[caminho] = lon
    return lon


def horas_utc_do_modo(cfg_era5, lon=None):
    """Horas UTC necessárias: uma no modo fixo, várias no modo solar
    (conforme as longitudes da grade)."""
    cfg = era5_tempo.normaliza(cfg_era5)
    if cfg["horario"] == "fixo" or cfg["horas"]:
        return era5_tempo.horas_para_grade(cfg, [-45.0])
    if lon is None:
        lon = np.linspace(-75.0, -35.0, 200)      # Brasil, como referência
    return era5_tempo.horas_para_grade(cfg, lon)


def entradas_do_dia(base, caminhos, dia, cfg_era5, grade=None,
                    cfg_precip=None):
    """Lê e harmoniza as entradas do dia: (t °C, ur %, vento km/h,
    chuva mm, lat, lon). Devolve (None, faltas) se faltar algum arquivo.

    O horário das variáveis meteorológicas segue a seção ``era5``: uma
    hora UTC fixa, ou a hora solar local montada por faixas de longitude.

    ``grade``: (lat, lon) de destino; as variáveis da ERA5 são
    interpoladas para essa grade (por padrão, a da precipitação).

    ``cfg_precip``: seção 'precipitacao' da configuração (IMERG ou
    MSWEP); None usa o padrão (IMERG)."""
    cfg = era5_tempo.normaliza(cfg_era5)
    horas = horas_utc_do_modo(
        cfg, _lon_do_banco(base, caminhos, dia, cfg_precip))

    arq_prec = rf_config.caminho_precipitacao(base, caminhos, dia, cfg_precip)
    faltam = [] if os.path.exists(arq_prec) else [arq_prec]
    arqs_termo, arqs_vento = {}, {}
    for hora_utc in horas:
        quando = dia.replace(hour=hora_utc)
        a1 = rf_config.caminho_era5(base, caminhos, quando, hora_utc)
        a2 = rf_config.caminho_era5(base, caminhos, quando, hora_utc,
                                    vento=True)
        if os.path.exists(a1) and os.path.exists(a2):
            arqs_termo[hora_utc], arqs_vento[hora_utc] = a1, a2
        else:
            faltam += [a for a in (a1, a2) if not os.path.exists(a)]
    if faltam:
        return None, faltam

    chuva, lat_p, lon_p = le_precipitacao(
        arq_prec, rf_config.variavel_precipitacao(cfg_precip),
        rf_config.recorte_precipitacao(cfg_precip))

    if len(horas) == 1:
        t2m, ur2m, lat_m, lon_m = rf_core.ler_temp_ur(arqs_termo[horas[0]])
        vento, lat_v, lon_v = le_vento(arqs_vento[horas[0]])
        t2m = np.asarray(t2m, dtype=np.float64)
        ur2m = np.asarray(ur2m, dtype=np.float64) * 100.0
    else:
        ct, cu, cv = {}, {}, {}
        lat_m = lon_m = lat_v = lon_v = None
        for hora_utc in horas:
            tt, uu, lat_m, lon_m = rf_core.ler_temp_ur(arqs_termo[hora_utc])
            vv, lat_v, lon_v = le_vento(arqs_vento[hora_utc])
            ct[hora_utc] = np.asarray(tt, dtype=np.float64)
            cu[hora_utc] = np.asarray(uu, dtype=np.float64) * 100.0
            cv[hora_utc] = vv
        local = cfg["hora_local"]
        t2m = era5_tempo.compoe_por_longitude(ct, lon_m, local)
        ur2m = era5_tempo.compoe_por_longitude(cu, lon_m, local)
        vento = era5_tempo.compoe_por_longitude(cv, lon_v, local)

    lat, lon = grade if grade is not None else (lat_p, lon_p)

    def para_grade(campo, la, lo):
        if la.size == lat.size and lo.size == lon.size and \
                np.allclose(la, lat) and np.allclose(lo, lon):
            return campo
        return rf_core.interp_bilinear(campo, la, lo, lat, lon).astype(
            np.float64)

    return (para_grade(t2m, lat_m, lon_m),
            np.clip(para_grade(ur2m, lat_m, lon_m), 0.0, 100.0),
            np.maximum(para_grade(vento, lat_v, lon_v), 0.0),
            np.maximum(para_grade(chuva, lat_p, lon_p), 0.0),
            lat, lon), []


# ---------------------------------------------------------------------------
# Escrita
# ---------------------------------------------------------------------------

def grava_netcdf_fwi(indices, lat, lon, quando, arquivo_saida, titulo=None,
                     atributos_extras=None):
    """Grava um NetCDF com todos os componentes do dia."""
    import xarray as xr

    dados = {nome: (("time", "lat", "lon"),
                    np.round(np.asarray(campo, dtype=np.float32),
                             2)[np.newaxis],
                    {"long_name": DESCRICOES[nome], "units": UNIDADES[nome]})
             for nome, campo in indices.items()}
    ds = xr.Dataset(
        dados,
        coords={
            "time": [quando],
            "lat": ("lat", np.asarray(lat, dtype=np.float64),
                    {"standard_name": "latitude", "units": "degrees_north"}),
            "lon": ("lon", np.asarray(lon, dtype=np.float64),
                    {"standard_name": "longitude", "units": "degrees_east"}),
        },
        attrs={
            "title": titulo or f"FWI observado (IMERG + ERA5) {quando:%Y%m%d%H}",
            "sistema": "Canadian Forest Fire Weather Index System "
                       "(Van Wagner & Pickett, 1985)",
            "fonte": "IMERG (precipitacao) + ERA5 (T2m, UR2m, vento 10 m)",
            "history": f"gerado em {dt.datetime.now():%Y-%m-%d %H:%M} por "
                       f"fwi_observado.py",
        },
    )
    if atributos_extras:
        ds.attrs.update(atributos_extras)
    enc = {nome: {"dtype": "float32", "zlib": True, "complevel": 4,
                  "_FillValue": rf_core.FILL_VALUE} for nome in indices}
    enc["time"] = {"units": "hours since 1900-01-01 00:00:00",
                   "calendar": "standard", "dtype": "float64"}
    os.makedirs(os.path.dirname(arquivo_saida), exist_ok=True)
    ds.to_netcdf(arquivo_saida, format="NETCDF4_CLASSIC", encoding=enc)
    return arquivo_saida


def grava_estado(estado, lat, lon, quando, caminho):
    """Salva FFMC/DMC/DC para retomar a rodada depois."""
    import xarray as xr
    ds = xr.Dataset(
        {"FFMC": (("lat", "lon"), estado.ffmc.astype(np.float32)),
         "DMC": (("lat", "lon"), estado.dmc.astype(np.float32)),
         "DC": (("lat", "lon"), estado.dc.astype(np.float32))},
        coords={"lat": lat, "lon": lon},
        attrs={"data_estado": quando.strftime("%Y%m%d%H"),
               "descricao": "Estado dos codigos de umidade do FWI ao fim "
                            "do dia indicado em data_estado"},
    )
    os.makedirs(os.path.dirname(os.path.abspath(caminho)), exist_ok=True)
    ds.to_netcdf(caminho)
    return caminho


def le_estado(caminho):
    """Lê um estado salvo: (EstadoFWI, data do estado)."""
    import xarray as xr
    with xr.open_dataset(caminho) as ds:
        estado = fwi_core.EstadoFWI(
            np.asarray(ds["FFMC"].values, dtype=np.float64),
            np.asarray(ds["DMC"].values, dtype=np.float64),
            np.asarray(ds["DC"].values, dtype=np.float64))
        data = ds.attrs.get("data_estado")
    quando = dt.datetime.strptime(data, "%Y%m%d%H") if data else None
    return estado, quando


# ---------------------------------------------------------------------------
# Período
# ---------------------------------------------------------------------------

def _hoje_utc():
    return dt.datetime.now(dt.timezone.utc).replace(
        tzinfo=None, hour=0, minute=0, second=0, microsecond=0)


def _soma_meses(data, n):
    import calendar
    m = data.month - 1 + n
    ano = data.year + m // 12
    mes = m % 12 + 1
    dia = min(data.day, calendar.monthrange(ano, mes)[1])
    return data.replace(year=ano, month=mes, day=dia)


def resolve_periodo(args):
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
        fim = _hoje_utc() - dt.timedelta(days=ATRASO_ERA5_DIAS)

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
        description="FWI observado (IMERG + ERA5), com spin-up e estado "
                    "contínuo dos códigos de umidade.")
    grupo = parser.add_mutually_exclusive_group()
    grupo.add_argument("--dias", type=int, default=None,
                       help="Últimos N dias (padrão: 7).")
    grupo.add_argument("--semanas", type=int, default=None,
                       help="Últimas N semanas.")
    grupo.add_argument("--meses", type=int, default=None,
                       help="Últimos N meses-calendário.")
    parser.add_argument("--de", default=None, help="Início YYYYMMDD.")
    parser.add_argument("--ate", default=None, help="Fim YYYYMMDD.")
    parser.add_argument("--data-final", default=None,
                        help=f"Fim da janela (padrão: {ATRASO_ERA5_DIAS} "
                             f"dias atrás; aceita 'hoje').")
    parser.add_argument("--hora", default=None,
                        help="Hora UTC das condições no modo fixo (padrão: "
                             "seção 'era5' do config, ou 18).")
    parser.add_argument("--horario", default=None, choices=era5_tempo.MODOS,
                        help="'fixo' (uma hora UTC) ou 'solar' (hora solar "
                             "local por faixas de longitude — a convenção "
                             "do sistema canadense é o meio-dia local).")
    parser.add_argument("--hora-local", type=int, default=None,
                        help="Hora solar local no modo solar (padrão: 15; "
                             "use 12 para a convenção do FWI).")
    parser.add_argument("--spinup", type=int, default=SPINUP_PADRAO,
                        help=f"Dias de aquecimento antes do período "
                             f"(padrão: {SPINUP_PADRAO}). Ignorado quando "
                             f"há --estado-inicial.")
    parser.add_argument("--estado-inicial", default=None,
                        help="NetCDF com FFMC/DMC/DC de onde retomar.")
    parser.add_argument("--salvar-estado", default=None,
                        help="Grava o estado ao fim do período.")
    parser.add_argument("--ffmc0", type=float, default=fwi_core.FFMC_INICIAL,
                        help="FFMC de partida a frio (padrão: 85).")
    parser.add_argument("--dmc0", type=float, default=fwi_core.DMC_INICIAL,
                        help="DMC de partida a frio (padrão: 6).")
    parser.add_argument("--dc0", type=float, default=fwi_core.DC_INICIAL,
                        help="DC de partida a frio (padrão: 15).")
    parser.add_argument("--produto", default=PRODUTO_PADRAO,
                        help=f"Nome do produto (padrão: {PRODUTO_PADRAO}).")
    parser.add_argument("--base", default=None,
                        help="Diretório base (padrão: da configuração).")
    parser.add_argument("--config", default=None,
                        help="Arquivo YAML/JSON de configuração.")
    parser.add_argument("--media", action="store_true",
                        help="Gera também a média do período.")
    parser.add_argument("--media-mensal", action="store_true",
                        help="Gera a média de cada mês-calendário.")
    parser.add_argument("--maximo", action="store_true",
                        help="Nas agregações, usa o máximo em vez da média.")
    parser.add_argument("--frequencia", type=float, default=None,
                        help="Gera também a FREQUÊNCIA de dias com o "
                             "componente agregado >= LIMIAR (nº e %%) — "
                             "ex.: --frequencia 22 (classe Alto do FWI).")
    parser.add_argument("--percentil", type=float, default=None,
                        help="Gera também o PERCENTIL da distribuição dos "
                             "dias (0–100) — ex.: --percentil 90.")
    parser.add_argument("--var-agrega", default="FWI", choices=VARIAVEIS,
                        help="Componente agregado nas médias (padrão: FWI).")
    parser.add_argument("--precipitacao", default=None,
                        choices=list(rf_config.FONTES_PRECIPITACAO),
                        help="Fonte da precipitação observada: 'imerg' "
                             "(padrão) ou 'mswep'. Padrão: seção "
                             "'precipitacao' do config. Sufixo _MSWEP.")
    parser.add_argument("--modo-precipitacao", default=None,
                        choices=["in_loco", "convertido"],
                        help="Leitura do MSWEP: 'in_loco' (originais "
                             "globais) ou 'convertido' (prepara_mswep.py).")
    parser.add_argument("--simular", action="store_true",
                        help="Só confere as entradas do período.")
    args = parser.parse_args()

    cfg = (rf_config.carrega(args.config) if args.config
           else rf_config.padrao())
    base = (args.base or cfg["base"]).rstrip("/")
    caminhos = cfg["caminhos"]

    cfg_precip = dict(cfg.get("precipitacao")
                      or rf_config.PRECIPITACAO_PADRAO)
    if args.precipitacao:
        cfg_precip["fonte"] = args.precipitacao
    if args.modo_precipitacao:
        cfg_precip["modo"] = args.modo_precipitacao
    rf_config.valida_precipitacao(cfg_precip)

    cfg_era5 = dict(era5_tempo.normaliza(cfg.get("era5")))
    if args.horario:
        cfg_era5["horario"] = args.horario
    if args.hora_local is not None:
        cfg_era5["hora_local"] = int(args.hora_local)
    if args.hora is not None:
        cfg_era5["hora"] = int(args.hora)
        if not args.horario:
            cfg_era5["horario"] = "fixo"
    cfg_era5 = era5_tempo.normaliza(cfg_era5)
    hora = era5_tempo.rotulo_hora(cfg_era5)     # rótulo dos arquivos

    inicio, fim = resolve_periodo(args)
    produto = args.produto + rf_config.sufixo_precipitacao(cfg_precip)
    if cfg_era5["horario"] == "solar":
        produto += "_SOLAR"
    dir_saida = f"{base}/data/output/2.2/{produto}/netcdf"

    # -----------------------------------------------------------------------
    # Estado inicial: retomado de arquivo, ou partida a frio com spin-up
    # -----------------------------------------------------------------------
    estado = None
    if args.estado_inicial:
        estado, data_estado = le_estado(args.estado_inicial)
        aquecimento = 0
        if data_estado:
            # O dia seguinte ao estado salvo, à meia-noite (o horário do
            # estado é o da hora das condições, não do início do dia).
            seguinte = (data_estado + dt.timedelta(days=1)).replace(
                hour=0, minute=0, second=0, microsecond=0)
            # Se o estado for anterior ao período pedido, os dias no meio
            # entram como aquecimento (calculados, não gravados).
            primeiro = min(seguinte, inicio)
            print(f"Estado inicial: {args.estado_inicial} "
                  f"({data_estado:%Y-%m-%d}) — cálculo retomado em "
                  f"{primeiro:%Y-%m-%d}")
            if seguinte > inicio:
                print(f"AVISO: o estado é posterior ao início pedido; os "
                      f"dias de {inicio:%Y-%m-%d} a "
                      f"{seguinte - dt.timedelta(days=1):%Y-%m-%d} serão "
                      f"recalculados a partir dele.", file=sys.stderr)
        else:
            primeiro = inicio
            print(f"Estado inicial: {args.estado_inicial} (sem data)")
    else:
        aquecimento = max(int(args.spinup), 0)
        primeiro = inicio - dt.timedelta(days=aquecimento)

    dias = [primeiro + dt.timedelta(days=i)
            for i in range((fim - primeiro).days + 1)]

    print(f"FWI OBSERVADO: {inicio:%Y%m%d} a {fim:%Y%m%d} "
          f"({(fim - inicio).days + 1} dia(s) gravados)")
    print(f"precip.: >>{rf_config.descricao_precipitacao(cfg_precip)}")
    print(f"horario: >>{era5_tempo.descricao(cfg_era5)}")
    if aquecimento:
        print(f"spin-up: >>{aquecimento} dia(s) antes "
              f"({primeiro:%Y%m%d} a {inicio - dt.timedelta(days=1):%Y%m%d})")
    print(f"produto: >>{produto}")
    print(f"saida: >>>>{dir_saida}")
    if cfg_era5["horario"] == "fixo":
        print(f"NOTA: a convenção do FWI é o meio-dia LOCAL; esta rodada "
              f"usa a hora fixa {cfg_era5['hora']:02d} UTC (que equivale a "
              f"horas locais diferentes de leste a oeste). Para seguir a "
              f"convenção, use era5.horario: solar e hora_local: 12.")

    # -----------------------------------------------------------------------
    # Conferência das entradas
    # -----------------------------------------------------------------------
    faltantes = []
    for dia in dias:
        _, faltas = entradas_do_dia(base, caminhos, dia, cfg_era5,
                                    cfg_precip=cfg_precip)
        if faltas:
            faltantes.append((dia, faltas))

    if faltantes:
        print(f"Aviso: {len(faltantes)} de {len(dias)} dia(s) sem entradas "
              f"completas (o estado é mantido e o dia não é gravado):",
              file=sys.stderr)
        for dia, faltas in faltantes[:5]:
            print(f"  {dia:%Y-%m-%d}: falta "
                  f"{os.path.basename(faltas[0])}"
                  + (f" (+{len(faltas)-1})" if len(faltas) > 1 else ""),
                  file=sys.stderr)
        if len(faltantes) > 5:
            print(f"  ... e mais {len(faltantes) - 5} dia(s)",
                  file=sys.stderr)
        preparador = ("prepara_mswep.py" if cfg_precip["fonte"] == "mswep"
                      else "prepara_imerg.py")
        print(f"  -> rode {preparador} / prepara_era5.py para o período.",
              file=sys.stderr)

    if args.simular:
        print(f"(--simular: {len(dias) - len(faltantes)} de {len(dias)} "
              f"dia(s) com entradas completas; nada foi calculado)")
        return

    if len(faltantes) == len(dias):
        sys.exit("Nenhum dia com entradas completas.")

    # -----------------------------------------------------------------------
    # Laço temporal (sequencial — o estado atravessa os dias)
    # -----------------------------------------------------------------------
    grade = None
    lat = lon = None
    gravados = []
    for dia in dias:
        entradas, faltas = entradas_do_dia(base, caminhos, dia, cfg_era5,
                                           grade, cfg_precip)
        if faltas:
            continue
        t2m, ur2m, vento, chuva, lat, lon = entradas
        if grade is None:
            grade = (lat, lon)
            if estado is None:
                estado = fwi_core.EstadoFWI.inicial(
                    t2m.shape, args.ffmc0, args.dmc0, args.dc0)
            elif estado.ffmc.shape != t2m.shape:
                sys.exit(f"Estado inicial na grade {estado.ffmc.shape} "
                         f"difere da grade dos dados {t2m.shape}.")

        estado, indices = fwi_core.passo_diario(
            estado, t2m, ur2m, vento, chuva, dia.month, lat)

        if dia < inicio:                      # dia de spin-up: não grava
            continue
        quando = dia.replace(hour=hora)
        arquivo = os.path.join(dir_saida, f"FWI.OBS.{quando:%Y%m%d%H}.nc")
        grava_netcdf_fwi(indices, lat, lon, quando, arquivo)
        gravados.append(dia)
        print(f"OK   {quando:%Y%m%d%H}: FWI médio "
              f"{np.nanmean(indices['FWI']):.1f} | DC médio "
              f"{np.nanmean(indices['DC']):.0f} -> {arquivo}")

    if args.salvar_estado and estado is not None:
        ultimo = (gravados[-1] if gravados else dias[-1]).replace(hour=hora)
        grava_estado(estado, lat, lon, ultimo, args.salvar_estado)
        print(f"Estado salvo ({ultimo:%Y%m%d%H}): {args.salvar_estado}")

    print(f"Concluído: {len(gravados)} dia(s) gravados, "
          f"{len(faltantes)} pulado(s) por falta de entradas.")

    # -----------------------------------------------------------------------
    # Agregações
    # -----------------------------------------------------------------------
    operacoes = rf_core.operacoes_pedidas(args)
    if not operacoes or not gravados:
        return
    # --frequencia/--percentil sozinhos valem para todo o período
    faz_periodo = args.media or not args.media_mensal

    def caminho(dia):
        return os.path.join(dir_saida,
                            f"FWI.OBS.{dia.replace(hour=hora):%Y%m%d%H}.nc")

    var = args.var_agrega

    for rotulo, operacao, extra in operacoes:
        if args.media_mensal:
            for (ano, mes), do_mes in rf_core.agrupa_por_mes(gravados):
                saida = os.path.join(
                    dir_saida,
                    f"FWI.OBS.{var}.{rotulo}.{ano:04d}{mes:02d}.nc")
                _, usados = rf_core.agrega_campos(
                    [caminho(d) for d in do_mes], saida, operacao,
                    titulo=(f"{var} observado — {rotulo} de {ano:04d}-"
                            f"{mes:02d} ({len(do_mes)} dias)"),
                    data_ref=do_mes[-1].replace(hour=hora), nome_var=var,
                    **extra)
                print(f"{var} {rotulo} {ano:04d}-{mes:02d} ({usados} dias): "
                      f"{saida}")

        if faz_periodo:
            saida = os.path.join(
                dir_saida,
                f"FWI.OBS.{var}.{rotulo}.{inicio:%Y%m%d}-{fim:%Y%m%d}.nc")
            _, usados = rf_core.agrega_campos(
                [caminho(d) for d in gravados], saida, operacao,
                titulo=(f"{var} observado — {rotulo} de {inicio:%Y%m%d} a "
                        f"{fim:%Y%m%d} ({len(gravados)} dias)"),
                data_ref=fim.replace(hour=hora), nome_var=var, **extra)
            print(f"{var} {rotulo} do período ({usados} dias): {saida}")


if __name__ == "__main__":
    main()
