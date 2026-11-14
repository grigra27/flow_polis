(() => {
    'use strict';
    document.addEventListener('DOMContentLoaded', () => {
        const fields = ['insurer','insurance_type','kv_percent','effective_from'].map(name => document.getElementById('id_' + name));
        const preview = document.getElementById('rate-version-preview');
        if (!preview || fields.some(field => !field)) return;
        let revision = 0;
        async function update() {
            const current = ++revision;
            const [insurer, kind, percent, from] = fields;
            const parts = from.value.match(/^(\d{1,2})\.(\d{1,2})\.(\d{4})$/);
            const iso = parts ? parts[3] + '-' + parts[2].padStart(2,'0') + '-' + parts[1].padStart(2,'0') : from.value;
            preview.textContent = '';
            if (!insurer.value || !kind.value || !percent.value || !/^\d{4}-\d{2}-\d{2}$/.test(iso)) return;
            const previous = new Date(iso + 'T00:00:00Z');
            if (Number.isNaN(previous.getTime())) return;
            previous.setUTCDate(previous.getUTCDate() - 1);
            const params = new URLSearchParams({insurer_id:insurer.value,insurance_type_id:kind.value,start_date:previous.toISOString().slice(0,10)});
            try {
                const response = await fetch('/insurers/api/commission-rate/?' + params, {credentials:'same-origin'});
                const data = await response.json();
                if (current !== revision) return;
                preview.textContent = (data.success ? 'Предыдущая ставка ' + data.kv_percent + '%' : 'Предыдущая ставка не задана') + ' → ' + percent.value + '% с ' + iso.split('-').reverse().join('.') + ' включительно.';
            } catch (_) { if (current === revision) preview.textContent = 'Предпросмотр недоступен. Проверьте дату и процент перед сохранением.'; }
        }
        fields.forEach(field => {
            field.addEventListener('change', update);
            if (field.tagName === 'INPUT') field.addEventListener('input', update);
            if (field.tagName === 'SELECT' && window.django && django.jQuery) django.jQuery(field).on('change.rateVersion', update);
        });
        update();
    });
})();
