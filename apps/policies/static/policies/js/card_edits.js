(() => {
    const card = document.querySelector('.policy-detail');
    let activeButton;
    let pending = false;

    function closeEditor(restoreFocus) {
        if (!activeButton) return;
        document.getElementById(activeButton.dataset.editTarget).hidden = true;
        activeButton.setAttribute('aria-expanded', 'false');
        if (restoreFocus) activeButton.focus();
        activeButton = null;
    }

    function openEditor(button) {
        closeEditor(false);
        const panel = document.getElementById(button.dataset.editTarget);
        const form = panel.querySelector('form');
        form.reset();
        if (form.hasAttribute('data-date-editor')) {
            form.action = button.dataset.dateUrl;
            form.querySelector('[data-date-label]').textContent = button.dataset.label;
            form.elements.value.value = button.dataset.value;
            form.elements.value.required = !button.dataset.value;
        }
        form.elements.original.value = form.elements.value.value;
        form.querySelector('[role="alert"]').textContent = '';
        form.elements.value.removeAttribute('aria-invalid');
        panel.hidden = false;
        activeButton = button;
        button.setAttribute('aria-expanded', 'true');
        form.elements.value.focus();
    }

    card.addEventListener('click', event => {
        const button = event.target.closest('button');
        if (button?.hasAttribute('data-edit-target')) {
            if (!pending) openEditor(button);
        } else if (button?.hasAttribute('data-edit-cancel')) {
            if (!pending) closeEditor(true);
        } else if (button?.hasAttribute('data-today')) {
            button.form.elements.value.value = button.dataset.today;
            button.form.elements.value.focus();
        } else if (!event.target.closest('a, button, input, label')) {
            event.target.closest('.payment-row')?.querySelector('.payment-toggle').click();
        }
    });

    card.addEventListener('keydown', event => {
        if (event.key === 'Escape' && activeButton && !pending) closeEditor(true);
    });

    card.addEventListener('submit', async event => {
        const form = event.target;
        if (!form.matches('.card-edit-form')) return;
        event.preventDefault();
        if (pending) return;
        const submit = form.querySelector('[type="submit"]');
        const error = form.querySelector('[role="alert"]');
        error.textContent = '';
        pending = true;
        submit.disabled = true;
        try {
            const response = await fetch(form.action, {method: 'POST', body: new FormData(form)});
            if (response.status !== 204) {
                const result = await response.json().catch(() => ({}));
                error.textContent = result.error || 'Не удалось сохранить. Обновите карточку и повторите попытку.';
                form.elements.value.setAttribute('aria-invalid', 'true');
                form.elements.value.focus();
                return;
            }
            const url = new URL(window.location.href);
            url.hash = form.dataset.returnAnchor || activeButton.closest('tr').id;
            window.history.replaceState(null, '', url);
            window.location.reload();
        } catch {
            error.textContent = 'Не удалось связаться с сервером. Попробуйте ещё раз.';
        } finally {
            pending = false;
            submit.disabled = false;
        }
    });
})();
