// Gera os dois documentos Word: relatório de conversão e manual do usuário.
const fs = require("fs");
const {
  Document, Packer, Paragraph, TextRun, HeadingLevel, AlignmentType,
  Table, TableRow, TableCell, WidthType, BorderStyle, ShadingType,
  LevelFormat, TableOfContents, PageBreak,
} = require("docx");

const AZUL = "1F4E79";
const CINZA = "595959";
const FONTE = "Calibri";
const LARG_TABELA = 9026; // A4, margens de 1"

// ---------------------------------------------------------------- helpers
const p = (text, opts = {}) =>
  new Paragraph({
    spacing: { after: 160, line: 276 },
    alignment: AlignmentType.JUSTIFIED,
    ...opts.para,
    children: (Array.isArray(text) ? text : [{ t: text }]).map(
      (r) =>
        new TextRun({
          text: r.t,
          font: FONTE,
          size: 22,
          bold: r.b || false,
          italics: r.i || false,
          color: r.c || "000000",
          ...r.o,
        })
    ),
  });

const h1 = (t) => new Paragraph({ heading: HeadingLevel.HEADING_1, spacing: { before: 360, after: 200 }, children: [new TextRun({ text: t, font: FONTE, size: 30, bold: true, color: AZUL })] });
const h2 = (t) => new Paragraph({ heading: HeadingLevel.HEADING_2, spacing: { before: 280, after: 160 }, children: [new TextRun({ text: t, font: FONTE, size: 25, bold: true, color: AZUL })] });

const bullet = (t) =>
  new Paragraph({
    numbering: { reference: "lista-bullet", level: 0 },
    spacing: { after: 100, line: 276 },
    alignment: AlignmentType.JUSTIFIED,
    children: (Array.isArray(t) ? t : [{ t }]).map((r) => new TextRun({ text: r.t, font: FONTE, size: 22, bold: r.b || false })),
  });

const numbered = (t, ref) =>
  new Paragraph({
    numbering: { reference: ref, level: 0 },
    spacing: { after: 100, line: 276 },
    alignment: AlignmentType.JUSTIFIED,
    children: (Array.isArray(t) ? t : [{ t }]).map((r) => new TextRun({ text: r.t, font: FONTE, size: 22, bold: r.b || false })),
  });

const codigo = (linhas) =>
  linhas.map(
    (l, i) =>
      new Paragraph({
        shading: { type: ShadingType.CLEAR, fill: "F2F2F2" },
        spacing: { after: i === linhas.length - 1 ? 160 : 0 },
        children: [new TextRun({ text: l === "" ? " " : l, font: "Consolas", size: 19 })],
      })
  );

function tabela(cabecalho, linhas, larguras) {
  const total = larguras.reduce((a, b) => a + b, 0);
  const fator = LARG_TABELA / total;
  const cols = larguras.map((l) => Math.round(l * fator));
  const borda = { style: BorderStyle.SINGLE, size: 4, color: "BFBFBF" };
  const bordas = { top: borda, bottom: borda, left: borda, right: borda };

  const celula = (texto, largura, ehCab) =>
    new TableCell({
      width: { size: largura, type: WidthType.DXA },
      borders: bordas,
      shading: ehCab ? { type: ShadingType.CLEAR, fill: AZUL } : undefined,
      margins: { top: 60, bottom: 60, left: 100, right: 100 },
      children: [
        new Paragraph({
          spacing: { after: 0 },
          children: [
            new TextRun({
              text: texto,
              font: FONTE,
              size: 19,
              bold: ehCab,
              color: ehCab ? "FFFFFF" : "000000",
            }),
          ],
        }),
      ],
    });

  return new Table({
    width: { size: LARG_TABELA, type: WidthType.DXA },
    columnWidths: cols,
    rows: [
      new TableRow({ tableHeader: true, children: cabecalho.map((c, i) => celula(c, cols[i], true)) }),
      ...linhas.map((linha) => new TableRow({ children: linha.map((c, i) => celula(c, cols[i], false)) })),
    ],
  });
}

const TOC_ESTATICO = process.env.STATIC_TOC === "1";

const capa = (titulo, subtitulo, infos, secoes) => [
  new Paragraph({ spacing: { before: 3200, after: 240 }, alignment: AlignmentType.CENTER, children: [new TextRun({ text: titulo, font: FONTE, size: 52, bold: true, color: AZUL })] }),
  new Paragraph({ spacing: { after: 480 }, alignment: AlignmentType.CENTER, children: [new TextRun({ text: subtitulo, font: FONTE, size: 30, color: CINZA })] }),
  ...infos.map((l) => new Paragraph({ spacing: { after: 120 }, alignment: AlignmentType.CENTER, children: [new TextRun({ text: l, font: FONTE, size: 22, color: CINZA })] })),
  new Paragraph({ children: [new PageBreak()] }),
  new Paragraph({ spacing: { after: 200 }, children: [new TextRun({ text: "Sumário", font: FONTE, size: 30, bold: true, color: AZUL })] }),
  ...(TOC_ESTATICO
    ? secoes.map(
        (s) =>
          new Paragraph({
            spacing: { after: 120 },
            children: [new TextRun({ text: s, font: FONTE, size: 22, color: "000000" })],
          })
      )
    : [new TableOfContents("Sumário", { hyperlink: true, headingStyleRange: "1-2" })]),
  new Paragraph({ children: [new PageBreak()] }),
];

const numeracao = {
  config: [
    { reference: "lista-bullet", levels: [{ level: 0, format: LevelFormat.BULLET, text: "•", alignment: AlignmentType.LEFT, style: { paragraph: { indent: { left: 480, hanging: 240 } } } }] },
    { reference: "num-rel", levels: [{ level: 0, format: LevelFormat.DECIMAL, text: "%1.", alignment: AlignmentType.LEFT, style: { paragraph: { indent: { left: 480, hanging: 240 } } } }] },
    { reference: "num-man", levels: [{ level: 0, format: LevelFormat.DECIMAL, text: "%1.", alignment: AlignmentType.LEFT, style: { paragraph: { indent: { left: 480, hanging: 240 } } } }] },
    { reference: "num-form", levels: [{ level: 0, format: LevelFormat.DECIMAL, text: "%1.", alignment: AlignmentType.LEFT, style: { paragraph: { indent: { left: 480, hanging: 240 } } } }] },
  ],
};

function documento(children) {
  return new Document({
    numbering: numeracao,
    styles: { default: { document: { run: { font: FONTE, size: 22 } } } },
    features: { updateFields: true },
    sections: [{ properties: {}, children }],
  });
}

// ================================================================ RELATÓRIO
const rel = [];
rel.push(
  ...capa(
    "Relatório de Conversão NCL → Python",
    "Modelo de Risco de Fogo Previsto — INPE_FireRiskModel v2.2",
    [
      "4 de agosto de 2026",
      "Scripts convertidos: rf_previsto_1-5dias_2023.sh e rf_previsto_1-2_semanas_2024.sh",
      "Modelo: Alberto Setzer (INPE) · Código NCL original: Guilherme Martins (INPE)",
      "Programa Queimadas — http://www.inpe.br/queimadas/",
    ],
    [
      "1. Objetivo",
      "2. Arquitetura original",
      "3. Arquitetura convertida",
      "4. Formulação do modelo (inalterada)",
      "5. Tabela de substituições",
      "6. Validação",
      "7. Diferenças de comportamento e melhorias",
      "8. Pontos de atenção",
      "9. Conclusão",
    ]
  )
);

rel.push(h1("1. Objetivo"));
rel.push(p("Este relatório documenta a conversão dos dois scripts operacionais de cálculo do Risco de Fogo (RF) previsto em 1 km, originalmente escritos em Bash com o núcleo de cálculo em NCL (NCAR Command Language), para Python. A motivação principal é a descontinuação do NCL pelo NCAR, que o mantém apenas em modo de manutenção, e a consolidação da cadeia de processamento em uma única linguagem com ecossistema ativo."));
rel.push(p([{ t: "A conversão eliminou todas as dependências do ambiente conda " }, { t: "ncl_stable", o: { font: "Consolas", size: 20 } }, { t: ": o interpretador ncl, o cdo, o gdal_translate (binário) e o GNU parallel. Todo o processamento passa a ser feito com bibliotecas Python de uso amplo na comunidade científica: numpy, xarray, netCDF4 e rasterio." }]));

rel.push(h1("2. Arquitetura original"));
rel.push(p("Cada script original operava em quatro etapas. Primeiro, montava em arquivos temporários a lista dos 119 arquivos diários de precipitação observada do IMERG mais um arquivo de precipitação prevista do GFS. Em seguida, gerava dinamicamente (via heredoc) um script NCL por horário de previsão e os executava em paralelo com o GNU parallel. Depois, aguardava a produção dos arquivos com um laço de espera (sleep 600), corrigia o eixo de tempo e o valor ausente de cada NetCDF com o cdo e convertia para GeoTIFF com o gdal_translate. Por fim, publicava os resultados no geoserver TerraBrasilis (script auxiliar, lftp e scp)."));
rel.push(p("As principais diferenças entre os dois scripts:"));
rel.push(
  tabela(
    ["Característica", "1 a 5 dias (2023)", "1 a 2 semanas (2024)"],
    [
      ["Horizontes de previsão", "+6 h até +4 dias 18 UTC, a cada 6 h", "+7 e +14 dias, às 18 UTC"],
      ["Número de previsões", "19", "2"],
      ["Risco básico máximo (rb)", "0.9", "0.8"],
      ["Paralelismo", "parallel -j 20", "parallel -j 2"],
      ["Particularidade", "Fogograma (mergetime) e envio via envia_geoserv_tbrasilis.sh", "Cópia dos arquivos GFS de 12 UTC para 18 UTC no dia +14; envio via lftp e scp"],
      ["Diretório de saída", "RF_PREV", "RF_PREV_SEMANAL"],
    ],
    [26, 37, 37]
  )
);
rel.push(p(""));

rel.push(h1("3. Arquitetura convertida"));
rel.push(p("A versão Python é composta por quatro programas e dois testes:"));
rel.push(
  tabela(
    ["Arquivo", "Papel"],
    [
      ["rf_core.py", "Núcleo do cálculo do RF, compartilhado por todos os scripts. Substitui o script NCL gerado via heredoc, o cdo e o gdal_translate."],
      ["rf_previsto_1_5dias.py", "Orquestrador equivalente ao rf_previsto_1-5dias_2023.sh."],
      ["rf_previsto_1_2_semanas.py", "Orquestrador equivalente ao rf_previsto_1-2_semanas_2024.sh."],
      ["rf_previsto.py", "Script genérico: calcula o RF para qualquer horizonte de previsão (lista ou intervalo, inclusive meses) e qualquer fonte de dados (--fonte gfs|eta|besm), com rb máximo, produto e diretório base configuráveis e fallback opcional do GFS."],
      ["rf_fontes.py", "Camada de fontes de previsão: configuração por fonte (padrões de nome, variáveis, frequência dos acúmulos 1h/12h/1d, unidades, alcance), agregação para o passo diário e montagem da série de 120 dias misturando IMERG observado e precipitação prevista."],
      ["teste_rf.py", "Teste de validação com dados sintéticos e comparação com implementação de referência fiel ao NCL."],
      ["teste_rf_previsto.py", "Teste de ponta a ponta do script genérico com a estrutura de diretórios da produção reproduzida em /tmp."],
      ["teste_rf_multifonte.py", "Teste do modo multifonte: Eta a 13 meses, BESM com acúmulos de 12 h, fonte via JSON com frequência de 1 h e equivalência numérica com o núcleo."],
    ],
    [30, 70]
  )
);
rel.push(p(""));
rel.push(p("A geração de scripts NCL temporários foi substituída por uma chamada de função (rf_core.calcula_risco_fogo), e o parallel por um ProcessPoolExecutor da biblioteca padrão, com o mesmo número de processos dos scripts originais (configurável por --jobs). O laço de espera com sleep 600 tornou-se desnecessário: o pool de processos é controlado diretamente e, se alguma previsão falhar, o erro é registrado em log e o script termina com código de saída 1, preservando o contrato do original."));

rel.push(h1("4. Formulação do modelo (inalterada)"));
rel.push(p("A formulação física do RF foi preservada exatamente como no NCL:"));
rel.push(numbered([{ t: "Precipitação acumulada — ", b: true }, { t: "a série de 120 tempos (119 dias de IMERG + 1 previsão do GFS) é invertida no tempo e acumulada olhando para trás: vprec(i) = vprec(i−1) + precip(i)." }], "num-form"));
rel.push(numbered([{ t: "Fatores de precipitação (fp) — ", b: true }, { t: "onze fatores exponenciais fp = exp(cte × Δvprec) com as constantes −0.14, −0.07, −0.04, −0.03, −0.02, −0.01, −0.008, −0.004, −0.002, −0.001 e −0.0007, cobrindo as janelas de 1, 2, 3, 4, 5, 6–10, 11–15, 16–30, 31–60, 61–90 e 91–120 dias." }], "num-form"));
rel.push(numbered([{ t: "Dias de secura (PSE) — ", b: true }, { t: "PSE = 105 × fp1 × fp2 × … × fp11, interpolado bilinearmente da grade da precipitação (~10 km) para a grade de 1 km do mapa de vegetação." }], "num-form"));
rel.push(numbered([{ t: "Risco básico (rb) — ", b: true }, { t: "por classe de vegetação, com A = (−999.9, 6, 4, 3, 2.4, 2, 1.72, 1.5) e PSE_max = (−999.9, 30, 45, 60, 75, 90, 105, 120). Se PSE > PSE_max da classe, rb = rb_max (0.9 ou 0.8); caso contrário, rb = (rb_max × (1 + sin((A×PSE − 90) × 3.1416/180))) / 2. A classe 0 (superfícies líquidas) é valor ausente." }], "num-form"));
rel.push(numbered([{ t: "Fatores meteorológicos — ", b: true }, { t: "Fator de Umidade FU = −0.008×UR + 1.3 (UR em décimos; coeficiente alterado de −0.006 para −0.008 em 11/04/2019 para incluir a sazonalidade) e Fator de Temperatura FT = 0.02×T + 0.4 (T em °C), ambos interpolados para 1 km." }], "num-form"));
rel.push(numbered([{ t: "Risco final — ", b: true }, { t: "rbf = rb × FT × FU, limitado a 1; corrigido pelo Fator de Latitude FLAT = 1 + |lat| × 0.003 e pelo Fator Topográfico FTOP = 1 + elev × 0.00003 (equações de Setzer, 05/04/2019), novamente limitado a 1 e arredondado a 2 casas decimais." }], "num-form"));
rel.push(p([{ t: "Observação de fidelidade: ", b: true }, { t: "o NCL usa a constante 3.1416 (e não π) na conversão para radianos da equação do rb. Esse valor foi mantido deliberadamente para reproduzir os resultados operacionais." }]));

rel.push(h1("5. Tabela de substituições"));
rel.push(
  tabela(
    ["NCL / ferramenta externa", "Equivalente em Python"],
    [
      ["addfile / addfiles + ListSetType(\"cat\")", "xarray.open_dataset + numpy.concatenate"],
      ["precip(::-1,:,:) — inversão do tempo", "precip[::-1, :, :]"],
      ["Laço do while da precipitação acumulada", "numpy.cumsum(precip, axis=0)"],
      ["exp, sin, abs, where", "numpy.exp, numpy.sin, numpy.abs, numpy.where"],
      ["linint2_Wrap (interpolação bilinear)", "rf_core.interp_bilinear (numpy vetorizado)"],
      ["Duplo laço do i / do k do risco básico", "Indexação vetorizada A_VEG[veg], PSE_MAX_VEG[veg]"],
      ["floattoint(mapa_veg)", "Conversão para int32 na leitura"],
      ["mapa_veg@_FillValue = 0.0", "Classe 0 → NaN (índice 0 dos vetores A / PSE_max)"],
      ["conform_dims (FLAT 1D → 2D)", "Broadcasting FLAT[:, np.newaxis]"],
      ["fspan(latS, latN, n)", "numpy.linspace"],
      ["decimalPlaces(rbfn, 2, True)", "numpy.round(rbfn, 2)"],
      ["copy_VarCoords", "Coordenadas explícitas do xarray.Dataset"],
      ["Escrita NetCDF (addfile \"c\", fileattdef, filedimdef)", "xarray.Dataset.to_netcdf (NETCDF4_CLASSIC, time ilimitado)"],
      ["cdo -r -setmissval,-999 -settaxis,...", "Eixo de tempo e _FillValue −999 definidos na gravação"],
      ["cdo -O mergetime", "rf_core.mergetime (xarray.concat + sortby)"],
      ["gdal_translate (GTiff, EPSG:4326, TILED, LZW)", "rf_core.netcdf_para_geotiff (rasterio)"],
      ["parallel -j N + scripts .ncl temporários", "ProcessPoolExecutor(max_workers=N)"],
      ["Heredoc cat << EOF > rf.prev.*.ncl", "Chamada direta de rf_core.calcula_risco_fogo"],
      ["Laço de espera (sleep 600 + contagem)", "Controle direto do pool + verificação final + exit 1"],
      ["lftp / scp / envia_geoserv_tbrasilis.sh", "subprocess.run (desativável com --sem-envio)"],
    ],
    [48, 52]
  )
);
rel.push(p(""));

rel.push(h1("6. Validação"));
rel.push(p("O teste teste_rf.py constrói um cenário sintético completo (119 arquivos IMERG + GFS de precipitação e de temperatura/umidade + mapa de vegetação + topografia) e valida a cadeia de ponta a ponta:"));
rel.push(
  tabela(
    ["Verificação", "Resultado"],
    [
      ["RF final vetorizado vs. implementação de referência com laços explícitos idêntica ao NCL", "erro máximo ≈ 3×10⁻⁸"],
      ["interp_bilinear vs. scipy.RegularGridInterpolator", "erro máximo ≈ 2×10⁻⁶"],
      ["Classe de vegetação 0 (água)", "valor ausente (NaN), como no NCL"],
      ["Faixa de valores do RF", "[0, 1]"],
      ["Eixo de tempo do NetCDF de saída", "data/hora da previsão, time ilimitado, _FillValue −999"],
      ["GeoTIFF", "EPSG:4326, nodata −999, LZW, tiled, orientação norte→sul, limites corretos"],
      ["mergetime", "horários concatenados e ordenados corretamente"],
      ["Leitura do IMERG real (IMERG.YYYYMMDD.nc)", "variável prec, grade 0.1°, 901×850 pontos, lat −60.05…29.95, lon −114.95…−30.05"],
    ],
    [55, 45]
  )
);
rel.push(p(""));

rel.push(h1("7. Diferenças de comportamento e melhorias"));
rel.push(numbered([{ t: "Desempenho — ", b: true }, { t: "o duplo laço do NCL sobre a grade de 1 km (dezenas de milhões de pontos) foi vetorizado em numpy; o tempo de cálculo por previsão cai de forma expressiva em relação às ~3 h totais originais." }], "num-rel"));
rel.push(numbered([{ t: "Arquivos temporários — ", b: true }, { t: "arquivo.prev.prec.*, paralelizar_RF_PREV.txt e os scripts .ncl gerados dinamicamente deixam de existir; as listas são montadas em memória." }], "num-rel"));
rel.push(numbered([{ t: "Tratamento de falhas — ", b: true }, { t: "o NCL abortaria com erro de índice se houvesse menos de 120 tempos de precipitação; a versão Python valida explicitamente e registra mensagem clara no log. Arquivos IMERG faltantes continuam listados em log.falta.arquivos.prev.prec.txt." }], "num-rel"));
rel.push(numbered([{ t: "Aviso do NCL suprimido — ", b: true }, { t: "a mensagem \"warning: error attempting to fix non-monotonic aggregation variable\" (inofensiva, causada pela inversão do tempo) não existe mais, pois a concatenação é feita em numpy." }], "num-rel"));
rel.push(numbered([{ t: "Logs — ", b: true }, { t: "cada previsão grava seu log em log/log.<data_modelo>.<data_previsao>, como no original." }], "num-rel"));
rel.push(numbered([{ t: "Novos parâmetros de linha de comando — ", b: true }, { t: "--data-final YYYYMMDD (reprocessamento de datas passadas), --jobs N e --sem-envio (executa sem publicar nos servidores)." }], "num-rel"));
rel.push(numbered([{ t: "Script genérico de horizontes — ", b: true }, { t: "o rf_previsto.py (inexistente na versão NCL) permite gerar o RF para qualquer conjunto de horizontes, via --horizontes 18h,2d18h,7d18h,6m ou --de 1m --ate 13m --passo 1m, com --rb-max, --produto, --base, --fallback-gfs, --sem-tif e --fogograma." }], "num-rel"));
rel.push(numbered([{ t: "Múltiplas fontes de previsão — ", b: true }, { t: "com --fonte gfs|eta|besm (e --config-fontes para ajustar padrões de nome, variáveis e frequências via JSON), a série diária de 120 tempos passa a combinar IMERG observado com precipitação prevista da fonte, agregando acúmulos de 1h/12h/1 dia para o passo diário e regradeando para a grade do IMERG. Isso estende o alcance do RF de ~16 dias (GFS) para até 13 meses (Eta e BESM)." }], "num-rel"));

rel.push(h1("8. Pontos de atenção"));
rel.push(bullet([{ t: "Credenciais do lftp — ", b: true }, { t: "o script original continha usuário e senha em texto claro; foram mantidos como constantes no topo de rf_previsto_1_2_semanas.py para não alterar o comportamento, mas recomenda-se fortemente migrá-los para variáveis de ambiente ou ~/.netrc." }]));
rel.push(bullet([{ t: "Memória — ", b: true }, { t: "cada processo carrega arrays de 1 km em float64 (na grade completa da América do Sul, ~0.6 GB por array). Com --jobs 20 o consumo agregado é alto, como no original; ajuste --jobs à capacidade da máquina." }]));
rel.push(bullet([{ t: "Caminhos absolutos — ", b: true }, { t: "os diretórios de produção (/home/queimadas/INPE_FireRiskModel/...) foram mantidos idênticos e estão centralizados em constantes no topo de cada script." }]));
rel.push(bullet([{ t: "Interpolação nas bordas — ", b: true }, { t: "linint2 do NCL retorna valor ausente fora do domínio de origem; a implementação Python usa \"clamp\" nas bordas. Como a grade de 1 km está contida no domínio da precipitação e do GFS, não há diferença prática." }]));
rel.push(bullet([{ t: "Ano do mapa de vegetação — ", b: true }, { t: "mantida a regra original: anos ≥ 2020 usam o mapa de 2019 (Merge_MapBiomas_V5_IGBP_C6_2019.nc)." }]));

rel.push(h1("9. Conclusão"));
rel.push(p("A conversão reproduz a formulação e os produtos dos scripts originais com fidelidade numérica verificada (diferenças da ordem de 10⁻⁸, atribuíveis a arredondamento de ponto flutuante), elimina a dependência de NCL, cdo, GDAL (binário) e GNU parallel, reduz o tempo de execução pela vetorização do cálculo do risco básico e melhora a operação com validações explícitas, logs por previsão e parâmetros de linha de comando para reprocessamento e testes."));

// ================================================================ MANUAL
const man = [];
man.push(
  ...capa(
    "Manual do Usuário",
    "Risco de Fogo Previsto em Python — INPE_FireRiskModel v2.2",
    [
      "Versão 1.8 · 5 de agosto de 2026",
      "Substitui: rf_previsto_1-5dias_2023.sh e rf_previsto_1-2_semanas_2024.sh (bash + NCL)",
      "Programa Queimadas — http://www.inpe.br/queimadas/",
    ],
    [
      "1. Visão geral",
      "2. Requisitos",
      "3. Instalação",
      "4. Uso",
      "5. Script genérico para qualquer horizonte (rf_previsto.py)",
      "6. Preparo dos dados de entrada (prepara_gfs.py e prepara_imerg.py)",
      "7. Saídas",
      "8. Logs e monitoramento",
      "9. Solução de problemas",
      "10. Testes de validação",
      "11. Segurança",
      "12. Suporte",
    ]
  )
);

man.push(h1("1. Visão geral"));
man.push(p("Este pacote calcula o Risco de Fogo (RF) previsto em resolução de 1 km para a América do Sul, combinando a precipitação observada do IMERG (últimos 119 dias), as previsões do GFS (precipitação, temperatura e umidade relativa a 2 m), o mapa de vegetação (MapBiomas/IGBP) e a topografia (GTOPO30). São três programas:"));
man.push(bullet([{ t: "rf_previsto_1_5dias.py", b: true }, { t: " — gera 19 previsões, de +6 h até +4 dias 18 UTC, a cada 6 horas (produto RF_PREV)." }]));
man.push(bullet([{ t: "rf_previsto_1_2_semanas.py", b: true }, { t: " — gera 2 previsões, para +7 e +14 dias às 18 UTC (produto RF_PREV_SEMANAL)." }]));
man.push(bullet([{ t: "rf_previsto.py", b: true }, { t: " — script genérico: gera o RF para qualquer horizonte de previsão e diferentes fontes de dados (GFS, Eta, BESM) informados na linha de comando (seção 5)." }]));
man.push(p("Ambos usam o módulo comum rf_core.py e produzem, para cada horário de previsão, um NetCDF (RF.PREV.YYYYMMDDHH.nc) e um GeoTIFF (RF.PREV.YYYYMMDDHH.tif), além dos produtos derivados (links D1–D5, cópias T0–T4/T7/T14 e fogograma)."));

man.push(h1("2. Requisitos"));
man.push(h2("2.1 Software"));
man.push(p("Python 3.9 ou superior e as bibliotecas:"));
man.push(...codigo(["pip install numpy xarray netCDF4 rasterio pyyaml"]));
man.push(p("Para rodar o teste de validação, instale também o scipy:"));
man.push(...codigo(["pip install scipy"]));
man.push(p([{ t: "Não são mais necessários: ", b: true }, { t: "NCL, cdo, gdal (binário), GNU parallel nem o ambiente conda ncl_stable." }]));
man.push(h2("2.2 Dados de entrada"));
man.push(
  tabela(
    ["Dado", "Local esperado", "Observação"],
    [
      ["Precipitação IMERG (diária)", "data/output/2.2/Precipitation-2_2/AAAA/MM/INPE_FireRiskModel_2.2_Precipitation_AAAAMMDD.nc", "119 dias anteriores à execução; variável prec"],
      ["Previsões do GFS", "data/output/2.2/GFS/netcdf/AAAAMMDD00/", "GFS.PREV.PREC.* e GFS.PREV.TEMP2m.RH2m.*"],
      ["Mapa de vegetação 1 km", "data/input/Veg_Map_2020/Merge_MapBiomas_V5_IGBP_C6_<ano>.nc", "Band1, classes 0–7, sul→norte; anos ≥ 2020 usam 2019"],
      ["Topografia 1 km", "data/input/topografia/GeoTOPOAmericaSulCentral_V3.nc", "Band1 (metros), mesma grade da vegetação"],
    ],
    [22, 46, 32]
  )
);
man.push(p(""));
man.push(p("Todos os caminhos partem de /home/queimadas/INPE_FireRiskModel e estão definidos como constantes no topo de cada script (seção \"Configurações\"). Para rodar em outra máquina, basta editar a constante BASE."));

man.push(h1("3. Instalação"));
man.push(p("Copie os arquivos para o diretório de scripts do modelo (os testes são opcionais):"));
man.push(...codigo(["rf_core.py", "rf_fontes.py", "rf_config.py", "config_exemplo.yaml", "ativa_riscofogo.sh", "rf_previsto_1_5dias.py", "rf_previsto_1_2_semanas.py", "rf_previsto.py", "prepara_gfs.py", "prepara_imerg.py", "teste_rf.py", "teste_rf_previsto.py", "teste_rf_multifonte.py", "teste_prepara_gfs.py", "teste_prepara_imerg.py"]));
man.push(p("Os scripts devem ficar no mesmo diretório (os orquestradores fazem import rf_core). Se desejar, torne-os executáveis:"));
man.push(...codigo(["chmod +x rf_previsto_1_5dias.py rf_previsto_1_2_semanas.py"]));
man.push(h2("3.1 Ambiente Python no cluster (ativa_riscofogo.sh)"));
man.push(p("Em clusters, o erro mais comum é instalar/rodar com interpretadores diferentes (o pip do sistema instala num lugar, o python3 do ambiente lê de outro). O ativa_riscofogo.sh resolve isso — use SEMPRE com source, a cada login (ou adicione ao ~/.bashrc):"));
man.push(...codigo(["source ativa_riscofogo.sh"]));
man.push(p("Ele carrega o módulo Anaconda do sistema (se existir; nome ajustável em MODULO_ANACONDA), ativa o env conda riscofogo — localizado por nome ou por caminho (envs fora do diretório padrão aparecem sem nome no conda env list) —, detecta env conda sem Python próprio (caindo para o venv ~/envs/riscofogo e imprimindo o conda install -p ... para populá-lo) e confere versão e bibliotecas ao final. Regra de ouro: dentro de qualquer ambiente, instale com python3 -m pip install ..., nunca com pip solto."));

man.push(h1("4. Uso"));
man.push(h2("4.1 Execução operacional (data de hoje)"));
man.push(...codigo(["python3 rf_previsto_1_5dias.py", "python3 rf_previsto_1_2_semanas.py"]));
man.push(p("O comportamento é o mesmo dos shell scripts originais: as datas são calculadas a partir do dia corrente, as saídas vão para os mesmos diretórios e, ao final, os arquivos são publicados nos servidores."));
man.push(h2("4.2 Opções de linha de comando"));
man.push(
  tabela(
    ["Opção", "Efeito", "Padrão"],
    [
      ["--data-final YYYYMMDD", "Executa como se \"hoje\" fosse a data informada (reprocessamento)", "data corrente"],
      ["--jobs N", "Número de previsões calculadas em paralelo", "20 (diário) / 2 (semanal)"],
      ["--sem-envio", "Não publica nos servidores (geoserver/lftp/scp) — útil para testes", "envio ativado"],
    ],
    [26, 50, 24]
  )
);
man.push(p(""));
man.push(p("Exemplos:"));
man.push(...codigo([
  "# Reprocessar 1º/08/2026 sem publicar, usando 8 processos",
  "python3 rf_previsto_1_5dias.py --data-final 20260801 --jobs 8 --sem-envio",
  "",
  "# Rodada semanal de teste",
  "python3 rf_previsto_1_2_semanas.py --sem-envio",
]));
man.push(h2("4.3 Agendamento (cron)"));
man.push(p("Substitua as entradas existentes que chamavam os shell scripts, por exemplo:"));
man.push(...codigo([
  "30 6 * * * cd /home/queimadas/INPE_FireRiskModel/scr/risco_fogo/RF_Previsto \\",
  "  && /usr/bin/python3 rf_previsto_1_5dias.py \\",
  "  >> /home/queimadas/INPE_FireRiskModel/log/cron.rf_prev.log 2>&1",
]));

man.push(h1("5. Script genérico para qualquer horizonte (rf_previsto.py)"));
man.push(p("O rf_previsto.py generaliza os dois produtos: os horizontes de previsão são informados na linha de comando, contados a partir das 00 UTC da data do modelo. Um horizonte pode ser escrito como Nh (horas), Nd (dias), Nm (meses de calendário), combinações como 4d18h ou 1m15d, ou como data/hora absoluta YYYYMMDDHH."));
man.push(h2("5.1 Exemplos"));
man.push(...codigo([
  "# Um único horizonte: 36 horas",
  "python3 rf_previsto.py --horizontes 36h",
  "",
  "# Lista de horizontes: 1, 3, 7 e 14 dias às 18 UTC",
  "python3 rf_previsto.py --horizontes 18h,2d18h,6d18h,13d18h",
  "",
  "# Intervalo (equivalente ao produto diário de 1 a 5 dias)",
  "python3 rf_previsto.py --de 6h --ate 4d18h --passo 6h",
  "",
  "# Equivalente ao produto semanal (7 e 14 dias)",
  "python3 rf_previsto.py --horizontes 7d18h,14d18h --rb-max 0.8 --fallback-gfs",
  "",
  "# Data/hora absoluta com reprocessamento",
  "python3 rf_previsto.py --data-final 20260801 --horizontes 2026080618",
  "",
  "# Eta: previsões mensais de 1 a 13 meses",
  "python3 rf_previsto.py --fonte eta --de 1m --ate 13m --passo 1m",
  "",
  "# BESM (acúmulos de 12 h agregados automaticamente): 6 meses",
  "python3 rf_previsto.py --fonte besm --horizontes 6m",
]));
man.push(h2("5.2 Opções"));
man.push(
  tabela(
    ["Opção", "Efeito", "Padrão"],
    [
      ["--horizontes LISTA", "Horizontes separados por vírgula (Nh, Nd, Nm, combinações ou YYYYMMDDHH)", "—"],
      ["--fonte NOME", "Fonte de previsão: gfs, eta, besm ou outra definida via JSON (seção 5.4); padrao (ou legado/nenhuma) força a composição legada do GFS mesmo com fonte no YAML", "composição legada (GFS)"],
      ["--config-fontes ARQ", "Arquivo JSON que ajusta/acrescenta fontes (nomes de arquivos, variáveis, frequência)", "—"],
      ["--de / --ate / --passo", "Intervalo de horizontes relativo (pode ser combinado com --horizontes)", "passo 6h"],
      ["--rb-max X", "Risco básico máximo (o produto semanal usa 0.8)", "0.9"],
      ["--produto NOME", "Subdiretório de saída em data/output/2.2/", "RF_PREV_CUSTOM"],
      ["--base DIR", "Diretório base do modelo (permite rodar fora da produção)", "/home/queimadas/INPE_FireRiskModel"],
      ["--fallback-gfs", "Se o GFS do horário exato não existir, usa o horário anterior do mesmo dia (generaliza a cópia 12 UTC → 18 UTC do produto semanal)", "desativado"],
      ["--sem-tif", "Gera apenas os NetCDF, sem GeoTIFF", "TIF ativado"],
      ["--fogograma", "Gera também um único NetCDF com todos os horizontes", "desativado"],
      ["--sem-vegetacao", "Sensibilidade: desliga o efeito da vegetação; o mapa não é lido (classe uniforme --classe-veg, saída na grade da precipitação, sem máscara d'água); sufixo _SEMVEG no produto", "desativado"],
      ["--sem-topografia", "Sensibilidade: desliga o Fator Topográfico (FTOP=1; arquivo de topografia dispensado); sufixo _SEMTOPO no produto", "desativado"],
      ["--classe-veg N", "Classe usada com --sem-vegetacao", "4 (A=2,4; PSE_max=75)"],
      ["--data-final / --jobs N", "Como nos demais scripts; aceita também \"hoje\" (= data do sistema, útil no YAML)", "hoje / 4"],
    ],
    [24, 52, 24]
  )
);
man.push(p(""));
man.push(p("As saídas seguem o mesmo formato dos demais produtos (RF.PREV.YYYYMMDDHH.nc e .tif), gravadas em data/output/2.2/<produto>/netcdf|tif/<modelo>/. O script genérico não gera links D1–D5, cópias T7/T14 nem faz envio a servidores — para os produtos operacionais, use os scripts dedicados."));
man.push(h2("5.3 Fontes de dados e horizontes longos (--fonte)"));
man.push(p("O alcance depende da fonte de previsão escolhida com --fonte:"));
man.push(
  tabela(
    ["Fonte", "Alcance", "Frequência padrão dos acúmulos"],
    [
      ["gfs", "~16 dias", "1 dia"],
      ["eta", "até 13 meses", "1 dia"],
      ["besm", "até 13 meses", "1 dia (arquivo único por variável)"],
    ],
    [20, 40, 40]
  )
);
man.push(p(""));
man.push(p([{ t: "Sem --fonte", b: true }, { t: ", o script usa a composição original dos produtos operacionais: 119 dias de IMERG observado + o acumulado do GFS do dia previsto (idêntica aos scripts dedicados, limitada ao alcance do GFS)." }]));
man.push(p([{ t: "Com --fonte", b: true }, { t: ", a série diária de 120 tempos que antecede cada data prevista é montada de forma completa: IMERG observado para os dias anteriores à rodada e precipitação PREVISTA da fonte para os dias entre a rodada e a data válida. É isso que viabiliza horizontes de semanas a 13 meses (Eta/BESM) — num horizonte de 13 meses, os 120 dias da janela são inteiramente previstos. Os acúmulos da fonte podem vir em qualquer frequência (1h, 12h, 1d): são somados para o passo diário automaticamente, e campos em grade diferente da do IMERG são regradeados por interpolação bilinear. O horizonte pedido é validado contra o alcance da fonte (horizonte_max_dias)." }]));
man.push(h2("5.4 Configuração das fontes (rf_fontes.py e --config-fontes)"));
man.push(p([{ t: "Cada fonte é descrita em rf_fontes.py por: " }, { t: "layout", b: true }, { t: " dos arquivos (por_tempo = um arquivo por horário previsto, como o GFS deste pipeline; serie = um arquivo por variável com todos os tempos da rodada, como o BESM T062), subdiretório dos dados, padrões de nome dos arquivos (com os marcadores {modelo} e {valida}), nomes das variáveis (var_prec, var_temp, var_ur), frequência dos acúmulos (freq_prec: 1h, 12h, 1d), tipo de acumulação (intervalo = acumulado do próprio intervalo; desde_inicio = acumulado desde o início da rodada), unidades (unidade_temp: K/C; unidade_ur: %/frac) e alcance (horizonte_max_dias)." }]));
man.push(p([{ t: "A fonte besm já vem configurada com a convenção real do BESM T062 (pacote besm_queimada do CPTEC): ", b: true }, { t: "layout serie com tmp_prec.nc (mm/dia), tmp_t2mt.nc (K, média diária) e tmp_rsmt.nc (%, 0–100) em BESM/netcdf/<modelo>/, 396 tempos diários (rodada+1 até rodada+13 meses), grade gaussiana ~1,875° com latitude norte→sul (invertida automaticamente na leitura). Como a série começa em rodada+1, o dia da própria rodada é preenchido com o IMERG observado, se existir, ou aproximado pelo primeiro dia da série (aviso no log). Os padrões do Eta seguem PROVISÓRIOS — ajuste-os à convenção real com um JSON, sem alterar o código:" }]));
man.push(...codigo([
  '{',
  '  "eta": {',
  '    "subdir": "ETA/netcdf/{modelo}",',
  '    "padrao_prec": "ETA.PREV.PREC.{modelo}.{valida}.nc",',
  '    "padrao_temp_ur": "ETA.PREV.TEMP2m.RH2m.{modelo}.{valida}.nc",',
  '    "var_prec": "prec",',
  '    "freq_prec": "1d",',
  '    "horizonte_max_dias": 396',
  '  },',
  '  "besm": { "freq_prec": "12h" }',
  '}',
]));
man.push(...codigo(["python3 rf_previsto.py --fonte eta --horizontes 13m --config-fontes fontes.json"]));
man.push(p("Os arquivos das fontes devem ser NetCDF em grade regular lat/lon (como os do GFS já pré-processados neste pipeline); saídas nativas (grib do Eta, espectral do BESM) precisam ser convertidas antes. Novas fontes podem ser acrescentadas no mesmo JSON — o nome da chave passa a valer em --fonte."));
man.push(h2("5.5 Arquivo de configuração YAML (--config)"));
man.push(p("O --config arquivo.yaml centraliza toda a configuração dos dados de entrada num único arquivo YAML (ou JSON), com seções opcionais — o que não for informado usa os padrões da produção, e a linha de comando sempre prevalece sobre o arquivo:"));
man.push(
  tabela(
    ["Seção", "Conteúdo"],
    [
      ["base", "Diretório base do modelo; os caminhos relativos são ancorados nele"],
      ["caminhos", "Onde estão os dados de entrada: imerg_dir, imerg_subpastas ({ano}/{mes}), imerg_padrao ({data}), mapa_vegetacao ({ano_veg}), topografia, log"],
      ["fontes", "Mesmas chaves do --config-fontes: ajusta ou acrescenta fontes (gfs, eta, besm, ...)"],
      ["execucao", "Padrões da linha de comando: fonte, horizontes ou de/ate/passo, data_final, rb_max, produto, jobs, fallback_gfs, sem_tif, fogograma, sem_vegetacao, sem_topografia, classe_veg"],
    ],
    [20, 80]
  )
);
man.push(p(""));
man.push(...codigo([
  "base: /home/queimadas/INPE_FireRiskModel",
  "caminhos:",
  "  imerg_dir: data/output/2.2/Precipitation-2_2",
  '  imerg_padrao: "INPE_FireRiskModel_2.2_Precipitation_{data}.nc"',
  "fontes:",
  "  besm: { horizonte_max_dias: 396 }",
  "execucao:",
  "  fonte: besm",
  "  de: 1m",
  "  ate: 13m",
  "  passo: 1m",
  "  data_final: hoje       # data do sistema (tambem: auto, sistema) — ou \"20260804\"",
  "  produto: RF_PREV_BESM",
  "  sem_vegetacao: false   # sensibilidade (secao 5.6): true dispensa o mapa",
  "  sem_topografia: false  # true dispensa a topografia (FTOP = 1)",
  "  classe_veg: 4",
]));
man.push(...codigo([
  "python3 rf_previsto.py --config config.yaml               # tudo do arquivo",
  "python3 rf_previsto.py --config config.yaml --horizontes 6m   # CLI prevalece",
]));
man.push(p("Com data_final: hoje (equivalente a omitir a chave) e horizontes (ou de/ate/passo) declarados no arquivo, o YAML define uma rodada diária operacional: cada execução usa a data corrente do sistema e produz sempre os mesmos horizontes pré-estabelecidos — ideal para agendar no cron. As chaves de sensibilidade permitem manter arquivos separados por experimento (ex.: config.yaml de referência e config_semveg.yaml com sem_vegetacao: true), sem alterar a linha de comando."));
man.push(p("Atenção com a chave fonte: sem ela (e sem --fonte na CLI), a rodada usa a composição original dos produtos operacionais com o GFS — este é o padrão. Se o YAML declarar fonte: besm (ou outra), essa fonte vale em toda execução que não passar --fonte na linha de comando (precedência CLI > YAML). Para forçar o GFS sem editar o arquivo, use --fonte padrao (aceita também legado/nenhuma). Por isso o config_exemplo.yaml traz a chave comentada: declare-a apenas em arquivos dedicados a uma fonte específica (ex.: config_besm.yaml)."));
man.push(p("O arquivo config_exemplo.yaml traz o modelo completo comentado; as seções são validadas na leitura (chave desconhecida gera erro com a lista das válidas). Requer PyYAML (pip install pyyaml) — arquivos .json funcionam sem ele."));
man.push(h2("5.6 Análise de sensibilidade (--sem-vegetacao / --sem-topografia)"));
man.push(p("Para medir o impacto individual de cada componente do modelo, as duas chaves podem ser desligadas de forma independente (e combinadas):"));
man.push(...codigo([
  "python3 rf_previsto.py --data-final 20260804 --horizontes 3d              # referência",
  "python3 rf_previsto.py --data-final 20260804 --horizontes 3d --sem-topografia",
  "python3 rf_previsto.py --data-final 20260804 --horizontes 3d --sem-vegetacao",
  "python3 rf_previsto.py --data-final 20260804 --horizontes 3d --sem-vegetacao --sem-topografia",
]));
man.push(p("Semântica: topografia desligada zera a correção (FTOP≡1) e dispensa o arquivo de topografia; vegetação desligada dispensa o mapa de vegetação (o arquivo não é lido): todos os pontos recebem uma classe uniforme (--classe-veg, padrão 4) e a saída passa a usar a grade da precipitação — sem interpolação para 1 km e sem máscara d'água. Com as duas chaves ligadas, o RF roda sem nenhum arquivo estático (útil quando o mapa de vegetação e a topografia ainda não estão disponíveis); se a topografia permanecer ligada com a vegetação desligada, a elevação é regradeada automaticamente para a grade da precipitação. Os fatores de latitude e meteorológicos permanecem ativos. Proteções: o produto ganha sufixo automático (_SEMVEG/_SEMTOPO), nunca sobrescrevendo a referência, e o NetCDF registra os fatores desligados nos atributos globais (fator_vegetacao/fator_topografia). As chaves também existem no YAML (sem_vegetacao, sem_topografia, classe_veg)."));

man.push(h1("6. Preparo dos dados de entrada (prepara_gfs.py e prepara_imerg.py)"));
man.push(p("Dois scripts geram o banco de dados de entrada do RF sem depender da área de produção do Programa Queimadas: o prepara_gfs.py (previsões) e o prepara_imerg.py (precipitação observada). Fluxo completo de uma rodada:"));
man.push(...codigo([
  "python3 prepara_imerg.py --config config.yaml         # 1. IMERG observado (119 dias)",
  "python3 prepara_gfs.py   --config config.yaml         # 2. previsões do GFS",
  "python3 rf_previsto.py   --de 6h --ate 4d18h --passo 6h   # 3. RF",
]));
man.push(h2("6.1 GFS (prepara_gfs.py)"));
man.push(p("O prepara_gfs.py baixa a previsão do GFS 0,25° da NOAA e grava os arquivos GFS.PREV.PREC.* (prec em mm/dia) e GFS.PREV.TEMP2m.RH2m.* (T2m em K, UR2m em %) na convenção da seção 2.2, prontos para o rf_previsto.py. Requer o pygrib (python3 -m pip install pygrib)."));
man.push(p([{ t: "Importante: ", b: true }, { t: "o serviço OpenDAP do NOMADS foi aposentado pela NOAA (Service Change Notice 25-81, efetivo em 23/02/2026). O script usa os serviços vigentes indicados no próprio aviso:" }]));
man.push(
  tabela(
    ["Método", "Descrição"],
    [
      ["s3 (padrão)", "\"Fast download method\": lê o índice .idx de cada horário e baixa por byte-range só as 3 mensagens GRIB necessárias, no espelho oficial da AWS (noaa-gfs-bdp-pds), ~2 MB por horário"],
      ["nomads", "O mesmo fast download, direto no HTTPS do NOMADS (/pub/data/nccf/com/gfs/prod/...)"],
      ["filtro", "Grib filter do NOMADS (recorte de variáveis/região no servidor; URL ajustável via --url-filtro)"],
    ],
    [22, 78]
  )
);
man.push(p(""));
man.push(...codigo([
  "python3 prepara_gfs.py                          # rodada de hoje 00 UTC, 16 dias",
  "python3 prepara_gfs.py --data 20260805 --config config.yaml",
  "python3 prepara_gfs.py --simular                # só mostra o plano e a URL",
  "python3 prepara_gfs.py --metodo nomads          # se a AWS estiver bloqueada",
]));
man.push(p("Opções principais: --data/--rodada (rodada), --dias (alcance, padrão 16), --passo (validades, padrão 6 h), --dominio latS,latN,lonW,lonE, --acumulo 24h|dia, --jobs (downloads simultâneos), --base/--config (destino), --sobrescrever e --simular."));
man.push(p("Sobre a precipitação: o APCP do GFS vem em \"baldes\" (6 h até +240 h; 12 h de +240 h a +384 h). O acumulado diário de cada validade soma os baldes que cobrem as 24 h anteriores, com o intervalo lido do próprio GRIB — a transição 6 h/12 h é automática, e validades sem arquivo além de +240 h (fora do passo de 12 h) são puladas com aviso."));
man.push(h2("6.2 IMERG (prepara_imerg.py)"));
man.push(p("O prepara_imerg.py baixa a precipitação diária observada do IMERG — produto GPM_3IMERGDE V07 (Early Daily, ~4 h de latência, o mesmo da operação) — do GES DISC/NASA e converte para o padrão de leitura do pipeline (INPE_FireRiskModel_2.2_Precipitation_AAAAMMDD.nc, variável prec em mm/dia, lat sul→norte, domínio recortado), no destino definido pela seção caminhos do config.yaml."));
man.push(p([{ t: "Pré-requisito (uma única vez): ", b: true }, { t: "conta gratuita no Earthdata (urs.earthdata.nasa.gov) e um dos dois modos de autenticação:" }]));
man.push(bullet([{ t: "Modo A — token (recomendado): ", b: true }, { t: "no perfil do Earthdata, aba Generate Token, copie o token e salve no servidor: echo 'SEU_TOKEN' > ~/.edl_token && chmod 600 ~/.edl_token (ou exporte EARTHDATA_TOKEN). Dispensa autorização de app e senha no disco." }]));
man.push(bullet([{ t: "Modo B — usuário/senha: ", b: true }, { t: "autorize o app \"NASA GESDISC DATA ARCHIVE\" em Applications → Authorized Apps (obrigatório) e crie o ~/.netrc (chmod 600; o login é o nome de usuário, não o e-mail):" }]));
man.push(...codigo(["machine urs.earthdata.nasa.gov login SEU_USUARIO password SUA_SENHA"]));
man.push(p("Se a autenticação falhar, o script diz o motivo (página de LOGIN = usuário/senha errados; pedido de AUTORIZAÇÃO = app não aprovado; 401 = token inválido/expirado)."));
man.push(p("Modos de uso:"));
man.push(...codigo([
  "python3 prepara_imerg.py                           # data corrente: 119 dias até ontem",
  "python3 prepara_imerg.py --data-final 20260804     # janela da rodada (reprocessamento)",
  "python3 prepara_imerg.py --inicio 20250101 --fim 20251231   # período explícito",
  "python3 prepara_imerg.py --produto final ...       # histórico consolidado da NASA",
  "python3 prepara_imerg.py --simular                 # confere período e URLs",
]));
man.push(p("O script pula dias já existentes (rodar de novo completa o que faltou; --sobrescrever regrava), tenta as letras de versão da NASA automaticamente (V07D→V07A), baixa em paralelo (--jobs) e trata a transposição lon/lat e os valores inválidos do formato IMERG. Cada dia baixa ~25 MB do arquivo global e grava ~2–3 MB recortados. Produtos: early (padrão), late (~14 h) e final (pesquisa, meses de latência — ideal para períodos históricos)."));

man.push(h1("7. Saídas"));
man.push(h2("7.1 Produto diário (1 a 5 dias)"));
man.push(
  tabela(
    ["Saída", "Local"],
    [
      ["NetCDF por horário (19 arquivos)", "data/output/2.2/RF_PREV/netcdf/<modelo>/RF.PREV.YYYYMMDDHH.nc"],
      ["GeoTIFF por horário", "data/output/2.2/RF_PREV/tif/<modelo>/RF.PREV.YYYYMMDDHH.tif"],
      ["Links para o mapserver (D1–D5, 18 UTC)", "dados/mapfiles/tmp/RF.PREV.D<dia>.tif"],
      ["Cópias T0–T4 (18 UTC)", "…/tif/<modelo>/RF.PREV.T<d>.YYYYMMDD18.tif"],
      ["Fogograma (todos os horários juntos)", "data/output/2.2/fogograma/RF.PREV.<data>00.nc"],
    ],
    [40, 60]
  )
);
man.push(p(""));
man.push(h2("7.2 Produto semanal (1 a 2 semanas)"));
man.push(
  tabela(
    ["Saída", "Local"],
    [
      ["NetCDF (2 arquivos: +7 e +14 dias)", "data/output/2.2/RF_PREV_SEMANAL/netcdf/<modelo>/"],
      ["GeoTIFF T7 e T14", "…/RF_PREV_SEMANAL/tif/<modelo>/RF.PREV.T7.tif e RF.PREV.T14.tif"],
    ],
    [40, 60]
  )
);
man.push(p(""));
man.push(h2("7.3 Formato dos arquivos"));
man.push(p("O NetCDF contém a variável rbf(time, lat, lon) com o RF em [0, 1], arredondado a 2 casas decimais, valor ausente −999 e eixo de tempo na data/hora da previsão. O GeoTIFF está em EPSG:4326, orientado de norte para sul, com nodata −999, compressão LZW e organização em tiles."));
man.push(p("Interpretação usual do RF: mínimo (< 0.15), baixo (0.15–0.40), médio (0.40–0.70), alto (0.70–0.95) e crítico (≥ 0.95)."));

man.push(h1("8. Logs e monitoramento"));
man.push(
  tabela(
    ["Log", "Conteúdo"],
    [
      ["log/log.<modelo>.<previsão>", "Progresso e eventuais erros de cada previsão (um por horário)"],
      ["log.falta.arquivos.prev.prec.txt (diretório de execução)", "Arquivos IMERG esperados e não encontrados"],
      ["Saída padrão", "Datas da rodada, horários processados e tempo total"],
    ],
    [45, 55]
  )
);
man.push(p(""));
man.push(p("O código de saída é 0 em caso de sucesso e 1 se alguma previsão não foi gerada (mensagem \"PROBLEMA - FALTAM ARQUIVOS EM <dir>\"), o que permite monitorar a rodada no cron da mesma forma que antes."));

man.push(h1("9. Solução de problemas"));
man.push(
  tabela(
    ["Sintoma", "Causa provável", "O que fazer"],
    [
      ["Número de tempos de precipitação insuficiente: N (esperado 120)", "Faltam arquivos IMERG no período de 119 dias", "Verifique log.falta.arquivos.prev.prec.txt e reponha os arquivos"],
      ["PROBLEMA - FALTAM ARQUIVOS EM ...", "Uma ou mais previsões falharam", "Consulte log/log.<modelo>.<previsão> do horário faltante"],
      ["FileNotFoundError em arquivo GFS.PREV.*", "A rodada do GFS ainda não foi processada para o dia", "Aguarde/reprocesse a etapa do GFS e rode novamente"],
      ["A topografia (...) não tem a mesma grade do mapa de vegetação (...)", "Arquivo de topografia ou vegetação trocado", "Confira os arquivos em data/input/"],
      ["Consumo excessivo de memória / máquina lenta", "Muitos processos simultâneos em grade de 1 km", "Reduza --jobs"],
      ["Falha no envio (lftp/scp)", "Rede ou credenciais", "O cálculo não é afetado; reenvie manualmente ou rode novamente"],
      ["ModuleNotFoundError: rasterio (ou outra biblioteca)", "Dependências não instaladas no Python usado", "source ativa_riscofogo.sh e instale com python3 -m pip install ... (nunca pip solto)"],
      ["prepara_imerg: erro \"resposta HTML\" do Earthdata", "Autenticação incompleta (app não autorizado, login=e-mail ou token expirado)", "A mensagem indica o caso; prefira o token (~/.edl_token) — seção 6.2"],
      ["Segmentation fault em prepara_imerg/prepara_gfs", "Versão antiga dos scripts (conversão HDF5/GRIB em threads simultâneas)", "Atualize: as versões atuais serializam a conversão com lock"],
      ["python3 continua sendo o 3.6 do sistema após ativar o conda", "Env conda sem Python próprio (env \"vazio\")", "conda install -p <caminho_do_env> -c conda-forge python=3.12 ... ou use o venv"],
    ],
    [36, 32, 32]
  )
);
man.push(p(""));

man.push(h1("10. Testes de validação"));
man.push(p("Após instalar ou alterar qualquer coisa, rode:"));
man.push(...codigo(["python3 teste_rf.py            # valida o núcleo do cálculo (rf_core)", "python3 teste_rf_previsto.py   # valida o script genérico de ponta a ponta", "python3 teste_rf_multifonte.py # valida o modo multifonte (Eta 13m, BESM 12h, JSON)", "python3 teste_prepara_gfs.py   # valida o preparo do GFS (idx, baldes, NetCDF)", "python3 teste_prepara_imerg.py # valida o preparo do IMERG (conversão, caminhos)"]));
man.push(p("O primeiro teste cria dados sintéticos em /tmp/teste_rf, executa o cálculo completo e compara com uma implementação de referência fiel ao NCL; a saída esperada termina com \"TODOS OS TESTES PASSARAM\". O segundo monta uma árvore com a estrutura de diretórios da produção em /tmp/teste_generico e executa o rf_previsto.py real em cinco cenários (lista, intervalo, fallback do GFS, horizonte absoluto e falha controlada)."));

man.push(h1("11. Segurança"));
man.push(p("O script semanal contém as credenciais do lftp (herdadas do shell script original) nas constantes LFTP_USUARIO e LFTP_SENHA. Recomenda-se movê-las para variáveis de ambiente ou para o arquivo ~/.netrc e restringir a permissão de leitura dos scripts."));

man.push(h1("12. Suporte"));
man.push(p("Modelo: Alberto Setzer (alberto.setzer@inpe.br) · Código NCL original: Guilherme Martins (guilherme.martins@inpe.br) · Programa Queimadas: http://www.inpe.br/queimadas/"));

// ---------------------------------------------------------------- gravação
(async () => {
  fs.writeFileSync("relatorio_conversao.docx", await Packer.toBuffer(documento(rel)));
  fs.writeFileSync("manual_usuario.docx", await Packer.toBuffer(documento(man)));
  console.log("ok");
})();
