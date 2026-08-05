# Instruções de Git e GitHub

## Risco de Fogo Previsto em Python — repositório `JorgeLGomes/risco-fogo-python`

**Versão:** 1.3 · 5 de agosto de 2026

Este documento descreve como manter o repositório do projeto no GitHub:
estrutura, fluxo de commits, convenções de mensagem, versões (tags) e
solução dos problemas mais comuns.

---

## 1. Estrutura do repositório

```
risco-fogo-python/
├── rf_core.py                  # Núcleo do cálculo do RF
├── rf_fontes.py                # Camada de fontes (GFS, Eta, BESM)
├── rf_config.py                # Configuração YAML dos dados de entrada
├── config_exemplo.yaml         # Modelo comentado do config
├── ativa_riscofogo.sh          # Ativação do ambiente no cluster (source)
├── rf_previsto_1_5dias.py      # Produto diário (1–5 dias)
├── rf_previsto_1_2_semanas.py  # Produto semanal (7 e 14 dias)
├── rf_previsto.py              # Script genérico (qualquer horizonte/fonte)
├── prepara_gfs.py              # Download/preparo do GFS (pós-SCN 25-81)
├── prepara_imerg.py            # Download/conversão do IMERG (GES DISC)
├── teste_rf.py                 # Teste do núcleo
├── teste_rf_previsto.py        # Teste do script genérico
├── teste_rf_multifonte.py      # Teste do modo multifonte
├── teste_besm_real.py          # Teste com dados reais do BESM T062
├── teste_prepara_gfs.py        # Teste do preparo do GFS
├── teste_prepara_imerg.py      # Teste do preparo do IMERG
├── requirements.txt            # Dependências Python
├── README.md
├── .gitignore                  # Ignora __pycache__, *.nc, *.tif e logs
├── docs/                       # Relatório, manual e estas instruções
└── originais/                  # Scripts bash+NCL originais (referência)
```

O repositório local fica em `C:\Users\jorge\Claude\Projects\risco-fogo-python`
e o remoto em `https://github.com/JorgeLGomes/risco-fogo-python`.

## 2. Fluxo de trabalho para qualquer atualização

Sempre nesta ordem — editar, testar, commitar, enviar:

```powershell
cd C:\Users\jorge\Claude\Projects\risco-fogo-python

# 1. Confira o que mudou
git status
git diff

# 2. Rode os testes antes de commitar
python teste_rf.py
python teste_rf_previsto.py
python teste_rf_multifonte.py

# 3. Adicione e commite (agrupe mudanças relacionadas num mesmo commit)
git add <arquivos>
git commit -m "Mensagem curta no imperativo

Detalhes opcionais em linhas seguintes: o que mudou e por quê."

# 4. Envie ao GitHub
git push origin main
```

## 3. Convenções de mensagem de commit

A primeira linha resume a mudança no imperativo, com até ~70 caracteres
(ex.: "Adiciona fonte Eta", "Corrige agregação de acúmulos de 12h").
Depois de uma linha em branco, detalhe o que mudou e por quê, em itens se
ajudar. Agrupe por assunto: código em um commit, documentação em outro.
Exemplos usados neste projeto:

```
Adiciona suporte multifonte: GFS, Eta e BESM ate 13 meses

- rf_fontes.py: camada de fontes configuravel (padroes de nome, variaveis,
  frequencia dos acumulos 1h/12h/1d, tipo de acumulacao, unidades, alcance)
- Serie diaria de 120 tempos combinando IMERG observado + previsao da fonte
- rf_core: nova calcula_risco_fogo_dados (arrays), mantendo compatibilidade
- rf_previsto.py: --fonte, --config-fontes e horizontes em meses (Nm)
- teste_rf_multifonte.py: 6 cenarios, incluindo Eta 13m e BESM 12h
```

Se o console do Windows não estiver em UTF-8, escreva as mensagens sem
acentos (como acima) para evitar caracteres corrompidos no histórico.

## 4. Versões (tags)

A cada marco, crie uma tag anotada e envie-a (o push de tags é separado):

```powershell
git tag -a v1.2.0 -m "Multifonte: Eta e BESM ate 13 meses"
git push origin v1.2.0

git tag                  # lista as tags locais
git push origin --tags   # envia todas as tags de uma vez (alternativa)
```

Histórico de versões do projeto:

| Tag | Conteúdo |
|---|---|
| `v1.0.0` | Conversão NCL → Python dos dois produtos operacionais + documentação |
| `v1.1.0` | Script genérico de horizontes (`rf_previsto.py`) + documentação v1.1 |
| `v1.2.0` | Multifonte (GFS/Eta/BESM até 13 meses, acúmulos 1h/12h/1d) + documentação v1.2 |
| `v1.3.0` | Config YAML (--config), prepara_gfs.py (pós-SCN 25-81) e documentação v1.4 |
| — | Commit seguinte: prepara_imerg.py (banco IMERG via GES DISC) e manual v1.5 |

No GitHub, cada tag pode virar um "Release": página do repositório →
*Releases* → *Draft a new release* → escolha a tag, descreva e publique.

## 5. Commits pendentes desta atualização

Todos os arquivos já estão no repositório local (gravados diretamente).
Se commits anteriores ainda não subiram, tudo vai junto no mesmo push:

```powershell
cd C:\Users\jorge\Claude\Projects\risco-fogo-python

git status
git add -A
git commit -m "Sensibilidade sem arquivos estaticos e rodada diaria via YAML

- rf_core: com usar_vegetacao=False o mapa NAO e lido; classe uniforme em
  todos os pontos e saida na grade da precipitacao, sem mascara d'agua;
  topografia (se ligada) regradeada automaticamente (ler_topografia_grade);
  com --sem-vegetacao --sem-topografia o RF roda sem NENHUM arquivo estatico
- rf_previsto: --data-final aceita 'hoje'/'auto'/'sistema' (data do sistema),
  permitindo rodada diaria operacional definida so no YAML (data_final: hoje
  + horizontes pre-estabelecidos)
- config_exemplo.yaml: chaves de sensibilidade (sem_vegetacao,
  sem_topografia, classe_veg) comentadas com as combinacoes de rodada
- Manual v1.8: secoes 5.2, 5.5 e 5.6 atualizadas"

git push origin main
```

E no servidor (ian01): `git pull`.

Se o commit "Dispensa o mapa de vegetacao..." já tiver sido feito antes,
este novo `git add -A` + commit leva apenas o restante — a mensagem acima
continua válida.

## 6. Comandos úteis do dia a dia

```powershell
git log --oneline --decorate     # histórico resumido com tags
git log --follow -- rf_core.py   # histórico de um arquivo
git diff HEAD~1                  # o que mudou no último commit
git restore <arquivo>            # descarta alterações não commitadas
git pull origin main             # traz mudanças feitas em outra máquina
git remote -v                    # confere o remoto configurado
```

## 7. Problemas comuns

| Sintoma | Causa | Solução |
|---|---|---|
| `fatal: not a git repository` | O comando foi executado fora da pasta do repositório (ou a pasta foi copiada sem a subpasta oculta `.git`) | `cd` até a pasta certa; se o `.git` não existir, re-extraia o zip do repositório completo |
| `remote origin already exists` | O remoto já foi adicionado antes | `git remote set-url origin https://github.com/JorgeLGomes/risco-fogo-python.git` |
| Push rejeitado (`fetch first` / `non-fast-forward`) | O remoto tem commits que o local não tem (ex.: README criado pelo site, edição direta no GitHub) | `git pull origin main --no-rebase` e depois `git push` |
| Pede usuário/senha e a senha da conta falha | O GitHub não aceita senha de conta no git | Use o navegador quando o Git Credential Manager abrir, ou um Personal Access Token como senha (Settings → Developer settings → Personal access tokens) |
| Acentos corrompidos nas mensagens | Console do Windows fora de UTF-8 | `chcp 65001` antes dos commits, ou escreva as mensagens sem acentos |
| Arquivo grande recusado (>100 MB) | NetCDF/GeoTIFF commitado por engano | Os padrões `*.nc` e `*.tif` já estão no `.gitignore`; remova com `git rm --cached <arquivo>` e commite novamente |

## 8. Segurança

Antes de tornar o repositório público, remova as credenciais do `lftp` que
estão em `rf_previsto_1_2_semanas.py` (e nos scripts originais em
`originais/` e nos documentos): mova usuário/senha para variáveis de
ambiente ou `~/.netrc`. Atenção: apagar do arquivo não apaga do histórico
do git — se a senha já foi commitada e o repositório for público, troque a
senha no servidor e reescreva o histórico (ex.: `git filter-repo`) se
necessário.
