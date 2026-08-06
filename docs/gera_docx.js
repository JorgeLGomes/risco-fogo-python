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
      "Versão 2.6 · 6 de agosto de 2026",
      "Substitui: rf_previsto_1-5dias_2023.sh e rf_previsto_1-2_semanas_2024.sh (bash + NCL)",
      "Programa Queimadas — http://www.inpe.br/queimadas/",
    ],
    [
      "1. Visão geral",
      "2. Requisitos",
      "3. Instalação",
      "4. Uso",
      "5. Script genérico para qualquer horizonte (rf_previsto.py)",
      "6. Preparo dos dados, RF observado e figuras (prepara_gfs, prepara_imerg, prepara_era5, rf_observado, rf_figura)",
      "7. FWI — Canadian Fire Weather Index System",
      "8. Saídas",
      "9. Logs e monitoramento",
      "10. Solução de problemas",
      "11. Testes de validação",
      "12. Segurança",
      "13. Suporte",
    ]
  )
);

man.push(h1("1. Visão geral"));
man.push(p("Este pacote calcula o Risco de Fogo (RF) previsto em resolução de 1 km para a América do Sul, combinando a precipitação observada do IMERG (últimos 119 dias), as previsões do GFS (precipitação, temperatura e umidade relativa a 2 m), o mapa de vegetação (MapBiomas/IGBP) e a topografia (GTOPO30). São três programas:"));
man.push(bullet([{ t: "rf_previsto_1_5dias.py", b: true }, { t: " — gera 19 previsões, de +6 h até +4 dias 18 UTC, a cada 6 horas (produto RF_PREV)." }]));
man.push(bullet([{ t: "rf_previsto_1_2_semanas.py", b: true }, { t: " — gera 2 previsões, para +7 e +14 dias às 18 UTC (produto RF_PREV_SEMANAL)." }]));
man.push(bullet([{ t: "rf_previsto.py", b: true }, { t: " — script genérico: gera o RF para qualquer horizonte de previsão e diferentes fontes de dados (GFS, Eta, BESM) informados na linha de comando (seção 5)." }]));
man.push(bullet([{ t: "rf_observado.py", b: true }, { t: " — RF observado dos últimos dias, semanas ou meses, com IMERG + ERA5, incluindo médias do período e mensais (seção 6.4)." }]));
man.push(bullet([{ t: "rf_figura.py", b: true }, { t: " — figuras PNG dos campos de RF na paleta oficial da operação (seção 6.5)." }]));
man.push(bullet([{ t: "fwi_core.py / fwi_observado.py", b: true }, { t: " — motor do FWI (Canadian Fire Weather Index System) e o FWI observado diário (seção 7)." }]));
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
man.push(p("Todos os caminhos partem do diretório base. O padrão embutido (em rf_config.py) é /p/projetos/grpeta/Team/jorge.gomes/risco-fogo-python; a precedência é --base (CLI) > base do --config > variável de ambiente RF_BASE > padrão embutido. Exceção: os dois scripts legados (rf_previsto_1_5dias.py e rf_previsto_1_2_semanas.py) mantêm a constante BASE = /home/queimadas/INPE_FireRiskModel da produção, editável no topo de cada um."));

man.push(h1("3. Instalação"));
man.push(p("Copie os arquivos para o diretório de scripts do modelo (os testes são opcionais):"));
man.push(...codigo(["rf_core.py", "rf_fontes.py", "rf_config.py", "config_exemplo.yaml", "ativa_riscofogo.sh", "rf_previsto_1_5dias.py", "rf_previsto_1_2_semanas.py", "rf_previsto.py", "prepara_gfs.py", "prepara_imerg.py", "prepara_era5.py", "rf_observado.py", "rf_figura.py", "fwi_core.py", "fwi_observado.py", "era5_tempo.py", "config_besm.yaml", "teste_rf.py", "teste_rf_previsto.py", "teste_rf_multifonte.py", "teste_prepara_gfs.py", "teste_prepara_imerg.py", "teste_prepara_era5.py", "teste_rf_observado.py"]));
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
      ["--base DIR", "Diretório base do modelo (precedência: --base > base do --config > variável RF_BASE > padrão embutido; produção: /home/queimadas/INPE_FireRiskModel)", "/p/projetos/grpeta/Team/jorge.gomes/risco-fogo-python"],
      ["--fallback-gfs", "Se o GFS do horário exato não existir, usa o horário anterior do mesmo dia (generaliza a cópia 12 UTC → 18 UTC do produto semanal)", "desativado"],
      ["--sem-tif", "Gera apenas os NetCDF, sem GeoTIFF", "TIF ativado"],
      ["--fogograma", "Gera também um único NetCDF com todos os horizontes", "desativado"],
      ["--sem-vegetacao", "Sensibilidade: desliga o efeito da vegetação; o mapa não é lido (classe uniforme --classe-veg, saída na grade da precipitação, sem máscara d'água); sufixo _SEMVEG no produto", "desativado"],
      ["--sem-topografia", "Sensibilidade: desliga o Fator Topográfico (FTOP=1; arquivo de topografia dispensado); sufixo _SEMTOPO no produto", "desativado"],
      ["--classe-veg N", "Classe usada com --sem-vegetacao", "4 (A=2,4; PSE_max=75)"],
      ["--media-mensal / --media / --maximo", "Agregações da rodada: média por mês-calendário, média de toda a rodada, ou máximo (seção 5.7)", "desativado"],
      ["--so-agrega", "Só agrega os arquivos já existentes (não recalcula)", "desativado"],
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

man.push(h2("5.7 Risco médio: agregações da rodada (--media-mensal / --media)"));
man.push(p("Cada horizonte gera o seu RF.PREV.{data}{hora}.nc. Para obter o risco médio — típico das rodadas sazonais (Eta/BESM), em que interessa o mês e não o dia — o rf_previsto.py agrega os campos ao final:"));
man.push(tabela(["Opção", "Papel", "Saída"], [
  ["--media-mensal", "agrupamento", "uma agregação por mês-calendário coberto pelas previsões"],
  ["--media", "agrupamento", "uma agregação de toda a rodada"],
  ["--maximo", "operação", "usa o máximo em vez da média (RF.PREV.MAXIMO.*)"],
  ["--frequencia L", "operação adicional", "nº de previsões com valor >= L e o percentual delas (RF.PREV.FREQ<L>.*, variáveis dias e frequencia)"],
  ["--percentil N", "operação adicional", "percentil N da distribuição (RF.PREV.P<N>.*)"],
  ["--so-agrega", "—", "não recalcula nada: agrega os arquivos já existentes da rodada"],
], [22, 20, 58]));
man.push(p("As opções de agrupamento dizem sobre o quê agregar (o mês ou a rodada inteira) e as de operação dizem como. --frequencia e --percentil são acumulativas: pedidas junto com --media-mensal, geram, para cada mês, a média e os campos de frequência e percentil. Pedidas sozinhas, valem para a rodada inteira e produzem só o que foi pedido — --frequencia 0.7 sem mais nada não gera arquivo de média."));
man.push(p("Os campos são agrupados pela data válida de cada previsão, e as médias ignoram valores ausentes ponto a ponto (o número de campos usados vai no atributo global dias_agregados). As mesmas chaves existem no YAML (media_mensal, media, maximo)."));
man.push(p([{ t: "Rodada sazonal do BESM (1 a 13 meses). ", b: true }, { t: "O BESM traz previsão diária por ~13 meses (396 dias), então há duas formas de produzir \"um valor por mês\":" }]));
man.push(...codigo([
  "# (a) Instantaneo: 13 mapas, um no mesmo dia de cada mes - rapido (13 calculos)",
  "python3 rf_previsto.py --fonte besm --de 1m --ate 13m --passo 1m \\",
  "    --produto RF_PREV_BESM",
  "",
  "# (b) Risco MEDIO de cada mes: usa todos os dias previstos (396 calculos)",
  "python3 rf_previsto.py --fonte besm --de 1d --ate 396d --passo 1d \\",
  "    --media-mensal --media --produto RF_PREV_BESM --jobs 8 --sem-tif",
  "",
  "# Se os diarios ja existirem, so as medias (nao recalcula nada):",
  "python3 rf_previsto.py --fonte besm --de 1d --ate 396d --passo 1d \\",
  "    --media-mensal --so-agrega --produto RF_PREV_BESM",
]));
man.push(p("A forma (b) é a recomendada quando o objetivo é a climatologia mensal prevista: o mapa de cada mês passa a representar todos os dias, e não um dia específico. O arquivo config_besm.yaml já traz essa configuração pronta — basta python3 rf_previsto.py --config config_besm.yaml. As figuras dos 13 mapas saem com o rf_figura.py (seção 6.5)."));
man.push(...codigo([
  "python3 rf_figura.py <saida>/RF.PREV.MEDIA.2026*.nc --painel --colunas 4 \\",
  "    --titulo \"BESM - Risco de Fogo medio mensal\"",
]));
man.push(p([{ t: "Frequência prevista. ", b: true }, { t: "Na escala sazonal a frequência costuma comunicar melhor que a média: em vez de \"o risco médio de setembro é 0,68\", diz-se \"26 dos 30 dias previstos ficam em risco Alto ou Crítico\". O caminho é o mesmo, trocando a operação:" }]));
man.push(...codigo([
  "# Dias (e % dos dias) com RF >= 0,7 em cada mes da rodada sazonal",
  "python3 rf_previsto.py --fonte besm --de 1d --ate 396d --passo 1d \\",
  "    --media-mensal --frequencia 0.7 --percentil 90 \\",
  "    --produto RF_PREV_BESM --jobs 8 --sem-tif",
  "",
  "# So as agregacoes, se os diarios ja existirem",
  "python3 rf_previsto.py --fonte besm --de 1d --ate 396d --passo 1d \\",
  "    --media-mensal --frequencia 0.7 --so-agrega --produto RF_PREV_BESM",
  "",
  "# Figuras: um painel com os meses (a escala e comum aos 13 mapas)",
  "S=data/output/2.2/RF_PREV_BESM/netcdf/<modelo>",
  "python3 rf_figura.py \"$S/RF.PREV.FREQ0.7.2026*.nc\" --painel --colunas 4 \\",
  "    --titulo \"BESM - dias com RF >= 0,7\" --saida besm_freq.png",
  "python3 rf_figura.py \"$S/RF.PREV.FREQ0.7.2026*.nc\" --painel --colunas 4 \\",
  "    --var frequencia --titulo \"BESM - % dos dias com RF >= 0,7\"",
]));
man.push(p("Aplicada às previsões, a frequência é a leitura mais próxima de uma probabilidade: com um único membro ela mede a fração de dias do mês acima do limiar; com um ensemble (quando os membros do BESM estiverem disponíveis), a mesma conta sobre os membros vira a probabilidade de o mês exceder o limiar."));
man.push(p("Atenção ao passo: ele tem a mesma unidade dos horizontes e precisa ser compatível com o intervalo — --de 6h --ate 4d18h --passo 1m não produz nada útil (o primeiro passo já ultrapassa o fim)."));

man.push(h1("6. Preparo dos dados, RF observado e figuras (prepara_gfs, prepara_imerg, prepara_era5, rf_observado, rf_figura)"));
man.push(p("Dois scripts geram o banco de dados de entrada do RF sem depender da área de produção do Programa Queimadas: o prepara_gfs.py (previsões) e o prepara_imerg.py (precipitação observada). Fluxo completo de uma rodada:"));
man.push(...codigo([
  "python3 prepara_imerg.py --config config.yaml         # 1. IMERG observado (119 dias)",
  "python3 prepara_gfs.py   --config config.yaml         # 2. previsões do GFS",
  "python3 rf_previsto.py   --de 6h --ate 4d18h --passo 6h   # 3. RF",
]));
man.push(h2("6.1 GFS (prepara_gfs.py)"));
man.push(p("O prepara_gfs.py baixa a previsão do GFS 0,25° da NOAA e grava, na convenção da seção 2.2, GFS.PREV.PREC.* (prec em mm/dia), GFS.PREV.TEMP2m.RH2m.* (T2m em K, UR2m em %) e GFS.PREV.U10m.V10m.* (vento a 10 m em m/s). Requer o pygrib (python3 -m pip install pygrib)."));
man.push(p([{ t: "Vento a 10 m. ", b: true }, { t: "O RF não usa vento, mas o FWI exige (é o insumo do ISI), então o download traz UGRD/VGRD por padrão — duas mensagens GRIB a mais por horário (~1 MB, de ~2 para ~3 MB). O arquivo de vento segue o mesmo formato do gerado pelo prepara_era5.py e é lido pela mesma função, o que permitirá encadear a análise observada com a previsão no FWI. Use --sem-vento para baixar apenas o necessário ao RF." }]));
man.push(p([{ t: "Importante: ", b: true }, { t: "o serviço OpenDAP do NOMADS foi aposentado pela NOAA (Service Change Notice 25-81, efetivo em 23/02/2026). O script usa os serviços vigentes indicados no próprio aviso:" }]));
man.push(
  tabela(
    ["Método", "Descrição"],
    [
      ["s3 (padrão)", "\"Fast download method\": lê o índice .idx de cada horário e baixa por byte-range só as mensagens GRIB necessárias (3 sem vento, 5 com), no espelho oficial da AWS (noaa-gfs-bdp-pds), ~2–3 MB por horário"],
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
man.push(p("Opções principais: --data/--rodada (rodada), --dias (alcance, padrão 16), --passo (validades, padrão 6 h), --dominio latS,latN,lonW,lonE, --acumulo 24h|dia, --jobs (downloads simultâneos), --base/--config (destino), --sem-vento, --auto-rodada, --sobrescrever e --simular."));
man.push(p([{ t: "Rodada ainda não publicada. ", b: true }, { t: "O GFS 00 UTC só começa a aparecer nos servidores ~3,5 h depois do horário sinótico (e completa em ~5 h), então uma execução de madrugada encontra 404 em todos os horários. O script trata isso de duas formas: um 404 não é repetido (não adianta insistir — o arquivo não está lá) e a mensagem diz o que fazer; e a opção --auto-rodada faz o script recuar de 6 em 6 horas até achar a rodada mais recente já publicada (--voltar-rodadas, padrão 4 = 24 h):" }]));
man.push(...codigo([
  "python3 prepara_gfs.py --config config.yaml --auto-rodada",
  "# Rodada 2026080600 ainda nao publicada; usando 2026080518 (6 h antes).",
]));
man.push(p("Para uma rodada operacional agendada no cron, --auto-rodada é o modo recomendado: a execução nunca falha por chegar cedo demais, apenas usa a rodada anterior."));
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

man.push(h2("6.3 ERA5 (prepara_era5.py)"));
man.push(p("O prepara_era5.py baixa a reanálise ERA5 (Copernicus/ECMWF, 0,25°) e converte para o padrão de leitura do RF: temperatura a 2 m, umidade relativa a 2 m calculada da temperatura + ponto de orvalho (fórmula de Magnus, Alduchov & Eskridge 1996) e vento a 10 m (u10/v10, para uso futuro). Para cada dia são gravados dois arquivos no destino da chave era5_dir do config.yaml:"));
man.push(tabela(["Arquivo", "Variáveis"], [
  ["ERA5.OBS.TEMP2m.RH2m.{data}{hora}.nc", "TEMP2m (K) e RH2m (%) — lido por rf_core.ler_temp_ur, mesmo formato do GFS"],
  ["ERA5.OBS.U10m.V10m.{data}{hora}.nc", "U10m e V10m (m/s)"],
], [45, 55]));
man.push(p([{ t: "Pré-requisito (uma única vez): ", b: true }, { t: "conta gratuita no CDS (cds.climate.copernicus.eu), aceitar no site a licença do dataset \"ERA5 hourly data on single levels\", instalar a API (python3 -m pip install cdsapi) e criar o ~/.cdsapirc (chmod 600):" }]));
man.push(...codigo(["url: https://cds.climate.copernicus.eu/api", "key: SEU-TOKEN-PESSOAL"]));
man.push(p("Modos de uso:"));
man.push(...codigo([
  "python3 prepara_era5.py --config config.yaml                 # últimos 7 dias disponíveis",
  "python3 prepara_era5.py --inicio 20260601 --fim 20260731     # período explícito",
  "python3 prepara_era5.py --data-final 20260730 --dias 120     # janela p/ rf_observado",
  "python3 prepara_era5.py --simular                            # só o plano (sem baixar)",
]));
man.push(p("A ERA5 tem atraso de ~5 dias (dias recentes vêm do produto preliminar ERA5T, tratado automaticamente), por isso a janela padrão termina 6 dias atrás. As requisições ao CDS são agrupadas por mês (mais eficientes na fila do Copernicus — cada uma pode esperar alguns minutos); a hora da análise é configurável (--hora, padrão 18 UTC, a mesma dos produtos do RF), dias completos são pulados e --sobrescrever regrava."));
man.push(p([{ t: "Download incremental. ", b: true }, { t: "O script confere o que já existe por par (dia, hora) antes de pedir qualquer coisa ao CDS: um dia só é considerado pronto quando os dois arquivos daquela hora existem (T/UR e vento). O que já está no disco não é baixado nem regravado (para refazer, use --sobrescrever), então uma execução interrompida é retomada sem custo — basta rodar de novo que ele completa apenas as lacunas. O --simular mostra exatamente esse plano, uma requisição por mês e por hora:" }]));
man.push(...codigo([
  "Arquivos (dia x hora): 21; 5 ja existem, 16 a baixar",
  "  requisicao CDS: 2026-06 as 17 UTC, 2 dia(s): [2, 3]",
  "  requisicao CDS: 2026-06 as 18 UTC, 1 dia(s): [3]",
]));
man.push(p([{ t: "Dica de volume. ", b: true }, { t: "No modo solar, o número de horas depende da largura do domínio: o padrão (-114,95 a -30,05, que alcança o Pacífico) exige 7 horas UTC; restringindo ao Brasil (--dominio -35,7,-75,-32) caem para 4 — quase metade do volume. Confira antes se o domínio menor cobre toda a grade do IMERG, já que os produtos observados usam a grade da precipitação como referência." }]));
man.push(h2("6.4 Risco de Fogo observado (rf_observado.py)"));
man.push(p("O rf_observado.py calcula o RF observado de dias que já passaram — últimos dias, semanas ou meses — usando apenas observações: a série completa de 120 dias do IMERG (incluindo o próprio dia analisado) e a T2m/UR2m da ERA5 na hora da análise. É a mesma formulação do modelo (rb_max 0,9 e fatores FU/FT/FLAT/FTOP), o que permite reconstituir o histórico recente e comparar com as previsões (RF.PREV.* × RF.OBS.*)."));
man.push(...codigo([
  "python3 rf_observado.py --config config.yaml --dias 7        # últimos 7 dias",
  "python3 rf_observado.py --config config.yaml --semanas 2     # últimas 2 semanas",
  "python3 rf_observado.py --config config.yaml --meses 3       # últimos 3 meses-calendário",
  "python3 rf_observado.py --config config.yaml --de 20260601 --ate 20260731",
  "python3 rf_observado.py --config config.yaml --dias 7 --simular   # confere as entradas",
  "python3 rf_observado.py --config config.yaml --dias 7 --sem-vegetacao --sem-topografia",
]));
man.push(p("O fluxo completo é: prepara_imerg.py (precipitação do período + 119 dias anteriores) → prepara_era5.py (T/UR do período) → rf_observado.py. O --simular confere as entradas e aponta o que falta; dias com entradas incompletas são pulados com aviso (e o comando de preparo sugerido), sem interromper os demais. As saídas RF.OBS.{data}{hora}.nc (e .tif) vão para data/output/2.2/RF_OBS/netcdf (produto configurável via --produto, com os sufixos automáticos _SEMVEG/_SEMTOPO da análise de sensibilidade). Demais opções como no rf_previsto.py: --hora, --rb-max, --jobs, --sem-tif, --classe-veg, --data-final (aceita 'hoje'; padrão 6 dias atrás, pelo atraso da ERA5)."));
man.push(p([{ t: "Um arquivo por dia + agregações. ", b: true }, { t: "Cada dia do período gera o seu RF.OBS.{data}{hora}.nc. Para o risco médio — como nos mapas mensais do BESM — acrescente:" }]));
man.push(tabela(["Opção", "Saída"], [
  ["--media", "RF.OBS.MEDIA.{ini}-{fim}.nc — média de todo o período"],
  ["--media-mensal", "RF.OBS.MEDIA.AAAAMM.nc — uma média por mês-calendário do período"],
  ["--maximo", "usa o máximo em vez da média (arquivos RF.OBS.MAXIMO.*)"],
  ["--frequencia L", "RF.OBS.FREQ<L>.* — nº de dias com RF >= L (variável dias) e o percentual dos dias válidos (variável frequencia)"],
  ["--percentil N", "RF.OBS.P<N>.* — percentil N da distribuição dos dias"],
  ["--mergetime", "RF.OBS.SERIE.{ini}-{fim}.nc — todos os dias num só arquivo, com eixo de tempo"],
  ["--so-agrega", "não recalcula nada: agrega os diários já existentes no período"],
], [24, 76]));
man.push(p("As médias ignoram valores ausentes ponto a ponto (a contagem efetiva de dias usados fica no atributo global dias_agregados), e os arquivos saem no mesmo formato dos diários — podem ser abertos no QGIS/GeoServer ou passados ao rf_figura.py."));
man.push(...codigo([
  "# Julho de 2026: 31 mapas diarios + a media do mes",
  "python3 rf_observado.py --de 20260701 --ate 20260731 --media",
  "",
  "# Jan-jul/2026: media de cada mes + media do periodo todo",
  "python3 rf_observado.py --de 20260101 --ate 20260731 --media-mensal --media",
  "",
  "# So as medias, a partir dos diarios ja calculados",
  "python3 rf_observado.py --de 20260701 --ate 20260731 --media --so-agrega",
]));
man.push(h2("6.5 Figuras dos campos de RF (rf_figura.py)"));
man.push(p("O rf_figura.py gera PNG de qualquer NetCDF do pipeline (RF.OBS.*, RF.PREV.*, médias mensais) usando a paleta oficial da operação, idêntica ao SLD do GeoServer (INPE_FireRiskModel_2.2): -999 transparente e as paradas #17b617 (Mínimo, 0,15), #79f674 (Baixo, 0,40), #ffff82 (Médio, 0,70), #ff2e00 (Alto, 0,95) e #a70000 (Crítico, 1,00), interpoladas como no type=\"ramp\" do SLD."));
man.push(...codigo([
  "# Um mapa (a figura vai para o lado do NetCDF, se --saida for omitido)",
  "python3 rf_figura.py data/output/2.2/RF_OBS/netcdf/RF.OBS.MEDIA.202607.nc",
  "",
  "# Painel com as medias mensais do ano",
  "python3 rf_figura.py data/output/2.2/RF_OBS/netcdf/RF.OBS.MEDIA.2026*.nc \\",
  "    --painel --titulo \"Risco de Fogo observado - media mensal\" \\",
  "    --saida rf_obs_mensal_2026.png",
  "",
  "# Todos os dias de julho, 7 colunas, faixas discretas",
  "python3 rf_figura.py '.../RF.OBS.202607*18.nc' --painel --colunas 7 --classes",
]));
man.push(p("Opções: --painel (vários campos numa figura) com --colunas, --titulo, --saida (arquivo ou pasta), --dpi, --classes (uma cor por faixa, em vez da rampa — útil para leitura por classe) e --sem-mascara (não aplica a máscara de oceano, necessária apenas em campos gerados com --sem-vegetacao, que não trazem a máscara d'água). Requer matplotlib (e global-land-mask para a máscara de oceano)."));
man.push(p([{ t: "Figuras de frequência e de percentil. ", b: true }, { t: "São os mesmos comandos — o script reconhece o tipo do arquivo pelo conteúdo e escolhe a escala sozinho:" }]));
man.push(tabela(["Arquivo", "Escala usada", "Comando"], [
  ["RF.OBS.P90.* (percentil)", "paleta oficial do RF (0-1), igual às médias", "python3 rf_figura.py .../RF.OBS.P90.202607.nc"],
  ["RF.OBS.FREQ0.7.* (nº de dias)", "sequencial de contagem (YlOrRd), 0 ao total de dias", "python3 rf_figura.py .../RF.OBS.FREQ0.7.202607.nc"],
  ["RF.OBS.FREQ0.7.* (% dos dias)", "a mesma, em percentual", "python3 rf_figura.py .../RF.OBS.FREQ0.7.202607.nc --var frequencia"],
], [26, 34, 40]));
man.push(p("O arquivo de frequência traz duas variáveis: dias (contagem, o padrão da figura) e frequencia (percentual dos dias válidos); --var frequencia troca de uma para a outra. O limiar aparece no rótulo da barra de cores, lido do atributo limiar do NetCDF, e o número de dias agregados vai no título."));
man.push(...codigo([
  "# Julho/2026: gerar as tres agregacoes e depois as figuras",
  "python3 rf_observado.py --de 20260701 --ate 20260731 \\",
  "    --media --frequencia 0.7 --percentil 90",
  "",
  "D=data/output/2.2/RF_OBS/netcdf",
  "python3 rf_figura.py $D/RF.OBS.FREQ0.7.202607.nc                  # dias",
  "python3 rf_figura.py $D/RF.OBS.FREQ0.7.202607.nc --var frequencia # % dos dias",
  "python3 rf_figura.py $D/RF.OBS.P90.202607.nc                      # percentil 90",
  "",
  "# Painel do ano: 12 mapas de dias acima do limiar (mesma escala nos 12)",
  "python3 rf_figura.py \"$D/RF.OBS.FREQ0.7.2026*.nc\" --painel --colunas 4 \\",
  "    --titulo \"Dias com RF >= 0,7 - 2026\" --saida freq_2026.png",
]));
man.push(p("Num painel, a escala é comum a todos os campos, o que torna os meses comparáveis entre si. Por isso não é possível misturar frequência (contagem de dias) e risco (0-1) na mesma figura: uma figura tem uma só barra de cores, e o script recusa a mistura com uma mensagem explicando como separar. O FWI segue a mesma lógica (--var escolhe o componente, --escala-fwi força a escala 0-5-12-22-35-60)."));
man.push(...codigo([
  "python3 rf_figura.py .../FWI.OBS.FREQ22.202607.nc          # dias com FWI >= 22",
  "python3 rf_figura.py .../FWI.OBS.P90.202607.nc --var DSR   # percentil 90 do DSR",
]));

man.push(h2("6.6 Horário da ERA5: hora fixa ou hora solar local"));
man.push(p("As variáveis da ERA5 são instantâneas (o valor da hora cheia), e é isso que os índices de perigo pedem: as condições do momento mais crítico do dia — o meio da tarde no RF, o meio-dia local no FWI. Uma média diária não seria equivalente: ela rebaixa a temperatura, sobe a umidade e comprime a variabilidade, subestimando o risco de forma sistemática (num dia típico de seca no Cerrado, trocar as 18 UTC pela média do dia derruba o fator de temperatura em ~13 %)."));
man.push(p("Há, porém, um problema real com a hora fixa num domínio largo: 18 UTC é 16 h no litoral do Nordeste e 13 h no Acre. Por isso a seção era5 do config.yaml oferece os dois modos:"));
man.push(...codigo([
  "era5:",
  "  horario: fixo          # fixo | solar",
  "  hora: 18               # hora UTC no modo fixo (o que a operacao usa)",
  "  hora_local: 15         # hora solar local no modo solar (12 = convencao do FWI)",
  "  # horas: [17, 18, 19, 20]   # opcional: horas UTC explicitas",
]));
man.push(p("No modo solar, cada faixa de longitude (fusos solares de 15°) usa a hora UTC correspondente à hora local pedida, e o campo é montado faixa a faixa. Sobre o Brasil, hora_local: 15 precisa das horas 17, 18, 19 e 20 UTC; hora_local: 12 (FWI) precisa de 14 a 17 UTC. O prepara_era5.py lê a mesma seção e baixa exatamente essas horas:"));
man.push(...codigo([
  "python3 prepara_era5.py --config config.yaml --dias 30   # horas conforme o config",
  "python3 prepara_era5.py --dias 30 --hora 17,18,19,20     # horas explicitas",
  "python3 prepara_era5.py --config config.yaml --simular   # mostra o plano por hora",
]));
man.push(p("Os produtos observados (rf_observado.py e fwi_observado.py) seguem a mesma configuração, com --horario e --hora-local para sobrepor pontualmente. No modo solar o produto ganha o sufixo _SOLAR e os arquivos são rotulados pela hora local (RF.OBS.2026073115.nc), de modo que as duas convenções nunca se misturam. Custo a considerar: o modo solar multiplica o volume baixado da ERA5 pelo número de horas (4x sobre o Brasil, mais em domínios que chegam ao Pacífico)."));
man.push(h2("6.7 Escala da umidade relativa no Fator de Umidade (correcao_ur)"));
man.push(p("Um achado da conversão que merece atenção: o NCL original converte a UR de porcentagem para fração (ur2m = ur2m/100.) antes de aplicar FU = -0,008·UR + 1,3. Com a UR entre 0 e 1, o FU fica praticamente constante (1,292 a 1,300) — ou seja, na prática a umidade quase não modula o RF operacional, e o produto sai multiplicado por ~1,3. Os coeficientes, porém, parecem ter sido pensados para a UR em porcentagem: aí o FU iria de 1,14 (UR 20 %) a 0,58 (UR 90 %), que é o comportamento que a descrição do modelo sugere."));
man.push(p("Como a conversão para Python reproduz o NCL fielmente, o padrão continua sendo o comportamento da operação. A chave correcao_ur permite quantificar o efeito da escolha:"));
man.push(tabela(["Valor", "UR usada no FU", "FU a 40 % de UR"], [
  ["ncl (padrão)", "fração (0–1)", "1,297"],
  ["decimos", "décimos (0–10)", "1,268"],
  ["percentual", "porcentagem (0–100)", "0,980"],
], [25, 45, 30]));
man.push(...codigo([
  "execucao:",
  "  correcao_ur: ncl        # ncl | decimos | percentual",
  "",
  "python3 rf_observado.py --de 20260701 --ate 20260731 --correcao-ur percentual",
  "python3 rf_previsto.py  --horizontes 3d --correcao-ur percentual",
]));
man.push(p([{ t: "Recomendação: ", b: true }, { t: "qualquer valor diferente de ncl acrescenta sufixo ao produto (_URDEC, _URPER) e registra a escolha no atributo global escala_ur_no_FU, para nunca se misturar com a rodada de referência. Trate como análise de sensibilidade e valide com o autor do modelo antes de qualquer mudança na operação." }]));

man.push(h2("6.8 Qual métrica usar no produto mensal"));
man.push(p("A média dos dias é a leitura mais simples, mas não é a única — e para risco de fogo raramente é suficiente sozinha. A distribuição do RF é assimétrica e o impacto vem da cauda: um mês com 25 dias tranquilos e 5 críticos pode ter a mesma média de um mês com 30 dias medianos, com comportamento do fogo completamente diferente."));
man.push(tabela(["Métrica", "Quando usar"], [
  ["Média (--media, --media-mensal)", "condição típica do mês; bom para mapa climatológico e comparação entre meses"],
  ["Frequência (--frequencia 0.7)", "leitura operacional direta — \"neste mês, 12 dias de risco Alto ou Crítico\"; é também a forma que vira probabilidade quando aplicada aos membros de um ensemble em vez dos dias"],
  ["Percentil (--percentil 90)", "pega a cauda sem depender de um único dia; base natural para expressar o índice em percentis da climatologia local"],
  ["Máximo (--maximo)", "diagnóstico apenas — um único dia com erro de modelo domina o campo"],
], [32, 68]));
man.push(...codigo([
  "# Julho de 2026: media, dias com RF >= 0,7 e percentil 90 do mes",
  "python3 rf_observado.py --de 20260701 --ate 20260731 --media-mensal \\",
  "    --frequencia 0.7 --percentil 90",
]));
man.push(p([{ t: "No FWI a resposta é canônica: ", b: true }, { t: "o índice não deve ser promediado — a relação dele com a dificuldade de controle não é linear. Van Wagner criou o DSR (Daily Severity Rating) justamente para poder ser promediado, e o produto mensal padrão do sistema é o MSR (Monthly Severity Rating) = média do DSR:" }]));
man.push(...codigo([
  "# MSR: produto mensal recomendado do sistema canadense",
  "python3 fwi_observado.py --de 20260701 --ate 20260731 --media-mensal \\",
  "    --var-agrega DSR",
  "",
  "# Dias de perigo alto (FWI >= 22) e percentil 90 do mes",
  "python3 fwi_observado.py --de 20260701 --ate 20260731 --media-mensal \\",
  "    --frequencia 22 --percentil 90",
]));
man.push(p("Detalhes de implementação: valores ausentes são ignorados ponto a ponto (a frequência é sempre relativa aos dias válidos daquele ponto, e o número de dias entra no atributo dias_agregados); o percentil é calculado por blocos de latitude, para não carregar a série inteira na memória na grade de 1 km. O rf_figura.py reconhece os arquivos de frequência e usa uma escala sequencial de contagem em vez da paleta de risco."));

man.push(h2("6.9 Fonte da precipitação observada: IMERG ou MSWEP (prepara_mswep.py)"));
man.push(p("A precipitação observada alimenta os 119 dias da janela do RF previsto, o RF observado e o FWI observado. Por padrão ela vem do IMERG, baixado pelo prepara_imerg.py. Como alternativa, o pipeline lê o MSWEP (Multi-Source Weighted-Ensemble Precipitation), que já está no disco do CPTEC e portanto dispensa download:"));
man.push(...codigo([
  "/pesq/dados/sismom/SisMOM/sipec/mswep/daily/{ano}/{mes}/{AAAAMMDD}.nc",
]));
man.push(p("Os arquivos originais são globais de 0,1° (3600 x 1800), com latitude de norte para sul, longitude -179,95..179,95 e a variável sem nome reconhecível (o cdo sinfo mostra \"unknown\"). O pipeline resolve os três pontos sozinho: detecta a variável, inverte a latitude para sul->norte e recorta o domínio na leitura, de modo que a grade global nunca é carregada inteira na memória."));
man.push(p("A escolha é feita no config.yaml (ou na linha de comando, que prevalece):"));
man.push(...codigo([
  "precipitacao:",
  "  fonte: mswep           # imerg (padrao) | mswep",
  "  modo: in_loco          # in_loco (arquivos originais) | convertido",
  "  variavel: auto         # nome da variavel no arquivo (auto detecta)",
  "  dominio: \"-60.05,29.95,-114.95,-30.05\"   # recorte da leitura in loco",
  "",
  "python3 rf_observado.py  --config config.yaml --dias 7  --precipitacao mswep",
  "python3 fwi_observado.py --config config.yaml --dias 30 --precipitacao mswep",
  "python3 rf_previsto.py   --config config.yaml --horizontes 3d --precipitacao mswep",
]));
man.push(p("Os produtos ganham o sufixo _MSWEP (RF_OBS_MSWEP, FWI_OBS_MSWEP, RF_PREV_GFS_MSWEP...), de modo que uma rodada com MSWEP nunca sobrescreve a rodada de referência com IMERG — as duas podem ser comparadas ponto a ponto."));
man.push(p([{ t: "Converter é opcional. ", b: true }, { t: "No modo in_loco (padrão) nada precisa ser preparado. O prepara_mswep.py grava uma cópia já recortada no padrão do pipeline (~2 MB/dia em vez de ~7 MB globais), o que compensa quando a mesma janela de 120 dias é relida todo dia, quando o disco do MSWEP é lento ou indisponível na hora da rodada, ou quando se quer congelar uma versão do banco para reprocessamento:" }]));
man.push(...codigo([
  "# Converte a janela de 119 dias que antecede hoje",
  "python3 prepara_mswep.py --config config.yaml",
  "",
  "# Periodo explicito, e conferencia sem gravar",
  "python3 prepara_mswep.py --config config.yaml --inicio 20230101 --fim 20230131",
  "python3 prepara_mswep.py --config config.yaml --simular",
]));
man.push(p("Depois, basta trocar modo: in_loco por modo: convertido (ou usar --modo-precipitacao convertido). O script é incremental — pula os dias já convertidos, --sobrescrever regrava — e, se o arquivo diário não existir, tenta automaticamente o arquivo mensal da mesma pasta (jan.nc, feb.nc, ...), extraindo o dia pedido pelo eixo de tempo. As duas formas de leitura foram verificadas ponto a ponto: teste_mswep.py confirma que o RF observado sai idêntico in loco e convertido."));
man.push(p([{ t: "Qual usar? ", b: true }, { t: "O IMERG é o dado da operação do Queimadas e tem latência de ~4 h, o que o torna obrigatório na rodada diária. O MSWEP combina satélite, estações e reanálise, costuma representar melhor a chuva sobre áreas com rede de superfície densa e cobre desde 1979 — sendo mais adequado a reconstruções históricas, calibração e comparação de sensibilidade da precipitação, que é a variável de maior peso no RF (os 120 acumulados diários). Como as duas rodadas escrevem em produtos separados, a comparação é direta." }]));

man.push(h1("7. FWI — Canadian Fire Weather Index System"));
man.push(p("Além do RF do INPE, o pacote traz o FWI canadense completo, o índice único proposto na metodologia multi-horizonte. Os dois convivem: consomem os mesmos arquivos de entrada e escrevem no mesmo padrão de saída, o que permite compará-los ponto a ponto."));
man.push(h2("7.1 O motor (fwi_core.py)"));
man.push(p("Implementação vetorizada em numpy dos seis componentes do sistema, na ordem de cálculo:"));
man.push(tabela(["Componente", "O que representa", "Memória"], [
  ["FFMC", "umidade do combustível fino", "~2/3 de dia"],
  ["DMC", "umidade da camada orgânica", "~12 dias"],
  ["DC", "seca profunda", "~52 dias"],
  ["ISI", "FFMC + vento (espalhamento inicial)", "—"],
  ["BUI", "DMC + DC (combustível disponível)", "—"],
  ["FWI", "ISI + BUI (índice final)", "—"],
], [18, 57, 25]));
man.push(p("Também é calculado o DSR (Daily Severity Rating). As entradas seguem a convenção do sistema — condições do meio-dia local: temperatura (°C), umidade relativa (%), vento a 10 m (km/h) e precipitação acumulada nas 24 h anteriores (mm). O ajuste hemisférico é feito por faixas de latitude (tabelas de duração do dia para DMC e DC), de modo que o comportamento sazonal fica correto no Hemisfério Sul e na faixa equatorial."));
man.push(p([{ t: "Validação: ", b: true }, { t: "o motor é comparado, no teste_fwi.py, com a tabela de referência do sistema — incluindo o exemplo clássico de Van Wagner & Pickett (T=17 °C, UR=42 %, vento=25 km/h, chuva=0, partindo de FFMC=85, DMC=6, DC=15, que deve dar FFMC 87,7 · DMC 8,5 · DC 19,0 · ISI 10,9 · BUI 8,5 · FWI 10,1) — e, quando o xclim está instalado, também contra a implementação de referência do CFFWIS, em cinco faixas de latitude e quatro meses, com diferença menor que 1e-9." }]));
man.push(h2("7.2 FWI observado (fwi_observado.py)"));
man.push(p("Calcula o FWI diário a partir do IMERG (chuva) e da ERA5 (T, UR e vento — daí a importância do prepara_era5.py já baixar U10m/V10m). Diferente do RF, que é independente por dia, o FWI é sequencial: cada dia parte dos códigos de umidade do dia anterior. O script cuida disso de duas formas: rodando um período de aquecimento (spin-up, padrão 90 dias) antes do primeiro dia pedido, e permitindo salvar/retomar o estado entre execuções."));
man.push(...codigo([
  "# Ultimos 30 dias (com 90 dias de spin-up antes)",
  "python3 fwi_observado.py --config config.yaml --dias 30",
  "",
  "# Um mes fechado + a media mensal do FWI",
  "python3 fwi_observado.py --de 20260701 --ate 20260731 --media-mensal",
  "",
  "# Rodada continua: retoma do estado salvo e grava o novo",
  "python3 fwi_observado.py --de 20260801 --ate 20260805 \\",
  "    --estado-inicial estado_fwi.nc --salvar-estado estado_fwi.nc",
  "",
  "# Conferir as entradas sem calcular",
  "python3 fwi_observado.py --de 20260701 --ate 20260731 --simular",
]));
man.push(p("Cada dia gera um FWI.OBS.{data}{hora}.nc com os sete campos (FFMC, DMC, DC, ISI, BUI, FWI, DSR) em data/output/2.2/FWI_OBS/netcdf. As variáveis meteorológicas da ERA5 (0,25°) são interpoladas para a grade do IMERG (0,1°), que é a grade de saída. Dias sem entradas completas são pulados com aviso e o estado é mantido, sem quebrar a série."));
man.push(p("Opções: --dias/--semanas/--meses/--de+--ate e --data-final (como no rf_observado.py), --spinup N, --estado-inicial/--salvar-estado, --ffmc0/--dmc0/--dc0 (partida a frio, padrão 85/6/15), --media, --media-mensal, --maximo, --var-agrega (componente agregado, padrão FWI), --produto, --hora e --simular."));
man.push(p([{ t: "Convenção de hora: ", b: true }, { t: "o sistema canadense usa as condições do meio-dia local — sobre o Brasil (UTC−3), ~15 UTC. O padrão do script é 18 UTC apenas para reaproveitar o banco de ERA5 já baixado para o RF; para seguir a convenção à risca, baixe a ERA5 com prepara_era5.py --hora 15 e rode o FWI com --hora 15." }]));
man.push(h2("7.3 Figuras do FWI"));
man.push(p("O rf_figura.py reconhece os arquivos FWI.* e usa automaticamente as classes do índice (0–5–12–22–35), além de permitir plotar qualquer componente:"));
man.push(...codigo([
  "python3 rf_figura.py data/output/2.2/FWI_OBS/netcdf/FWI.OBS.2026073118.nc",
  "python3 rf_figura.py .../FWI.OBS.2026073118.nc --var DC     # seca profunda",
  "python3 rf_figura.py .../FWI.OBS.202607*.nc --painel --colunas 7",
]));
man.push(h2("7.4 O que falta para o FWI previsto"));
man.push(p("O FWI observado fecha a \"análise de fogo contínua\" da metodologia. Para o FWI previsto faltam, nesta ordem:"));
man.push(numbered([{ t: "Vento nas fontes — ", b: true }, { t: "resolvido para o GFS: o prepara_gfs.py já grava GFS.PREV.U10m.V10m.* (seção 6.1). Nas fontes sazonais (BESM/Eta) o vento ainda não vem no pacote de dados e precisa ser solicitado ao CPTEC — sem ele não há ISI e, portanto, não há FWI sazonal." }], "num-fwi"));
man.push(numbered([{ t: "Camada de fontes — ", b: true }, { t: "o rf_fontes.py entrega precipitação, temperatura e umidade; falta declarar os padrões de arquivo e variáveis do vento." }], "num-fwi"));
man.push(numbered([{ t: "Um fwi_previsto.py — ", b: true }, { t: "diferente do RF (independente por horizonte), o FWI previsto é sequencial: parte do estado dos códigos de umidade no dia da rodada e avança dia a dia até o horizonte. Essa peça já existe: o fwi_observado.py salva o estado (--salvar-estado) e o fwi_previsto o consumiria com --estado-inicial." }], "num-fwi"));

man.push(h1("8. Saídas"));
man.push(h2("8.1 Produto diário (1 a 5 dias)"));
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
man.push(h2("8.2 Produto semanal (1 a 2 semanas)"));
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
man.push(h2("8.3 Formato dos arquivos"));
man.push(p("O NetCDF contém a variável rbf(time, lat, lon) com o RF em [0, 1], arredondado a 2 casas decimais, valor ausente −999 e eixo de tempo na data/hora da previsão. O GeoTIFF está em EPSG:4326, orientado de norte para sul, com nodata −999, compressão LZW e organização em tiles."));
man.push(p("Interpretação usual do RF: mínimo (< 0.15), baixo (0.15–0.40), médio (0.40–0.70), alto (0.70–0.95) e crítico (≥ 0.95)."));

man.push(h1("9. Logs e monitoramento"));
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

man.push(h1("10. Solução de problemas"));
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

man.push(h1("11. Testes de validação"));
man.push(p("Após instalar ou alterar qualquer coisa, rode:"));
man.push(...codigo(["python3 teste_rf.py            # valida o núcleo do cálculo (rf_core)", "python3 teste_rf_previsto.py   # valida o script genérico de ponta a ponta", "python3 teste_rf_multifonte.py # valida o modo multifonte (Eta 13m, BESM 12h, JSON)", "python3 teste_prepara_gfs.py   # valida o preparo do GFS (idx, baldes, NetCDF)", "python3 teste_prepara_imerg.py # valida o preparo do IMERG (conversão, caminhos)", "python3 teste_prepara_era5.py  # valida o preparo da ERA5 (UR de T+Td, conversão)", "python3 teste_rf_observado.py  # valida o RF observado, as agregacoes e as figuras", "python3 teste_fwi.py           # valida o motor FWI (referencia + xclim) e o FWI observado", "python3 teste_era5_horario.py  # valida o horario da ERA5 (fixo/solar) e a escala da UR"]));
man.push(p("O primeiro teste cria dados sintéticos em /tmp/teste_rf, executa o cálculo completo e compara com uma implementação de referência fiel ao NCL; a saída esperada termina com \"TODOS OS TESTES PASSARAM\". O segundo monta uma árvore com a estrutura de diretórios da produção em /tmp/teste_generico e executa o rf_previsto.py real em cinco cenários (lista, intervalo, fallback do GFS, horizonte absoluto e falha controlada)."));

man.push(h1("12. Segurança"));
man.push(p("O script semanal contém as credenciais do lftp (herdadas do shell script original) nas constantes LFTP_USUARIO e LFTP_SENHA. Recomenda-se movê-las para variáveis de ambiente ou para o arquivo ~/.netrc e restringir a permissão de leitura dos scripts."));

man.push(h1("13. Suporte"));
man.push(p("Modelo: Alberto Setzer (alberto.setzer@inpe.br) · Código NCL original: Guilherme Martins (guilherme.martins@inpe.br) · Programa Queimadas: http://www.inpe.br/queimadas/"));

// ---------------------------------------------------------------- gravação
(async () => {
  fs.writeFileSync("relatorio_conversao.docx", await Packer.toBuffer(documento(rel)));
  fs.writeFileSync("manual_usuario.docx", await Packer.toBuffer(documento(man)));
  console.log("ok");
})();
