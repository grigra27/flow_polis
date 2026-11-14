/** Версии КВ: дата нового полиса / закреплённая ставка существующего. */
(() => {
    'use strict';
    document.addEventListener('DOMContentLoaded', () => {
        const context = document.getElementById('commission-context');
        if (!context) return;
        const insurer = document.getElementById('id_insurer');
        const kind = document.getElementById('id_insurance_type');
        const start = document.getElementById('id_start_date');
        const policy = document.getElementById('id_policy');
        const selectedRate = document.getElementById('id_commission_rate');
        const separate = !insurer && Boolean(policy);
        const state = new WeakMap();
        let currentRate = null;
        let requestVersion = 0;
        const form = context.closest('form') || document.querySelector('form[method="post"]');

        function rows() {
            if (separate) return form ? [form] : [];
            return [...document.querySelectorAll('.payment-inline .payment-row:not(.empty-form), .dynamic-payment_schedule:not(.empty-form)')];
        }
        function field(row, name) {
            return row.querySelector(separate ? '#id_' + name : '[name$="-' + name + '"]');
        }
        function scaled(value) {
            const match = String(value).replace(',', '.').match(/^(\d+)(?:\.(\d{0,2}))?$/);
            return match ? BigInt(match[1]) * 100n + BigInt((match[2] || '').padEnd(2, '0')) : null;
        }
        function amountText(cents) {
            return String(cents / 100n) + '.' + String(cents % 100n).padStart(2, '0');
        }
        function rateFor(row) {
            const data = state.get(row);
            return data && data.saved ? data.base : currentRate;
        }
        function calculate(row) {
            const input = field(row, 'kv_rub');
            const amount = scaled(field(row, 'amount').value);
            const rate = rateFor(row);
            const percent = rate === null ? null : scaled(rate);
            if (amount === null || percent === null) return false;
            input.value = amountText((amount * percent + 5000n) / 10000n);
            return true;
        }
        function refreshRows() {
            rows().forEach(row => {
                prepare(row);
                const data = state.get(row);
                if (!data) return;
                const rate = rateFor(row);
                data.label.textContent = rate === null ? 'Базовая ставка не задана' : 'Базовая ' + rate + '%';
                data.button.disabled = rate === null;
                if (!data.saved && !data.manual) {
                    if (!calculate(row)) field(row, 'kv_rub').value = '';
                }
            });
        }
        function prepare(row) {
            if (state.has(row)) return;
            const input = field(row, 'kv_rub');
            const amount = field(row, 'amount');
            if (!input || !amount) return;
            const saved = input.dataset.savedPayment === 'true';
            const label = document.createElement('small');
            label.className = 'commission-row-rate';
            const button = document.createElement('button');
            button.type = 'button'; button.className = 'commission-recalculate'; button.textContent = 'По ставке';
            button.setAttribute('aria-label', 'Пересчитать комиссию этого взноса по базовой ставке');
            input.after(label, button);
            const data = {saved, base: input.dataset.basePercent || null, manual: input.value !== '', label, button};
            state.set(row, data);
            input.addEventListener('input', () => { data.manual = input.value !== ''; });
            amount.addEventListener('input', () => { if (!data.saved && !data.manual) calculate(row); });
            button.addEventListener('click', () => { if (calculate(row)) data.manual = false; });
        }
        function isoDate(value) {
            if (/^\d{4}-\d{2}-\d{2}$/.test(value)) return value;
            const match = value.match(/^(\d{1,2})\.(\d{1,2})\.(\d{4})$/);
            return match ? match[3] + '-' + match[2].padStart(2, '0') + '-' + match[1].padStart(2, '0') : '';
        }
        async function update() {
            const version = ++requestVersion;
            currentRate = null;
            if (selectedRate) {
                const option = selectedRate.selectedOptions[0];
                currentRate = option && option.dataset.percent || null;
                context.textContent = currentRate === null ? 'Базовая ставка новых взносов не задана.' : 'Базовая ставка новых взносов: ' + currentRate + '%. Сохранённые платежи не пересчитываются.';
                refreshRows();
                return;
            }
            const params = new URLSearchParams();
            const policyId = context.dataset.policyId || (policy && policy.value);
            if (policyId) params.set('policy_id', policyId);
            else if (insurer && kind && start && insurer.value && kind.value && isoDate(start.value)) {
                params.set('insurer_id', insurer.value); params.set('insurance_type_id', kind.value); params.set('start_date', isoDate(start.value));
            } else {
                context.textContent = separate ? 'Выберите полис для подбора ставки.' : 'Укажите страховщика, вид и дату начала страхования для подбора КВ.';
                refreshRows(); return;
            }
            context.textContent = 'Подбор базовой ставки…';
            refreshRows();
            try {
                const response = await fetch('/insurers/api/commission-rate/?' + params, {credentials: 'same-origin'});
                const result = await response.json();
                if (version !== requestVersion) return;
                if (response.ok && result.success) {
                    currentRate = result.kv_percent;
                    context.textContent = result.display_name + ' · ' + result.source;
                } else context.textContent = result.error || 'Не удалось получить ставку. Проверьте КВ.';
            } catch (_) {
                if (version !== requestVersion) return;
                context.textContent = 'Не удалось получить ставку. Проверьте КВ перед сохранением.';
            }
            refreshRows();
        }
        [insurer, kind, start, policy, selectedRate].filter(Boolean).forEach(input => {
            input.addEventListener('change', update);
            if (input === start) input.addEventListener('input', update);
            // Django Select2 сообщает об изменениях через jQuery.
            if (input.tagName === 'SELECT' && window.django && django.jQuery) django.jQuery(input).on('change.commission', update);
        });
        document.addEventListener('formset:added', event => {
            if (event.detail && event.detail.formsetName === 'payment_schedule') { prepare(event.target); refreshRows(); }
        });
        if (form) form.addEventListener('submit', () => {
            // Окончательный автоматический расчёт выполняет сервер. Ручные суммы и старые строки сохраняются.
            rows().forEach(row => { const data = state.get(row); if (data && !data.saved && !data.manual) field(row, 'kv_rub').value = ''; });
        });
        refreshRows(); update();
    });
})();
