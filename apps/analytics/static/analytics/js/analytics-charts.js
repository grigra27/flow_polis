/**
 * Analytics Charts Manager
 * Manages chart creation and updates for analytics pages
 */

class AnalyticsCharts {
    constructor() {
        this.charts = new Map();
        this.chartContainers = new Map();
    }

    /**
     * Initialize charts on page load
     */
    init() {
        // Find all chart containers and initialize them
        document.querySelectorAll('[data-chart-type]').forEach(container => {
            this.initializeChart(container);
        });

        // Set up filter change handlers
        this.setupFilterHandlers();
    }

    /**
     * Initialize a single chart
     * @param {HTMLElement} container - Chart container element
     */
    initializeChart(container) {
        const chartType = container.dataset.chartType;
        const chartId = container.id;
        const canvas = container.querySelector('canvas');

        if (!canvas) {
            console.error(`Canvas not found in chart container ${chartId}`);
            return;
        }

        // Store container reference
        this.chartContainers.set(chartId, container);

        // Get chart data from data attribute or global variable
        let chartData;
        if (container.dataset.chartData) {
            try {
                chartData = JSON.parse(container.dataset.chartData);
            } catch (e) {
                console.error(`Invalid chart data for ${chartId}:`, e);
                return;
            }
        } else if (window.chartData && window.chartData[chartId]) {
            chartData = window.chartData[chartId];
        } else {
            console.warn(`No chart data found for ${chartId}`);
            return;
        }

        // Create chart based on type
        let chart;
        try {
            switch (chartType) {
                case 'pie':
                    chart = ChartUtils.createPieChart(canvas, chartData);
                    break;
                case 'bar':
                    chart = ChartUtils.createBarChart(canvas, chartData);
                    break;
                case 'line':
                    chart = ChartUtils.createLineChart(canvas, chartData);
                    break;
                case 'timeseries':
                    chart = ChartUtils.createTimeSeriesChart(canvas, chartData);
                    break;
                default:
                    console.error(`Unknown chart type: ${chartType}`);
                    return;
            }

            // Store chart reference
            this.charts.set(chartId, chart);

            // Add drill-down functionality if specified
            if (container.dataset.drillDown === 'true') {
                this.addDrillDownHandler(chartId, chart);
            }

            // Add export functionality if specified
            if (container.dataset.exportable === 'true') {
                this.addExportButton(container, chart);
            }

        } catch (error) {
            console.error(`Error creating chart ${chartId}:`, error);
        }
    }

    /**
     * Update chart with new data
     * @param {string} chartId - Chart ID
     * @param {Object} newData - New chart data
     */
    updateChart(chartId, newData) {
        const chart = this.charts.get(chartId);
        if (chart) {
            ChartUtils.updateChart(chart, newData);
        }
    }

    /**
     * Destroy chart
     * @param {string} chartId - Chart ID
     */
    destroyChart(chartId) {
        const chart = this.charts.get(chartId);
        if (chart) {
            ChartUtils.destroyChart(chart);
            this.charts.delete(chartId);
        }
    }

    /**
     * Refresh all charts with new data
     * @param {Object} allChartData - Object containing data for all charts
     */
    refreshAllCharts(allChartData) {
        for (const [chartId, chartData] of Object.entries(allChartData)) {
            this.updateChart(chartId, chartData);
        }
    }

    /**
     * Show loading state for all charts
     */
    showAllLoading() {
        this.chartContainers.forEach((container, chartId) => {
            ChartUtils.showLoading(container);
        });
    }

    /**
     * Hide loading state for all charts
     */
    hideAllLoading() {
        this.chartContainers.forEach((container, chartId) => {
            ChartUtils.hideLoading(container);
        });
    }

    /**
     * Set up filter change handlers
     */
    setupFilterHandlers() {
        // Handle filter form submission
        const filterForm = document.getElementById('analytics-filter-form');
        if (filterForm) {
            filterForm.addEventListener('submit', (e) => {
                e.preventDefault();
                this.handleFilterChange();
            });
        }

        // Handle individual filter changes
        document.querySelectorAll('.analytics-filter').forEach(filter => {
            filter.addEventListener('change', () => {
                // Debounce filter changes
                clearTimeout(this.filterTimeout);
                this.filterTimeout = setTimeout(() => {
                    this.handleFilterChange();
                }, 500);
            });
        });

        // Handle filter reset
        const resetButton = document.getElementById('reset-filters');
        if (resetButton) {
            resetButton.addEventListener('click', () => {
                this.resetFilters();
            });
        }
    }

    /**
     * Handle filter changes
     */
    async handleFilterChange() {
        try {
            this.showAllLoading();

            // Get current page URL for AJAX request
            const currentUrl = window.location.pathname;

            // Get form data
            const filterForm = document.getElementById('analytics-filter-form');
            const formData = new FormData(filterForm);

            // Make AJAX request
            const response = await fetch(currentUrl, {
                method: 'POST',
                body: formData,
                headers: {
                    'X-CSRFToken': document.querySelector('[name=csrfmiddlewaretoken]').value,
                    'X-Requested-With': 'XMLHttpRequest'
                }
            });

            if (!response.ok) {
                throw new Error(`HTTP error! status: ${response.status}`);
            }

            const data = await response.json();

            if (data.success) {
                // Update charts with new data
                if (data.charts) {
                    this.refreshAllCharts(data.charts);
                }

                // Update metrics display
                if (data.metrics) {
                    this.updateMetricsDisplay(data.metrics);
                }

                // Show success message
                this.showMessage('Фильтры применены успешно', 'success');
            } else {
                throw new Error(data.error || 'Неизвестная ошибка');
            }

        } catch (error) {
            console.error('Error applying filters:', error);
            this.showMessage('Ошибка при применении фильтров: ' + error.message, 'error');
        } finally {
            this.hideAllLoading();
        }
    }

    /**
     * Reset all filters
     */
    resetFilters() {
        const filterForm = document.getElementById('analytics-filter-form');
        if (filterForm) {
            filterForm.reset();
            this.handleFilterChange();
        }
    }

    /**
     * Update metrics display
     * @param {Object} metrics - New metrics data
     */
    updateMetricsDisplay(metrics) {
        for (const [key, value] of Object.entries(metrics)) {
            const element = document.querySelector(`[data-metric="${key}"]`);
            if (element) {
                // Format the value based on its type
                let formattedValue = value;
                if (typeof value === 'number' || !isNaN(value)) {
                    if (key.includes('rate') || key.includes('percentage')) {
                        formattedValue = parseFloat(value).toFixed(2) + '%';
                    } else if (key.includes('amount') || key.includes('volume') || key.includes('sum')) {
                        formattedValue = ChartUtils.formatCurrency(value);
                    } else {
                        formattedValue = ChartUtils.formatNumber(value);
                    }
                }
                element.textContent = formattedValue;
            }
        }
    }

    /**
     * Add drill-down handler to chart
     * @param {string} chartId - Chart ID
     * @param {Chart} chart - Chart.js instance
     */
    addDrillDownHandler(chartId, chart) {
        ChartUtils.addDrillDown(chart, (data) => {
            // Emit custom event for drill-down
            const event = new CustomEvent('chartDrillDown', {
                detail: {
                    chartId: chartId,
                    data: data
                }
            });
            document.dispatchEvent(event);
        });
    }

    /**
     * Add export button to chart container
     * @param {HTMLElement} container - Chart container
     * @param {Chart} chart - Chart.js instance
     */
    addExportButton(container, chart) {
        const exportButton = document.createElement('button');
        exportButton.className = 'btn btn-sm btn-outline-secondary chart-export-btn';
        exportButton.innerHTML = '<i class="fas fa-download"></i>';
        exportButton.title = 'Экспорт графика';
        exportButton.style.position = 'absolute';
        exportButton.style.top = '10px';
        exportButton.style.right = '10px';
        exportButton.style.zIndex = '1000';

        exportButton.addEventListener('click', () => {
            const chartTitle = container.dataset.chartTitle || 'chart';
            const filename = `${chartTitle.replace(/\s+/g, '_').toLowerCase()}.png`;
            ChartUtils.exportChart(chart, filename);
        });

        container.style.position = 'relative';
        container.appendChild(exportButton);
    }

    /**
     * Show message to user
     * @param {string} message - Message text
     * @param {string} type - Message type ('success', 'error', 'warning', 'info')
     */
    showMessage(message, type = 'info') {
        // Create toast notification
        const toast = document.createElement('div');
        toast.className = `toast align-items-center text-white bg-${type === 'error' ? 'danger' : type} border-0`;
        toast.setAttribute('role', 'alert');
        toast.setAttribute('aria-live', 'assertive');
        toast.setAttribute('aria-atomic', 'true');

        toast.innerHTML = `
            <div class="d-flex">
                <div class="toast-body">
                    ${message}
                </div>
                <button type="button" class="btn-close btn-close-white me-2 m-auto" data-bs-dismiss="toast"></button>
            </div>
        `;

        // Add to toast container or create one
        let toastContainer = document.querySelector('.toast-container');
        if (!toastContainer) {
            toastContainer = document.createElement('div');
            toastContainer.className = 'toast-container position-fixed top-0 end-0 p-3';
            toastContainer.style.zIndex = '1055';
            document.body.appendChild(toastContainer);
        }

        toastContainer.appendChild(toast);

        // Initialize and show toast
        const bsToast = new bootstrap.Toast(toast);
        bsToast.show();

        // Remove toast element after it's hidden
        toast.addEventListener('hidden.bs.toast', () => {
            toast.remove();
        });
    }

    /**
     * Resize all charts (useful for responsive layouts)
     */
    resizeAllCharts() {
        this.charts.forEach((chart, chartId) => {
            chart.resize();
        });
    }
}

// Initialize analytics charts when DOM is loaded
document.addEventListener('DOMContentLoaded', () => {
    window.analyticsCharts = new AnalyticsCharts();
    window.analyticsCharts.init();
});

// Handle window resize
window.addEventListener('resize', () => {
    if (window.analyticsCharts) {
        window.analyticsCharts.resizeAllCharts();
    }
});
