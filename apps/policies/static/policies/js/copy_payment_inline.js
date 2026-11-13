(() => {
    'use strict';

    function field(row, name) {
        return row.querySelector('[name$="-' + name + '"]');
    }

    function updateSummary(row) {
        const summary = row.querySelector('.payment-summary');
        const note = field(row, 'payment_info');
        if (!summary || !note) return; // Read-only rows already have a server-rendered summary.
        const labels = [];
        if (field(row, 'insurer_date').value) labels.push('Акт');
        if (field(row, 'alliance_paid').checked) labels.push('Альянс');
        if (note.value.trim()) labels.push('Примечание');
        summary.textContent = labels.join(' · ');
    }

    function setExpanded(row, open) {
        const toggle = row.querySelector('.payment-expand');
        const details = row.querySelector('.payment-details');
        details.hidden = !open;
        toggle.setAttribute('aria-expanded', String(open));
        toggle.title = open ? 'Свернуть детали платежа' : 'Раскрыть детали платежа';
        toggle.setAttribute('aria-label', toggle.title);
        updateSummary(row);
    }

    function copyValues(source, target) {
        // A payment copy includes the editable details but never the PK, FK or DELETE field.
        for (const name of ['year_number', 'installment_number', 'due_date', 'insurance_sum',
            'amount', 'commission_rate', 'kv_rub', 'paid_date', 'insurer_date', 'alliance_paid', 'payment_info']) {
            const from = field(source, name);
            const to = field(target, name);
            if (!from || !to) continue;
            if (from.type === 'checkbox') to.checked = from.checked;
            else to.value = from.value;
        }
    }

    function init(group) {
        const prefix = JSON.parse(group.dataset.inlineFormset).options.prefix;
        const toggleAll = group.querySelector('.payment-toggle-all');
        const status = group.querySelector('.payment-copy-status');
        const rows = () => [...group.querySelectorAll('.payment-row:not(.empty-form)')];
        let nextDetailsId = 0;

        function prepare(row) {
            const copy = row.querySelector('.copy-payment-btn');
            if (copy) copy.hidden = false;
            const toggle = row.querySelector('.payment-expand');
            if (toggle) {
                const details = row.querySelector('.payment-details');
                details.id = group.id + '-details-' + nextDetailsId++;
                toggle.setAttribute('aria-controls', details.id);
                toggle.hidden = false;
                setExpanded(row, Boolean(details.querySelector('.errorlist')));
            }
        }

        function refreshControls() {
            const current = rows();
            if (toggleAll) {
                toggleAll.hidden = current.length === 0;
                const allOpen = current.every(row => !row.querySelector('.payment-details').hidden);
                toggleAll.textContent = allOpen ? 'Свернуть все' : 'Раскрыть все';
            }
            const max = document.getElementById('id_' + prefix + '-MAX_NUM_FORMS').value;
            const atLimit = max !== '' && current.length >= Number(max);
            for (const row of current) {
                const copy = row.querySelector('.copy-payment-btn');
                if (copy) copy.disabled = atLimit;
            }
        }

        rows().forEach(prepare);
        refreshControls();
        group.addEventListener('formset:added', event => {
            prepare(event.target);
            refreshControls();
        });
        document.addEventListener('formset:removed', event => {
            if (event.detail.formsetName === prefix) refreshControls();
        });
        group.addEventListener('input', event => {
            if (event.target.closest('.payment-details')) updateSummary(event.target.closest('.payment-row'));
        });
        group.addEventListener('click', event => {
            const button = event.target.closest('button');
            if (!button) return;
            const row = button.closest('.payment-row');
            if (button === toggleAll) {
                const current = rows();
                const open = current.some(item => item.querySelector('.payment-details').hidden);
                current.forEach(item => setExpanded(item, open));
                refreshControls();
            } else if (button.matches('.payment-expand')) {
                setExpanded(row, row.querySelector('.payment-details').hidden);
                refreshControls();
            } else if (button.matches('.copy-payment-btn')) {
                const add = group.querySelector('.add-row a');
                if (!add || !add.getClientRects().length) return;
                // Django creates and indexes this exact form synchronously during the click.
                group.addEventListener('formset:added', added => {
                    const target = added.target;
                    copyValues(row, target);
                    updateSummary(target);
                    const number = field(target, 'installment_number');
                    number.focus();
                    number.select();
                    status.textContent = 'Добавлена копия платежа. Проверьте год и номер взноса.';
                }, {once: true});
                add.click();
            }
        });
    }

    document.addEventListener('DOMContentLoaded', () => {
        document.querySelectorAll('.payment-inline').forEach(init);
    });
})();
