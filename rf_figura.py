# -*- coding: utf-8 -*-
"""
rf_figura.py
============

Gera figuras PNG dos campos de Risco de Fogo (RF.OBS.*, RF.PREV.*,
médias mensais, etc.) com a **paleta oficial da operação**, idêntica ao
SLD do GeoServer (INPE_FireRiskModel_2.2):

    -999 (ausente)  transparente
    Mínimo   0,15   #17b617
    Baixo    0,40   #79f674
    Médio    0,70   #ffff82
    Alto     0,95   #ff2e00
    Crítico  1,00   #a70000

Como no SLD (``type="ramp"``), as cores são interpoladas linearmente
entre essas paradas. Use ``--classes`` para a versão discreta (uma cor
por faixa), útil quando se quer contar área por classe.

Uso
---
    # Um mapa por arquivo
    python3 rf_figura.py data/output/2.2/RF_OBS/netcdf/RF.OBS.MEDIA.202607.nc

    # Vários arquivos num painel único (ex.: médias mensais)
    python3 rf_figura.py data/output/2.2/RF_OBS/netcdf/RF.OBS.MEDIA.2026*.nc \
        --painel --saida rf_obs_mensal_2026.png

    # Todos os dias de um mês, num painel
    python3 rf_figura.py .../RF.OBS.202607*18.nc --painel --colunas 7

Opções principais: --saida (arquivo ou pasta), --painel, --colunas,
--titulo, --dpi, --sem-mascara (não aplica a máscara de oceano).

Requer matplotlib. A máscara de oceano usa o pacote global-land-mask
quando disponível (necessária apenas para campos gerados com
--sem-vegetacao, que não trazem a máscara d'água do mapa de vegetação).
"""

import argparse
import datetime as dt
import glob
import os
import re
import sys

import numpy as np

import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt                       # noqa: E402
from matplotlib.colors import (BoundaryNorm, LinearSegmentedColormap,
                               ListedColormap, Normalize)   # noqa: E402

# Paleta oficial da operação — mesma do SLD do GeoServer
# (INPE_FireRiskModel_2.2): pares (quantidade, cor, rótulo).
PALETA_SLD = [
    (0.15, "#17b617", "Mínimo"),
    (0.40, "#79f674", "Baixo"),
    (0.70, "#ffff82", "Médio"),
    (0.95, "#ff2e00", "Alto"),
    (1.00, "#a70000", "Crítico"),
]
QUANTIDADES = [q for q, _, _ in PALETA_SLD]
CORES = [c for _, c, _ in PALETA_SLD]
NOMES = [n for _, _, n in PALETA_SLD]
# Limites das faixas na versão discreta (--classes).
LIMITES = [0.0] + QUANTIDADES[:-1] + [1.0001]
ROTULOS = ["Mínimo\n0–0,15", "Baixo\n0,15–0,40", "Médio\n0,40–0,70",
           "Alto\n0,70–0,95", "Crítico\n0,95–1"]

# Classes do FWI (Canadian FWI System) — faixas usuais de perigo. Como o
# FWI não é limitado a 1, a escala é definida por limiares absolutos.
LIMITES_FWI = [0.0, 5.0, 12.0, 22.0, 35.0, 60.0]
CORES_FWI = ["#17b617", "#79f674", "#ffff82", "#ff2e00", "#a70000"]
ROTULOS_FWI = ["Muito baixo\n0–5", "Baixo\n5–12", "Moderado\n12–22",
               "Alto\n22–35", "Muito alto\n> 35"]


def escala_fwi():
    """Escala em classes para os campos do FWI (limiares absolutos)."""
    cmap = ListedColormap(CORES_FWI)
    return cmap, BoundaryNorm(LIMITES_FWI, cmap.N)


def escala(discreta=False):
    """Devolve (cmap, norm) na paleta oficial. Por padrão reproduz o
    ``type="ramp"`` do SLD (interpolação linear entre as paradas);
    ``discreta=True`` dá uma cor por faixa."""
    if discreta:
        cmap = ListedColormap(CORES)
        return cmap, BoundaryNorm(LIMITES, cmap.N)
    # Rampa: abaixo da primeira parada, a cor da primeira parada
    # (comportamento do GeoServer).
    paradas = [(0.0, CORES[0])] + [(q, c) for q, c in zip(QUANTIDADES, CORES)]
    cmap = LinearSegmentedColormap.from_list("rf_sld", paradas)
    return cmap, Normalize(vmin=0.0, vmax=1.0)

_RE_DATA = re.compile(r"(\d{8})(\d{2})?")


def le_campo(caminho, nome_var=None):
    """Lê um campo do pipeline: (campo 2D com NaN, lat, lon, atributos).

    ``nome_var`` escolhe a variável em arquivos com várias (componentes do
    FWI); por padrão usa a primeira — ou ``FWI``, se existir."""
    import xarray as xr
    with xr.open_dataset(caminho, decode_times=False) as ds:
        if nome_var and nome_var in ds.data_vars:
            nome = nome_var
        elif "FWI" in ds.data_vars:
            nome = "FWI"
        else:
            nome = next(iter(ds.data_vars))
        dados = np.asarray(ds[nome].values, dtype=np.float32)
        if dados.ndim == 3:
            dados = dados[0]
        dados = np.where(dados <= -998.0, np.nan, dados)
        lat = np.asarray(ds["lat"].values, dtype=np.float64)
        lon = np.asarray(ds["lon"].values, dtype=np.float64)
        atributos = dict(ds.attrs)
        atributos["_variavel"] = nome
    return dados, lat, lon, atributos


def rotulo_do_arquivo(caminho, atributos):
    """Título curto para o painel, a partir do nome do arquivo."""
    nome = os.path.basename(caminho)
    if ".MEDIA." in nome or ".MAXIMO." in nome:
        op = "Média" if ".MEDIA." in nome else "Máximo"
        alvo = nome.split(".MEDIA." if ".MEDIA." in nome
                          else ".MAXIMO.")[1].replace(".nc", "")
        dias = atributos.get("dias_agregados")
        if re.fullmatch(r"\d{6}", alvo):               # AAAAMM
            quando = dt.datetime.strptime(alvo, "%Y%m")
            texto = f"{op} de {quando:%m/%Y}"
        elif "-" in alvo:                              # período
            a, b = alvo.split("-")[:2]
            texto = (f"{op} {dt.datetime.strptime(a, '%Y%m%d'):%d/%m/%Y} a "
                     f"{dt.datetime.strptime(b, '%Y%m%d'):%d/%m/%Y}")
        else:
            texto = f"{op} {alvo}"
        return texto + (f" ({dias} dias)" if dias else "")

    m = _RE_DATA.search(nome)
    if m:
        quando = dt.datetime.strptime(m.group(1), "%Y%m%d")
        hora = f" {m.group(2)} UTC" if m.group(2) else ""
        return f"{quando:%d/%m/%Y}{hora}"
    return nome.replace(".nc", "")


def mascara_oceano(dados, lat, lon):
    """Aplica NaN sobre o oceano (útil para campos gerados sem o mapa de
    vegetação, que não trazem a máscara d'água). Sem o pacote
    global-land-mask, devolve o campo inalterado."""
    try:
        from global_land_mask import globe
    except ImportError:
        return dados
    grade_lon, grade_lat = np.meshgrid(lon, lat)
    terra = globe.is_land(grade_lat, np.where(grade_lon > 180.0,
                                              grade_lon - 360.0, grade_lon))
    return np.where(terra, dados, np.nan)


def desenha(ax, dados, lat, lon, titulo, cmap, norm):
    extensao = [lon.min(), lon.max(), lat.min(), lat.max()]
    ax.imshow(dados, origin="lower", extent=extensao, cmap=cmap, norm=norm,
              interpolation="nearest", aspect="auto")
    ax.set_title(titulo, fontsize=10, pad=4)
    ax.set_xlim(extensao[0], extensao[1])
    ax.set_ylim(extensao[2], extensao[3])
    ax.tick_params(labelsize=7)
    ax.grid(True, color="0.85", linewidth=0.4, linestyle=":")
    ax.set_facecolor("#eaf1f7")          # oceano/ausente


def main():
    parser = argparse.ArgumentParser(
        description="Gera figuras PNG dos campos de Risco de Fogo.")
    parser.add_argument("arquivos", nargs="+",
                        help="NetCDF do RF (aceita curingas do shell).")
    parser.add_argument("--saida", default=None,
                        help="Arquivo PNG (com --painel) ou pasta de "
                             "destino (padrão: ao lado de cada NetCDF).")
    parser.add_argument("--painel", action="store_true",
                        help="Junta todos os campos numa única figura.")
    parser.add_argument("--colunas", type=int, default=None,
                        help="Colunas do painel (padrão: automático).")
    parser.add_argument("--titulo", default=None,
                        help="Título geral da figura.")
    parser.add_argument("--dpi", type=int, default=140)
    parser.add_argument("--var", default=None,
                        help="Variável a plotar em arquivos com mais de "
                             "uma (ex.: FFMC, DMC, DC, ISI, BUI, FWI). "
                             "Padrão: FWI, se existir.")
    parser.add_argument("--escala-fwi", action="store_true",
                        help="Usa as classes do FWI (0–5–12–22–35) em vez "
                             "da escala 0–1 do RF. Ativada "
                             "automaticamente para arquivos FWI.*")
    parser.add_argument("--classes", action="store_true",
                        help="Usa as faixas discretas (uma cor por classe) "
                             "em vez da rampa interpolada do SLD oficial.")
    parser.add_argument("--sem-mascara", action="store_true",
                        help="Não aplica a máscara de oceano.")
    args = parser.parse_args()

    caminhos = []
    for padrao in args.arquivos:
        achados = sorted(glob.glob(padrao)) if any(c in padrao
                                                   for c in "*?[") else [padrao]
        caminhos.extend(achados)
    caminhos = [c for c in caminhos if c.endswith(".nc")]
    if not caminhos:
        sys.exit("Nenhum arquivo NetCDF encontrado.")

    usa_fwi = args.escala_fwi or all(
        os.path.basename(c).upper().startswith("FWI.") for c in caminhos)
    cmap, norm = escala_fwi() if usa_fwi else escala(discreta=args.classes)

    campos = []
    for caminho in caminhos:
        dados, lat, lon, atributos = le_campo(caminho, args.var)
        if not args.sem_mascara:
            dados = mascara_oceano(dados, lat, lon)
        rot = rotulo_do_arquivo(caminho, atributos)
        if usa_fwi or args.var:
            rot = f"{atributos.get('_variavel', 'FWI')} — {rot}"
        campos.append((caminho, dados, lat, lon, rot))

    def barra(fig, eixos):
        mapa = plt.cm.ScalarMappable(cmap=cmap, norm=norm)
        if usa_fwi:
            marcas = [(LIMITES_FWI[i] + LIMITES_FWI[i + 1]) / 2
                      for i in range(len(CORES_FWI))]
            cb = fig.colorbar(mapa, ax=eixos, orientation="horizontal",
                              fraction=0.05, pad=0.10, aspect=40,
                              ticks=marcas, extend="max")
            cb.ax.set_xticklabels(ROTULOS_FWI, fontsize=8)
            cb.set_label("Fire Weather Index", fontsize=9, labelpad=6)
        elif args.classes:
            marcas = [(LIMITES[i] + LIMITES[i + 1]) / 2
                      for i in range(len(CORES))]
            cb = fig.colorbar(mapa, ax=eixos, orientation="horizontal",
                              fraction=0.05, pad=0.10, aspect=40,
                              ticks=marcas)
            cb.ax.set_xticklabels(ROTULOS, fontsize=8)
            cb.set_label("Risco de Fogo", fontsize=9, labelpad=6)
        else:
            # Rampa do SLD: números nas paradas e o nome da classe
            # centralizado em cada faixa (evita rótulos sobrepostos em
            # 0,95 e 1,00).
            cb = fig.colorbar(mapa, ax=eixos, orientation="horizontal",
                              fraction=0.05, pad=0.10, aspect=40,
                              ticks=QUANTIDADES)
            cb.ax.set_xticklabels([f"{q:.2f}".replace(".", ",")
                                   for q in QUANTIDADES], fontsize=7)
            faixas = [0.0] + QUANTIDADES
            for i, nome in enumerate(NOMES):
                meio = (faixas[i] + faixas[i + 1]) / 2
                cb.ax.text(meio, -2.3, nome, fontsize=8, ha="center",
                           va="top", transform=cb.ax.get_xaxis_transform())
            cb.set_label("Risco de Fogo", fontsize=9, labelpad=26)
        cb.outline.set_linewidth(0.5)

    if args.painel:
        n = len(campos)
        colunas = args.colunas or min(4, max(1, int(np.ceil(np.sqrt(n)))))
        linhas = int(np.ceil(n / colunas))
        fig, eixos = plt.subplots(linhas, colunas,
                                  figsize=(4.2 * colunas, 4.0 * linhas),
                                  squeeze=False)
        for i, (_, dados, lat, lon, rotulo) in enumerate(campos):
            desenha(eixos[i // colunas][i % colunas], dados, lat, lon,
                    rotulo, cmap, norm)
        for j in range(n, linhas * colunas):
            eixos[j // colunas][j % colunas].axis("off")
        if args.titulo:
            fig.suptitle(args.titulo, fontsize=13, y=0.995)
        barra(fig, eixos.ravel().tolist())
        saida = args.saida or "rf_painel.png"
        if os.path.isdir(saida):
            saida = os.path.join(saida, "rf_painel.png")
        fig.savefig(saida, dpi=args.dpi, bbox_inches="tight")
        plt.close(fig)
        print(f"Figura: {saida}  ({n} campo(s))")
        return

    for caminho, dados, lat, lon, rotulo in campos:
        fig, ax = plt.subplots(figsize=(7.2, 7.0))
        desenha(ax, dados, lat, lon, args.titulo or rotulo, cmap, norm)
        ax.set_xlabel("Longitude", fontsize=9)
        ax.set_ylabel("Latitude", fontsize=9)
        barra(fig, [ax])
        if args.saida and not os.path.splitext(args.saida)[1]:
            os.makedirs(args.saida, exist_ok=True)
            saida = os.path.join(
                args.saida,
                os.path.basename(caminho).replace(".nc", ".png"))
        elif args.saida and len(campos) == 1:
            saida = args.saida
        else:
            saida = caminho.replace(".nc", ".png")
        fig.savefig(saida, dpi=args.dpi, bbox_inches="tight")
        plt.close(fig)
        print(f"Figura: {saida}")


if __name__ == "__main__":
    main()
