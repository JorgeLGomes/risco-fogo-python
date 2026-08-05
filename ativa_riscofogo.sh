# ============================================================================
# ativa_riscofogo.sh — ambiente Python do Risco de Fogo no cluster
#
# USE SEMPRE COM "source" (o script altera o shell atual):
#     source ativa_riscofogo.sh
#
# O que ele faz, nesta ordem:
#   1. Carrega o módulo Anaconda do sistema (environment modules), se houver;
#   2. Inicializa o conda e ativa o env "riscofogo" (se existir);
#   3. Se não houver conda/env, usa o venv ~/envs/riscofogo como alternativa;
#   4. Confere o interpretador e as bibliotecas, avisando o que faltar.
#
# Ajustes rápidos (podem ser definidos antes do source):
#   MODULO_ANACONDA  nome do módulo (descubra com: module avail 2>&1 | grep -i conda)
#   ENV_CONDA        nome do ambiente conda           (padrão: riscofogo)
#   VENV_FALLBACK    caminho do venv alternativo      (padrão: ~/envs/riscofogo)
#
# Para automatizar em todo login, adicione ao final do ~/.bashrc:
#   source /p/projetos/grpeta/Team/jorge.gomes/risco-fogo-python/ativa_riscofogo.sh
# (e remova qualquer ativação antiga que só imprime "(riscofogo)" no prompt)
# ============================================================================

MODULO_ANACONDA="${MODULO_ANACONDA:-anaconda3}"
ENV_CONDA="${ENV_CONDA:-riscofogo}"
VENV_FALLBACK="${VENV_FALLBACK:-$HOME/envs/riscofogo}"

# ----------------------------------------------------------------- proteção
# Precisa ser "sourced": executado (./ativa...) não altera o shell do usuário.
if [[ "${BASH_SOURCE[0]}" == "$0" ]]; then
    echo "ERRO: rode com  source ${BASH_SOURCE[0]}  (não ./...)" >&2
    exit 1
fi

_rf_ok=0

# ------------------------------------------------- 1. módulo do sistema
if command -v module >/dev/null 2>&1; then
    if module avail 2>&1 | grep -qi "$MODULO_ANACONDA"; then
        module load "$MODULO_ANACONDA" 2>/dev/null \
            && echo "[ativa_riscofogo] módulo carregado: $MODULO_ANACONDA"
    else
        echo "[ativa_riscofogo] aviso: módulo '$MODULO_ANACONDA' não existe." >&2
        echo "  Descubra o nome certo com:  module avail 2>&1 | grep -iE 'conda|python'" >&2
        echo "  e rode:  MODULO_ANACONDA=nome_certo source ${BASH_SOURCE[0]}" >&2
    fi
fi

# ------------------------------------------------- 2. conda + env
if command -v conda >/dev/null 2>&1; then
    # Inicializa o conda neste shell (hook moderno; conda.sh como reserva).
    eval "$(conda shell.bash hook 2>/dev/null)" 2>/dev/null \
        || source "$(conda info --base 2>/dev/null)/etc/profile.d/conda.sh" 2>/dev/null

    # Procura o env pelo NOME e também pelo CAMINHO (envs criados fora do
    # diretório padrão aparecem no "conda env list" sem nome, só o caminho —
    # ex.: /p/projetos/.../conda/envs/riscofogo).
    _rf_env=""
    if conda env list 2>/dev/null | awk '{print $1}' | grep -qx "$ENV_CONDA"; then
        _rf_env="$ENV_CONDA"
    else
        _rf_env=$(conda env list 2>/dev/null | tr -d '*' \
                  | awk '{print $NF}' | grep -E "/envs/${ENV_CONDA}\$" | head -1)
    fi

    if [[ -n "$_rf_env" ]]; then
        conda activate "$_rf_env" \
            && echo "[ativa_riscofogo] conda env ativado: $_rf_env"
        # Env "vazio" (sem python próprio): o python3 continuaria sendo o do
        # sistema (ex.: /usr/bin/python3 3.6). Detecta e cai para o venv.
        if [[ -x "$CONDA_PREFIX/bin/python3" ]]; then
            _rf_ok=1
        else
            echo "[ativa_riscofogo] aviso: o env conda NÃO tem Python instalado." >&2
            echo "  Popular com:  conda install -p $CONDA_PREFIX \\" >&2
            echo "    -c conda-forge python=3.12 numpy xarray netcdf4 rasterio pyyaml pygrib scipy -y" >&2
            conda deactivate 2>/dev/null
        fi
    else
        echo "[ativa_riscofogo] aviso: o env conda '$ENV_CONDA' não existe ainda." >&2
        echo "  Crie uma única vez com:" >&2
        echo "    conda create -n $ENV_CONDA python=3.12 -y" >&2
        echo "    conda activate $ENV_CONDA" >&2
        echo "    conda install -c conda-forge numpy xarray netcdf4 rasterio pyyaml pygrib scipy -y" >&2
    fi
    unset _rf_env
fi

# ------------------------------------------------- 3. alternativa: venv
if [[ $_rf_ok -eq 0 && -f "$VENV_FALLBACK/bin/activate" ]]; then
    source "$VENV_FALLBACK/bin/activate" && _rf_ok=1 \
        && echo "[ativa_riscofogo] venv ativado: $VENV_FALLBACK"
fi

if [[ $_rf_ok -eq 0 ]]; then
    echo "[ativa_riscofogo] ERRO: nenhum ambiente disponível (nem conda '$ENV_CONDA', nem venv $VENV_FALLBACK)." >&2
    echo "  Crie o venv com:  python3.12 -m venv $VENV_FALLBACK && source $VENV_FALLBACK/bin/activate \\" >&2
    echo "                    && python3 -m pip install numpy xarray netCDF4 rasterio pyyaml pygrib scipy" >&2
    return 1
fi

# ------------------------------------------------- 4. sanidade
echo "[ativa_riscofogo] python3: $(command -v python3)  ($(python3 -V 2>&1))"
python3 - <<'PYEOF'
import importlib.util, sys
if sys.version_info < (3, 9):
    print("[ativa_riscofogo] AVISO: Python < 3.9 — o pipeline exige 3.9+.")
pacote = {"yaml": "pyyaml"}          # módulo -> nome no pip
faltando = [m for m in ("numpy", "xarray", "netCDF4", "rasterio", "yaml")
            if importlib.util.find_spec(m) is None]
opcional = [m for m in ("pygrib", "scipy") if importlib.util.find_spec(m) is None]
if faltando:
    print(f"[ativa_riscofogo] AVISO: faltam bibliotecas: {', '.join(faltando)}"
          "\n  instale com:  python3 -m pip install "
          + " ".join(pacote.get(m, m) for m in faltando)
          + "   (ou conda install -c conda-forge ...)")
else:
    print("[ativa_riscofogo] bibliotecas principais OK"
          + (f" (opcionais ausentes: {', '.join(opcional)})" if opcional else ""))
PYEOF

unset _rf_ok
