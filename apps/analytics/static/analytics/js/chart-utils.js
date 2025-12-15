/**
 * Chart utilities for analytics visualization
 * Provides common functionality for Chart.js integration
 */

class ChartUtils {
    /**
     * Default Chart.js configuration options
     */
    static getDefaultOptions() {
        return {
            responsive: true,
            maintainAspectRatio: false,
            plugins: {
                legend: {
                    position: 'top',
                },
                tooltip: {
                    mode: 'index',
                    intersect: false,
                    callbacks: {
                        label: function(context) {
                            let label = context.dataset.label || '';
                            if (label) {
                                label += ': ';
                            }

                            // Format numbers with thousand separators
                            if (typeof context.parsed.y === 'number') {
                                label += new Intl.NumberFormat('ru-RU').format(context.parsed.y);
                            } else {
                                label += context.parsed.y;
                            }

                            return label;
                        }
                    }
                }
            },
            scales: {
                y: {
                    beginAtZero: true,
                    ticks: {
                        callback: function(value) {
                            return new Intl.NumberFormat('ru-RU').format(value);
                        }
                    }
                }
            }
        };
    }

    /**
     * Create a pie chart
     * @param {HTMLCanvasElement} canvas - Canvas element
     * @param {Object} data - Chart data
     * @param {Object} options - Additional options
     * @returns {Chart} Chart.js instance
     */
    static createPieChart(canvas, data, options = {}) {
        const defaultOptions = {
            type: 'pie',
            data: {
                labels: data.labels,
                datasets: [{
                    data: data.data,
                    backgroundColor: data.colors,
                    borderWidth: 1
                }]
            },
            options: {
                responsive: true,
                maintainAspectRatio: true,
                aspectRatio: 1.2,
                plugins: {
                    legend: {
                        position: 'bottom',
                        labels: {
                            boxWidth: 12,
                            padding: 10
                        }
                    },
                    tooltip: {
                        callbacks: {
                            label: function(context) {
                                const label = context.label || '';
                                const value = context.parsed;
                                const total = context.dataset.data.reduce((a, b) => a + b, 0);
                                const percentage = ((value / total) * 100).toFixed(1);

                                return `${label}: ${new Intl.NumberFormat('ru-RU').format(value)} (${percentage}%)`;
                            }
                        }
                    }
                },
                ...options
            }
        };

        return new Chart(canvas, defaultOptions);
    }

    /**
     * Create a bar chart
     * @param {HTMLCanvasElement} canvas - Canvas element
     * @param {Object} data - Chart data
     * @param {Object} options - Additional options
     * @returns {Chart} Chart.js instance
     */
    static createBarChart(canvas, data, options = {}) {
        const defaultOptions = {
            type: 'bar',
            data: {
                labels: data.labels,
                datasets: data.datasets
            },
            options: {
                responsive: true,
                maintainAspectRatio: true,
                aspectRatio: 1.5,
                plugins: {
                    legend: {
                        position: 'top',
                    },
                    tooltip: {
                        mode: 'index',
                        intersect: false,
                        callbacks: {
                            label: function(context) {
                                let label = context.dataset.label || '';
                                if (label) {
                                    label += ': ';
                                }

                                // Format currency values
                                if (typeof context.parsed.y === 'number') {
                                    if (label.toLowerCase().includes('премий') ||
                                        label.toLowerCase().includes('доход') ||
                                        label.toLowerCase().includes('сумма') ||
                                        label.toLowerCase().includes('руб')) {
                                        label += new Intl.NumberFormat('ru-RU').format(context.parsed.y) + ' ₽';
                                    } else {
                                        label += new Intl.NumberFormat('ru-RU').format(context.parsed.y);
                                    }
                                } else {
                                    label += context.parsed.y;
                                }

                                return label;
                            }
                        }
                    }
                },
                scales: {
                    y: {
                        beginAtZero: true,
                        ticks: {
                            callback: function(value) {
                                // Check if this is a currency axis by looking at the chart title or dataset labels
                                const chart = this.chart;
                                const isCurrency = chart.data.datasets.some(dataset =>
                                    dataset.label && (
                                        dataset.label.toLowerCase().includes('премий') ||
                                        dataset.label.toLowerCase().includes('доход') ||
                                        dataset.label.toLowerCase().includes('сумма') ||
                                        dataset.label.toLowerCase().includes('руб')
                                    )
                                );

                                if (isCurrency) {
                                    return new Intl.NumberFormat('ru-RU').format(value) + ' ₽';
                                } else {
                                    return new Intl.NumberFormat('ru-RU').format(value);
                                }
                            }
                        }
                    }
                },
                ...options
            }
        };

        return new Chart(canvas, defaultOptions);
    }

    /**
     * Create a line chart
     * @param {HTMLCanvasElement} canvas - Canvas element
     * @param {Object} data - Chart data
     * @param {Object} options - Additional options
     * @returns {Chart} Chart.js instance
     */
    static createLineChart(canvas, data, options = {}) {
        const defaultOptions = {
            type: 'line',
            data: {
                labels: data.labels,
                datasets: data.datasets
            },
            options: {
                ...this.getDefaultOptions(),
                interaction: {
                    mode: 'index',
                    intersect: false,
                },
                ...options
            }
        };

        return new Chart(canvas, defaultOptions);
    }

    /**
     * Create a time series chart
     * @param {HTMLCanvasElement} canvas - Canvas element
     * @param {Object} data - Chart data
     * @param {Object} options - Additional options
     * @returns {Chart} Chart.js instance
     */
    static createTimeSeriesChart(canvas, data, options = {}) {
        const defaultOptions = {
            type: 'line',
            data: {
                datasets: data.datasets
            },
            options: {
                responsive: true,
                maintainAspectRatio: false,
                plugins: {
                    legend: {
                        position: 'top',
                    },
                    tooltip: {
                        mode: 'index',
                        intersect: false,
                        callbacks: {
                            label: function(context) {
                                let label = context.dataset.label || '';
                                if (label) {
                                    label += ': ';
                                }
                                label += new Intl.NumberFormat('ru-RU').format(context.parsed.y);
                                return label;
                            }
                        }
                    }
                },
                scales: {
                    x: {
                        type: 'time',
                        time: {
                            unit: data.time_unit || 'month',
                            displayFormats: {
                                month: 'MMM YYYY',
                                quarter: 'Q YYYY',
                                year: 'YYYY'
                            }
                        },
                        title: {
                            display: true,
                            text: data.x_axis_label || 'Время'
                        }
                    },
                    y: {
                        beginAtZero: true,
                        title: {
                            display: true,
                            text: data.y_axis_label || 'Значения'
                        },
                        ticks: {
                            callback: function(value) {
                                return new Intl.NumberFormat('ru-RU').format(value);
                            }
                        }
                    }
                },
                interaction: {
                    mode: 'index',
                    intersect: false,
                },
                ...options
            }
        };

        return new Chart(canvas, defaultOptions);
    }

    /**
     * Update chart data
     * @param {Chart} chart - Chart.js instance
     * @param {Object} newData - New data
     */
    static updateChart(chart, newData) {
        if (chart.data.labels) {
            chart.data.labels = newData.labels;
        }

        if (newData.datasets) {
            chart.data.datasets = newData.datasets;
        } else if (newData.data) {
            chart.data.datasets[0].data = newData.data;
        }

        chart.update();
    }

    /**
     * Destroy chart safely
     * @param {Chart} chart - Chart.js instance
     */
    static destroyChart(chart) {
        if (chart && typeof chart.destroy === 'function') {
            chart.destroy();
        }
    }

    /**
     * Format number for display
     * @param {number} value - Number to format
     * @param {string} locale - Locale for formatting
     * @returns {string} Formatted number
     */
    static formatNumber(value, locale = 'ru-RU') {
        return new Intl.NumberFormat(locale).format(value);
    }

    /**
     * Format currency for display
     * @param {number} value - Number to format
     * @param {string} currency - Currency code
     * @param {string} locale - Locale for formatting
     * @returns {string} Formatted currency
     */
    static formatCurrency(value, currency = 'RUB', locale = 'ru-RU') {
        return new Intl.NumberFormat(locale, {
            style: 'currency',
            currency: currency
        }).format(value);
    }

    /**
     * Get responsive chart height based on container
     * @param {HTMLElement} container - Container element
     * @returns {number} Calculated height
     */
    static getResponsiveHeight(container) {
        const containerWidth = container.offsetWidth;

        // Calculate height based on aspect ratio
        if (containerWidth < 576) {
            return Math.max(250, containerWidth * 0.8); // Mobile
        } else if (containerWidth < 768) {
            return Math.max(300, containerWidth * 0.6); // Tablet
        } else {
            return Math.max(350, containerWidth * 0.4); // Desktop
        }
    }

    /**
     * Add drill-down functionality to chart
     * @param {Chart} chart - Chart.js instance
     * @param {Function} callback - Callback function for drill-down
     */
    static addDrillDown(chart, callback) {
        chart.canvas.addEventListener('click', (event) => {
            const points = chart.getElementsAtEventForMode(event, 'nearest', { intersect: true }, true);

            if (points.length) {
                const firstPoint = points[0];
                const label = chart.data.labels[firstPoint.index];
                const value = chart.data.datasets[firstPoint.datasetIndex].data[firstPoint.index];

                callback({
                    label: label,
                    value: value,
                    datasetIndex: firstPoint.datasetIndex,
                    index: firstPoint.index
                });
            }
        });
    }

    /**
     * Show loading state on chart container
     * @param {HTMLElement} container - Chart container
     */
    static showLoading(container) {
        const loadingDiv = document.createElement('div');
        loadingDiv.className = 'chart-loading';
        loadingDiv.innerHTML = `
            <div class="d-flex justify-content-center align-items-center h-100">
                <div class="spinner-border text-primary" role="status">
                    <span class="visually-hidden">Загрузка...</span>
                </div>
            </div>
        `;
        loadingDiv.style.position = 'absolute';
        loadingDiv.style.top = '0';
        loadingDiv.style.left = '0';
        loadingDiv.style.width = '100%';
        loadingDiv.style.height = '100%';
        loadingDiv.style.backgroundColor = 'rgba(255, 255, 255, 0.8)';
        loadingDiv.style.zIndex = '1000';

        container.style.position = 'relative';
        container.appendChild(loadingDiv);
    }

    /**
     * Hide loading state on chart container
     * @param {HTMLElement} container - Chart container
     */
    static hideLoading(container) {
        const loadingDiv = container.querySelector('.chart-loading');
        if (loadingDiv) {
            loadingDiv.remove();
        }
    }

    /**
     * Export chart as image
     * @param {Chart} chart - Chart.js instance
     * @param {string} filename - Filename for download
     */
    static exportChart(chart, filename = 'chart.png') {
        const url = chart.toBase64Image();
        const link = document.createElement('a');
        link.download = filename;
        link.href = url;
        link.click();
    }
}

// Make ChartUtils available globally
window.ChartUtils = ChartUtils;
