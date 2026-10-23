/* Аналитика 2.0: единые настройки графиков (Chart.js 4). */
(function () {
    const COLORS = {
        series1: '#2a78d6',
        series2: '#eb6834',
        muted: '#5d748d',
        grid: '#eef3f9',
        title: '#17324f',
    };

    const nf0 = new Intl.NumberFormat('ru-RU', {maximumFractionDigits: 0});

    function money(value) {
        return nf0.format(value) + ' ₽';
    }

    function short(value) {
        const abs = Math.abs(value);
        if (abs >= 1e6) return (value / 1e6).toLocaleString('ru-RU', {maximumFractionDigits: 2}) + ' млн';
        if (abs >= 1e3) return nf0.format(value / 1e3) + ' тыс.';
        return nf0.format(value);
    }

    if (window.Chart) {
        Chart.defaults.font.family = getComputedStyle(document.body).fontFamily;
        Chart.defaults.font.size = 12;
        Chart.defaults.color = COLORS.muted;
        Chart.defaults.maintainAspectRatio = false;
        Chart.defaults.plugins.legend.display = false; // легенда — HTML над графиком
        Chart.defaults.plugins.tooltip.backgroundColor = '#17324f';
        Chart.defaults.plugins.tooltip.padding = 10;
        Chart.defaults.plugins.tooltip.cornerRadius = 8;
        Chart.defaults.plugins.tooltip.boxPadding = 4;
        Chart.defaults.interaction = {mode: 'index', intersect: false};
    }

    function axes(kind) {
        return {
            x: {grid: {display: false}, border: {display: false}, ticks: {maxRotation: 0, autoSkipPadding: 8}},
            y: {
                beginAtZero: true,
                grid: {color: COLORS.grid},
                border: {display: false},
                ticks: {
                    maxTicksLimit: 5,
                    precision: 0,
                    callback: (v) => (kind === 'money' ? short(v) : nf0.format(v)),
                },
            },
        };
    }

    function tooltip(kind, extra) {
        return {
            callbacks: {
                label: (c) => ' ' + c.dataset.label + ': ' + (kind === 'money' ? money(c.parsed.y) : nf0.format(c.parsed.y)),
                ...(extra || {}),
            },
        };
    }

    function barDataset(label, data, color, stack) {
        return {
            type: 'bar', label, data, backgroundColor: color, stack,
            borderRadius: 4, borderSkipped: 'start', maxBarThickness: 28,
            categoryPercentage: 0.72, barPercentage: 0.9,
            borderColor: '#ffffff', borderWidth: stack ? {top: 2} : 0,
        };
    }

    function lineDataset(label, data, color) {
        return {
            type: 'line', label, data, borderColor: color, backgroundColor: color,
            borderWidth: 2, pointRadius: 4, pointHoverRadius: 5,
            pointBorderColor: "#ffffff", pointBorderWidth: 2, tension: 0,
        };
    }

    function chart(canvasId, config) {
        const el = document.getElementById(canvasId);
        if (!el || !window.Chart) return null;
        return new Chart(el, config);
    }

    function data(id) {
        const el = document.getElementById(id);
        return el ? JSON.parse(el.textContent) : null;
    }

    window.AX = {COLORS, money, short, axes, tooltip, barDataset, lineDataset, chart, data};
})();
