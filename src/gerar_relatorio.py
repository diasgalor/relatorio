    // ==============================================
    // CONFIGURAÇÕES INICIAIS
    // ==============================================

    var idImagemFallback = 'COPERNICUS/S2_SR_HARMONIZED/20250315T133839_20250315T134222_T22KCE';
    var diasAposPlantio = 25;
    var janelaBuscaDias = 20;
    var janelaHistoricaDias = 45;
    var limiteNuvemPercentual = 60;
    var maxImagensHistorico = 12;
    var areaMinimaEquipamentoHa = 2;
    var codigosOperacaoPlantio = ['138'];
    var areas = ee.FeatureCollection('projects/ee-diasgalor/assets/plmiuni');
    var limitesTalhoes = ee.FeatureCollection('projects/ee-diasgalor/assets/pantanal');

    var calcularIndices = function(img) {
    return img.addBands([
        img.normalizedDifference(['B8', 'B4']).rename('NDVI'),
        img.normalizedDifference(['B8', 'B5']).rename('NDRE'),
        img.expression(
        '(2 * NIR + 1 - sqrt((2 * NIR + 1) ** 2 - 8 * (NIR - RED))) / 2', {
            'NIR': img.select('B8'),
            'RED': img.select('B4')
        }
        ).rename('MSAVI')
    ]);
    };

    // ==============================================
    // PADRONIZAÇÃO DOS CAMPOS
    // ==============================================

    var extrairTextoDataPlantio = function(f) {
    var camposData = ee.List([
        'dt_hr_lo_1',
        'dt_hr_loca',
        'dt_hr_local_inicial',
        'dt_hr_local_final'
    ]);

    var dataTexto = ee.String(camposData.iterate(function(campo, acumulado) {
        var valorAcumulado = ee.String(acumulado);
        var nomeCampo = ee.String(campo);
        var existeCampo = f.propertyNames().contains(nomeCampo);
        var valorCampo = ee.String(ee.Algorithms.If(existeCampo, f.get(nomeCampo), ''));
        var valorValido = valorCampo.length().gte(10);

        return ee.Algorithms.If(
        valorAcumulado.length().gt(0),
        valorAcumulado,
        ee.Algorithms.If(valorValido, valorCampo, '')
        );
    }, ''));

    return dataTexto;
    };

    var converterDataParaMillis = function(dataTexto) {
    var dataDia = ee.String(dataTexto).slice(0, 10);
    var formatoIso = dataDia.slice(4, 5).compareTo('-').eq(0);
    var formatoBr = dataDia.slice(2, 3).compareTo('/').eq(0);
    var formatoBrHifen = dataDia.slice(2, 3).compareTo('-').eq(0);

    return ee.Number(ee.Algorithms.If(
        dataDia.length().eq(10),
        ee.Algorithms.If(
        formatoIso,
        ee.Date.parse('YYYY-MM-dd', dataDia).millis(),
        ee.Algorithms.If(
            formatoBr,
            ee.Date.parse('dd/MM/YYYY', dataDia).millis(),
            ee.Algorithms.If(
            formatoBrHifen,
            ee.Date.parse('dd-MM-YYYY', dataDia).millis(),
            -1
            )
        )
        ),
        -1
    ));
    };

    var areasPadronizadas = areas.map(function(f) {
    var dataPlantioTexto = extrairTextoDataPlantio(f);
    var dataPlantioMillis = converterDataParaMillis(dataPlantioTexto);
    var operacao = ee.String(ee.Algorithms.If(
        f.propertyNames().contains('cd_operaca'),
        f.get('cd_operaca'),
        ee.Algorithms.If(
        f.propertyNames().contains('cd_operacao'),
        f.get('cd_operacao'),
        ''
        )
    )).trim();

    return f.set({
        Talhao: ee.String(f.get('cd_talhao')),
        Equipamento: ee.String(f.get('cd_equipam')),
        Operacao: operacao,
        DATA_PLANTIO_TXT: dataPlantioTexto,
        DATA_PLANTIO_MILLIS: dataPlantioMillis
    });
    });

    var limitesPadronizados = limitesTalhoes.map(function(f) {
    return f.set({
        Talhao: ee.String(f.get('TALHAO')),
        FazendaLimite: ee.String(f.get('FAZENDA')),
        ZonaLimite: ee.String(f.get('ZONA'))
    });
    });

    var limitesComDados = limitesPadronizados.map(function(f) {
    var qtdOperacoes = areasPadronizadas.filterBounds(f.geometry()).size();
    return f.set('QTD_OPERACOES', qtdOperacoes);
    });

    var limitesDisponiveis = limitesComDados.filter(ee.Filter.gt('QTD_OPERACOES', 0));
    var talhoes = limitesDisponiveis.aggregate_array('Talhao').distinct().sort();

    var recortarAreasAoTalhao = function(areasFiltradas, geometriaTalhao) {
    return areasFiltradas
        .filterBounds(geometriaTalhao)
        .map(function(f) {
        var geometriaIntersecao = f.geometry().intersection(geometriaTalhao, ee.ErrorMargin(1));
        var areaIntersecao = geometriaIntersecao.area(1);

        return f
            .setGeometry(geometriaIntersecao)
            .set('AREA_INTERSECAO', areaIntersecao);
        })
        .filter(ee.Filter.gt('AREA_INTERSECAO', 0));
    };

    // ==============================================
    // FUNÇÕES AUXILIARES
    // ==============================================

    var classificarNdvi = function(valorNdvi) {
    var ndvi = ee.Number(valorNdvi);
    return ee.Algorithms.If(
        ndvi.lt(0.2), 'Muito Baixo',
        ee.Algorithms.If(
        ndvi.lt(0.4), 'Baixo',
        ee.Algorithms.If(
            ndvi.lt(0.6), 'Médio',
            ee.Algorithms.If(ndvi.lt(0.8), 'Alto', 'Muito Alto')
        )
        )
    );
    };

    var codigoClasseNdvi = function(valorNdvi) {
    var ndvi = ee.Number(valorNdvi);
    return ee.Algorithms.If(
        ndvi.lt(0.2), 1,
        ee.Algorithms.If(
        ndvi.lt(0.4), 2,
        ee.Algorithms.If(
            ndvi.lt(0.6), 3,
            ee.Algorithms.If(ndvi.lt(0.8), 4, 5)
        )
        )
    );
    };

    var normalizarMinMax = function(valor, minimo, maximo) {
    var v = ee.Number(valor);
    var min = ee.Number(minimo);
    var max = ee.Number(maximo);
    var range = max.subtract(min);

    return ee.Number(ee.Algorithms.If(
        range.abs().lt(1e-6),
        1,
        v.subtract(min).divide(range)
    )).max(0).min(1);
    };

    var coresMaquinas = [
    'e41a1c', '377eb8', '4daf4a', '984ea3', 'ff7f00',
    'ffff33', 'a65628', 'f781bf', '999999', '17becf'
    ];

    var visRgb = {
    bands: ['B4', 'B3', 'B2'],
    min: 0.03,
    max: 0.35,
    gamma: 1.2
    };
    var visNdvi = {min: 0.2, max: 0.9, palette: ['red', 'yellow', 'green']};
    var visNdre = {min: 0.05, max: 0.5, palette: ['#8b0000', '#ffd700', '#006400']};
    var visMsavi = {min: 0.0, max: 0.8, palette: ['#6b3e26', '#f1c27d', '#2e8b57']};

    var obterInfoDataPlantioTalhao = function(areasTalhaoBase) {
    var areasComData = areasTalhaoBase.filter(ee.Filter.gte('DATA_PLANTIO_MILLIS', 0));
    var areasPlantio = areasComData.filter(ee.Filter.inList('Operacao', codigosOperacaoPlantio));

    var usaDataPlantioPorOperacao = areasPlantio.size().gt(0);
    var dataPlantioMillis = ee.Number(ee.Algorithms.If(
        usaDataPlantioPorOperacao,
        areasPlantio.aggregate_min('DATA_PLANTIO_MILLIS'),
        ee.Algorithms.If(
        areasComData.size().gt(0),
        areasComData.aggregate_min('DATA_PLANTIO_MILLIS'),
        ee.Date('2025-01-01').millis()
        )
    ));

    var fonteDataPlantio = ee.String(ee.Algorithms.If(
        usaDataPlantioPorOperacao,
        'operacao_plantio',
        ee.Algorithms.If(
        areasComData.size().gt(0),
        'fallback_primeira_operacao',
        'fallback_data_padrao'
        )
    ));

    return ee.Dictionary({
        dataPlantioMillis: dataPlantioMillis,
        fonteDataPlantio: fonteDataPlantio,
        qtdRegistrosPlantio: areasPlantio.size(),
        dataPlantioMin: ee.Date(ee.Number(ee.Algorithms.If(
        areasComData.size().gt(0),
        areasComData.aggregate_min('DATA_PLANTIO_MILLIS'),
        ee.Date('2025-01-01').millis()
        ))).format('YYYY-MM-dd'),
        dataPlantioMax: ee.Date(ee.Number(ee.Algorithms.If(
        areasComData.size().gt(0),
        areasComData.aggregate_max('DATA_PLANTIO_MILLIS'),
        ee.Date('2025-01-01').millis()
        ))).format('YYYY-MM-dd')
    });
    };

    var obterMelhorImagemAposPlantio = function(geometriaTalhao, dataPlantioMillis, fonteDataPlantio, qtdRegistrosPlantio, dataPlantioMin, dataPlantioMax, usaPeriodoManual, dataInicialManual, dataFinalManual) {

    var dataPlantio = ee.Date(dataPlantioMillis);
    var inicioJanela = usaPeriodoManual ? ee.Date(dataInicialManual) : dataPlantio.advance(diasAposPlantio, 'day');
    var fimJanela = usaPeriodoManual ? ee.Date(dataFinalManual).advance(1, 'day') : inicioJanela.advance(janelaBuscaDias, 'day');

    var colecao = ee.ImageCollection('COPERNICUS/S2_SR_HARMONIZED')
        .filterBounds(geometriaTalhao)
        .filterDate(inicioJanela, fimJanela)
        .filter(ee.Filter.lt('CLOUDY_PIXEL_PERCENTAGE', limiteNuvemPercentual));

    var melhorImagem = ee.Image(ee.Algorithms.If(
        colecao.size().gt(0),
        colecao.sort('CLOUDY_PIXEL_PERCENTAGE').first(),
        ee.Image(idImagemFallback)
    ));

    var nuvemImagemSelecionada = ee.Number(ee.Algorithms.If(
        melhorImagem.propertyNames().contains('CLOUDY_PIXEL_PERCENTAGE'),
        melhorImagem.get('CLOUDY_PIXEL_PERCENTAGE'),
        -1
    ));

    var datasColecao = ee.List(colecao.aggregate_array('system:time_start')).map(function(t) {
        return ee.Date(t).format('YYYY-MM-dd');
    });

    var nuvensColecao = ee.List(colecao.aggregate_array('CLOUDY_PIXEL_PERCENTAGE'));

    return ee.Dictionary({
        imagem: melhorImagem,
        metadados: ee.Dictionary({
        dataPlantio: dataPlantio.format('YYYY-MM-dd'),
        fonteDataPlantio: fonteDataPlantio,
        qtdRegistrosPlantio: qtdRegistrosPlantio,
        usaPeriodoManual: usaPeriodoManual,
        dataInicialManual: usaPeriodoManual ? ee.Date(dataInicialManual).format('YYYY-MM-dd') : '',
        dataFinalManual: usaPeriodoManual ? ee.Date(dataFinalManual).format('YYYY-MM-dd') : '',
        dataPlantioMin: dataPlantioMin,
        dataPlantioMax: dataPlantioMax,
        inicioJanela: inicioJanela.format('YYYY-MM-dd'),
        fimJanela: fimJanela.format('YYYY-MM-dd'),
        quantidadeImagens: colecao.size(),
        dataImagemSelecionada: melhorImagem.date().format('YYYY-MM-dd'),
        nuvemImagemSelecionada: nuvemImagemSelecionada,
        datasColecao: datasColecao,
        nuvensColecao: nuvensColecao
        })
    });
    };

    var gerarHistoricoEmergencia = function(areasTalhao, geometriaTalhao, dataPlantioMillis, usaPeriodoManual, dataInicialManual, dataFinalManual) {
    var dataPlantio = ee.Date(dataPlantioMillis);
    var inicioHistorico = usaPeriodoManual ? ee.Date(dataInicialManual) : dataPlantio.advance(diasAposPlantio, 'day');
    var fimHistorico = usaPeriodoManual ? ee.Date(dataFinalManual).advance(1, 'day') : inicioHistorico.advance(janelaHistoricaDias, 'day');

    var colecaoHistorica = ee.ImageCollection('COPERNICUS/S2_SR_HARMONIZED')
        .filterBounds(geometriaTalhao)
        .filterDate(inicioHistorico, fimHistorico)
        .filter(ee.Filter.lt('CLOUDY_PIXEL_PERCENTAGE', limiteNuvemPercentual))
        .sort('system:time_start')
        .limit(maxImagensHistorico);

    var colecaoComFallback = ee.ImageCollection(ee.Algorithms.If(
        colecaoHistorica.size().gt(0),
        colecaoHistorica,
        ee.ImageCollection.fromImages([ee.Image(idImagemFallback)])
    ));

    var listaImagens = colecaoComFallback.toList(colecaoComFallback.size());
    var indices = ee.List.sequence(0, ee.Number(colecaoComFallback.size()).subtract(1));

    var historico = ee.FeatureCollection(indices.iterate(function(i, acc) {
        var acumulado = ee.FeatureCollection(acc);
        var imagemAtual = ee.Image(listaImagens.get(ee.Number(i)));
        var dataImagem = imagemAtual.date().format('YYYY-MM-dd');
        var nuvemImagem = ee.Number(ee.Algorithms.If(
        imagemAtual.propertyNames().contains('CLOUDY_PIXEL_PERCENTAGE'),
        imagemAtual.get('CLOUDY_PIXEL_PERCENTAGE'),
        -1
        ));

        var ndviImagem = calcularIndices(
        imagemAtual.clip(geometriaTalhao).divide(10000)
        ).select('NDVI');

        var estatisticasImagem = ee.FeatureCollection(ee.Algorithms.If(
        areasTalhao.size().gt(0),
        ndviImagem.reduceRegions({
            collection: areasTalhao,
            reducer: ee.Reducer.mean(),
            scale: 10
        }).map(function(f) {
            var ndviMedio = ee.Number(f.get('mean'));
            return f.set({
            NDVI_MEDIO: ndviMedio,
            NDVI_CLASSE: classificarNdvi(ndviMedio),
            NDVI_CLASSE_CODIGO: codigoClasseNdvi(ndviMedio),
            DATA_IMAGEM: dataImagem,
            NUVEM_IMAGEM: nuvemImagem
            });
        }),
        ee.FeatureCollection([])
        ));

        return acumulado.merge(estatisticasImagem);
    }, ee.FeatureCollection([])));

    return ee.Dictionary({
        historico: historico,
        inicioHistorico: inicioHistorico.format('YYYY-MM-dd'),
        fimHistorico: fimHistorico.format('YYYY-MM-dd'),
        quantidadeImagensHistorico: colecaoHistorica.size()
    });
    };

    // ==============================================
    // INTERFACE (SELETOR DE TALHÃO)
    // ==============================================

    var painel = ui.Panel({
    style: {width: '430px', padding: '10px'}
    });

    var titulo = ui.Label('Relatório NDVI por Talhão', {
    fontWeight: 'bold',
    fontSize: '16px',
    margin: '0 0 8px 0'
    });

    var subtitulo = ui.Label('Selecione o talhão para ver polígonos por máquina e classificação NDVI.', {
    fontSize: '12px',
    margin: '0 0 8px 0'
    });

    var rotuloPeriodo = ui.Label('Período de avaliação (opcional, formato YYYY-MM-DD):', {
    fontSize: '12px',
    margin: '2px 0 4px 0'
    });

    var caixaDataInicial = ui.Textbox({
    placeholder: 'Data inicial (YYYY-MM-DD)',
    style: {stretch: 'horizontal'}
    });

    var caixaDataFinal = ui.Textbox({
    placeholder: 'Data final (YYYY-MM-DD)',
    style: {stretch: 'horizontal', margin: '4px 0 8px 0'}
    });

    var botaoExecutar = ui.Button({
    label: 'Executar análise',
    style: {stretch: 'horizontal', margin: '0 0 8px 0'}
    });

    var infoImagem = ui.Label('', {
    fontSize: '12px',
    color: '#666666',
    margin: '0 0 8px 0'
    });

    var seletorTalhao = ui.Select({
    placeholder: 'Selecione um talhão',
    style: {stretch: 'horizontal'}
    });

    var painelGraficos = ui.Panel({style: {stretch: 'both'}});

    painel.add(titulo);
    painel.add(subtitulo);
    painel.add(seletorTalhao);
    painel.add(rotuloPeriodo);
    painel.add(caixaDataInicial);
    painel.add(caixaDataFinal);
    painel.add(botaoExecutar);
    painel.add(infoImagem);
    painel.add(painelGraficos);
    ui.root.insert(0, painel);

    // ==============================================
    // ATUALIZAÇÃO DO MAPA E GRÁFICOS
    // ==============================================

    var atualizarTalhao = function(talhaoSelecionado) {
    if (!talhaoSelecionado) {
        infoImagem.setValue('Selecione um talhão e clique em Executar análise.');
        return;
    }

    var talhaoTxt = ee.String(talhaoSelecionado);
    var limiteTalhao = limitesDisponiveis.filter(ee.Filter.eq('Talhao', talhaoTxt));

    var geometriaTalhao = ee.Geometry(ee.Algorithms.If(
        limiteTalhao.size().gt(0),
        limiteTalhao.geometry(),
        limitesPadronizados.filter(ee.Filter.eq('Talhao', talhaoTxt)).geometry()
    ));

    var areasTalhaoBruto = recortarAreasAoTalhao(
        areasPadronizadas.filterBounds(geometriaTalhao),
        geometriaTalhao
    );

    var resumoAreaEquipamentos = ee.List(ee.Dictionary(areasTalhaoBruto.reduceColumns({
        selectors: ['AREA_INTERSECAO', 'Equipamento'],
        reducer: ee.Reducer.sum().group({
        groupField: 1,
        groupName: 'Equipamento'
        })
    })).get('groups', ee.List([])));

    var equipamentosValidos = ee.List(resumoAreaEquipamentos.map(function(item) {
        var grupo = ee.Dictionary(item);
        var areaHa = ee.Number(grupo.get('sum', 0)).divide(10000);
        return ee.Algorithms.If(
        areaHa.gte(areaMinimaEquipamentoHa),
        ee.String(grupo.get('Equipamento')),
        null
        );
    })).removeAll([null]);

    var areasTalhao = areasTalhaoBruto.filter(ee.Filter.inList('Equipamento', equipamentosValidos));

    var equipamentosExcluidos = ee.List(resumoAreaEquipamentos.map(function(item) {
        var grupo = ee.Dictionary(item);
        var areaHa = ee.Number(grupo.get('sum', 0)).divide(10000);
        return ee.Algorithms.If(
        areaHa.lt(areaMinimaEquipamentoHa),
        ee.String(grupo.get('Equipamento')),
        null
        );
    })).removeAll([null]);

    if (String(talhaoSelecionado) === '108') {
    var dados108ComData = areasTalhaoBruto.filter(ee.Filter.gte('DATA_PLANTIO_MILLIS', 0));
    var dados108Plantio = dados108ComData.filter(ee.Filter.inList('Operacao', codigosOperacaoPlantio));

    var dataFallback = ee.Date('1970-01-01').millis();
    var resumoDebug108 = ee.Dictionary({
        totalRegistrosIntersecao: areasTalhaoBruto.size(),
        totalComData: dados108ComData.size(),
        totalOperacaoPlantio: dados108Plantio.size(),
        minDataGeral: ee.Date(ee.Number(ee.Algorithms.If(
        dados108ComData.size().gt(0),
        dados108ComData.aggregate_min('DATA_PLANTIO_MILLIS'),
        dataFallback
        ))).format('YYYY-MM-dd'),
        maxDataGeral: ee.Date(ee.Number(ee.Algorithms.If(
        dados108ComData.size().gt(0),
        dados108ComData.aggregate_max('DATA_PLANTIO_MILLIS'),
        dataFallback
        ))).format('YYYY-MM-dd'),
        minDataPlantio: ee.Algorithms.If(
        dados108Plantio.size().gt(0),
        ee.Date(ee.Number(dados108Plantio.aggregate_min('DATA_PLANTIO_MILLIS'))).format('YYYY-MM-dd'),
        'sem_registro_plantio'
        ),
        maxDataPlantio: ee.Algorithms.If(
        dados108Plantio.size().gt(0),
        ee.Date(ee.Number(dados108Plantio.aggregate_max('DATA_PLANTIO_MILLIS'))).format('YYYY-MM-dd'),
        'sem_registro_plantio'
        )
    });

    var operacoes108 = ee.Dictionary(
        dados108ComData.reduceColumns({
        selectors: ['Operacao'],
        reducer: ee.Reducer.frequencyHistogram()
        })
    ).get('histogram');

    print('[DEBUG 108] Resumo datas/plantio', resumoDebug108);
    print('[DEBUG 108] Frequência de Operacao', operacoes108);
    print(
        '[DEBUG 108] Amostra registros (data texto, millis, operação, equipamento)',
        areasTalhaoBruto
        .sort('DATA_PLANTIO_MILLIS')
        .limit(120)
        .select(['Talhao', 'Equipamento', 'Operacao', 'DATA_PLANTIO_TXT', 'DATA_PLANTIO_MILLIS'])
    );
    print(
        '[DEBUG 108] Somente registros de operação de plantio',
        dados108Plantio
        .sort('DATA_PLANTIO_MILLIS')
        .limit(120)
        .select(['Talhao', 'Equipamento', 'Operacao', 'DATA_PLANTIO_TXT', 'DATA_PLANTIO_MILLIS'])
    );
    }

    var infoDataPlantio = obterInfoDataPlantioTalhao(areasTalhaoBruto);
    var dataPlantioMillisTalhao = ee.Number(infoDataPlantio.get('dataPlantioMillis'));
    var fonteDataPlantio = ee.String(infoDataPlantio.get('fonteDataPlantio'));
    var qtdRegistrosPlantio = ee.Number(infoDataPlantio.get('qtdRegistrosPlantio'));
    var dataPlantioMin = ee.String(infoDataPlantio.get('dataPlantioMin'));
    var dataPlantioMax = ee.String(infoDataPlantio.get('dataPlantioMax'));

    var dataInicialManual = (caixaDataInicial.getValue() || '').trim();
    var dataFinalManual = (caixaDataFinal.getValue() || '').trim();
    var usaPeriodoManual = dataInicialManual.length === 10 && dataFinalManual.length === 10;

    if ((dataInicialManual.length > 0 || dataFinalManual.length > 0) && !usaPeriodoManual) {
    infoImagem.setValue('Preencha data inicial e final no formato YYYY-MM-DD para aplicar período manual.');
    return;
    }

    if (usaPeriodoManual && dataInicialManual > dataFinalManual) {
    infoImagem.setValue('Período inválido: a data inicial deve ser menor ou igual à data final.');
    return;
    }

    var resultadoImagem = obterMelhorImagemAposPlantio(
        geometriaTalhao,
        dataPlantioMillisTalhao,
        fonteDataPlantio,
        qtdRegistrosPlantio,
        dataPlantioMin,
        dataPlantioMax,
        usaPeriodoManual,
        dataInicialManual,
        dataFinalManual
    );
    var metadadosImagem = ee.Dictionary(resultadoImagem.get('metadados'));
    var imagemSelecionada = ee.Image(resultadoImagem.get('imagem'))
        .clip(geometriaTalhao)
        .divide(10000);
    var imgTalhao = calcularIndices(imagemSelecionada);

    var resultadoHistorico = gerarHistoricoEmergencia(areasTalhao, geometriaTalhao, dataPlantioMillisTalhao, usaPeriodoManual, dataInicialManual, dataFinalManual);
    var historicoEmergencia = ee.FeatureCollection(resultadoHistorico.get('historico'));

    var listaEquipScore = areasTalhao.aggregate_array('Equipamento').distinct().sort();
    var resumoEmergenciaBase = ee.FeatureCollection(listaEquipScore.map(function(equip) {
        var equipamento = ee.String(equip);
        var histEq = historicoEmergencia
        .filter(ee.Filter.eq('Equipamento', equipamento))
        .filter(ee.Filter.notNull(['NDVI_MEDIO', 'NDVI_CLASSE_CODIGO']));

        var nObs = ee.Number(histEq.size());
        var ndviMedioHist = ee.Number(ee.Algorithms.If(nObs.gt(0), histEq.aggregate_mean('NDVI_MEDIO'), 0));
        var ndviStdHist = ee.Number(ee.Algorithms.If(nObs.gt(1), histEq.aggregate_total_sd('NDVI_MEDIO'), 0));
        var cvNdvi = ee.Number(ee.Algorithms.If(ndviMedioHist.gt(0), ndviStdHist.divide(ndviMedioHist), 1));
        var estabilidade = ee.Number(1).subtract(cvNdvi).max(0).min(1);

        var nAltoMuitoAlto = ee.Number(histEq.filter(ee.Filter.gte('NDVI_CLASSE_CODIGO', 4)).size());
        var propAlto = ee.Number(ee.Algorithms.If(nObs.gt(0), nAltoMuitoAlto.divide(nObs), 0));

        var areaHa = ee.Number(
        areasTalhao
            .filter(ee.Filter.eq('Equipamento', equipamento))
            .aggregate_sum('AREA_INTERSECAO')
        ).divide(10000);

        var confiancaAmostral = nObs.divide(4).min(1);
        var confiancaArea = areaHa.divide(areaMinimaEquipamentoHa).min(1);
        var fatorConfianca = confiancaAmostral.multiply(confiancaArea).max(0).min(1);

        return ee.Feature(null, {
        Equipamento: equipamento,
        OBS_HIST: nObs,
        AREA_HA: areaHa,
        NDVI_MEDIO_HIST: ndviMedioHist,
        NDVI_STD_HIST: ndviStdHist,
        CV_NDVI: cvNdvi,
        ESTABILIDADE: estabilidade,
        PROP_ALTO: propAlto,
        FATOR_CONFIANCA: fatorConfianca
        });
    }));

    var ndviMin = ee.Number(ee.Algorithms.If(
        resumoEmergenciaBase.size().gt(0),
        resumoEmergenciaBase.aggregate_min('NDVI_MEDIO_HIST'),
        0
    ));
    var ndviMax = ee.Number(ee.Algorithms.If(
        resumoEmergenciaBase.size().gt(0),
        resumoEmergenciaBase.aggregate_max('NDVI_MEDIO_HIST'),
        1
    ));

    var resumoEmergenciaPontuado = resumoEmergenciaBase.map(function(f) {
        var ndviNorm = normalizarMinMax(f.get('NDVI_MEDIO_HIST'), ndviMin, ndviMax);
        var estabilidade = ee.Number(f.get('ESTABILIDADE'));
        var propAlto = ee.Number(f.get('PROP_ALTO'));
        var fatorConfianca = ee.Number(f.get('FATOR_CONFIANCA'));

        // Score de qualidade da emergência (0 a 100)
        // 50% Vigor médio (NDVI), 30% Estabilidade temporal, 20% Frequência de classe alta
        var scoreBase = ndviNorm.multiply(0.5)
        .add(estabilidade.multiply(0.3))
        .add(propAlto.multiply(0.2));

        var scoreFinal = scoreBase.multiply(fatorConfianca).multiply(100);

        var classeEmergencia = ee.Algorithms.If(
        scoreFinal.gte(80), 'Excelente',
        ee.Algorithms.If(
            scoreFinal.gte(65), 'Boa',
            ee.Algorithms.If(
            scoreFinal.gte(50), 'Regular',
            ee.Algorithms.If(scoreFinal.gte(35), 'Baixa', 'Crítica')
            )
        )
        );

        return f.set({
        NDVI_NORM: ndviNorm,
        SCORE_BASE: scoreBase,
        SCORE_EMERGENCIA: scoreFinal,
        CLASSE_EMERGENCIA: classeEmergencia
        });
    });

    var resumoEmergencia = resumoEmergenciaPontuado.sort('SCORE_EMERGENCIA', false);

    Map.layers().reset();
    Map.centerObject(geometriaTalhao, 14);
    Map.addLayer(limiteTalhao.style({color: '000000', fillColor: '00000000', width: 2}), {}, 'Limite Talhão ' + talhaoSelecionado, true);
    Map.addLayer(imagemSelecionada, visRgb, 'RGB (imagem selecionada) - Talhão ' + talhaoSelecionado, true);
    Map.addLayer(imgTalhao.select('NDVI'), visNdvi, 'NDVI (imagem selecionada) - Talhão ' + talhaoSelecionado, false);
    Map.addLayer(imgTalhao.select('NDRE'), visNdre, 'NDRE (imagem selecionada) - Talhão ' + talhaoSelecionado, false);
    Map.addLayer(imgTalhao.select('MSAVI'), visMsavi, 'MSAVI (imagem selecionada) - Talhão ' + talhaoSelecionado, false);

    Map.addLayer(
        areasTalhao.style({
        color: 'ffffff',
        fillColor: '00000000',
        width: 1
        }),
        {},
        'Máquinas (todas) - Talhão ' + talhaoSelecionado,
        true
    );

    var maquinasTalhao = areasTalhao.aggregate_array('Equipamento').distinct().sort();

    maquinasTalhao.evaluate(function(listaEquipamentos) {
        listaEquipamentos.forEach(function(equip, i) {
        var cor = coresMaquinas[i % coresMaquinas.length];
        var areaMaquina = areasTalhao.filter(ee.Filter.eq('Equipamento', equip));

        Map.addLayer(
            areaMaquina.style({
            color: cor,
            fillColor: cor + '22',
            width: 2
            }),
            {},
            'Máquina ' + equip + ' - Talhão ' + talhaoSelecionado,
            true
        );
        });
    });

    var estatisticas = imgTalhao.select('NDVI').reduceRegions({
        collection: areasTalhao,
        reducer: ee.Reducer.mean(),
        scale: 10
    }).map(function(f) {
        var ndviMedio = ee.Number(f.get('mean'));
        return f.set({
        NDVI_MEDIO: ndviMedio,
        NDVI_CLASSE: classificarNdvi(ndviMedio),
        NDVI_CLASSE_CODIGO: codigoClasseNdvi(ndviMedio)
        });
    });

    var estatisticasSeguras = ee.FeatureCollection(ee.Algorithms.If(
        estatisticas.size().gt(0),
        estatisticas,
        ee.FeatureCollection([
        ee.Feature(null, {
            Equipamento: 'SEM_DADO',
            NDVI_MEDIO: 0,
            NDVI_CLASSE: 'Sem dados',
            NDVI_CLASSE_CODIGO: 0
        })
        ])
    ));

    var historicoSeguro = ee.FeatureCollection(ee.Algorithms.If(
        historicoEmergencia.size().gt(0),
        historicoEmergencia,
        ee.FeatureCollection([
        ee.Feature(null, {
            Equipamento: 'SEM_DADO',
            DATA_IMAGEM: ee.Image(resultadoImagem.get('imagem')).date().format('YYYY-MM-dd'),
            NDVI_MEDIO: 0,
            NDVI_CLASSE_CODIGO: 0
        })
        ])
    ));

    var graficoNdvi = ui.Chart.feature.byFeature({
        features: estatisticasSeguras,
        xProperty: 'Equipamento',
        yProperties: ['NDVI_MEDIO']
    })
        .setChartType('ColumnChart')
        .setOptions({
        title: 'NDVI médio por máquina (Talhão ' + talhaoSelecionado + ')',
        hAxis: {title: 'Máquina'},
        vAxis: {title: 'NDVI médio', viewWindow: {min: 0, max: 1}},
        legend: {position: 'none'},
        colors: ['#1f77b4']
        });

    var graficoClasse = ui.Chart.feature.byFeature({
        features: estatisticasSeguras,
        xProperty: 'Equipamento',
        yProperties: ['NDVI_CLASSE_CODIGO']
    })
        .setChartType('ColumnChart')
        .setOptions({
        title: 'Classificação NDVI por máquina (Talhão ' + talhaoSelecionado + ')',
        hAxis: {title: 'Máquina'},
        vAxis: {
            title: 'Classe NDVI',
            ticks: [
            {v: 1, f: 'Muito Baixo'},
            {v: 2, f: 'Baixo'},
            {v: 3, f: 'Médio'},
            {v: 4, f: 'Alto'},
            {v: 5, f: 'Muito Alto'}
            ],
            viewWindow: {min: 1, max: 5}
        },
        legend: {position: 'none'},
        colors: ['#2ca02c']
        });

    var graficoHistoricoNdvi = ui.Chart.feature.groups({
        features: historicoSeguro,
        xProperty: 'DATA_IMAGEM',
        yProperty: 'NDVI_MEDIO',
        seriesProperty: 'Equipamento'
    })
        .setChartType('LineChart')
        .setOptions({
        title: 'Histórico NDVI por máquina (Talhão ' + talhaoSelecionado + ')',
        hAxis: {title: 'Data da imagem'},
        vAxis: {title: 'NDVI médio', viewWindow: {min: 0, max: 1}},
        pointSize: 4,
        lineWidth: 2
        });

    var graficoHistoricoClasse = ui.Chart.feature.groups({
        features: historicoSeguro,
        xProperty: 'DATA_IMAGEM',
        yProperty: 'NDVI_CLASSE_CODIGO',
        seriesProperty: 'Equipamento'
    })
        .setChartType('LineChart')
        .setOptions({
        title: 'Histórico da classe NDVI por máquina (Talhão ' + talhaoSelecionado + ')',
        hAxis: {title: 'Data da imagem'},
        vAxis: {
            title: 'Classe NDVI',
            ticks: [
            {v: 1, f: 'Muito Baixo'},
            {v: 2, f: 'Baixo'},
            {v: 3, f: 'Médio'},
            {v: 4, f: 'Alto'},
            {v: 5, f: 'Muito Alto'}
            ],
            viewWindow: {min: 1, max: 5}
        },
        pointSize: 4,
        lineWidth: 2
        });

    var graficoScoreEmergencia = ui.Chart.feature.byFeature({
        features: resumoEmergencia,
        xProperty: 'Equipamento',
        yProperties: ['SCORE_EMERGENCIA']
    })
        .setChartType('ColumnChart')
        .setOptions({
        title: 'Score de emergência por máquina (Talhão ' + talhaoSelecionado + ')',
        hAxis: {title: 'Máquina'},
        vAxis: {title: 'Score (0-100)', viewWindow: {min: 0, max: 100}},
        legend: {position: 'none'},
        colors: ['#7b1fa2']
        });

    painelGraficos.clear();
    painelGraficos.add(graficoNdvi);
    painelGraficos.add(graficoClasse);
    painelGraficos.add(graficoHistoricoNdvi);
    painelGraficos.add(graficoHistoricoClasse);
    painelGraficos.add(graficoScoreEmergencia);

    metadadosImagem.evaluate(function(meta) {
        var textoInfo =
        'Plantio: ' + meta.dataPlantio +
        ' | Fonte: ' + meta.fonteDataPlantio +
        ' | Registros plantio: ' + meta.qtdRegistrosPlantio +
        ' | Intervalo operações: ' + meta.dataPlantioMin + ' a ' + meta.dataPlantioMax +
        ' | Período manual: ' + (meta.usaPeriodoManual ? (meta.dataInicialManual + ' a ' + meta.dataFinalManual) : 'não') +
        ' | Janela +' + diasAposPlantio + ' dias: ' + meta.inicioJanela + ' a ' + meta.fimJanela +
        ' | Imagens válidas: ' + meta.quantidadeImagens +
        ' | Imagem usada: ' + meta.dataImagemSelecionada +
        ' (nuvem: ' + Number(meta.nuvemImagemSelecionada || 0).toFixed(1) + '%)';
        infoImagem.setValue(textoInfo);
    });

    print('Classificação NDVI por máquina - Talhão ' + talhaoSelecionado, estatisticas.select(['Equipamento', 'NDVI_MEDIO', 'NDVI_CLASSE']));
    print('Metadados da imagem selecionada - Talhão ' + talhaoSelecionado, metadadosImagem);
    print('Histórico de emergência NDVI por máquina - Talhão ' + talhaoSelecionado, historicoEmergencia);
    print('Ranking de emergência por máquina - Talhão ' + talhaoSelecionado, resumoEmergencia.select([
        'Equipamento',
        'AREA_HA',
        'OBS_HIST',
        'NDVI_MEDIO_HIST',
        'NDVI_STD_HIST',
        'ESTABILIDADE',
        'PROP_ALTO',
        'FATOR_CONFIANCA',
        'SCORE_EMERGENCIA',
        'CLASSE_EMERGENCIA'
    ]));
    print('Metodologia do score de emergência', ee.Dictionary({
        formula: 'Score = (0.5*NDVI_NORM + 0.3*ESTABILIDADE + 0.2*PROP_ALTO) * FATOR_CONFIANCA * 100',
        ndviNorm: 'NDVI médio histórico normalizado no conjunto de máquinas do talhão',
        estabilidade: '1 - CV(NDVI), limitado entre 0 e 1',
        propAlto: 'proporção de observações em classe NDVI >= Alto (código >= 4)',
        fatorConfianca: 'min(OBS/4,1) * min(AREA_HA/areaMinimaEquipamentoHa,1)'
    }));
    print('Resumo da janela histórica - Talhão ' + talhaoSelecionado, ee.Dictionary({
        inicioHistorico: resultadoHistorico.get('inicioHistorico'),
        fimHistorico: resultadoHistorico.get('fimHistorico'),
        quantidadeImagensHistorico: resultadoHistorico.get('quantidadeImagensHistorico')
    }));
    };

    // ==============================================
    // INICIALIZAÇÃO
    // ==============================================

    talhoes.evaluate(function(listaTalhoes) {
    seletorTalhao.items().reset(listaTalhoes);

    if (listaTalhoes.length > 0) {
        seletorTalhao.setValue(listaTalhoes[0], false);
        infoImagem.setValue('Selecione talhão/datas e clique em Executar análise.');
    }
    });

    botaoExecutar.onClick(function() {
    var talhaoSelecionado = seletorTalhao.getValue();
    if (!talhaoSelecionado) {
        infoImagem.setValue('Selecione um talhão e clique em Executar análise.');
        return;
    }
    atualizarTalhao(talhaoSelecionado);
    });

    Map.centerObject(limitesTalhoes, 12);
