# -*- coding: utf-8 -*-
"""
era5_tempo.py
=============

Escolha do **horário** das variáveis meteorológicas da ERA5 usadas pelos
produtos observados (RF e FWI), com dois modos:

``fixo``   uma única hora UTC para todo o domínio (ex.: 18 UTC, a hora dos
           produtos operacionais de RF).

``solar``  **hora solar local**: cada faixa de longitude usa a hora UTC
           correspondente à hora local pedida. Como o Brasil vai de
           ~UTC−2 a ~UTC−5, uma hora UTC fixa significa horas locais
           diferentes de leste a oeste (18 UTC = 16 h no litoral do
           Nordeste e 13 h no Acre). No modo solar, o campo é montado
           faixa a faixa a partir dos arquivos das horas UTC necessárias.

As faixas são os fusos solares de 15° (deslocamento = round(lon/15)), e
não os fusos legais — é a convenção usada pelos índices de perigo, que
pedem as condições do meio-dia (FWI) ou do meio da tarde (RF) *locais*.

Configuração (seção ``era5`` do config.yaml)::

    era5:
      horario: solar        # fixo | solar
      hora: 18              # usado quando horario: fixo
      hora_local: 15        # usado quando horario: solar
      horas: [17, 18, 19, 20]   # opcional: horas UTC a baixar/usar
"""

import numpy as np

MODOS = ("fixo", "solar")


def offset_utc(lon):
    """Deslocamento do fuso solar (h) de cada longitude: round(lon/15).

    Ex.: −45° -> −3 (UTC−3); −67,5° -> −4 ou −5 conforme o arredondamento."""
    lon = np.asarray(lon, dtype=np.float64)
    lon = np.where(lon > 180.0, lon - 360.0, lon)
    return np.round(lon / 15.0).astype(int)


def hora_utc_por_longitude(lon, hora_local):
    """Hora UTC (0–23) que corresponde a ``hora_local`` em cada longitude."""
    return np.mod(int(hora_local) - offset_utc(lon), 24)


def horas_utc_necessarias(lon, hora_local):
    """Horas UTC distintas necessárias para cobrir todas as longitudes."""
    return sorted(set(int(h) for h in
                      np.unique(hora_utc_por_longitude(lon, hora_local))))


def compoe_por_longitude(campos_por_hora, lon, hora_local):
    """Monta um campo 2D pegando, em cada coluna de longitude, o campo da
    hora UTC correspondente à hora solar local.

    ``campos_por_hora``: dict {hora_utc: campo 2D} na mesma grade.
    Colunas cuja hora não estiver disponível ficam com NaN."""
    horas = hora_utc_por_longitude(lon, hora_local)
    referencia = next(iter(campos_por_hora.values()))
    saida = np.full(np.shape(referencia), np.nan, dtype=np.float64)
    for hora in np.unique(horas):
        campo = campos_por_hora.get(int(hora))
        if campo is None:
            continue
        colunas = horas == hora
        saida[:, colunas] = np.asarray(campo, dtype=np.float64)[:, colunas]
    return saida


# ---------------------------------------------------------------------------
# Configuração
# ---------------------------------------------------------------------------

def normaliza(cfg_era5):
    """Valida e completa a seção ``era5`` da configuração."""
    cfg = dict(cfg_era5 or {})
    modo = str(cfg.get("horario", "fixo")).lower()
    if modo not in MODOS:
        raise ValueError(f"era5.horario inválido: '{modo}'. "
                         f"Use um de {MODOS}.")
    cfg["horario"] = modo
    cfg["hora"] = int(cfg.get("hora", 18))
    cfg["hora_local"] = int(cfg.get("hora_local", 15))
    horas = cfg.get("horas")
    cfg["horas"] = ([int(h) for h in horas] if horas else None)
    return cfg


def horas_para_baixar(cfg_era5, lon_oeste, lon_leste):
    """Horas UTC que o ``prepara_era5.py`` deve baixar para atender à
    configuração no domínio informado."""
    cfg = normaliza(cfg_era5)
    if cfg["horas"]:
        return sorted(set(cfg["horas"]))
    if cfg["horario"] == "fixo":
        return [cfg["hora"]]
    # Modo solar: cobre todas as faixas de longitude do domínio.
    lons = np.linspace(float(lon_oeste), float(lon_leste), 400)
    return horas_utc_necessarias(lons, cfg["hora_local"])


def horas_para_grade(cfg_era5, lon):
    """Horas UTC necessárias para a grade de longitudes informada."""
    cfg = normaliza(cfg_era5)
    if cfg["horas"]:
        return sorted(set(cfg["horas"]))
    if cfg["horario"] == "fixo":
        return [cfg["hora"]]
    return horas_utc_necessarias(lon, cfg["hora_local"])


def rotulo_hora(cfg_era5):
    """Hora usada como rótulo dos arquivos de saída dos produtos
    observados: a hora UTC no modo fixo, a hora local no modo solar."""
    cfg = normaliza(cfg_era5)
    return cfg["hora"] if cfg["horario"] == "fixo" else cfg["hora_local"]


def descricao(cfg_era5):
    """Texto curto para logs e atributos do NetCDF."""
    cfg = normaliza(cfg_era5)
    if cfg["horario"] == "fixo":
        return f"hora fixa {cfg['hora']:02d} UTC"
    return (f"hora solar local {cfg['hora_local']:02d} h "
            f"(composta por faixas de longitude)")
