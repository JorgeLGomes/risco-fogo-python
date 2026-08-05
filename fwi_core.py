# -*- coding: utf-8 -*-
"""
fwi_core.py
===========

Motor do **FWI** — Canadian Forest Fire Weather Index System (Van Wagner &
Pickett, 1985; Van Wagner, 1987), implementado em numpy **vetorizado**
(campos 2D inteiros por passo de tempo), no mesmo estilo do ``rf_core.py``.

Componentes, na ordem de cálculo:

    FFMC  Fine Fuel Moisture Code    umidade do combustível fino (memória ~2/3 dia)
    DMC   Duff Moisture Code         umidade da camada orgânica (memória ~12 dias)
    DC    Drought Code               seca profunda (memória ~52 dias)
      ↓
    ISI   Initial Spread Index       FFMC + vento
    BUI   Build Up Index             DMC + DC
      ↓
    FWI   Fire Weather Index         ISI + BUI
    DSR   Daily Severity Rating      0,0272 · FWI^1,77

Entradas do passo diário (convenção do sistema: **meio-dia local**):

    t      temperatura do ar a 2 m .................. °C
    ur     umidade relativa a 2 m ................... %
    vento  velocidade do vento a 10 m ............... km/h
    chuva  precipitação acumulada nas 24 h anteriores  mm

Os três códigos de umidade são **integradores**: cada dia parte do valor do
dia anterior. Por isso o cálculo é sequencial no tempo (não paralelizável
por dia, ao contrário do RF) e exige um período de aquecimento (*spin-up*)
antes do primeiro dia de interesse — o ``fwi_observado.py`` cuida disso.

Ajuste hemisférico: os fatores de duração do dia (DMC) e o fator de
duração do dia (DC) dependem da latitude e do mês. As tabelas aqui usadas
são as faixas latitudinais padrão do sistema (as mesmas do xclim/cffdrs),
o que dá o comportamento correto no Hemisfério Sul e na faixa equatorial.

Valores iniciais usuais em partida a frio (start-up), quando não há estado
anterior: FFMC = 85, DMC = 6, DC = 15.

Referências
-----------
Van Wagner, C.E.; Pickett, T.L. (1985). *Equations and FORTRAN program for
the Canadian Forest Fire Weather Index System*. Canadian Forestry Service,
Forestry Technical Report 33.
Van Wagner, C.E. (1987). *Development and structure of the Canadian Forest
Fire Weather Index System*. Forestry Technical Report 35.
"""

from dataclasses import dataclass

import numpy as np

# ---------------------------------------------------------------------------
# Valores iniciais padrão (partida a frio)
# ---------------------------------------------------------------------------

FFMC_INICIAL = 85.0
DMC_INICIAL = 6.0
DC_INICIAL = 15.0

# ---------------------------------------------------------------------------
# Tabelas de duração do dia, por faixa de latitude e mês (jan..dez)
# ---------------------------------------------------------------------------

# Duração efetiva do dia (Le) usada no DMC.
# Faixas: 0 = [-90,-30) | 1 = [-30,-15) | 2 = [-15,15) | 3 = [15,30) | 4 = [30,90]
DIA_LUZ = np.array([
    [11.5, 10.5, 9.2, 7.9, 6.8, 6.2, 6.5, 7.4, 8.7, 10.0, 11.2, 11.8],
    [10.1, 9.6, 9.1, 8.5, 8.1, 7.8, 7.9, 8.3, 8.9, 9.4, 9.9, 10.2],
    [9.0] * 12,
    [7.9, 8.4, 8.9, 9.5, 9.9, 10.2, 10.1, 9.7, 9.1, 8.6, 8.1, 7.8],
    [6.5, 7.5, 9.0, 12.8, 13.9, 13.9, 12.4, 10.9, 9.4, 8.0, 7.0, 6.0],
], dtype=np.float64)

# Fator de duração do dia (Lf) usado no DC.
# Faixas: 0 = [-90,-15) | 1 = [-15,15) | 2 = [15,90]
FATOR_DIA_LUZ = np.array([
    [6.4, 5.0, 2.4, 0.4, -1.6, -1.6, -1.6, -1.6, -1.6, 0.9, 3.8, 5.8],
    [1.39] * 12,
    [-1.6, -1.6, -1.6, 0.9, 3.8, 5.8, 6.4, 5.0, 2.4, 0.4, -1.6, -1.6],
], dtype=np.float64)


def dia_luz(lat, mes):
    """Duração efetiva do dia (h) para o DMC, por ponto de grade.

    ``lat`` pode ser escalar ou array (2D, já conformado à grade);
    ``mes`` é o mês do ano (1–12)."""
    lat = np.asarray(lat, dtype=np.float64)
    faixa = np.select(
        [lat < -30.0, lat < -15.0, lat < 15.0, lat < 30.0],
        [0, 1, 2, 3], default=4)
    return DIA_LUZ[faixa, int(mes) - 1]


def fator_dia_luz(lat, mes):
    """Fator de duração do dia (Lf) para o DC, por ponto de grade."""
    lat = np.asarray(lat, dtype=np.float64)
    faixa = np.select([lat < -15.0, lat < 15.0], [0, 1], default=2)
    return FATOR_DIA_LUZ[faixa, int(mes) - 1]


# ---------------------------------------------------------------------------
# Códigos de umidade
# ---------------------------------------------------------------------------

def ffmc(t, ur, vento, chuva, ffmc_anterior):
    """Fine Fuel Moisture Code do dia (Eqs. 1–10).

    Parameters
    ----------
    t : temperatura ao meio-dia (°C)
    ur : umidade relativa ao meio-dia (%)
    vento : vento a 10 m ao meio-dia (km/h)
    chuva : precipitação das 24 h anteriores (mm)
    ffmc_anterior : FFMC do dia anterior
    """
    t = np.asarray(t, dtype=np.float64)
    h = np.clip(np.asarray(ur, dtype=np.float64), 0.0, 100.0)
    w = np.maximum(np.asarray(vento, dtype=np.float64), 0.0)
    p = np.maximum(np.asarray(chuva, dtype=np.float64), 0.0)
    f0 = np.asarray(ffmc_anterior, dtype=np.float64)

    # Eq. 1 — FFMC anterior -> teor de umidade
    mo = 147.2 * (101.0 - f0) / (59.5 + f0)

    # Eqs. 2, 3a e 3b — efeito da chuva
    chove = p > 0.5
    rf = np.where(chove, p - 0.5, 1.0)          # 1.0 = valor neutro seguro
    with np.errstate(over="ignore", invalid="ignore", divide="ignore"):
        base = mo + 42.5 * rf * np.exp(-100.0 / (251.0 - mo)) * \
            (1.0 - np.exp(-6.93 / rf))
        extra = 0.0015 * (mo - 150.0) ** 2 * np.sqrt(rf)
    mo_chuva = np.minimum(np.where(mo > 150.0, base + extra, base), 250.0)
    mo = np.where(chove, mo_chuva, mo)

    # Eq. 4 — teor de equilíbrio de secagem
    ed = (0.942 * h ** 0.679 + 11.0 * np.exp((h - 100.0) / 10.0)
          + 0.18 * (21.1 - t) * (1.0 - np.exp(-0.115 * h)))
    # Eq. 5 — teor de equilíbrio de umedecimento
    ew = (0.618 * h ** 0.753 + 10.0 * np.exp((h - 100.0) / 10.0)
          + 0.18 * (21.1 - t) * (1.0 - np.exp(-0.115 * h)))

    raiz_w = np.sqrt(w)
    # Eqs. 6a/6b e 8 — secagem (mo > ed)
    ko = (0.424 * (1.0 - (h / 100.0) ** 1.7)
          + 0.0694 * raiz_w * (1.0 - (h / 100.0) ** 8))
    kd = ko * 0.581 * np.exp(0.0365 * t)
    m_seca = ed + (mo - ed) / 10.0 ** kd

    # Eqs. 7a/7b e 9 — umedecimento (mo < ew)
    kl = (0.424 * (1.0 - ((100.0 - h) / 100.0) ** 1.7)
          + 0.0694 * raiz_w * (1.0 - ((100.0 - h) / 100.0) ** 8))
    kw = kl * 0.581 * np.exp(0.0365 * t)
    m_umida = ew - (ew - mo) / 10.0 ** kw

    m = np.where(mo > ed, m_seca, np.where(mo < ew, m_umida, mo))

    # Eq. 10 — teor de umidade -> FFMC
    f = 59.5 * (250.0 - m) / (147.2 + m)
    return np.clip(f, 0.0, 101.0)


def dmc(t, ur, chuva, mes, lat, dmc_anterior):
    """Duff Moisture Code do dia (Eqs. 11–17)."""
    t = np.asarray(t, dtype=np.float64)
    h = np.clip(np.asarray(ur, dtype=np.float64), 0.0, 100.0)
    p = np.maximum(np.asarray(chuva, dtype=np.float64), 0.0)
    p0 = np.asarray(dmc_anterior, dtype=np.float64)

    le = dia_luz(lat, mes)

    # Eqs. 16 e 17 — secagem do dia
    rk = np.where(t < -1.1, 0.0,
                  1.894 * (np.maximum(t, -1.1) + 1.1) * (100.0 - h)
                  * le * 1.0e-4)

    # Eqs. 11–15 — efeito da chuva
    chove = p > 1.5
    rw = 0.92 * p - 1.27
    with np.errstate(over="ignore", invalid="ignore", divide="ignore"):
        wmi = 20.0 + 280.0 / np.exp(0.023 * p0)      # Eq. 12 (convenção cffdrs)
        b = np.where(p0 <= 33.0, 100.0 / (0.5 + 0.3 * p0),
                     np.where(p0 <= 65.0, 14.0 - 1.3 * np.log(np.maximum(p0, 1e-6)),
                              6.2 * np.log(np.maximum(p0, 1e-6)) - 17.2))
        wmr = wmi + 1000.0 * rw / (48.77 + b * rw)   # Eq. 14
        pr_chuva = 43.43 * (5.6348 - np.log(np.maximum(wmr - 20.0, 1e-12)))
    pr = np.where(chove, pr_chuva, p0)               # Eq. 15
    pr = np.maximum(pr, 0.0)

    return np.maximum(pr + rk, 0.0)


def dc(t, chuva, mes, lat, dc_anterior):
    """Drought Code do dia (Eqs. 18–22)."""
    t = np.asarray(t, dtype=np.float64)
    p = np.maximum(np.asarray(chuva, dtype=np.float64), 0.0)
    d0 = np.asarray(dc_anterior, dtype=np.float64)

    lf = fator_dia_luz(lat, mes)

    # Eq. 22 — evapotranspiração potencial do dia
    pe = np.maximum((0.36 * (np.maximum(t, -2.8) + 2.8) + lf) / 2.0, 0.0)

    # Eqs. 18–21 — efeito da chuva
    chove = p > 2.8
    rw = 0.83 * p - 1.27
    with np.errstate(over="ignore", invalid="ignore", divide="ignore"):
        smi = 800.0 * np.exp(-d0 / 400.0)                  # Eq. 19
        dr = d0 - 400.0 * np.log(1.0 + 3.937 * rw / smi)   # Eqs. 20 e 21
    d_chuva = np.where(dr > 0.0, dr + pe, pe)
    return np.where(chove, d_chuva, d0 + pe)


# ---------------------------------------------------------------------------
# Índices derivados
# ---------------------------------------------------------------------------

def isi(vento, ffmc_dia):
    """Initial Spread Index (Eqs. 25 e 26)."""
    w = np.maximum(np.asarray(vento, dtype=np.float64), 0.0)
    f = np.asarray(ffmc_dia, dtype=np.float64)
    m = 147.2 * (101.0 - f) / (59.5 + f)                       # Eq. 1
    with np.errstate(over="ignore"):
        ff = 19.1152 * np.exp(-0.1386 * m) * (1.0 + m ** 5.31 / 4.93e7)
        return ff * np.exp(0.05039 * w)


def bui(dmc_dia, dc_dia):
    """Build Up Index (Eqs. 27a e 27b)."""
    p = np.asarray(dmc_dia, dtype=np.float64)
    d = np.asarray(dc_dia, dtype=np.float64)
    zerado = (p == 0) & (d == 0)
    denom = np.where(zerado, np.nan, p + 0.4 * d)
    with np.errstate(invalid="ignore", divide="ignore"):
        u = np.where(
            zerado, 0.0,
            np.where(p <= 0.4 * d,
                     0.8 * d * p / denom,
                     p - (1.0 - 0.8 * d / denom)
                     * (0.92 + (0.0114 * p) ** 1.7)))
    return np.clip(u, 0.0, None)


def fwi(isi_dia, bui_dia):
    """Fire Weather Index (Eqs. 28a, 28b, 30a e 30b)."""
    r = np.asarray(isi_dia, dtype=np.float64)
    u = np.asarray(bui_dia, dtype=np.float64)
    with np.errstate(over="ignore", invalid="ignore"):
        fd = np.where(u <= 80.0,
                      0.626 * u ** 0.809 + 2.0,
                      1000.0 / (25.0 + 108.64 / np.exp(0.023 * u)))
        b = 0.1 * r * fd
        s = np.where(b > 1.0,
                     np.exp(2.72 * (0.434 * np.log(np.maximum(b, 1e-12)))
                            ** 0.647),
                     b)
    return s


def dsr(fwi_dia):
    """Daily Severity Rating."""
    return 0.0272 * np.asarray(fwi_dia, dtype=np.float64) ** 1.77


# ---------------------------------------------------------------------------
# Estado e passo diário
# ---------------------------------------------------------------------------

@dataclass
class EstadoFWI:
    """Códigos de umidade que atravessam os dias (a "memória" do sistema)."""
    ffmc: np.ndarray
    dmc: np.ndarray
    dc: np.ndarray

    @classmethod
    def inicial(cls, forma, ffmc=FFMC_INICIAL, dmc=DMC_INICIAL, dc=DC_INICIAL):
        """Estado de partida a frio (start-up) com a forma da grade."""
        return cls(np.full(forma, float(ffmc)),
                   np.full(forma, float(dmc)),
                   np.full(forma, float(dc)))


def passo_diario(estado, t, ur, vento, chuva, mes, lat):
    """Avança um dia e devolve ``(novo_estado, indices)``.

    ``indices`` é um dict com FFMC, DMC, DC, ISI, BUI, FWI e DSR do dia.
    Todas as entradas são campos 2D na mesma grade; ``lat`` é a latitude
    de cada ponto (1D ou 2D — é conformada automaticamente)."""
    lat = np.asarray(lat, dtype=np.float64)
    forma = np.shape(t)
    if lat.ndim == 1 and len(forma) == 2 and lat.size == forma[0]:
        lat = lat[:, np.newaxis]                 # (nlat,) -> (nlat, 1)

    f = ffmc(t, ur, vento, chuva, estado.ffmc)
    p = dmc(t, ur, chuva, mes, lat, estado.dmc)
    d = dc(t, chuva, mes, lat, estado.dc)

    r = isi(vento, f)
    u = bui(p, d)
    s = fwi(r, u)

    novo = EstadoFWI(f, p, d)
    indices = {"FFMC": f, "DMC": p, "DC": d,
               "ISI": r, "BUI": u, "FWI": s, "DSR": dsr(s)}
    return novo, indices


def velocidade_vento(u10, v10, unidade_saida="km/h"):
    """Velocidade do vento a partir das componentes u e v (m/s).

    O FWI usa o vento em **km/h**; a ERA5 fornece u10/v10 em m/s."""
    vel = np.hypot(np.asarray(u10, dtype=np.float64),
                   np.asarray(v10, dtype=np.float64))
    if unidade_saida.lower() in ("km/h", "kmh", "km_h"):
        return vel * 3.6
    return vel
