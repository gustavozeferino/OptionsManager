/**
 * trading_chart.js - Versão Final Reformulada
 * Tema: Vintage | Estilo: Neutro com Volume Interativo
 */

document.addEventListener('DOMContentLoaded', function () {
    const chartDom = document.getElementById('main-chart');

    // Verifica se o container e os dados existem
    if (!chartDom || typeof chartData === 'undefined') {
        console.warn("Container do gráfico ou dados não encontrados.");
        return;
    }

    // Inicializa com o tema Macarons
    const myChart = echarts.init(chartDom, 'vintage');

    // Processamento de Dados
    const categoryData = chartData.ohlc.map(item => item.x);
    const values = chartData.ohlc.map(item => item.y);

    // volumes: [index, valor, sinal] onde sinal 1 = alta, -1 = baixa
    const volumes = chartData.volume.map((item, i) => [
        i,
        item.y,
        values[i][1] > values[i][0] ? 1 : -1
    ]);

    // Paleta de Cores para o Hover (Sincronizada com o Tema Macarons)
    const colors = {
        down: '#d87a80',        // Coral do tema macarons para alta
        up: '#2ec7c9',      // Turquesa do tema macarons para baixa
        volNeutral: 'rgba(182, 162, 222, 0.4)', // Roxo pastel do tema macarons
        axis: '#008acd'
    };

    const option = {
        animation: true,
        tooltip: {
            trigger: 'axis',
            axisPointer: { type: 'cross' },
            backgroundColor: 'rgba(255, 255, 255, 0.9)',
            borderWidth: 1,
            borderColor: '#ccc'
        },
        axisPointer: {
            link: [{ xAxisIndex: 'all' }],
            label: { backgroundColor: '#777' }
        },
        // Grid: Espaço para o Eixo Y na esquerda (80px)
        grid: [
            { left: '80px', right: '40px', height: '63%', top: '10%' },
            { left: '80px', right: '40px', top: '78%', height: '12%' }
        ],
        xAxis: [
            {
                type: 'category',
                data: categoryData,
                boundaryGap: false,
                axisLine: { lineStyle: { color: colors.axis } },
                splitLine: { show: false }
            },
            {
                type: 'category',
                gridIndex: 1,
                data: categoryData,
                boundaryGap: false,
                axisLabel: { show: false },
                axisTick: { show: false }
            }
        ],
        yAxis: [
            {
                scale: true,
                offset: 10,
                axisLabel: {
                    formatter: val => val.toFixed(2),
                    margin: 12
                },
                splitLine: { show: true, lineStyle: { type: 'dashed', color: '#ddd' } }
            },
            {
                scale: true,
                gridIndex: 1,
                splitNumber: 2,
                axisLabel: { show: false },
                axisLine: { show: false },
                axisTick: { show: false },
                splitLine: { show: false }
            }
        ],
        dataZoom: [
            { type: 'inside', xAxisIndex: [0, 1], start: 0, end: 100 },
            { type: 'slider', xAxisIndex: [0, 1], top: '92%', start: 0, end: 100 }
        ],
        series: [
            {
                name: 'Preço',
                type: 'candlestick',
                data: values,
                itemStyle: {
                    color: colors.up,
                    color0: colors.down,
                    borderColor: colors.up,
                    borderColor0: colors.down,
                    opacity: 0.85
                },
                emphasis: {
                    itemStyle: {
                        opacity: 1,
                        shadowBlur: 10,
                        shadowColor: 'rgba(0,0,0,0.2)'
                    }
                }
            },
            {
                name: 'Volume',
                type: 'bar',
                xAxisIndex: 1,
                yAxisIndex: 1,
                data: volumes.map(v => v[1]),
                itemStyle: {
                    color: colors.volNeutral
                },
                // REFORMA DE COR NO VOLUME: Realce ao passar o mouse
                emphasis: {
                    itemStyle: {
                        color: function (params) {
                            const signal = volumes[params.dataIndex][2];
                            return signal === 1 ? colors.up : colors.down;
                        },
                        opacity: 1
                    }
                }
            }
        ]
    };

    myChart.setOption(option);

    // Ajuste de redimensionamento
    window.addEventListener('resize', () => {
        myChart.resize();
    });
});